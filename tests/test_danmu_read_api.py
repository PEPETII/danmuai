"""读弹幕 Web API 与 DanmuApp façade。"""

from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore
from app.danmu_read_service import export_danmu_read_config
from app.tts_providers import (
    TTS_PROVIDER_DASHSCOPE_QWEN,
    validate_custom_tts_fields,
)
from app.web_api.danmu_read import normalize_probe_payload, normalize_put_payload
from app.web_api.routes import register_web_routes
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def test_get_danmu_read_catalog():
    app = FastAPI()
    bridge = MagicMock()
    register_web_routes(app, bridge, lambda _auth=None: None)
    client = TestClient(app)
    data = client.get("/api/danmu-read/catalog").json()
    ids = {p["id"] for p in data["providers"]}
    assert "mimo" in ids
    assert "dashscope_qwen" in ids
    assert "doubao" not in ids
    assert "custom_openai" not in ids


def test_get_danmu_read_config_masks_key(workspace_tmp):
    app = FastAPI()
    bridge = MagicMock()
    config = ConfigStore(db_path=workspace_tmp / "get_read.db")
    config.set_tts_api_key("secret-tts")
    bridge.danmu_app = MagicMock()
    bridge.danmu_app.config = config

    register_web_routes(app, bridge, lambda _auth=None: None)
    client = TestClient(app)
    data = client.get("/api/danmu-read/config").json()
    assert data["model"] == "mimo-v2.5-tts"
    assert data["api_key"] == "********"
    assert data["use_custom_model"] is False
    assert data["custom_endpoint"] == ""


def test_put_danmu_read_config_invoke_main(workspace_tmp):
    app = FastAPI()
    bridge = MagicMock()
    config = ConfigStore(db_path=workspace_tmp / "put_read.db")
    danmu_app = MagicMock()
    danmu_app.config = config
    captured: list[dict] = []

    def apply(patch):
        captured.append(patch)
        config.set("danmu_read_enabled", "1" if patch.get("enabled") else "0")
        if "interval_sec" in patch:
            config.set("danmu_read_interval_sec", str(patch["interval_sec"]))
        if "voice" in patch:
            config.set("tts_voice", patch["voice"])
        return export_danmu_read_config(config)

    danmu_app.apply_danmu_read_config = apply
    bridge.danmu_app = danmu_app
    bridge.invoke_on_main = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    register_web_routes(app, bridge, lambda _auth=None: None)
    client = TestClient(app)
    res = client.put(
        "/api/danmu-read/config",
        headers={"Authorization": "Bearer test"},
        json={"enabled": True, "interval_sec": 8, "voice": "Chloe"},
    )
    assert res.status_code == 200
    assert res.json()["interval_sec"] == 8
    assert captured[0]["enabled"] is True


def _apply_preset_tts_patch(config: ConfigStore, patch: dict) -> dict:
    provider = str(patch.get("provider") or "").strip()
    model_id = str(patch.get("model_id") or "").strip()
    if "provider" in patch or "model_id" in patch:
        if not provider and not model_id:
            config.set_batch(
                {"tts_provider": "", "tts_endpoint": "", "tts_model_id": ""}
            )
        else:
            validate_custom_tts_fields(provider, "", model_id)
            config.set_batch(
                {
                    "tts_provider": provider,
                    "tts_endpoint": "",
                    "tts_model_id": model_id,
                }
            )
    return export_danmu_read_config(config)


def test_put_danmu_read_config_custom_model_rejected(workspace_tmp):
    app = FastAPI()
    bridge = MagicMock()
    config = ConfigStore(db_path=workspace_tmp / "custom_read.db")
    danmu_app = MagicMock()
    danmu_app.config = config
    danmu_app.apply_danmu_read_config = lambda patch: _apply_preset_tts_patch(config, patch)
    bridge.danmu_app = danmu_app
    bridge.invoke_on_main = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    register_web_routes(app, bridge, lambda _auth=None: None)
    client = TestClient(app)
    res = client.put(
        "/api/danmu-read/config",
        headers={"Authorization": "Bearer test"},
        json={
            "provider": "custom_openai",
            "endpoint": "https://tts.example.com/v1",
            "model_id": "my-tts",
        },
    )
    assert res.status_code == 400


