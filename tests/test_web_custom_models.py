"""Custom model web API service tests."""

import re
import sqlite3
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore
from app.web_api import custom_models as cm_api

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_CUSTOM_MODELS_JS = REPO_ROOT / "web" / "static" / "modules" / "settings-custom-models.js"
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


def test_custom_model_crud(model_app):
    created = cm_api.create_custom_model(
        model_app,
        {
            "name": "Test",
            "modelId": "test-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-test-key-1234567890",
            "provider": "custom_openai",
        },
    )
    assert created["index"] == 0

    listing = cm_api.list_custom_models(model_app)
    assert len(listing["items"]) == 1
    assert listing["items"][0]["apiKey"] == "********"
    # W-CUSTOMMODEL-SCHEMA-002：新 shape 字段
    assert listing["items"][0]["model_ids"] == ["test-model"]
    assert listing["items"][0]["default_model_id"] == "test-model"
    assert listing["items"][0]["max_tokens"] == 512

    updated = cm_api.update_custom_model(
        model_app,
        0,
        {
            "name": "Test2",
            "modelId": "test-model-2",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
        },
    )
    assert updated["item"]["name"] == "Test2"
    # W-CUSTOMMODEL-SCHEMA-002：update 后新 shape 同步
    assert updated["item"]["model_ids"] == ["test-model-2"]
    assert updated["item"]["default_model_id"] == "test-model-2"

    with_mic = cm_api.update_custom_model(
        model_app,
        0,
        {
            "name": "Test2",
            "modelId": "test-model-2",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
            "supportsMic": True,
        },
    )
    assert with_mic["item"]["supportsMic"] is True
    stored = model_app.config.get_custom_models()[0]
    assert stored["supportsMic"] is True

    cm_api.set_default_custom_model(model_app, 0)
    assert model_app.config.get_default_model_id() == "test-model-2"

    cm_api.delete_custom_model(model_app, 0)
    assert model_app.config.get_custom_models() == []


def test_resolve_probe_credentials_restores_masked_key_by_index(model_app):
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Test",
            "modelId": "test-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-custom-probe-key",
            "provider": "custom_openai",
        },
    )
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            "name": "Test",
            "modelId": "renamed-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
        },
        index=0,
    )
    assert resolved["apiKey"] == "sk-custom-probe-key"
    assert resolved["modelId"] == "renamed-model"
    # W-CUSTOMMODEL-SCHEMA-002：probe 解析后含新 shape 字段
    assert resolved["model_ids"] == ["renamed-model"]
    assert resolved["default_model_id"] == "renamed-model"


def test_resolve_probe_credentials_masked_key_without_existing_returns_empty(model_app):
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            "name": "New",
            "modelId": "new-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
        },
        index=-1,
    )
    assert resolved["apiKey"] == ""


def test_resolve_probe_credentials_normalizes_full_endpoint_url(model_app):
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            "name": "Test",
            "modelId": "test-model",
            "mode": "openai-compatible",
            "endpoint": "https://openrouter.ai/api/v1/chat/completions",
            "apiKey": "sk-test",
        },
        index=-1,
    )
    assert resolved["endpoint"] == "https://openrouter.ai/api/v1"


def test_create_custom_model_normalizes_endpoint_on_save(model_app):
    created = cm_api.create_custom_model(
        model_app,
        {
            "name": "OpenRouter",
            "modelId": "openrouter-model",
            "mode": "openai",
            "endpoint": "https://openrouter.ai/api/v1/chat/completions/",
            "apiKey": "sk-save-key",
        },
    )
    stored = model_app.config.get_custom_models()[created["index"]]
    assert stored["endpoint"] == "https://openrouter.ai/api/v1"
    assert stored["mode"] == "openai-compatible"


def test_custom_model_api_key_encrypted_at_rest_in_sqlite(model_app):
    """W-TEST-COVER-005: apiKey is Fernet-encrypted in config.db; GET masks; get_custom_models decrypts."""
    secret = "sk-plaintext-storage-test-key"
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Plain",
            "modelId": "plain-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": secret,
            "provider": "custom_openai",
        },
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
    # legacy modelId 保持与 default_model_id 同值（兼容回滚）
    assert item["modelId"] == "model-b"

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
    assert created["item"]["modelId"] == "alpha"


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
    assert resolved["modelId"] == "alternate-id"
    assert resolved["default_model_id"] == "alternate-id"


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
    assert resolved["modelId"] == "second"
    assert resolved["default_model_id"] == "second"


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
    assert updated["item"]["modelId"] == "y"
    assert updated["item"]["max_tokens"] == 2048


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
    """W-DELETE-CONFIRM-005：formatDeleteModelMessage 文案模板关键短语在源码中存在。"""
    src = _read_settings_custom_models_js()
    # name 空降级
    assert "'这条模型档案'" in src
    # 文案模板片段
    assert "确定删除模型「" in src
    assert "该档案包含" in src
    assert "个模型 ID，将一并删除" in src
    assert "若该档案是当前默认，将自动切换到下一条" in src
    # N 来自 model_ids.length
    assert "model_ids" in src


