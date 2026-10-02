"""Custom model web API service tests."""

import json
import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from app.config_store import ConfigStore
from app.translations import tr
from app.translations_settings import TRANSLATIONS_EN, TRANSLATIONS_ZH
from app.web_api import custom_models as cm_api

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_CUSTOM_MODELS_JS = REPO_ROOT / "web" / "static" / "modules" / "settings-custom-models.js"
SETTINGS_MODEL_MODAL_FORM_JS = (
    REPO_ROOT / "web" / "static" / "modules" / "settings-model-modal-form.js"
)
SETTINGS_MODEL_MODAL_PROBE_JS = (
    REPO_ROOT / "web" / "static" / "modules" / "settings-model-modal-probe.js"
)
MODALS_HTML = REPO_ROOT / "web" / "static" / "partials" / "modals.html"
INDEX_HTML = REPO_ROOT / "web" / "static" / "index.html"
SETTINGS_HTML = REPO_ROOT / "web" / "static" / "partials" / "settings.html"
SETTINGS_DEFAULTS_JS = REPO_ROOT / "web" / "static" / "modules" / "settings-defaults.js"
SETTINGS_JS = REPO_ROOT / "web" / "static" / "modules" / "settings.js"


@pytest.fixture
def model_app(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config.db")
    app = SimpleNamespace(config=config, config_changed=MagicMock())
    return app


def _model_payload(model_id: str, **kwargs) -> dict:
    """Canonical custom model HTTP payload for tests."""
    payload = {
        "name": kwargs.get("name", "Test"),
        "model_ids": kwargs.get("model_ids", [model_id]),
        "default_model_id": kwargs.get("default_model_id", model_id),
        "mode": kwargs.get("mode", "openai"),
        "endpoint": kwargs.get("endpoint", "https://api.example.com/v1"),
        "apiKey": kwargs.get("apiKey", "sk-test-key-1234567890"),
        "provider": kwargs.get("provider", "custom_openai"),
    }
    if "api_key" in kwargs:
        payload["api_key"] = kwargs["api_key"]
        if "apiKey" not in kwargs:
            payload.pop("apiKey")
    if "max_tokens" in kwargs:
        payload["max_tokens"] = kwargs["max_tokens"]
    if "supportsMic" in kwargs:
        payload["supportsMic"] = kwargs["supportsMic"]
    if "thinking_effort" in kwargs:
        payload["thinking_effort"] = kwargs["thinking_effort"]
    if "temperature" in kwargs:
        payload["temperature"] = kwargs["temperature"]
    return payload


def test_custom_model_crud(model_app):
    created = cm_api.create_custom_model(
        model_app,
        _model_payload("test-model", thinking_effort="high"),
    )
    assert created["index"] == 0

    listing = cm_api.list_custom_models(model_app)
    assert len(listing["items"]) == 1
    assert listing["items"][0]["apiKey"] == "********"
    assert listing["items"][0]["model_ids"] == ["test-model"]
    assert listing["items"][0]["default_model_id"] == "test-model"
    assert listing["items"][0]["max_tokens"] == 512
    assert listing["items"][0]["thinking_effort"] == "high"
    assert "modelId" not in listing["items"][0]
    assert listing["active_profile_id"] == listing["items"][0]["profile_id"]

    updated = cm_api.update_custom_model(
        model_app,
        0,
        _model_payload(
            "test-model-2",
            name="Test2",
            apiKey="********",
        ),
    )
    assert updated["item"]["name"] == "Test2"
    assert updated["item"]["model_ids"] == ["test-model-2"]
    assert updated["item"]["default_model_id"] == "test-model-2"

    with_mic = cm_api.update_custom_model(
        model_app,
        0,
        _model_payload(
            "test-model-2",
            name="Test2",
            apiKey="********",
            supportsMic=True,
        ),
    )
    assert with_mic["item"]["supportsMic"] is True
    stored = model_app.config.get_custom_models()[0]
    assert stored["supportsMic"] is True

    assert "default_model_id" not in listing
    assert model_app.config.get_custom_models()[0]["default_model_id"] == "test-model-2"

    cm_api.delete_custom_model(model_app, 0)
    assert model_app.config.get_custom_models() == []


def test_custom_model_global_activation_uses_profile_id(model_app):
    first = cm_api.create_custom_model(model_app, _model_payload("model-a", name="A"))
    second = cm_api.create_custom_model(model_app, _model_payload("model-b", name="B"))
    first_id = first["item"]["profile_id"]
    second_id = second["item"]["profile_id"]
    assert model_app.config.get("active_model_profile_id") == first_id

    result = cm_api.activate_custom_model(model_app, second_id)
    assert result == {"ok": True, "active_profile_id": second_id}
    assert model_app.config.get("active_model_profile_id") == second_id
    assert cm_api.list_custom_models(model_app)["active_profile_id"] == second_id

    with pytest.raises(ValueError):
        cm_api.activate_custom_model(model_app, "not-a-profile-id")
    assert model_app.config.get("active_model_profile_id") == second_id


def test_incomplete_custom_model_cannot_be_activated(model_app):
    created = cm_api.create_custom_model(model_app, _model_payload("complete"))
    incomplete = dict(_model_payload("incomplete"))
    incomplete["apiKey"] = ""
    # Store-level fixtures can represent an upgrade-era incomplete profile.
    model_app.config.set_custom_models(
        [model_app.config.get_custom_models()[0], {**incomplete, "profile_id": "cmp_incomplete"}]
    )
    with pytest.raises(ValueError):
        cm_api.activate_custom_model(model_app, "cmp_incomplete")
    assert model_app.config.get("active_model_profile_id") == created["item"]["profile_id"]


def test_delete_active_custom_model_falls_back_and_last_delete_clears(model_app):
    first = cm_api.create_custom_model(model_app, _model_payload("model-a"))
    second = cm_api.create_custom_model(model_app, _model_payload("model-b"))
    cm_api.activate_custom_model(model_app, second["item"]["profile_id"])
    cm_api.delete_custom_model(model_app, 1)
    assert model_app.config.get("active_model_profile_id") == first["item"]["profile_id"]
    cm_api.delete_custom_model(model_app, 0)
    assert model_app.config.get("active_model_profile_id") == ""


@pytest.mark.parametrize(
    "value, expected",
    [
        ("off", "off"),
        ("low", "low"),
        ("medium", "medium"),
        ("high", "high"),
        ("xhigh", "xhigh"),
        ("invalid", "off"),
    ],
)
def test_custom_model_thinking_effort_is_normalized(model_app, value, expected):
    created = cm_api.create_custom_model(
        model_app,
        _model_payload("thinking-model", thinking_effort=value),
    )
    assert created["item"]["thinking_effort"] == expected


@pytest.mark.parametrize(
    "value, expected",
    [(0, 0.0), (0.0, 0.0), (0.2, 0.2), (1.5, 1.5), (2, 2.0), ("1.1", 1.1), ("invalid", 0.8), (-1, 0.8), (3, 0.8)],
)
def test_custom_model_temperature_is_normalized(model_app, value, expected):
    model_app.config.set("temperature", "0.8")
    created = cm_api.create_custom_model(
        model_app,
        _model_payload("temp-model", temperature=value),
    )
    assert created["item"]["temperature"] == expected
    stored = model_app.config.get_custom_models()[0]
    assert stored["temperature"] == expected


def test_custom_model_update_preserves_temperature_when_omitted(model_app):
    created = cm_api.create_custom_model(
        model_app,
        _model_payload("temp-model", temperature=0.2),
    )
    index = created["index"]
    payload = _model_payload("temp-model", name="Renamed", apiKey="********")
    payload.pop("temperature", None)
    updated = cm_api.update_custom_model(model_app, index, payload)
    assert updated["item"]["temperature"] == 0.2


def test_custom_model_create_without_temperature_uses_global_fallback(model_app):
    model_app.config.set("temperature", "0.6")
    created = cm_api.create_custom_model(model_app, _model_payload("temp-model"))
    assert created["item"]["temperature"] == 0.6


def test_settings_html_no_visible_global_temperature_field():
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    assert 'id="temperature"' not in html


def test_modals_html_has_model_temperature_field():
    html = MODALS_HTML.read_text(encoding="utf-8")
    assert 'id="modelTemperature"' in html
    assert 'min="0"' in html
    assert 'max="2"' in html
    assert 'step="0.1"' in html


def test_settings_custom_models_js_collects_model_temperature():
    src = SETTINGS_MODEL_MODAL_FORM_JS.read_text(encoding="utf-8")
    assert "temperature: parseModelTemperatureInput()" in src
    assert "model_names:" in src
    assert "resolveModelTemperatureFallback" in src
    assert "model.temperature" in src


def test_settings_defaults_api_restore_group_excludes_temperature():
    src = SETTINGS_DEFAULTS_JS.read_text(encoding="utf-8")
    api_group_start = src.index("api: [")
    api_group_end = src.index("],", api_group_start)
    api_group = src[api_group_start:api_group_end]
    assert "'temperature'" not in api_group
    assert "'temperature'" in src


def test_create_custom_model_returns_readable_validation_error(model_app):
    with pytest.raises(ValueError) as exc_info:
        cm_api.create_custom_model(model_app, _model_payload("invalid model id"))

    assert str(exc_info.value) == tr("custom_model.error_model_id_invalid")
    assert str(exc_info.value) != "custom_model.error_model_id_invalid"


def test_update_custom_model_returns_readable_validation_error(model_app):
    cm_api.create_custom_model(model_app, _model_payload("valid-model"))

    with pytest.raises(ValueError) as exc_info:
        cm_api.update_custom_model(model_app, 0, _model_payload("invalid model id"))

    assert str(exc_info.value) == tr("custom_model.error_model_id_invalid")
    assert str(exc_info.value) != "custom_model.error_model_id_invalid"


def test_model_id_invalid_translations_include_colon():
    assert "冒号" in TRANSLATIONS_ZH["custom_model.error_model_id_invalid"]
    assert "colons" in TRANSLATIONS_EN["custom_model.error_model_id_invalid"]


def test_resolve_probe_credentials_restores_masked_key_by_index(model_app):
    cm_api.create_custom_model(
        model_app,
        _model_payload("test-model", apiKey="sk-custom-probe-key"),
    )
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            "name": "Test",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
        },
        index=0,
    )
    assert resolved["apiKey"] == "sk-custom-probe-key"
    assert resolved["model_ids"] == ["test-model"]
    assert resolved["default_model_id"] == "test-model"
    assert "modelId" not in resolved