def test_put_danmu_read_config_custom_missing_endpoint(workspace_tmp):
    app = FastAPI()
    bridge = MagicMock()
    config = ConfigStore(db_path=workspace_tmp / "bad_read.db")
    danmu_app = MagicMock()
    danmu_app.config = config
    danmu_app.apply_danmu_read_config = lambda patch: _apply_preset_tts_patch(config, patch)
    bridge.danmu_app = danmu_app
    bridge.invoke_on_main = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    register_web_routes(app, bridge, lambda _auth=None: None)
    client = TestClient(app)
    res = client.put(
        "/api/danmu-read/config",
        headers={"Authorization": "Bearer test"},
        json={"provider": "custom_openai", "model_id": "my-tts"},
    )
    assert res.status_code == 400


def test_danmu_read_probe_route_rejects_doubao():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.run_danmu_read_probe.return_value = {"ok": True, "message": "试听播放中"}
    bridge.invoke_on_main = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    register_web_routes(app, bridge, lambda _auth=None: None)
    client = TestClient(app)
    res = client.post(
        "/api/danmu-read/probe",
        headers={"Authorization": "Bearer test"},
        json={
            "api_key": "sk-test-tts",
            "provider": "doubao",
            "model_id": "seed-tts-2.0",
        },
    )
    assert res.status_code == 400
    bridge.danmu_app.run_danmu_read_probe.assert_not_called()


def test_put_danmu_read_config_rejects_doubao_provider(workspace_tmp):
    app = FastAPI()
    bridge = MagicMock()
    config = ConfigStore(db_path=workspace_tmp / "doubao_read.db")
    danmu_app = MagicMock()
    danmu_app.config = config

    def apply(patch):
        raise AssertionError("should not reach apply for doubao")

    danmu_app.apply_danmu_read_config = apply
    bridge.danmu_app = danmu_app
    bridge.invoke_on_main = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    register_web_routes(app, bridge, lambda _auth=None: None)
    client = TestClient(app)
    res = client.put(
        "/api/danmu-read/config",
        headers={"Authorization": "Bearer test"},
        json={
            "provider": "doubao",
            "model_id": "seed-tts-2.0",
        },
    )
    assert res.status_code == 400


def test_export_danmu_read_config_legacy_doubao(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "legacy_doubao.db")
    store.set_batch(
        {
            "tts_provider": "doubao",
            "tts_model_id": "seed-tts-2.0",
        }
    )
    data = export_danmu_read_config(store)
    assert data["provider"] == ""
    assert data["custom_model_id"] == "seed-tts-2.0"
    assert data["use_custom_model"] is False
    assert data["model"] == "mimo-v2.5-tts"
    assert "app_id" not in data


def test_export_danmu_read_config_orphan_endpoint_use_custom_false(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "orphan_endpoint.db")
    store.set_batch(
        {
            "tts_endpoint": "https://tts.example.com/v1",
            "tts_model_id": "my-tts",
        }
    )
    data = export_danmu_read_config(store)
    assert data["use_custom_model"] is False
    assert data["custom_endpoint"] == "https://tts.example.com/v1"
    assert data["custom_model_id"] == "my-tts"


def test_export_danmu_read_config_dashscope_missing_model_use_custom_true(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "dashscope_no_model.db")
    store.set_batch(
        {
            "tts_provider": TTS_PROVIDER_DASHSCOPE_QWEN,
            "tts_model_id": "",
        }
    )
    data = export_danmu_read_config(store)
    assert data["use_custom_model"] is True
    assert data["provider"] == TTS_PROVIDER_DASHSCOPE_QWEN


def test_danmu_read_probe_route_rejects_custom_openai():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.run_danmu_read_probe.return_value = {"ok": True, "message": "试听播放中"}
    bridge.invoke_on_main = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    register_web_routes(app, bridge, lambda _auth=None: None)
    client = TestClient(app)
    res = client.post(
        "/api/danmu-read/probe",
        headers={"Authorization": "Bearer test"},
        json={
            "api_key": "sk-test-tts",
            "provider": "custom_openai",
            "endpoint": "https://tts.example.com/v1",
            "model_id": "probe-model",
        },
    )
    assert res.status_code == 400
    bridge.danmu_app.run_danmu_read_probe.assert_not_called()


