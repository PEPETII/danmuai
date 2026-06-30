"""W-CUSTOMMODEL-SCHEMA-002: CustomModel 1:N shape 迁移测试。

覆盖 5 种情形：
1. 旧 shape 升级（modelId 单值 → model_ids 数组 + default_model_id + max_tokens）
2. 新 shape 直写（model_ids + default_model_id → 写入成功；GET 返回含上述字段）
3. model_ids 空数组 → 400（validate_model_config 拒绝）
4. default_model_id 不在 model_ids 数组中 → 400
5. max_tokens 默认值（POST 不含 max_tokens → 默认 512）
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore, _migrate_custom_model_shape
from app.web_api import custom_models as cm_api


@pytest.fixture
def model_app(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config.db")
    app = SimpleNamespace(config=config, config_changed=MagicMock())
    return app


def _legacy_model(model_id: str = "legacy-model", name: str = "Legacy") -> dict:
    """旧 shape：仅有 modelId 单值，无 model_ids / default_model_id / max_tokens。"""
    return {
        "name": name,
        "modelId": model_id,
        "mode": "openai",
        "endpoint": "https://api.example.com/v1",
        "apiKey": "sk-legacy-key-1234567890",
        "provider": "custom_openai",
    }


# --- Step 8 测试情形 1：旧 shape 升级 ---

def test_migrate_custom_model_shape_legacy_to_new():
    """旧 shape（仅有 modelId）→ 自动补齐 model_ids / default_model_id / max_tokens。"""
    legacy = _legacy_model("gpt-4o", "GPT4o")
    migrated = _migrate_custom_model_shape(dict(legacy))
    assert migrated["model_ids"] == ["gpt-4o"]
    assert migrated["default_model_id"] == "gpt-4o"
    assert migrated["max_tokens"] == 512
    # 旧 modelId 字段保留
    assert migrated["modelId"] == "gpt-4o"


def test_get_custom_models_migrates_legacy_shape_in_place(model_app):
    """get_custom_models() 读到旧档案 → 自动补齐新字段（不写回 DB）。"""
    legacy = _legacy_model("legacy-model", "Legacy")
    # 直接写入旧 shape（绕过 _normalize_payload）
    model_app.config.set_custom_models([legacy])

    # 首次读取：应自动迁移
    models = model_app.config.get_custom_models()
    assert len(models) == 1
    m = models[0]
    assert m["model_ids"] == ["legacy-model"]
    assert m["default_model_id"] == "legacy-model"
    assert m["max_tokens"] == 512
    # 旧 modelId 保留
    assert m["modelId"] == "legacy-model"


def test_get_custom_models_migration_is_idempotent(model_app):
    """迁移幂等：多次读取不重复补齐。"""
    legacy = _legacy_model("legacy-model", "Legacy")
    model_app.config.set_custom_models([legacy])

    first = model_app.config.get_custom_models()
    second = model_app.config.get_custom_models()
    assert first[0]["model_ids"] == ["legacy-model"]
    assert second[0]["model_ids"] == ["legacy-model"]
    assert first[0]["default_model_id"] == second[0]["default_model_id"]


def test_get_custom_models_preserves_new_shape(model_app):
    """新 shape 档案读取后保持不变。"""
    new_shape = {
        "name": "Multi",
        "modelId": "gpt-4o",
        "model_ids": ["gpt-4o", "gpt-4o-mini"],
        "default_model_id": "gpt-4o",
        "max_tokens": 1024,
        "mode": "openai",
        "endpoint": "https://api.example.com/v1",
        "apiKey": "sk-multi-key-1234567890",
        "provider": "custom_openai",
    }
    model_app.config.set_custom_models([new_shape])
    models = model_app.config.get_custom_models()
    assert models[0]["model_ids"] == ["gpt-4o", "gpt-4o-mini"]
    assert models[0]["default_model_id"] == "gpt-4o"
    assert models[0]["max_tokens"] == 1024


def test_get_custom_models_empty_model_id_yields_empty_model_ids(model_app):
    """旧 modelId 为空 → model_ids 为空数组（不阻止返回，但 validate 会拒绝保存）。"""
    legacy_empty = {
        "name": "Empty",
        "modelId": "",
        "mode": "openai",
        "endpoint": "https://api.example.com/v1",
        "apiKey": "sk-empty-key-1234567890",
        "provider": "custom_openai",
    }
    model_app.config.set_custom_models([legacy_empty])
    models = model_app.config.get_custom_models()
    assert models[0]["model_ids"] == []
    assert models[0]["default_model_id"] == ""


# --- Step 8 测试情形 2：新 shape 直写 ---

def test_create_custom_model_with_model_ids_succeeds(model_app):
    """POST 入参含 model_ids + default_model_id → 写入成功；GET 返回含上述字段。"""
    created = cm_api.create_custom_model(
        model_app,
        {
            "name": "Multi-Model",
            "model_ids": ["gpt-4o", "gpt-4o-mini"],
            "default_model_id": "gpt-4o",
            "max_tokens": 1024,
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-multi-key-1234567890",
            "provider": "custom_openai",
        },
    )
    assert created["index"] == 0

    listing = cm_api.list_custom_models(model_app)
    assert len(listing["items"]) == 1
    item = listing["items"][0]
    assert item["model_ids"] == ["gpt-4o", "gpt-4o-mini"]
    assert item["default_model_id"] == "gpt-4o"
    assert item["max_tokens"] == 1024
    # 旧 modelId 字段保留与 default_model_id 同值
    assert item["modelId"] == "gpt-4o"


# --- Step 8 测试情形 3：model_ids 空数组 → 400 ---

def test_create_custom_model_empty_model_ids_rejected(model_app):
    """POST 入参 model_ids=[] → validate_model_config 拒绝。"""
    with pytest.raises(ValueError):
        cm_api.create_custom_model(
            model_app,
            {
                "name": "Empty-Model-IDs",
                "model_ids": [],
                "default_model_id": "",
                "mode": "openai",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "sk-empty-key-1234567890",
                "provider": "custom_openai",
            },
        )


# --- Step 8 测试情形 4：default_model_id 不在数组中 → 400 ---

def test_create_custom_model_default_not_in_model_ids_rejected(model_app):
    """POST 入参 model_ids=["gpt-4o"] + default_model_id="gpt-4o-mini" → 拒绝。"""
    with pytest.raises(ValueError):
        cm_api.create_custom_model(
            model_app,
            {
                "name": "Bad-Default",
                "model_ids": ["gpt-4o"],
                "default_model_id": "gpt-4o-mini",
                "mode": "openai",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "sk-bad-default-1234567890",
                "provider": "custom_openai",
            },
        )


# --- Step 8 测试情形 5：max_tokens 默认值 ---

def test_create_custom_model_max_tokens_defaults_to_512(model_app):
    """POST 入参不含 max_tokens → 默认 512。"""
    created = cm_api.create_custom_model(
        model_app,
        {
            "name": "Default-Tokens",
            "model_ids": ["gpt-4o"],
            "default_model_id": "gpt-4o",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-default-tokens-1234567890",
            "provider": "custom_openai",
        },
    )
    assert created["index"] == 0

    stored = model_app.config.get_custom_models()[0]
    assert stored["max_tokens"] == 512


# --- 补充：旧 modelId 单值 POST 仍可工作（兼容） ---

def test_create_custom_model_legacy_model_id_still_works(model_app):
    """旧 shape POST（仅有 modelId，无 model_ids）→ _normalize_payload 兜底为 model_ids=[modelId]。"""
    created = cm_api.create_custom_model(
        model_app,
        {
            "name": "Legacy-Post",
            "modelId": "legacy-post-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-legacy-post-1234567890",
            "provider": "custom_openai",
        },
    )
    assert created["index"] == 0

    stored = model_app.config.get_custom_models()[0]
    assert stored["model_ids"] == ["legacy-post-model"]
    assert stored["default_model_id"] == "legacy-post-model"
    assert stored["max_tokens"] == 512
    assert stored["modelId"] == "legacy-post-model"


# --- 补充：probe 入参 model_id 缺省取 default_model_id ---

def test_resolve_probe_credentials_model_id_defaults_to_default_model_id(model_app):
    """probe 入参不含 model_id → 取档案的 default_model_id。"""
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Probe-Default",
            "model_ids": ["gpt-4o", "gpt-4o-mini"],
            "default_model_id": "gpt-4o",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-probe-default-1234567890",
            "provider": "custom_openai",
        },
    )
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            "name": "Probe-Default",
            "model_ids": ["gpt-4o", "gpt-4o-mini"],
            "default_model_id": "gpt-4o",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
        },
        index=0,
    )
    # model_id 缺省 → 取 default_model_id
    assert resolved["modelId"] == "gpt-4o"


def test_resolve_probe_credentials_explicit_model_id_overrides_default(model_app):
    """probe 入参指定 model_id → 覆盖 default_model_id。"""
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Probe-Override",
            "model_ids": ["gpt-4o", "gpt-4o-mini"],
            "default_model_id": "gpt-4o",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-probe-override-1234567890",
            "provider": "custom_openai",
        },
    )
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            "name": "Probe-Override",
            "model_ids": ["gpt-4o", "gpt-4o-mini"],
            "default_model_id": "gpt-4o",
            "model_id": "gpt-4o-mini",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
        },
        index=0,
    )
    # model_id 显式指定 → 覆盖 default_model_id
    assert resolved["modelId"] == "gpt-4o-mini"