def test_resolve_probe_credentials_masked_key_without_existing_returns_empty(model_app):
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        _model_payload("new-model", apiKey="********"),
        index=-1,
    )
    assert resolved["apiKey"] == ""


def test_resolve_probe_credentials_normalizes_full_endpoint_url(model_app):
    with pytest.raises(ValueError):
        cm_api.resolve_probe_credentials(
            model_app,
            {
                "name": "Test",
                "mode": "openai-compatible",
                "endpoint": "https://openrouter.ai/api/v1/chat/completions",
                "apiKey": "sk-test",
            },
            index=-1,
        )


def test_create_custom_model_normalizes_endpoint_on_save(model_app):
    created = cm_api.create_custom_model(
        model_app,
        _model_payload(
            "openrouter-model",
            name="OpenRouter",
            endpoint="https://openrouter.ai/api/v1/chat/completions/",
            apiKey="sk-save-key",
            provider="",
        ),
    )
    stored = model_app.config.get_custom_models()[created["index"]]
    assert stored["endpoint"] == "https://openrouter.ai/api/v1"
    assert stored["mode"] == "openai-compatible"


def test_custom_model_api_key_encrypted_at_rest_in_sqlite(model_app):
    """W-TEST-COVER-005: apiKey is Fernet-encrypted in config.db; GET masks; get_custom_models decrypts."""
    secret = "sk-plaintext-storage-test-key"
    cm_api.create_custom_model(
        model_app,
        _model_payload(
            "plain-model",
            name="Plain",
            apiKey=secret,
        ),
    )
    listing = cm_api.list_custom_models(model_app)
    assert listing["items"][0]["apiKey"] == "********"
    assert model_app.config.get_custom_models()[0]["apiKey"] == secret

    conn = sqlite3.connect(str(model_app.config.db_path))
    try:
        row = conn.execute(
            "SELECT value FROM config WHERE key = ?",
            ("custom_models",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert secret not in row[0]


def test_create_custom_model_with_multiple_model_ids_and_default(model_app):
    """W-MODEL-MODAL-004：1:N shape — 保存 model_ids 列表 + default_model_id + max_tokens。"""
    created = cm_api.create_custom_model(
        model_app,
        {
            "name": "Multi",
            "model_ids": ["model-a", "model-b", "model-c"],
            "default_model_id": "model-b",
            "max_tokens": 1024,
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-multi-key",
            "provider": "custom_openai",
        },
    )
    assert created["index"] == 0
    item = created["item"]
    assert item["model_ids"] == ["model-a", "model-b", "model-c"]
    assert item["default_model_id"] == "model-b"
    assert item["max_tokens"] == 1024
    assert "modelId" not in item

    stored = model_app.config.get_custom_models()[0]
    assert stored["model_ids"] == ["model-a", "model-b", "model-c"]
    assert stored["default_model_id"] == "model-b"
    assert stored["max_tokens"] == 1024


def test_create_custom_model_default_model_id_falls_back_to_first(model_app):
    """W-MODEL-MODAL-004：default_model_id 缺省时取 model_ids[0]（首个 chip 自动默认）。"""
    created = cm_api.create_custom_model(
        model_app,
        {
            "name": "NoDefault",
            "model_ids": ["alpha", "beta"],
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-no-default",
            "provider": "custom_openai",
        },
    )
    assert created["item"]["default_model_id"] == "alpha"
    assert "modelId" not in created["item"]


def test_probe_with_explicit_model_id_overrides_default(model_app):
    """W-MODEL-MODAL-004：probe 入参 model_id 覆盖 default_model_id。"""
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Probe",
            "model_ids": ["default-id", "alternate-id"],
            "default_model_id": "default-id",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-probe-key",
            "provider": "custom_openai",
        },
    )
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            "name": "Probe",
            "model_ids": ["default-id", "alternate-id"],
            "default_model_id": "default-id",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
            "model_id": "alternate-id",
        },
        index=0,
    )
    assert resolved["apiKey"] == "sk-probe-key"
    assert resolved["default_model_id"] == "alternate-id"
    assert "modelId" not in resolved


def test_probe_without_model_id_uses_default(model_app):
    """W-MODEL-MODAL-004：probe 未指定 model_id 时取 default_model_id。"""
    cm_api.create_custom_model(
        model_app,
        {
            "name": "ProbeDefault",
            "model_ids": ["first", "second"],
            "default_model_id": "second",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-probe-default",
            "provider": "custom_openai",
        },
    )
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            "name": "ProbeDefault",
            "model_ids": ["first", "second"],
            "default_model_id": "second",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
        },
        index=0,
    )
    assert resolved["default_model_id"] == "second"
    assert "modelId" not in resolved


def test_update_custom_model_switches_default_within_model_ids(model_app):
    """W-MODEL-MODAL-004：update 时切换 default_model_id 到列表内另一个 model_id。"""
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Switch",
            "model_ids": ["x", "y"],
            "default_model_id": "x",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-switch",
            "provider": "custom_openai",
        },
    )
    updated = cm_api.update_custom_model(
        model_app,
        0,
        {
            "name": "Switch",
            "model_ids": ["x", "y"],
            "default_model_id": "y",
            "max_tokens": 2048,
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
        },
    )
    assert updated["item"]["default_model_id"] == "y"
    assert updated["item"]["max_tokens"] == 2048
    assert "modelId" not in updated["item"]


def test_create_custom_model_legacy_only_payload_rejected(model_app):
    """W-004：legacy-only POST body 获得明确 4xx。"""
    with pytest.raises(ValueError):
        cm_api.create_custom_model(
            model_app,
            {
                "name": "Legacy",
                "modelId": "legacy-only",
                "mode": "openai",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "sk-legacy-only",
                "provider": "custom_openai",
            },
        )


def test_list_custom_models_response_has_no_model_id(model_app):
    """W-004：GET 列表项不含 modelId。"""
    cm_api.create_custom_model(model_app, _model_payload("listed-model"))
    listing = cm_api.list_custom_models(model_app)
    assert "modelId" not in listing["items"][0]


def test_create_custom_model_empty_model_ids_rejected(model_app):
    """W-MODEL-MODAL-004：空 model_ids 列表应被校验拒绝（前端 tag 输入框空值忽略的对应后端保障）。"""
    with pytest.raises(ValueError):
        cm_api.create_custom_model(
            model_app,
            {
                "name": "Empty",
                "model_ids": [],
                "default_model_id": "",
                "mode": "openai",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "sk-empty",
                "provider": "custom_openai",
            },
        )