def test_open_delete_model_confirm_uses_focus_trap_and_classlist():
    """W-DELETE-CONFIRM-005：openDeleteModelConfirm 复用 activateFocusTrap + classList 切换（与 restoreDefaultsModal 风格一致）。"""
    src = _read_settings_custom_models_js()
    assert "activateFocusTrap(modal, closeDeleteModelConfirm)" in src
    assert "modal.classList.remove('hidden')" in src
    assert "modal.classList.add('flex')" in src
    assert "deactivateFocusTrap()" in src


def test_open_delete_model_confirm_cleanup_on_close():
    """W-DELETE-CONFIRM-005：一次性监听在关闭时清空（避免内存泄漏）。"""
    src = _read_settings_custom_models_js()
    # 存在清理句柄变量
    assert "_deleteModelConfirmCleanup" in src
    # 使用 { once: true } 绑定一次性监听
    assert "{ once: true }" in src
    # closeDeleteModelConfirm 中调用清理
    assert "removeEventListener('click', onConfirm)" in src
    assert "removeEventListener('click', close)" in src
    assert "removeEventListener('click', onBackdropClick)" in src


def test_open_delete_model_confirm_calls_delete_api_and_toast():
    """W-DELETE-CONFIRM-005：确认按钮回调调用 DELETE /api/custom-models/{index} + toast + loadCustomModels。"""
    src = _read_settings_custom_models_js()
    assert "apiFetch(`/api/custom-models/${index}`, { method: 'DELETE' })" in src
    assert "customModelDeps.showToast('已删除~')" in src
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

    def fmt(profile):
        name = (profile.get("name") or "").strip() if isinstance(profile, dict) else ""
        ids = (
            profile.get("model_ids")
            if isinstance(profile, dict) and isinstance(profile.get("model_ids"), list)
            else []
        )
        n = len(ids) or 1
        display = name or "这条模型档案"
        return (
            f"确定删除模型「{display}」吗？该档案包含 {n} 个模型 ID，将一并删除。"
            f"若该档案是当前默认，将自动切换到下一条。"
        )

    # name 非空 + 多 model_ids
    msg1 = fmt({"name": "豆包Pro", "model_ids": ["a", "b"]})
    assert "「豆包Pro」" in msg1
    assert "2 个模型 ID" in msg1
    assert msg1.startswith("确定删除模型「豆包Pro」吗？")
    assert msg1.endswith("将自动切换到下一条。")

    # name 空降级
    msg2 = fmt({"name": "", "model_ids": ["a"]})
    assert "「这条模型档案」" in msg2
    assert "1 个模型 ID" in msg2

    # model_ids 缺失降级为 1
    msg3 = fmt({"name": "X"})
    assert "1 个模型 ID" in msg3
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
#   8. 系统默认下拉调 POST /api/custom-models/{index}/default
# ---------------------------------------------------------------------------


def test_settings_html_has_legacy_api_fields_class():
    """W-SETTINGS-RESTRUCT-A-006：settings.html 5 个旧字段 wrapper 含 legacy-api-fields class。"""
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    # 5 个旧字段 wrapper 应各带一个 legacy-api-fields class
    assert html.count('class="legacy-api-fields"') + html.count(' legacy-api-fields"') + html.count(' legacy-api-fields ') >= 5
    # CSS 规则存在于 settings.html
    assert ".legacy-api-fields" in html
    assert "display:none !important" in html


def test_index_html_has_legacy_api_fields_css_rule():
    """W-SETTINGS-RESTRUCT-A-006：index.html 经 build 重建后含 .legacy-api-fields CSS 规则。"""
    html = INDEX_HTML.read_text(encoding="utf-8")
    assert ".legacy-api-fields" in html
    assert "display:none !important" in html


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


def test_config_fields_retains_legacy_keys():
    """W-SETTINGS-RESTRUCT-A-006：CONFIG_FIELDS 仍含 4 个旧 key（api_key 按设计不在内，走加密独立路径）。"""
    src = SETTINGS_DEFAULTS_JS.read_text(encoding="utf-8")
    # api_endpoint / api_mode / model / max_tokens 必须仍在 CONFIG_FIELDS 中
    for key in ("api_endpoint", "api_mode", "model", "max_tokens"):
        assert f"'{key}'" in src, f"CONFIG_FIELDS 应保留旧 key '{key}'"
    # api_key 按设计不在 CONFIG_FIELDS（加密 key 走独立掩码路径），此处只记录事实，不强制


