"""Web console tests: auth."""

from unittest.mock import MagicMock

import pytest
from app.web_console import (
    WEB_CONFIG_KEYS,
    apply_config_patch,
    export_config,
    extract_config_payload,
)

from tests.fakes import FakeConfig


def test_export_config_omits_visual_api_key():
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: export_config 不再返回 api_key / has_api_key。"""
    cfg = FakeConfig({"api_endpoint": "https://example.com", "_api_key": "sk-secret"})
    data = export_config(cfg)
    assert "api_key" not in data, "export_config 不应返回 api_key"
    assert "has_api_key" not in data, "export_config 不应返回 has_api_key"


def test_export_config_omits_has_api_key_with_custom_model_only():
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: 即使仅有 custom_models 档案，也不返回 api_key / has_api_key。"""
    model_id = "mimo-v2.5"
    cfg = FakeConfig(
        {
            "api_endpoint": "",
            "default_model_id": model_id,
        },
    )
    cfg.set_custom_models(
        [
            {
                "name": "MiMo",
                "default_model_id": model_id,
                "modelId": model_id,
                "endpoint": "https://api.xiaomimimo.com/v1",
                "apiKey": "sk-mimo",
                "mode": "openai",
            }
        ]
    )
    data = export_config(cfg)
    assert "api_key" not in data
    assert "has_api_key" not in data


def test_export_config_fills_defaults_for_empty_store(tmp_path):
    from app.config_store import ConfigStore

    store = ConfigStore(db_path=tmp_path / "fresh.db")
    data = export_config(store)
    assert data["danmu_speed"] == "2"
    assert data["danmu_lines"] == "20"
    assert data["dedup_threshold"] == "0.5"
    assert data["normal_recognition_interval_sec"] == "5"
    assert data["normal_reply_count"] == "5"
    assert "freshness" not in data
    assert data["eviction_mode"] == "natural"
    assert data["opacity"] == "100"
    assert data["font_size"] == "24"
    assert data["hotkey"] == "Ctrl+Shift+B"


def test_export_config_masks_custom_model_api_keys():
    cfg = FakeConfig()
    cfg.set_custom_models(
        [
            {
                "name": "Test",
                "modelId": "gpt-4o",
                "apiKey": "sk-custom-secret",
                "endpoint": "https://api.example.com",
                "mode": "openai",
            }
        ]
    )
    data = export_config(cfg)
    assert len(data["custom_models"]) == 1
    assert data["custom_models"][0]["apiKey"] == "********"
    assert "sk-custom-secret" not in str(data)


def test_apply_config_patch_preserves_masked_custom_model_key():
    config = FakeConfig()
    config.set_custom_models(
        [{"name": "M", "modelId": "m", "apiKey": "sk-keep", "endpoint": "https://x", "mode": "openai"}]
    )
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(
        app,
        {
            "custom_models": [
                {
                    "name": "M",
                    "modelId": "m",
                    "apiKey": "********",
                    "endpoint": "https://x",
                    "mode": "openai",
                }
            ]
        },
    )

    assert config.get_custom_models()[0]["apiKey"] == "sk-keep"