# ---------------------------------------------------------------------------
# W-DELETE-CONFIRM-005：删除二次确认 Modal 化（前端源码静态契约断言）
#
# 项目当前无 jsdom / JS 单测基础设施，tests/test_web_custom_models.py 本身
# 是后端 API service 测试。这里通过读取前端源码做静态断言，锁住以下不变量：
#   1. 裸 confirm(...) 调用已被替换为 openDeleteModelConfirm(...)
#   2. formatDeleteModelMessage / openDeleteModelConfirm / closeDeleteModelConfirm 已导出
#   3. 文案模板包含关键短语（name 空降级、N 个模型 ID、自动切换）
#   4. partials/modals.html 含 deleteModelConfirmModal 及按钮
#   5. index.html 经 build_index_html.py 重建后也含该 modal
#   6. 文案规则用 Python 等价实现交叉验证 spec
# ---------------------------------------------------------------------------


def _read_settings_custom_models_js():
    return SETTINGS_CUSTOM_MODELS_JS.read_text(encoding="utf-8")


def test_no_bare_confirm_call_in_settings_custom_models_js():
    """W-DELETE-CONFIRM-005：裸 confirm(...) 调用应被替换为 openDeleteModelConfirm。"""
    src = _read_settings_custom_models_js()
    # 匹配小写 confirm( 调用，排除 Confirm( 大写 C（函数名 openDeleteModelConfirm 不算裸调用）
    bare_calls = re.findall(r'(?<![A-Za-z])confirm\s*\(', src)
    assert bare_calls == [], f"应不再有裸 confirm(...) 调用，发现 {len(bare_calls)} 处"


def test_delete_button_onclick_uses_open_delete_model_confirm():
    """W-DELETE-CONFIRM-005：删除按钮 onclick 应改为 openDeleteModelConfirm(model, index)。"""
    src = _read_settings_custom_models_js()
    assert "openDeleteModelConfirm(model, index)" in src
    # 原始 confirm 模板字符串调用应不存在
    assert "if (!confirm(`确定删除模型" not in src
    assert "delBtn.onclick = () => openDeleteModelConfirm(model, index)" in src


def test_format_delete_model_message_function_exported():
    """W-DELETE-CONFIRM-005：formatDeleteModelMessage 应作为 export function 定义。"""
    src = _read_settings_custom_models_js()
    assert "export function formatDeleteModelMessage(profile)" in src
    assert "export function openDeleteModelConfirm(profile, index)" in src
    assert "export function closeDeleteModelConfirm()" in src


def test_format_delete_model_message_text_rules_in_source():
    """W-DELETE-CONFIRM-005：formatDeleteModelMessage 使用 i18n key 与 model_ids 契约。"""
    src = _read_settings_custom_models_js()
    assert "resolveProfileDisplayName(profile)" in src
    assert "dynamic.settingsCustomModels.确定删除模型_display_吗_该档案包" in src
    assert "model_ids" in src
    assert "display" in src
    assert "ids.length" in src
    zh_dynamic = json.loads(
        (REPO_ROOT / "web" / "static" / "locales" / "zh" / "dynamic.json").read_text(
            encoding="utf-8"
        )
    )
    custom_models = zh_dynamic["dynamic"]["settingsCustomModels"]
    assert "这条模型档案" in custom_models["这条模型档案"]
    assert "确定删除模型「" in custom_models["确定删除模型_display_吗_该档案包"]


def test_open_delete_model_confirm_uses_focus_trap_and_classlist():
    """W-DELETE-CONFIRM-005：openDeleteModelConfirm 复用 activateFocusTrap + classList 切换（与 restoreDefaultsModal 风格一致）。"""
    src = _read_settings_custom_models_js()
    assert "activateFocusTrap(modal, closeDeleteModelConfirm)" in src
    assert "modal.classList.remove(\"hidden\")" in src
    assert "modal.classList.add(\"flex\")" in src
    assert "deactivateFocusTrap()" in src


def test_open_delete_model_confirm_cleanup_on_close():
    """W-DELETE-CONFIRM-005：一次性监听在关闭时清空（避免内存泄漏）。"""
    src = _read_settings_custom_models_js()
    # 存在清理句柄变量
    assert "_deleteModelConfirmCleanup" in src
    # 使用 { once: true } 绑定一次性监听
    assert "{ once: true }" in src
    # closeDeleteModelConfirm 中调用清理
    assert "removeEventListener(\"click\", onConfirm)" in src
    assert "removeEventListener(\"click\", close)" in src
    assert "removeEventListener(\"click\", onBackdropClick)" in src


def test_open_delete_model_confirm_calls_delete_api_and_toast():
    """W-DELETE-CONFIRM-005：确认按钮回调调用 DELETE /api/custom-models/{index} + toast + loadCustomModels。"""
    src = _read_settings_custom_models_js()
    assert "apiFetch(`/api/custom-models/${index}`, { method: \"DELETE\" })" in src
    assert "customModelDeps.showToast(t(\"dynamic.settingsCustomModels.已删除_2\"))" in src
    assert "loadCustomModels()" in src
    # 错误处理：失败时关闭 modal + 错误 toast
    assert "customModelDeps.showToast(error.message, true)" in src


def test_delete_model_confirm_modal_in_modals_html():
    """W-DELETE-CONFIRM-005：partials/modals.html 含 deleteModelConfirmModal 及按钮。"""
    html = MODALS_HTML.read_text(encoding="utf-8")
    assert 'id="deleteModelConfirmModal"' in html
    assert 'id="deleteModelConfirmModalTitle"' in html
    assert 'id="deleteModelConfirmMessage"' in html
    assert 'id="btnDeleteModelConfirmOk"' in html
    assert 'id="btnDeleteModelConfirmCancel"' in html
    # 标题文本
    assert "删除模型档案" in html
    # 取消/确认按钮文本
    assert "取消" in html
    assert "确认删除" in html


def test_delete_model_confirm_modal_built_into_index_html():
    """W-DELETE-CONFIRM-005：index.html 经 build_index_html.py 重建后含 deleteModelConfirmModal。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert 'id="deleteModelConfirmModal"' in html
    assert 'id="btnDeleteModelConfirmOk"' in html
    assert 'id="btnDeleteModelConfirmCancel"' in html


def test_delete_model_confirm_modal_reuses_restore_defaults_styles():
    """W-DELETE-CONFIRM-005：deleteModelConfirmModal 与 restoreDefaultsModal 共享同一套 Tailwind 类（结构一致性）。"""
    html = MODALS_HTML.read_text(encoding="utf-8")
    restore_marker = 'id="restoreDefaultsModal" class="'
    delete_marker = 'id="deleteModelConfirmModal" class="'
    assert restore_marker in html
    assert delete_marker in html
    restore_idx = html.index(restore_marker) + len(restore_marker)
    delete_idx = html.index(delete_marker) + len(delete_marker)
    restore_cls = html[restore_idx:html.index('"', restore_idx)]
    delete_cls = html[delete_idx:html.index('"', delete_idx)]
    # 外层容器类应完全一致（z-50 / bg-black/20 / backdrop-blur-sm / hidden / items-center / justify-center / p-4）
    assert restore_cls == delete_cls, (
        f"deleteModelConfirmModal 外层类应与 restoreDefaultsModal 一致，"
        f"restore={restore_cls!r} delete={delete_cls!r}"
    )


def test_format_delete_model_message_python_equivalent():
    """W-DELETE-CONFIRM-005：Python 等价实现验证 spec 文案规则（与 JS 实现并行，锁住语义）。"""

    def fmt(profile, *, is_active=False, remaining_count=0):
        name = (profile.get("name") or "").strip() if isinstance(profile, dict) else ""
        ids = (
            profile.get("model_ids")
            if isinstance(profile, dict) and isinstance(profile.get("model_ids"), list)
            else []
        )
        n = len(ids) or 1
        display = name or "这条模型档案"
        message = (
            f"确定删除模型「{display}」吗？该档案包含 {n} 个模型 ID，将一并删除。"
        )
        if not is_active:
            return message
        return message + (
            "若该档案是当前默认，将自动切换到下一条。"
            if remaining_count > 0
            else "若该档案是当前默认，删除后将没有可用的 AI 模型。"
        )

    # name 非空 + 多 model_ids
    msg1 = fmt({"name": "豆包Pro", "model_ids": ["a", "b"]})
    assert "「豆包Pro」" in msg1
    assert "2 个模型 ID" in msg1
    assert msg1.startswith("确定删除模型「豆包Pro」吗？")
    assert not msg1.endswith("将自动切换到下一条。")
    active_msg = fmt(
        {"name": "豆包Pro", "model_ids": ["a", "b"]},
        is_active=True,
        remaining_count=1,
    )
    assert active_msg.endswith("将自动切换到下一条。")

    # name 空降级
    msg2 = fmt({"name": "", "model_ids": ["a"]})
    assert "「这条模型档案」" in msg2
    assert "1 个模型 ID" in msg2

    # model_ids 缺失降级为 1
    msg3 = fmt({"name": "X"})
    assert "1 个模型 ID" in msg3
    assert "没有可用的 AI 模型" not in msg3
    assert "「X」" in msg3

    # model_ids 空数组降级为 1
    msg4 = fmt({"name": "Y", "model_ids": []})
    assert "1 个模型 ID" in msg4

    # profile 完全空
    msg5 = fmt({})
    assert "「这条模型档案」" in msg5
    assert "1 个模型 ID" in msg5


# ---------------------------------------------------------------------------
# W-SETTINGS-RESTRUCT-A-006：顶栏旧字段软隐藏 + 列表行重排 4 列（前端静态契约断言）
#
# 锁住以下不变量：
#   1. partials/settings.html 含 .legacy-api-fields class（5 个旧字段 wrapper）
#   2. index.html 经 build 重建后含 .legacy-api-fields { display:none !important } CSS
#   3. 旧字段 DOM 节点仍存在（api_endpoint / api_key / model / max_tokens / api_mode ID）
#   4. settings-defaults.js CONFIG_FIELDS 仍含旧 key（api_key 按设计不在 CONFIG_FIELDS，
#      走加密独立路径；此处验证 4 个在 CONFIG_FIELDS 中的旧 key 保留）
#   5. settings.js 给旧字段 wrapper 同步 hidden=true（DOM 属性双保险）
#   6. settings-custom-models.js 列表行重排 4 列结构
#   7. "AI 模型" 标题 + "+ 添加模型" 按钮（btnAddCustomModel）→ openModelModal(-1)
#   8. 列表行含 custom-model-status-col + custom-model-in-use-badge（列 3：使用中状态徽章）
# ---------------------------------------------------------------------------


def test_settings_html_has_legacy_api_fields_class():
    """W-SETTINGS-RESTRUCT-A-006：settings.html 5 个旧字段 wrapper 含 legacy-api-fields class。"""
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    # 5 个旧字段 wrapper 应各带一个 legacy-api-fields class
    assert html.count('class="legacy-api-fields"') + html.count(' legacy-api-fields"') + html.count(' legacy-api-fields ') >= 5
    # 内联 <style> 已迁出（W-UI-SETTINGS-MIGRATE-001）；DOM class 仍保留
    assert "<style>" not in html
    assert "legacy-api-fields" in html


def test_index_html_has_legacy_api_fields_css_rule():
    """W-SETTINGS-RESTRUCT-A-006 / E：.legacy-api-fields 软隐藏规则在 compat CSS，DOM 仍在 index。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert "legacy-api-fields" in html
    # 规则迁入 warm-tokens-compat.css（由 warm-tokens.css @import）
    static = SETTINGS_HTML.parent.parent
    compat = (static / "warm-tokens-compat.css").read_text(encoding="utf-8")
    entry = (static / "warm-tokens.css").read_text(encoding="utf-8")
    assert ".legacy-api-fields" in compat
    assert "display: none !important" in compat or "display:none !important" in compat
    assert "warm-tokens-compat.css" in entry