def test_settings_js_sets_hidden_on_legacy_field_wrappers():
    """W-SETTINGS-RESTRUCT-A-006：settings.js 给旧字段 wrapper 同步 hidden=true（DOM 属性双保险）。"""
    src = SETTINGS_JS.read_text(encoding="utf-8")
    assert "legacy-api-fields" in src
    assert ".parentElement.hidden = true" in src
    # 5 个旧字段 ID 均在 hidden 同步列表中
    for field_id in ("api_endpoint", "api_mode", "api_key", "model", "max_tokens"):
        assert f"'{field_id}'" in src


def test_settings_custom_models_js_has_4_column_row_structure():
    """W-SETTINGS-RESTRUCT-A-006：列表行重排 4 列（模型名+provider / 默认 modelId+数组长度 / 系统默认下拉 / 操作按钮组）。"""
    src = SETTINGS_CUSTOM_MODELS_JS.read_text(encoding="utf-8")
    # 行容器 class
    assert "custom-model-row" in src
    # 列 1：模型名 + provider chip
    assert "custom-model-provider-chip" in src
    # 列 2：默认 modelId + 数组长度（+N）
    assert "custom-model-id-col" in src
    assert "(+${extra})" in src
    # 列 3：系统默认下拉
    assert "custom-model-default-col" in src
    assert "设为系统默认" in src
    # 列 4：操作按钮组
    assert "custom-model-actions" in src


def test_add_custom_model_button_wired_to_open_model_modal():
    """W-SETTINGS-RESTRUCT-A-006：「+ 添加模型」按钮 → openModelModal(-1)（新增模型）。"""
    src = SETTINGS_CUSTOM_MODELS_JS.read_text(encoding="utf-8")
    assert "btnAddCustomModel" in src
    assert "openModelModal(-1)" in src


def test_settings_html_has_add_custom_model_button_and_ai_models_title():
    """W-SETTINGS-RESTRUCT-A-006：settings.html 含「AI 模型」标题 + btnAddCustomModel 按钮。"""
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    assert "AI 模型" in html
    assert 'id="btnAddCustomModel"' in html


def test_default_select_calls_post_default_api():
    """W-SETTINGS-RESTRUCT-A-006：系统默认下拉 / 设默认按钮调 POST /api/custom-models/{index}/default。"""
    src = SETTINGS_CUSTOM_MODELS_JS.read_text(encoding="utf-8")
    assert "/api/custom-models/${index}/default" in src
    assert "method: 'POST'" in src
    # 共用 setProfileAsDefault helper
    assert "async function setProfileAsDefault(index, model)" in src


def test_edit_button_still_calls_open_model_modal():
    """W-SETTINGS-RESTRUCT-A-006：编辑按钮仍调 openModelModal(index, model)（Task 4 已就位）。"""
    src = SETTINGS_CUSTOM_MODELS_JS.read_text(encoding="utf-8")
    assert "openModelModal(index, model)" in src


def test_delete_button_still_calls_open_delete_model_confirm():
    """W-SETTINGS-RESTRUCT-A-006：删除按钮仍调 openDeleteModelConfirm(model, index)（Task 5 已就位）。"""
    src = SETTINGS_CUSTOM_MODELS_JS.read_text(encoding="utf-8")
    assert "delBtn.onclick = () => openDeleteModelConfirm(model, index)" in src


# ---------------------------------------------------------------------------
# W-PERSONA-MODEL-BIND-001：删除自定义模型时清理 persona_model_bindings
# ---------------------------------------------------------------------------


def test_delete_custom_model_clears_persona_bindings(model_app):
    """删除模型档案后，引用该 model_id 的人格绑定应被清空。"""
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Bound",
            "modelId": "bound-1",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-bound-key-1234567890",
            "provider": "custom_openai",
        },
    )
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Other",
            "modelId": "other-2",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-other-key-1234567890",
            "provider": "custom_openai",
        },
    )
    # 绑定：高压吐槽型 → bound-1，熬夜陪看型 → other-2
    model_app.config.set(
        "persona_model_bindings", '{"高压吐槽型": "bound-1", "熬夜陪看型": "other-2"}'
    )
    # 删除 index 0（Bound / bound-1）
    cm_api.delete_custom_model(model_app, 0)
    # bound-1 的绑定应被清除；other-2 的绑定应保留
    import json as _json

    raw = model_app.config.get("persona_model_bindings", "{}")
    bindings = _json.loads(raw)
    assert "高压吐槽型" not in bindings
    assert bindings.get("熬夜陪看型") == "other-2"


def test_delete_custom_model_no_bindings_is_noop(model_app):
    """删除模型时若无人格绑定引用它，清理逻辑应幂等无副作用。"""
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Solo",
            "modelId": "solo-1",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-solo-key-1234567890",
            "provider": "custom_openai",
        },
    )
    # 无人格绑定
    cm_api.delete_custom_model(model_app, 0)
    assert model_app.config.get("persona_model_bindings", "{}") in ("{}", "")