def test_apply_config_patch_updates_batch_and_ignores_visual_api_key():
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: apply_config_patch 不再接受 api_key / api_endpoint
    （WEB_CONFIG_KEYS 已移除）；model 仍可写入并同步 default_model_id。"""
    config = FakeConfig({"api_endpoint": "old", "default_model_id": "gpt-4o"})
    # 提供完整 custom_models 档案以通过 validate_web_config_patch
    config.set_custom_models(
        [
            {
                "name": "Test",
                "default_model_id": "gpt-4o",
                "modelId": "gpt-4o",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "sk-profile",
                "mode": "openai",
            }
        ]
    )
    personae = MagicMock()
    app = MagicMock()
    app.config = config
    app.personae = personae

    apply_config_patch(
        app,
        {
            "api_endpoint": "https://new.example/v1",
            "model": "gpt-4o",
            "api_key": "sk-new-key",
            "active_personae": ["吐槽型"],
        },
    )

    # api_endpoint 不在 WEB_CONFIG_KEYS 中，不会被写入
    assert config.get("api_endpoint") == "old"
    # model 仍可写入
    assert config.get("model") == "gpt-4o"
    assert config.get_default_model_id() == "gpt-4o"
    # api_key 被忽略（Phase 1 移除视觉 api_key 写入口）
    assert config.get_api_key() == ""
    personae.set_active.assert_called_once()
    app.config_changed.emit.assert_called_once()


def test_apply_config_patch_skips_masked_key():
    config = FakeConfig({"_api_key": "keep-me"})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"api_key": "********", "api_endpoint": "https://x.com"})

    assert config.get_api_key() == "keep-me"


def test_apply_config_patch_skips_blank_key():
    config = FakeConfig({"_api_key": "keep-me"})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"api_key": "   ", "api_endpoint": "https://x.com"})

    assert config.get_api_key() == "keep-me"


def test_apply_config_patch_preserves_masked_custom_model_key_by_identity():
    config = FakeConfig()
    config.set_custom_models(
        [
            {"name": "A", "modelId": "model-a", "apiKey": "sk-a", "endpoint": "https://a", "mode": "openai"},
            {"name": "B", "modelId": "model-b", "apiKey": "sk-b", "endpoint": "https://b", "mode": "openai"},
        ]
    )
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(
        app,
        {
            "custom_models": [
                {"name": "B", "modelId": "model-b", "apiKey": "********", "endpoint": "https://b2", "mode": "openai"},
                {"name": "A", "modelId": "model-a", "apiKey": "********", "endpoint": "https://a2", "mode": "openai"},
            ]
        },
    )

    models = config.get_custom_models()
    assert models[0]["apiKey"] == "sk-b"
    assert models[1]["apiKey"] == "sk-a"


def test_apply_config_patch_syncs_default_model_id_to_legacy_model():
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: default_model_id 写入需对应完整 custom_models 档案。"""
    new_model = "doubao-seed-1-6-flash-250828"
    config = FakeConfig({
        "model": "old-model",
        "default_model_id": new_model,
    })
    config.set_custom_models(
        [
            {
                "name": "Doubao",
                "default_model_id": new_model,
                "modelId": new_model,
                "endpoint": "https://ark.cn-beijing.volces.com/api/v3",
                "apiKey": "sk-profile",
                "mode": "doubao",
            }
        ]
    )
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"default_model_id": new_model})

    assert config.get_default_model_id() == new_model
    assert config.get("model") == new_model


def test_extract_config_payload_accepts_wrapped_and_flat():
    wrapped = extract_config_payload(
        {"data": {"empty_accel": "0", "api_endpoint": "https://x"}}
    )
    assert wrapped["empty_accel"] == "0"
    flat = extract_config_payload({"mic_mode_enabled": "1"})
    assert flat["mic_mode_enabled"] == "1"


def test_extract_config_payload_rejects_empty():
    with pytest.raises(ValueError, match="配置数据为空"):
        extract_config_payload({})