def test_legacy_field_dom_ids_still_present_in_settings_html():
    """W-SETTINGS-RESTRUCT-A-006：旧字段 DOM 节点保留（不删除），5 个 ID 仍可找到。"""
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    for field_id in ("api_endpoint", "api_mode", "api_key", "model", "max_tokens"):
        assert f'id="{field_id}"' in html, f"旧字段 DOM 节点 {field_id} 应保留"


def test_legacy_field_dom_ids_still_present_in_index_html():
    """W-SETTINGS-RESTRUCT-A-006：index.html 经 build 重建后旧字段 DOM 节点仍保留。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    for field_id in ("api_endpoint", "api_mode", "api_key", "model", "max_tokens"):
        assert f'id="{field_id}"' in html, f"旧字段 DOM 节点 {field_id} 应在 index.html 中保留"


def test_config_fields_drops_retired_global_model_key():
    """全局默认模型已移除；遗留隐藏 DOM 不再进入可保存字段。"""
    src = SETTINGS_DEFAULTS_JS.read_text(encoding="utf-8")
    for key in ("api_endpoint", "api_mode", "max_tokens"):
        assert f"'{key}'" in src, f"CONFIG_FIELDS 应保留旧 key '{key}'"
    assert "'model'" not in src


def test_settings_js_sets_hidden_on_legacy_field_wrappers():
    """W-SETTINGS-RESTRUCT-A-006：settings.js 给旧字段 wrapper 同步 hidden=true（DOM 属性双保险）。"""
    src = SETTINGS_JS.read_text(encoding="utf-8")
    assert "legacy-api-fields" in src
    assert ".parentElement.hidden = true" in src
    # 5 个旧字段 ID 均在 hidden 同步列表中
    for field_id in ("api_endpoint", "api_mode", "api_key", "model", "max_tokens"):
        assert f"'{field_id}'" in src


def test_settings_custom_models_js_has_global_activation_controls():
    """全局模型列表只通过启动/使用中按钮表达当前档案。"""
    src = SETTINGS_CUSTOM_MODELS_JS.read_text(encoding="utf-8")
    assert "custom-model-row" in src
    assert "custom-model-provider-chip" in src
    assert "custom-model-id-col" in src
    assert "(+${extra})" in src
    assert "custom-model-actions" in src
    assert "/api/custom-models/active" in src
    assert "active_profile_id" in src
    assert "dynamic.settingsCustomModels.使用中" in src
    assert "dynamic.settingsCustomModels.启动" in src
    assert "dynamic.settingsCustomModels.启动中" in src
    assert "custom-model-default-col" not in src
    assert "setProfileAsDefault" not in src
    assert "设为使用" not in src
    assert "设默认" not in src
    assert "/api/custom-models/${index}/default" not in src


def test_add_custom_model_button_wired_to_open_model_modal():
    """W-SETTINGS-RESTRUCT-A-006：「+ 添加模型」按钮 → openModelModal(-1)（新增模型）。"""
    form_src = SETTINGS_MODEL_MODAL_FORM_JS.read_text(encoding="utf-8")
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    assert "btnAddCustomModel" in html
    assert "btnAddCustomModel" in form_src
    assert "openModelModal(-1)" in form_src


def test_settings_html_has_add_custom_model_button_and_ai_models_title():
    """W-SETTINGS-RESTRUCT-A-006：settings.html 含「AI 模型」标题 + btnAddCustomModel 按钮。"""
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    assert "AI 模型" in html
    assert 'id="btnAddCustomModel"' in html


def test_edit_button_still_calls_open_model_modal():
    """W-SETTINGS-RESTRUCT-A-006：编辑按钮仍调 openModelModal(index, model)（Task 4 已就位）。"""
    src = SETTINGS_CUSTOM_MODELS_JS.read_text(encoding="utf-8")
    assert "openModelModal(index, model)" in src


def test_delete_button_still_calls_open_delete_model_confirm():
    """W-SETTINGS-RESTRUCT-A-006：删除按钮仍调 openDeleteModelConfirm(model, index)（Task 5 已就位）。"""
    src = SETTINGS_CUSTOM_MODELS_JS.read_text(encoding="utf-8")
    assert "delBtn.onclick = () => openDeleteModelConfirm(model, index)" in src


# ---------------------------------------------------------------------------
# W-ARCH-MODEL-PROFILE-CANONICAL-003：前端 canonical payload 与唯一 save/probe action
# ---------------------------------------------------------------------------


def _collect_model_form_return_block(src: str) -> str:
    marker = "export function collectModelForm()"
    start = src.index(marker)
    return_start = src.index("return {", start)
    return_end = src.index("};", return_start)
    return src[return_start:return_end]


def test_collect_model_form_payload_excludes_model_id():
    """W-ARCH-MODEL-PROFILE-CANONICAL-003：collectModelForm 提交块不含 legacy modelId。"""
    src = SETTINGS_MODEL_MODAL_FORM_JS.read_text(encoding="utf-8")
    block = _collect_model_form_return_block(src)
    assert "model_ids:" in block
    assert "default_model_id:" in block
    assert "model_names:" in block
    assert "modelId:" not in block


def test_settings_js_delegates_model_save_and_probe():
    """W-ARCH-MODEL-PROFILE-CANONICAL-003：settings.js 导入并调用 saveModel / probe。"""
    src = SETTINGS_JS.read_text(encoding="utf-8")
    assert "saveModel" in src
    assert "probe" in src
    assert "await saveModel()" in src
    assert "await probe()" in src


def test_settings_js_has_no_duplicate_custom_model_http():
    """W-ARCH-MODEL-PROFILE-CANONICAL-003：settings.js 不复制模型档案 POST/PUT/probe HTTP。"""
    src = SETTINGS_JS.read_text(encoding="utf-8")
    assert "/api/custom-models" not in src


def test_model_modal_form_is_unique_save_probe_owner():
    """W-ARCH-MODEL-PROFILE-CANONICAL-003：saveModel / probe 唯一实现在 form 模块。"""
    form_src = SETTINGS_MODEL_MODAL_FORM_JS.read_text(encoding="utf-8")
    settings_src = SETTINGS_JS.read_text(encoding="utf-8")
    assert "export async function saveModel()" in form_src
    assert "export async function probe()" in form_src
    assert "await apiFetch(`/api/custom-models/${index}`" in form_src
    assert "await apiFetch(\"/api/custom-models\"" in form_src
    assert "export async function saveModel()" not in settings_src
    assert "export async function probe()" not in settings_src


def test_probe_payload_includes_explicit_model_id():
    """W-ARCH-MODEL-PROFILE-CANONICAL-003：probe 显式携带 model_id=default_model_id。"""
    src = SETTINGS_MODEL_MODAL_PROBE_JS.read_text(encoding="utf-8")
    assert "model_id: form.default_model_id" in src


def test_custom_models_ui_no_model_id_fallback_reads():
    """W-ARCH-MODEL-PROFILE-CANONICAL-003：模型档案 UI 不以 model.modelId 回退读取。"""
    src = SETTINGS_CUSTOM_MODELS_JS.read_text(encoding="utf-8")
    assert "model.modelId" not in src


# ---------------------------------------------------------------------------
# 全局模型改造：删除模型不主动清理历史 persona_model_bindings
# ---------------------------------------------------------------------------


def test_delete_custom_model_preserves_persona_bindings(model_app):
    """删除模型档案不破坏历史人格绑定数据。"""
    cm_api.create_custom_model(model_app, _model_payload("bound-1", name="Bound"))
    cm_api.create_custom_model(model_app, _model_payload("other-2", name="Other"))
    # 绑定：高压吐槽型 → bound-1，熬夜陪看型 → other-2
    model_app.config.set(
        "persona_model_bindings", '{"高压吐槽型": "bound-1", "熬夜陪看型": "other-2"}'
    )
    # 删除 index 0（Bound / bound-1）
    cm_api.delete_custom_model(model_app, 0)
    # 历史绑定保留，运行时已不再读取它们
    import json as _json

    raw = model_app.config.get("persona_model_bindings", "{}")
    bindings = _json.loads(raw)
    assert bindings.get("高压吐槽型") == "bound-1"
    assert bindings.get("熬夜陪看型") == "other-2"


def test_delete_custom_model_no_bindings_is_noop(model_app):
    """删除模型时没有历史绑定仍保持幂等。"""
    cm_api.create_custom_model(model_app, _model_payload("solo-1", name="Solo"))
    # 无人格绑定
    cm_api.delete_custom_model(model_app, 0)
    assert model_app.config.get("persona_model_bindings", "{}") in ("{}", "")


# ---------------------------------------------------------------------------
# supportsMic user override vs catalog supports_mic (model modal)
# ---------------------------------------------------------------------------

DOUBAO_ENDPOINT = "https://ark.cn-beijing.volces.com/api/v3"
CATALOG_MIC_MODEL = "doubao-seed-2-0-mini-260428"
CATALOG_NO_MIC_MODEL = "doubao-seed-1-6-flash-250828"


def _doubao_catalog_payload(model_id: str, **kwargs) -> dict:
    return _model_payload(
        model_id,
        provider="doubao",
        mode="doubao",
        endpoint=DOUBAO_ENDPOINT,
        **kwargs,
    )


def test_custom_model_supports_mic_override_catalog_default_true(model_app):
    """Catalog supports_mic=true but user sets supportsMic=false; value persists."""
    created = cm_api.create_custom_model(
        model_app,
        _doubao_catalog_payload(CATALOG_MIC_MODEL, supportsMic=False),
    )
    item = created["item"]
    assert item["supportsMic"] is False
    stored = model_app.config.get_custom_models()[created["index"]]
    assert stored["supportsMic"] is False

    listed = cm_api.list_custom_models(model_app)["items"][0]
    assert listed["supportsMic"] is False


def test_custom_model_supports_mic_override_catalog_default_false(model_app):
    """Catalog supports_mic=false but user sets supportsMic=true; value persists."""
    created = cm_api.create_custom_model(
        model_app,
        _doubao_catalog_payload(CATALOG_NO_MIC_MODEL, supportsMic=True),
    )
    item = created["item"]
    assert item["supportsMic"] is True
    stored = model_app.config.get_custom_models()[created["index"]]
    assert stored["supportsMic"] is True


def test_custom_model_supports_mic_persists_after_update_and_reopen(model_app):
    """Edit + save supportsMic override; list API returns the same flag."""
    created = cm_api.create_custom_model(
        model_app,
        _doubao_catalog_payload(CATALOG_MIC_MODEL, supportsMic=False),
    )
    index = created["index"]
    assert created["item"]["supportsMic"] is False

    updated = cm_api.update_custom_model(
        model_app,
        index,
        _doubao_catalog_payload(
            CATALOG_MIC_MODEL,
            apiKey="********",
            supportsMic=True,
        ),
    )
    assert updated["item"]["supportsMic"] is True
    assert model_app.config.get_custom_models()[index]["supportsMic"] is True

    reopened = cm_api.list_custom_models(model_app)["items"][index]
    assert reopened["supportsMic"] is True


def test_modals_html_has_model_provider_picker_without_region_filter():
    html = MODALS_HTML.read_text(encoding="utf-8")
    assert 'id="modelProviderRegion"' not in html
    assert 'id="modelProvider"' in html
    assert 'id="modelProviderPicker"' in html
    assert 'id="modelProviderSearch"' in html
    assert 'id="modelProviderOptions"' in html
    assert 'id="modelProviderEmpty"' in html


def test_modals_html_has_model_list_table_without_mode_select():
    html = MODALS_HTML.read_text(encoding="utf-8")
    assert 'id="modelListTable"' in html
    assert 'id="modelListTableBody"' in html
    assert 'id="modelCatalogOptions"' in html
    assert 'id="modelModeReadonly"' in html
    assert 'id="modelMode"' not in html
    assert 'id="modelName"' not in html
    assert 'id="modelDescription"' not in html
    assert 'id="modelIdsTags"' not in html
    mode_pos = html.index('id="modelModeReadonly"')
    provider_pos = html.index('id="modelProvider"')
    assert mode_pos > provider_pos


def test_create_custom_model_persists_model_names(model_app):
    created = cm_api.create_custom_model(
        model_app,
        {
            "name": "Display A",
            "model_ids": ["model-a", "model-b"],
            "model_names": {"model-a": "Name A", "model-b": "Name B"},
            "default_model_id": "model-b",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-multi-names",
            "provider": "custom_openai",
        },
    )
    item = created["item"]
    assert item["model_names"] == {"model-a": "Name A", "model-b": "Name B"}
    assert item["name"] == "Name B"
    stored = model_app.config.get_custom_models()[0]
    assert stored["model_names"]["model-b"] == "Name B"


def test_settings_model_modal_form_wires_searchable_provider_picker():
    src = SETTINGS_MODEL_MODAL_FORM_JS.read_text(encoding="utf-8")
    assert "modelProviderRegion" not in src
    assert "initModelProviderRegionSelect" not in src
    assert "onModalProviderRegionChange" not in src
    assert "inferModalProviderRegion" not in src
    assert "fillModelProviderSelect" not in src
    assert "MODAL_PROVIDER_REGION_CHINA" not in src
    assert "modelProviderPicker" in src
    assert "modelProviderSearch" in src
    assert "onProviderChangeInModal(" in src
    assert "{ isEdit: false }" in src


# ---------------------------------------------------------------------------
# W-REVIEW-20260820-CUSTOMMODEL-HTTP-CONTRACT-001: HTTP schema ↔ UI payload
# ---------------------------------------------------------------------------

CUSTOM_MODELS_ROUTES_PY = REPO_ROOT / "app" / "web_api" / "custom_models_routes.py"


def test_custom_model_payload_schema_declares_form_fields():
    """CustomModelPayload must accept every field emitted by collectModelForm()."""
    src = CUSTOM_MODELS_ROUTES_PY.read_text(encoding="utf-8")
    for field in (
        "model_names:",
        "supportsMic:",
        "thinking_effort:",
        "temperature:",
        'extra="forbid"',
    ):
        assert field in src


def _custom_model_http_client(tmp_path):
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    config = ConfigStore(db_path=tmp_path / "routes.db")
    bridge.danmu_app = SimpleNamespace(config=config, config_changed=MagicMock())

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    return TestClient(app, raise_server_exceptions=False), config


def test_custom_model_http_post_persists_form_fields(tmp_path):
    client, config = _custom_model_http_client(tmp_path)
    payload = {
        "name": "Display A",
        "model_ids": ["model-a", "model-b"],
        "model_names": {"model-a": "Name A", "model-b": "Name B"},
        "default_model_id": "model-b",
        "max_tokens": 512,
        "mode": "openai",
        "endpoint": "https://api.example.com/v1",
        "apiKey": "sk-http-contract-key",
        "provider": "custom_openai",
        "supportsMic": True,
        "thinking_effort": "high",
        "temperature": 0.3,
    }
    res = client.post("/api/custom-models", json=payload)
    assert res.status_code == 200
    item = res.json()["item"]
    assert item["model_names"] == {"model-a": "Name A", "model-b": "Name B"}
    assert item["supportsMic"] is True
    assert item["thinking_effort"] == "high"
    assert item["temperature"] == 0.3
    assert item["apiKey"] == "********"

    stored = config.get_custom_models()[0]
    assert stored["model_names"]["model-b"] == "Name B"
    assert stored["supportsMic"] is True
    assert stored["thinking_effort"] == "high"
    assert stored["apiKey"] == "sk-http-contract-key"


def test_custom_model_http_active_route_uses_profile_id_and_rejects_invalid(tmp_path):
    client, config = _custom_model_http_client(tmp_path)
    first = client.post("/api/custom-models", json=_model_payload("route-model-a"))
    second = client.post("/api/custom-models", json=_model_payload("route-model-b"))
    assert first.status_code == 200
    assert second.status_code == 200
    first_id = first.json()["item"]["profile_id"]
    second_id = second.json()["item"]["profile_id"]

    activated = client.put("/api/custom-models/active", json={"profile_id": second_id})
    assert activated.status_code == 200
    assert activated.json() == {"ok": True, "active_profile_id": second_id}
    assert config.get("active_model_profile_id") == second_id

    invalid = client.put("/api/custom-models/active", json={"profile_id": "missing"})
    assert invalid.status_code == 400
    assert config.get("active_model_profile_id") == second_id
    assert first_id != second_id


def test_custom_model_http_put_persists_form_fields(tmp_path):
    client, config = _custom_model_http_client(tmp_path)
    created = client.post(
        "/api/custom-models",
        json=_model_payload("persist-model"),
    )
    assert created.status_code == 200

    updated = client.put(
        "/api/custom-models/0",
        json={
            **_model_payload("persist-model", apiKey="********"),
            "model_names": {"persist-model": "Renamed"},
            "supportsMic": True,
            "thinking_effort": "medium",
            "temperature": 1.1,
        },
    )
    assert updated.status_code == 200
    item = updated.json()["item"]
    assert item["model_names"] == {"persist-model": "Renamed"}
    assert item["supportsMic"] is True
    assert item["thinking_effort"] == "medium"
    assert item["temperature"] == 1.1

    listed = client.get("/api/custom-models").json()["items"][0]
    assert listed["supportsMic"] is True
    assert listed["thinking_effort"] == "medium"
    assert listed["apiKey"] == "********"
    stored = config.get_custom_models()[0]
    assert stored["model_names"]["persist-model"] == "Renamed"


def test_custom_model_http_rejects_unknown_fields(tmp_path):
    client, _config = _custom_model_http_client(tmp_path)
    res = client.post(
        "/api/custom-models",
        json={
            **_model_payload("unknown-field-model"),
            "unexpected_field": True,
        },
    )
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert any(
        err.get("loc") == ["body", "unexpected_field"] and err.get("type") == "extra_forbidden"
        for err in detail
    )


def test_custom_model_api_key_alias_create_encrypts_and_masks(model_app):
    secret = "sk-snake-alias-create-key"
    created = cm_api.create_custom_model(
        model_app,
        _model_payload("alias-create-model", api_key=secret),
    )
    item = created["item"]
    assert item["apiKey"] == "********"
    assert "api_key" not in item
    assert model_app.config.get_custom_models()[0]["apiKey"] == secret

    conn = sqlite3.connect(str(model_app.config.db_path))
    try:
        row = conn.execute(
            "SELECT value FROM config WHERE key = ?",
            ("custom_models",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert secret not in row[0]
    assert '"api_key"' not in row[0]


def test_custom_model_api_key_alias_conflict_does_not_leak_secrets(model_app):
    with pytest.raises(ValueError) as exc:
        cm_api.create_custom_model(
            model_app,
            {
                **_model_payload("conflict-model"),
                "apiKey": "sk-conflict-a",
                "api_key": "sk-conflict-b",
            },
        )
    message = str(exc.value)
    assert "sk-conflict-a" not in message
    assert "sk-conflict-b" not in message
    assert tr("custom_model.error_api_key_conflict") in message


def test_list_custom_model_masks_api_key_alias_only(model_app):
    model_app.config.set_json(
        "custom_models",
        [
            {
                "name": "AliasOnly",
                "modelId": "alias-only",
                "mode": "openai",
                "endpoint": "https://api.example.com/v1",
                "api_key": "sk-list-alias-only",
            }
        ],
    )
    listing = cm_api.list_custom_models(model_app)
    item = listing["items"][0]
    assert item["apiKey"] == "********"
    assert "api_key" not in item
    assert "sk-list-alias-only" not in json.dumps(listing)



# ---------------------------------------------------------------------------
# W-AUDIT-PROBE-SECRET-001：掩码 key 只能在同一档案作用域内恢复
# ---------------------------------------------------------------------------


def _seed_probe_profile(model_app):
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Scoped",
            "model_ids": ["scoped-a", "scoped-b"],
            "default_model_id": "scoped-a",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-scoped-stored-key",
            "provider": "custom_openai",
        },
    )


def _masked_probe_payload(**overrides) -> dict:
    payload = {
        "name": "Scoped",
        "model_ids": ["scoped-a", "scoped-b"],
        "default_model_id": "scoped-a",
        "mode": "openai",
        "endpoint": "https://api.example.com/v1",
        "apiKey": "********",
        "provider": "custom_openai",
        "model_id": "scoped-a",
    }
    payload.update(overrides)
    return payload


def test_probe_masked_key_same_scope_restores_stored_key(model_app):
    _seed_probe_profile(model_app)
    resolved = cm_api.resolve_probe_credentials(
        model_app, _masked_probe_payload(), index=0
    )
    assert resolved["apiKey"] == "sk-scoped-stored-key"
    assert resolved["endpoint"] == "https://api.example.com/v1"
    assert resolved["default_model_id"] == "scoped-a"


def test_probe_masked_key_with_changed_endpoint_requires_new_key(model_app):
    from app.api_probe import ProbeScopeViolation

    _seed_probe_profile(model_app)
    with pytest.raises(ProbeScopeViolation) as exc:
        cm_api.resolve_probe_credentials(
            model_app,
            _masked_probe_payload(endpoint="https://attacker.example.net/v1"),
            index=0,
        )
    assert exc.value.error_code == "probe_scope_violation"


def test_probe_masked_key_with_changed_provider_requires_new_key(model_app):
    from app.api_probe import ProbeScopeViolation

    _seed_probe_profile(model_app)
    with pytest.raises(ProbeScopeViolation):
        cm_api.resolve_probe_credentials(
            model_app,
            _masked_probe_payload(provider="custom_doubao"),
            index=0,
        )


def test_probe_masked_key_with_changed_mode_requires_new_key(model_app):
    from app.api_probe import ProbeScopeViolation

    _seed_probe_profile(model_app)
    with pytest.raises(ProbeScopeViolation):
        cm_api.resolve_probe_credentials(
            model_app, _masked_probe_payload(mode="doubao"), index=0
        )


def test_probe_masked_key_with_out_of_profile_model_requires_new_key(model_app):
    from app.api_probe import ProbeScopeViolation

    _seed_probe_profile(model_app)
    with pytest.raises(ProbeScopeViolation):
        cm_api.resolve_probe_credentials(
            model_app, _masked_probe_payload(model_id="not-in-profile"), index=0
        )


def test_probe_masked_key_and_no_existing_record_keeps_empty_key(model_app):
    """没有可命中的档案时不恢复任何 key（不会退回全局/首档案 key）。"""
    resolved = cm_api.resolve_probe_credentials(
        model_app, _masked_probe_payload(), index=-1
    )
    assert resolved["apiKey"] == ""


def test_probe_explicit_new_key_allows_changed_endpoint(model_app):
    """显式提供新 key 时允许探测新 endpoint（用户主动输入新凭据的合法路径）。"""
    _seed_probe_profile(model_app)
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        _masked_probe_payload(
            endpoint="https://attacker.example.net/v1",
            apiKey="sk-caller-supplied-key",
        ),
        index=0,
    )
    assert resolved["apiKey"] == "sk-caller-supplied-key"
    assert resolved["endpoint"] == "https://attacker.example.net/v1"


def test_custom_model_probe_http_rejects_masked_key_with_changed_endpoint(tmp_path):
    """POST /api/custom-models/probe 掩码 key + 改 endpoint → 400，不发 probe。"""
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    config = ConfigStore(db_path=tmp_path / "probe-scope.db")
    danmu_app = SimpleNamespace(
        config=config,
        config_changed=MagicMock(),
        probe_api_connection=MagicMock(return_value={"ok": True, "message": "ok"}),
    )
    bridge.danmu_app = danmu_app

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app, raise_server_exceptions=False)

    created = client.post(
        "/api/custom-models",
        json={
            "name": "Scoped",
            "model_ids": ["scoped-a"],
            "default_model_id": "scoped-a",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-scoped-http-key",
            "provider": "custom_openai",
        },
    )
    assert created.status_code == 200

    with patch("app.api_probe.probe_connection") as mock_probe:
        res = client.post(
            "/api/custom-models/probe",
            json={
                "name": "Scoped",
                "model_ids": ["scoped-a"],
                "default_model_id": "scoped-a",
                "mode": "openai",
                "endpoint": "https://attacker.example.net/v1",
                "apiKey": "********",
                "provider": "custom_openai",
                "index": 0,
                "model_id": "scoped-a",
            },
        )
    assert res.status_code == 400, res.text
    detail = res.json()["detail"]
    assert detail["ok"] is False
    assert detail["error"] == "probe_scope_violation"
    assert "sk-scoped-http-key" not in res.text
    mock_probe.assert_not_called()
    danmu_app.probe_api_connection.assert_not_called()


def test_custom_model_probe_http_allows_same_scope_masked_key(tmp_path):
    """同一档案、作用域未变更时 probe 仍可复用已存 key，并把档案参数交给探测。"""
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    config = ConfigStore(db_path=tmp_path / "probe-ok.db")
    danmu_app = SimpleNamespace(
        config=config,
        config_changed=MagicMock(),
        probe_api_connection=MagicMock(return_value={"ok": True, "message": "ok"}),
    )
    bridge.danmu_app = danmu_app

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app, raise_server_exceptions=False)

    client.post(
        "/api/custom-models",
        json={
            "name": "Scoped",
            "model_ids": ["scoped-a"],
            "default_model_id": "scoped-a",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-scoped-http-key",
            "provider": "custom_openai",
        },
    )
    with patch("app.api_probe.probe_connection") as mock_probe:
        mock_probe.return_value.to_dict.return_value = {"ok": True, "message": "ok"}
        res = client.post(
            "/api/custom-models/probe",
            json={
                "name": "Scoped",
                "model_ids": ["scoped-a"],
                "default_model_id": "scoped-a",
                "mode": "openai",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "********",
                "provider": "custom_openai",
                "index": 0,
                "model_id": "scoped-a",
                "stage": "full",
            },
        )
    assert res.status_code == 200, res.text
    assert res.json()["ok"] is True
    args, kwargs = mock_probe.call_args
    assert args == (
        "https://api.example.com/v1",
        "sk-scoped-http-key",
        "scoped-a",
        "openai-compatible",
    )
    assert kwargs["stage"] == "full"
    assert kwargs["profile_params"]["thinking_effort"] == "off"
    assert kwargs["profile_params"]["max_tokens"] == 512


# ---------------------------------------------------------------------------
# W-AUDIT-PROBE-SECRET-001：模型弹窗凭据作用域变更 → 使"沿用旧 key"失效
# ---------------------------------------------------------------------------


def test_model_modal_probe_exports_scope_fingerprint_and_stored_key_marker():
    src = SETTINGS_MODEL_MODAL_PROBE_JS.read_text(encoding="utf-8")
    assert "export function buildProbeScopeFingerprint(form = {})" in src
    assert "export function markModelModalStoredKey()" in src
    assert "clearStoredKeyIfScopeChanged" in src
    assert 'input.value = "";' in src
    assert "探测目标已修改_请重新输入_API_Key" in src


def test_model_modal_form_registers_stored_key_scope_when_opened():
    src = SETTINGS_MODEL_MODAL_FORM_JS.read_text(encoding="utf-8")
    assert "markModelModalStoredKey," in src.replace("\n", " ")
    assert "markModelModalStoredKey();" in src


def test_scope_rekey_locale_entries_exist_in_both_languages():
    for lang in ("zh", "en"):
        data = json.loads(
            (
                REPO_ROOT / "web" / "static" / "locales" / lang / "dynamic.json"
            ).read_text(encoding="utf-8")
        )
        custom_models = data["dynamic"]["settingsCustomModels"]
        assert "探测目标已修改" in custom_models
        assert "探测目标已修改_请重新输入_API_Key" in custom_models

# ---------------------------------------------------------------------------
# W-AUDIT-MODEL-IDENTITY-001：档案不可变 profile_id、按 profile_id 定位/清理、
# 探测身份判定与迁移诊断（工单 §5.1 / §5.3 / §6）
# ---------------------------------------------------------------------------


def _identity_diagnostics(app):
    return cm_api.list_custom_models(app)["identity_diagnostics"]


def test_create_assigns_unique_nonempty_profile_id_and_ignores_input(model_app):
    """创建时服务端分配非空且唯一的 profile_id；入参 profile_id 被忽略。"""
    cm_api.create_custom_model(
        model_app, {**_model_payload("dup-model", name="A"), "profile_id": "cmp_forged"}
    )
    cm_api.create_custom_model(
        model_app, {**_model_payload("dup-model", name="B"), "profile_id": "cmp_forged"}
    )
    profiles = model_app.config.get_custom_models()
    ids = [p["profile_id"] for p in profiles]
    assert all(isinstance(pid, str) and pid for pid in ids)
    assert len(set(ids)) == 2
    assert "cmp_forged" not in ids
    # 两个档案共享同一上游模型名仍合法
    assert {p["default_model_id"] for p in profiles} == {"dup-model"}


def test_update_locates_by_profile_id_and_keeps_identity(model_app):
    """更新以 profile_id 为准（index 只作兼容），改名/改 endpoint 后身份不变。"""
    cm_api.create_custom_model(model_app, _model_payload("dup-model", name="A"))
    cm_api.create_custom_model(model_app, _model_payload("dup-model", name="B"))
    profiles = model_app.config.get_custom_models()
    pid_a, pid_b = profiles[0]["profile_id"], profiles[1]["profile_id"]

    # 故意传陈旧的 index=0 但 profile_id=B → 必须更新 B
    updated = cm_api.update_custom_model(
        model_app,
        0,
        {
            **_model_payload(
                "renamed-model",
                name="B-renamed",
                endpoint="https://renamed.example.com/v1",
            ),
            "profile_id": pid_b,
        },
    )
    assert updated["index"] == 1
    profiles = model_app.config.get_custom_models()
    assert profiles[0]["profile_id"] == pid_a
    assert profiles[1]["profile_id"] == pid_b
    assert profiles[0]["name"] == "A"
    assert profiles[1]["name"] == "B-renamed"
    assert profiles[1]["endpoint"] == "https://renamed.example.com/v1"
    assert profiles[1]["default_model_id"] == "renamed-model"


def test_update_unknown_profile_id_raises(model_app):
    """profile_id 不存在 → 明确错误（不静默改写其它档案）。"""
    cm_api.create_custom_model(model_app, _model_payload("dup-model", name="A"))
    with pytest.raises(ValueError, match="模型档案不存在"):
        cm_api.update_custom_model(
            model_app,
            0,
            {**_model_payload("dup-model"), "profile_id": "cmp_missing"},
        )


def test_delete_duplicate_name_preserves_historical_profile_references(tmp_path):
    """删除档案不主动清理已退出产品能力的历史人格绑定。"""
    from app.persona_manager import PersonaManager

    config = ConfigStore(db_path=tmp_path / "config.db")
    personae = PersonaManager(config)
    app = SimpleNamespace(config=config, config_changed=MagicMock(), personae=personae)

    cm_api.create_custom_model(app, _model_payload("dup-model", name="A"))
    cm_api.create_custom_model(app, _model_payload("dup-model", name="B"))
    profiles = config.get_custom_models()
    pid_a, pid_b = profiles[0]["profile_id"], profiles[1]["profile_id"]

    personae.set_model_binding("甲方", profile_id=pid_a)
    personae.set_model_binding("乙方", profile_id=pid_b)

    cm_api.delete_custom_model(app, 0)

    historical = json.loads(config.get("persona_model_bindings", "{}"))
    assert historical["甲方"]["profile_id"] == pid_a
    assert historical["乙方"]["profile_id"] == pid_b
    remaining = config.get_custom_models()
    assert len(remaining) == 1
    assert remaining[0]["profile_id"] == pid_b


def test_identity_diagnostics_report_missing_and_duplicate_profile_ids(model_app):
    """缺失 / 重复身份必须产生明确诊断（不自动删改数据制造表面一致）。"""
    from app.config_store.storage_models import invalidate_custom_models_cache_for_store

    base = {
        "model_ids": ["m"],
        "default_model_id": "m",
        "mode": "openai-compatible",
        "endpoint": "https://api.example.com/v1",
        "apiKey": "",
    }
    raw = [
        {**base, "name": "Dup1", "profile_id": "cmp_dup"},
        {**base, "name": "Dup2", "profile_id": "cmp_dup"},
        {**base, "name": "Missing"},
    ]
    model_app.config.set("custom_models", json.dumps(raw))
    invalidate_custom_models_cache_for_store(model_app.config)

    codes = [issue["code"] for issue in _identity_diagnostics(model_app)["profiles"]]
    assert "profile_id_duplicate" in codes
    assert "profile_id_missing" in codes


def test_identity_diagnostics_no_longer_projects_persona_bindings(model_app):
    """人格模型绑定保留在历史配置中，但不再进入模型 API 诊断投影。"""
    cm_api.create_custom_model(model_app, _model_payload("real-model"))
    model_app.config.set(
        "persona_model_bindings", json.dumps({"高压吐槽型": "ghost-model"})
    )
    diagnostics = _identity_diagnostics(model_app)
    assert "persona_bindings" not in diagnostics
    assert json.loads(model_app.config.get("persona_model_bindings"))["高压吐槽型"] == "ghost-model"


def test_probe_masked_key_recovered_within_same_profile_id(model_app):
    """掩码 key + 同一 profile_id + 未变作用域 → 恢复档案已存 key。"""
    cm_api.create_custom_model(
        model_app, _model_payload("probe-model", apiKey="sk-probe-key-1234567890")
    )
    pid = model_app.config.get_custom_models()[0]["profile_id"]
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            **_model_payload("probe-model", apiKey="********"),
            "profile_id": pid,
            "model_id": "probe-model",
        },
        0,
    )
    assert resolved["apiKey"] == "sk-probe-key-1234567890"


def test_probe_masked_key_not_reused_across_profiles(model_app):
    """掩码 key 只在同一 profile_id 作用域内恢复，绝不跨档案泄漏旧 key。"""
    cm_api.create_custom_model(
        model_app, _model_payload("probe-model", apiKey="sk-probe-key-1234567890")
    )
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            **_model_payload("probe-model", apiKey="********"),
            "profile_id": "cmp_unknown",
            "model_id": "probe-model",
        },
        0,
    )
    assert resolved["apiKey"] == ""


def test_probe_masked_key_scope_violation_on_endpoint_change(model_app):
    """同一 profile_id 但改了出站 endpoint → 拒绝沿用已存 key。"""
    from app.api_probe import ProbeScopeViolation

    cm_api.create_custom_model(
        model_app, _model_payload("probe-model", apiKey="sk-probe-key-1234567890")
    )
    pid = model_app.config.get_custom_models()[0]["profile_id"]
    with pytest.raises(ProbeScopeViolation):
        cm_api.resolve_probe_credentials(
            model_app,
            {
                **_model_payload(
                    "probe-model",
                    apiKey="********",
                    endpoint="https://evil.example.com/v1",
                ),
                "profile_id": pid,
                "model_id": "probe-model",
            },
            0,
        )


def test_model_modal_form_carries_profile_id_hidden_field():
    """模型弹窗编辑时携带 profile_id 隐藏字段并在提交体里回传。"""
    modals = MODALS_HTML.read_text(encoding="utf-8")
    form_src = SETTINGS_MODEL_MODAL_FORM_JS.read_text(encoding="utf-8")
    assert 'id="modelEditProfileId"' in modals
    assert 'document.getElementById("modelEditProfileId")' in form_src
    assert "profile_id:" in form_src


# ---------------------------------------------------------------------------
# W-AUDIT-PROBE-PARITY-001：分阶段探活合同与只读性
# ---------------------------------------------------------------------------


def test_custom_model_probe_route_is_read_only(tmp_path):
    """完整链 probe 只读：只访问 app.config，不触碰任何运行态或主链路入口。"""
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    config = ConfigStore(db_path=tmp_path / "probe-readonly.db")
    danmu_app = MagicMock()
    danmu_app.config = config
    bridge.danmu_app = danmu_app

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app, raise_server_exceptions=False)

    client.post(
        "/api/custom-models",
        json={
            "name": "RO",
            "model_ids": ["ro-model"],
            "default_model_id": "ro-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-ro-key",
            "provider": "custom_openai",
        },
    )
    danmu_app.reset_mock()

    runtime = SimpleNamespace(
        ai_in_flight=0,
        request_meta={},
        token_stats={"input": 0, "output": 0},
        danmu_stats={},
        failure_count=0,
        empty_parse_count=0,
        reply_buffer=[],
        scene_generation=7,
    )
    before = json.dumps(vars(runtime), sort_keys=True, default=str)

    with patch("app.api_probe.probe_connection") as mock_probe:
        mock_probe.return_value.to_dict.return_value = {
            "ok": True,
            "message": "ok",
            "complete": True,
            "stages": [],
        }
        res = client.post(
            "/api/custom-models/probe",
            json={
                "name": "RO",
                "model_ids": ["ro-model"],
                "default_model_id": "ro-model",
                "mode": "openai",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "********",
                "provider": "custom_openai",
                "index": 0,
                "model_id": "ro-model",
                "stage": "full",
            },
        )
    assert res.status_code == 200, res.text

    after = json.dumps(vars(runtime), sort_keys=True, default=str)
    assert after == before, "probe 不得改变运行态字段"
    # danmu_app.config 是真实 ConfigStore，因此父 mock 不应记录到任何调用：
    # probe 路径完全没有触碰 DanmuApp 自身的方法/属性。
    assert danmu_app.mock_calls == [], f"probe 不应调用 DanmuApp 方法：{danmu_app.mock_calls}"
    for name in (
        "_on_ai_reply",
        "_trigger_api_call",
        "enqueue_reply_batch_for_pipeline",
        "display_danmu_text",
        "publish_live_status",
        "broadcast_live_overlay_item",
        "record_undisplayed",
        "update_stats_from_pipeline",
        "probe_api_connection",
    ):
        assert getattr(danmu_app, name).call_count == 0, name


def test_custom_model_probe_returns_profile_id_binding(tmp_path):
    """探活结果携带触发时的 profile_id，供 UI 使旧结果失效。"""
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    config = ConfigStore(db_path=tmp_path / "probe-binding.db")
    danmu_app = SimpleNamespace(config=config, config_changed=MagicMock())
    bridge.danmu_app = danmu_app

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app, raise_server_exceptions=False)

    client.post(
        "/api/custom-models",
        json={
            "name": "Bind",
            "model_ids": ["bind-model"],
            "default_model_id": "bind-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-bind-key",
            "provider": "custom_openai",
        },
    )
    profile_id = config.get_custom_models()[0]["profile_id"]
    assert profile_id
    with patch("app.api_probe.probe_connection") as mock_probe:
        mock_probe.return_value.to_dict.return_value = {"ok": True, "message": "ok"}
        res = client.post(
            "/api/custom-models/probe",
            json={
                "name": "Bind",
                "model_ids": ["bind-model"],
                "default_model_id": "bind-model",
                "mode": "openai",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "********",
                "provider": "custom_openai",
                "index": 0,
                "model_id": "bind-model",
                "stage": "full",
            },
        )
    assert res.status_code == 200, res.text
    assert res.json()["profile_id"] == profile_id


def test_model_modal_probe_stage_contract_sources():
    """前端默认执行完整阶段链，并逐项渲染阶段状态（源码静态合同）。"""
    src = SETTINGS_MODEL_MODAL_PROBE_JS.read_text(encoding="utf-8")
    assert 'stage: "full"' in src
    assert "MODEL_PROBE_STAGE_ORDER" in src
    for stage in ("local", "auth_model", "text", "vision_stream", "business_parse"):
        assert f'"{stage}"' in src
    assert "renderProbeStages" in src
    assert 'result.ok && result.complete' in src
    assert "完整视觉链路可用" in src
    assert "文本连接可用_完整视觉链路未通过" in src
    # 取消（AbortError）不得渲染为 provider 失败
    assert 'error?.name === "AbortError"' in src
    modals = MODALS_HTML.read_text(encoding="utf-8")
    assert 'id="modelProbeStages"' in modals
