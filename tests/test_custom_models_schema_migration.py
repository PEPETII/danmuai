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
from app.config_store import ConfigStore, _migrate_custom_model_shape, canonicalize_custom_model_profile
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


def _write_raw_custom_models(config, models: list[dict]) -> None:
    """绕过 set_custom_models canonicalize，直接写入含 legacy modelId 的 DB JSON。"""
    import json

    config.set("custom_models", json.dumps(models, ensure_ascii=False))
    config._invalidate_custom_models_cache()


# --- Step 8 测试情形 1：旧 shape 升级 ---

def test_migrate_custom_model_shape_legacy_to_new():
    """旧 shape（仅有 modelId）→ 自动补齐 model_ids / default_model_id / max_tokens。"""
    legacy = _legacy_model("gpt-4o", "GPT4o")
    migrated = _migrate_custom_model_shape(dict(legacy))
    assert migrated["model_ids"] == ["gpt-4o"]
    assert migrated["default_model_id"] == "gpt-4o"
    assert migrated["max_tokens"] == 512
    assert "modelId" not in migrated


def test_get_custom_models_migrates_legacy_shape_in_place(model_app):
    """get_custom_models() 读到旧档案 → 自动补齐新字段（不写回 DB）。"""
    legacy = _legacy_model("legacy-model", "Legacy")
    _write_raw_custom_models(model_app.config, [legacy])

    # 首次读取：应自动迁移
    models = model_app.config.get_custom_models()
    assert len(models) == 1
    m = models[0]
    assert m["model_ids"] == ["legacy-model"]
    assert m["default_model_id"] == "legacy-model"
    assert m["max_tokens"] == 512
    assert "modelId" not in m


def test_get_custom_models_migration_is_idempotent(model_app):
    """迁移幂等：多次读取不重复补齐。"""
    legacy = _legacy_model("legacy-model", "Legacy")
    _write_raw_custom_models(model_app.config, [legacy])

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
    assert "modelId" not in models[0]


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
    _write_raw_custom_models(model_app.config, [legacy_empty])
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
    assert "modelId" not in item


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


# --- W-004：legacy-only HTTP POST 拒绝 ---

def test_create_custom_model_legacy_model_id_only_rejected(model_app):
    """旧 shape POST（仅有 modelId，无 model_ids）→ 明确 4xx。"""
    with pytest.raises(ValueError):
        cm_api.create_custom_model(
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
    assert model_app.config.get_custom_models() == []


def test_persisted_custom_models_json_has_no_model_id(model_app):
    """新保存后 DB JSON 与 get_custom_models 均不含 modelId。"""
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Canonical-Only",
            "model_ids": ["gpt-4o"],
            "default_model_id": "gpt-4o",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-canonical-only-1234567890",
            "provider": "custom_openai",
        },
    )
    stored = model_app.config.get_custom_models()[0]
    assert "modelId" not in stored
    raw = model_app.config.get("custom_models", "")
    assert "modelId" not in raw


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
    assert resolved["default_model_id"] == "gpt-4o"
    assert "modelId" not in resolved


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
    assert resolved["default_model_id"] == "gpt-4o-mini"
    assert "modelId" not in resolved


# --- W-ARCH-MODEL-PROFILE-CANONICAL-001: adapter 定向用例 ---


def test_canonicalize_custom_model_profile_is_idempotent():
    """canonicalize 两次调用结果一致。"""
    legacy = _legacy_model("gpt-4o", "GPT4o")
    once = canonicalize_custom_model_profile(dict(legacy))
    twice = canonicalize_custom_model_profile(dict(once))
    assert once["model_ids"] == twice["model_ids"] == ["gpt-4o"]
    assert once["default_model_id"] == twice["default_model_id"] == "gpt-4o"
    assert once["max_tokens"] == twice["max_tokens"] == 512
    assert "modelId" not in twice
    assert twice["apiKey"] == legacy["apiKey"]


def test_canonicalize_repairs_invalid_max_tokens():
    """损坏的 max_tokens 被规范为 512；model_ids 顺序不变。"""
    entry = {
        "name": "Bad-Tokens",
        "modelId": "m1",
        "model_ids": ["m1", "m2"],
        "default_model_id": "m1",
        "max_tokens": "not-an-int",
    }
    out = canonicalize_custom_model_profile(dict(entry))
    assert out["model_ids"] == ["m1", "m2"]
    assert out["default_model_id"] == "m1"
    assert out["max_tokens"] == 512
    assert "modelId" not in out


def test_canonicalize_non_list_model_ids_falls_back_to_legacy():
    """model_ids 非 list 时从 legacy modelId 解析。"""
    entry = {
        "name": "Legacy-Only",
        "modelId": "legacy-id",
        "model_ids": "not-a-list",
        "max_tokens": 256,
    }
    out = canonicalize_custom_model_profile(dict(entry))
    assert out["model_ids"] == ["legacy-id"]
    assert out["default_model_id"] == "legacy-id"
    assert out["max_tokens"] == 256
    assert "modelId" not in out


def test_canonicalize_preserves_complete_new_shape_fields():
    """完整新 shape 不被 adapter 擅自改写顺序或 default。"""
    entry = {
        "name": "Complete",
        "modelId": "b",
        "model_ids": ["a", "b", "c"],
        "default_model_id": "b",
        "max_tokens": 2048,
        "apiKey": "sk-complete-key-1234567890",
        "endpoint": "https://api.example.com/v1",
    }
    out = canonicalize_custom_model_profile(dict(entry))
    assert out["model_ids"] == ["a", "b", "c"]
    assert out["default_model_id"] == "b"
    assert out["max_tokens"] == 2048
    assert out["apiKey"] == entry["apiKey"]
    assert out["endpoint"] == entry["endpoint"]
    assert "modelId" not in out


def test_migrate_alias_equals_canonicalize():
    """_migrate_custom_model_shape 别名与 canonicalize 行为一致。"""
    legacy = _legacy_model("alias-test")
    assert _migrate_custom_model_shape(dict(legacy)) == canonicalize_custom_model_profile(
        dict(legacy)
    )


def test_update_with_masked_key_preserves_api_key_via_adapter(model_app):
    """掩码 API Key 更新时原密钥不被清空（adapter 委托路径）。"""
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Masked-Key",
            "model_ids": ["masked-model"],
            "default_model_id": "masked-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-masked-key-1234567890",
            "provider": "custom_openai",
        },
    )
    original_key = model_app.config.get_custom_models()[0]["apiKey"]
    cm_api.update_custom_model(
        model_app,
        0,
        {
            "name": "Masked-Key-Updated",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": cm_api.MASKED_KEY,
            "provider": "custom_openai",
        },
    )
    stored = model_app.config.get_custom_models()[0]
    assert stored["apiKey"] == original_key
    assert stored["name"] == "Masked-Key-Updated"