def test_web_config_keys_cover_core_settings():
    # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: api_endpoint/api_mode 已从 WEB_CONFIG_KEYS 移除
    assert "api_endpoint" not in WEB_CONFIG_KEYS
    assert "api_mode" not in WEB_CONFIG_KEYS
    assert "screen_index" in WEB_CONFIG_KEYS
    assert "region_x" not in WEB_CONFIG_KEYS
    assert "hotkey" in WEB_CONFIG_KEYS
    assert "danmu_speed" in WEB_CONFIG_KEYS
    assert "danmu_max_chars" in WEB_CONFIG_KEYS
    assert "freq_mode" not in WEB_CONFIG_KEYS
    assert "capture_mode" not in WEB_CONFIG_KEYS
    assert "danmu_pool_enabled" not in WEB_CONFIG_KEYS
    assert "min_on_screen" not in WEB_CONFIG_KEYS
    assert "eviction_mode" in WEB_CONFIG_KEYS
    assert "danmu_pending_entry_cap" in WEB_CONFIG_KEYS
    assert "danmu_track_retention_cap" in WEB_CONFIG_KEYS
    assert "reply_queue_max_items" in WEB_CONFIG_KEYS
    assert "image_max_width" in WEB_CONFIG_KEYS
    assert "image_quality" in WEB_CONFIG_KEYS
    assert "scene_probe_size" not in WEB_CONFIG_KEYS
    assert "mic_mode_enabled" in WEB_CONFIG_KEYS
    assert "mic_window_sec" in WEB_CONFIG_KEYS
    assert "mic_input_device_id" in WEB_CONFIG_KEYS
    assert "mic_use_visual_model" in WEB_CONFIG_KEYS
    assert "mic_api_endpoint" in WEB_CONFIG_KEYS
    assert "mic_api_mode" in WEB_CONFIG_KEYS
    assert "mic_model" in WEB_CONFIG_KEYS
    assert "mic_insert_reply_count" not in WEB_CONFIG_KEYS
    assert "mic_insert_voice_reply_count" not in WEB_CONFIG_KEYS
    assert "reply_scene_count" not in WEB_CONFIG_KEYS
    assert "reply_filler_count" not in WEB_CONFIG_KEYS
    assert "danmu_display_mode" not in WEB_CONFIG_KEYS
    assert "normal_recognition_interval_sec" in WEB_CONFIG_KEYS
    assert "normal_reply_count" in WEB_CONFIG_KEYS


def test_export_web_config_defaults():
    from app.application.config_service import RESTORABLE_CONFIG_KEYS, WEB_CONFIG_KEYS
    from app.config_defaults import CONFIG_DEFAULTS, export_web_config_defaults
    from app.model_catalog import default_catalog_model_id
    from app.model_providers import get_provider

    data = export_web_config_defaults()

    assert set(data.keys()) == set(WEB_CONFIG_KEYS)
    assert RESTORABLE_CONFIG_KEYS == WEB_CONFIG_KEYS
    assert "api_key" not in data
    assert "has_api_key" not in data
    assert "custom_models" not in data

    doubao = get_provider("doubao")
    # W-GLOBAL-VISUAL-APIKEY-REMOVE-001: api_endpoint/api_mode 已不在 WEB_CONFIG_KEYS
    assert "api_endpoint" not in data
    assert "api_mode" not in data
    assert data["model"] == default_catalog_model_id("custom_openai")

    assert data["mic_api_endpoint"] == doubao.default_endpoint
    assert data["mic_input_device_id"] == ""
    assert data["temperature"] == "0.8"
    assert data["pet_scale"] == "0.5"

    for key in WEB_CONFIG_KEYS:
        if key in ("model", "mic_api_endpoint"):
            continue
        assert data[key] == CONFIG_DEFAULTS.get(key, ""), key


def test_apply_config_patch_dashscope_model_syncs_default_model_id():
    """W-GLOBAL-VISUAL-APIKEY-REMOVE-001: model 写入需对应完整 custom_models 档案。"""
    from app.model_catalog import default_catalog_model_id

    dash_model = default_catalog_model_id("dashscope")
    config = FakeConfig(
        {
            "model": "doubao-seed-1-6-flash-250828",
            "default_model_id": dash_model,
        }
    )
    config.set_custom_models(
        [
            {
                "name": "DashScope",
                "default_model_id": dash_model,
                "modelId": dash_model,
                "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "apiKey": "sk-profile",
                "mode": "openai",
            }
        ]
    )
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(
        app,
        {
            "model": dash_model,
        },
    )

    assert config.get("model") == dash_model
    assert config.get_default_model_id() == dash_model


def test_export_config_mismatched_model_still_loads():
    from app.model_catalog import is_catalog_model_for_provider

    cfg = FakeConfig(
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_mode": "openai",
            "model": "doubao-seed-1-6-flash-250828",
            "default_model_id": "doubao-seed-1-6-flash-250828",
        }
    )
    data = export_config(cfg)
    assert data["model"] == "doubao-seed-1-6-flash-250828"
    assert not is_catalog_model_for_provider("dashscope", data["active_model_id"])
    assert data["provider_model_mismatch"] is True
    assert data["inferred_provider_id"] == "dashscope"
    assert data["model_source"] == "freeform"