def test_export_danmu_read_config_empty_key(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "e.db")
    data = export_danmu_read_config(store)
    assert data["api_key"] == ""
    assert data["use_custom_model"] is False


def test_export_danmu_read_config_legacy_custom_openai(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "legacy.db")
    store.set_batch(
        {
            "tts_provider": "custom_openai",
            "tts_endpoint": "https://tts.example.com/v1",
            "tts_model_id": "my-tts",
        }
    )
    data = export_danmu_read_config(store)
    assert data["provider"] == ""
    assert data["custom_endpoint"] == ""
    assert data["custom_model_id"] == "my-tts"
    assert data["use_custom_model"] is False
    assert data["model"] == "mimo-v2.5-tts"


def test_normalize_put_payload_rejects_custom_openai():
    with pytest.raises(HTTPException) as exc:
        normalize_put_payload(
            {
                "provider": "custom_openai",
                "custom_endpoint": "https://tts.example.com/v1",
                "custom_model_id": "my-tts",
            }
        )
    assert exc.value.status_code == 400


def test_normalize_probe_payload_rejects_custom_openai():
    with pytest.raises(HTTPException) as exc:
        normalize_probe_payload(
            {
                "provider": "custom_openai",
                "custom_endpoint": "https://tts.example.com/v1",
                "custom_model_id": "probe-model",
            }
        )
    assert exc.value.status_code == 400


def test_put_danmu_read_config_dashscope_provider(workspace_tmp):
    app = FastAPI()
    bridge = MagicMock()
    config = ConfigStore(db_path=workspace_tmp / "ds_read.db")
    danmu_app = MagicMock()
    danmu_app.config = config
    danmu_app.apply_danmu_read_config = lambda patch: _apply_preset_tts_patch(config, patch)
    bridge.danmu_app = danmu_app
    bridge.invoke_on_main = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    register_web_routes(app, bridge, lambda _auth=None: None)
    client = TestClient(app)
    res = client.put(
        "/api/danmu-read/config",
        headers={"Authorization": "Bearer test"},
        json={
            "provider": TTS_PROVIDER_DASHSCOPE_QWEN,
            "model_id": "qwen3-tts-flash-2025-11-27",
            "voice": "Cherry",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["use_custom_model"] is True
    assert body["model"] == "qwen3-tts-flash-2025-11-27"


def test_danmu_read_probe_route_dashscope_provider():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.run_danmu_read_probe.return_value = {"ok": True, "message": "试听播放中"}
    bridge.invoke_on_main = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    register_web_routes(app, bridge, lambda _auth=None: None)
    client = TestClient(app)
    res = client.post(
        "/api/danmu-read/probe",
        headers={"Authorization": "Bearer test"},
        json={
            "provider": TTS_PROVIDER_DASHSCOPE_QWEN,
            "model_id": "qwen3-tts-flash-2025-11-27",
        },
    )
    assert res.status_code == 200
    bridge.danmu_app.run_danmu_read_probe.assert_called_once_with(
        api_key_override=None,
        provider_override=TTS_PROVIDER_DASHSCOPE_QWEN,
        endpoint_override=None,
        model_id_override="qwen3-tts-flash-2025-11-27",
    )


def test_normalize_put_payload_accepts_model_id_for_dashscope():
    out = normalize_put_payload(
        {
            "provider": TTS_PROVIDER_DASHSCOPE_QWEN,
            "model_id": "qwen3-tts-flash-2025-11-27",
        }
    )
    assert out["provider"] == TTS_PROVIDER_DASHSCOPE_QWEN
    assert out["model_id"] == "qwen3-tts-flash-2025-11-27"


def test_normalize_put_payload_rejects_orphan_endpoint():
    with pytest.raises(HTTPException) as exc:
        normalize_put_payload(
            {
                "endpoint": "https://tts.example.com/v1",
                "model_id": "my-tts",
            }
        )
    assert exc.value.status_code == 400