def test_export_config_includes_catalog_display_name():
    from app.model_catalog import default_catalog_model_id

    dash_model = default_catalog_model_id("dashscope")
    cfg = FakeConfig(
        {
            "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "api_mode": "openai",
            "model": dash_model,
            "default_model_id": dash_model,
        }
    )
    data = export_config(cfg)
    assert data["active_model_id"] == dash_model
    assert data["model_source"] == "catalog"
    assert data["model_display_name"]
    assert data["provider_model_mismatch"] is False


def test_apply_config_patch_clamps_normal_batch_settings():
    config = FakeConfig({})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(
        app,
        {
            "normal_recognition_interval_sec": "0",
            "normal_reply_count": "99",
        },
    )

    assert config.get("normal_recognition_interval_sec") == "1"
    assert config.get("normal_reply_count") == "50"


def test_apply_config_patch_ignores_legacy_danmu_display_mode():
    """danmu_display_mode 不在 WEB_CONFIG_KEYS 白名单中，Web API 应忽略该键。"""
    config = FakeConfig({"danmu_display_mode": "realtime"})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"danmu_display_mode": "realtime", "normal_reply_count": "6"})

    # danmu_display_mode 不在白名单中，Web API 不应写入该键
    assert config.get("danmu_display_mode") == "realtime"
    assert config.get("normal_reply_count") == "6"


def test_apply_config_patch_clamps_danmu_lines():
    config = FakeConfig({})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"danmu_lines": "5"})
    assert config.get("danmu_lines") == "12"

    apply_config_patch(app, {"danmu_lines": "25"})
    assert config.get("danmu_lines") == "20"

    apply_config_patch(app, {"danmu_lines": "16"})
    assert config.get("danmu_lines") == "16"


def test_apply_config_patch_clamps_opacity():
    config = FakeConfig({})
    app = MagicMock()
    app.config = config
    app.personae = MagicMock()

    apply_config_patch(app, {"opacity": "30"})
    assert config.get("opacity") == "30"

    apply_config_patch(app, {"opacity": "-5"})
    assert config.get("opacity") == "0"

    apply_config_patch(app, {"opacity": "200"})
    assert config.get("opacity") == "100"


def test_require_auth_rejects_missing_token():
    from fastapi import FastAPI, Header, HTTPException
    from fastapi.testclient import TestClient

    from app.web_api.auth import require_auth

    app = FastAPI()

    def _check_token(authorization: str | None = None) -> None:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="需要登录令牌")
        if authorization != "Bearer secret":
            raise HTTPException(status_code=403, detail="令牌无效")

    @app.get("/api/protected")
    @require_auth(_check_token)
    def protected(authorization: str | None = Header(default=None)):
        return {"ok": True}

    client = TestClient(app)
    denied = client.get("/api/protected")
    assert denied.status_code == 401

    invalid = client.get("/api/protected", headers={"Authorization": "Bearer wrong"})
    assert invalid.status_code == 403

    ok = client.get("/api/protected", headers={"Authorization": "Bearer secret"})
    assert ok.status_code == 200
    assert ok.json() == {"ok": True}


def test_require_auth_query_uses_query_param():
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient

    from app.web_api.auth import require_auth_query

    app = FastAPI()

    def _check_token(token: str | None = None) -> None:
        if token != "Bearer secret":
            raise HTTPException(status_code=401, detail="需要登录令牌")

    @app.get("/api/events")
    @require_auth_query(_check_token)
    async def events(token: str | None = None):
        return {"ok": True}

    client = TestClient(app)
    denied = client.get("/api/events")
    assert denied.status_code == 401

    ok = client.get("/api/events", params={"token": "Bearer secret"})
    assert ok.status_code == 200
    assert ok.json() == {"ok": True}










