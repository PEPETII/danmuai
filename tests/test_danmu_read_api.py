"""读弹幕 Web API 与 DanmuApp façade。"""

from unittest.mock import MagicMock

from app.config_store import ConfigStore
from app.danmu_read_service import export_danmu_read_config
from app.model_providers import normalize_endpoint
from app.tts_providers import TTS_PROVIDER_CUSTOM_OPENAI, validate_custom_tts_fields
from app.web_api.danmu_read import normalize_probe_payload, normalize_put_payload
from app.web_api.routes import register_web_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient


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


def _apply_custom_tts_patch(config: ConfigStore, patch: dict) -> dict:
    provider = str(patch.get("provider") or "").strip()
    endpoint = normalize_endpoint(str(patch.get("endpoint") or ""))
    model_id = str(patch.get("model_id") or "").strip()
    if "provider" in patch or "endpoint" in patch or "model_id" in patch:
        if provider in ("", "mimo") and not endpoint and not model_id:
            config.set_batch(
                {"tts_provider": "", "tts_endpoint": "", "tts_model_id": ""}
            )
        else:
            resolved_provider = provider or TTS_PROVIDER_CUSTOM_OPENAI
            validate_custom_tts_fields(resolved_provider, endpoint, model_id)
            config.set_batch(
                {
                    "tts_provider": resolved_provider,
                    "tts_endpoint": endpoint,
                    "tts_model_id": model_id,
                }
            )
    return export_danmu_read_config(config)


def test_put_danmu_read_config_custom_model(workspace_tmp):
    app = FastAPI()
    bridge = MagicMock()
    config = ConfigStore(db_path=workspace_tmp / "custom_read.db")
    danmu_app = MagicMock()
    danmu_app.config = config
    danmu_app.apply_danmu_read_config = lambda patch: _apply_custom_tts_patch(config, patch)
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
    assert res.status_code == 200
    body = res.json()
    assert body["use_custom_model"] is True
    assert body["custom_endpoint"] == "https://tts.example.com/v1"
    assert body["custom_model_id"] == "my-tts"
    assert body["model"] == "my-tts"
    assert body["endpoint"] == "https://tts.example.com/v1"


def test_put_danmu_read_config_custom_missing_endpoint(workspace_tmp):
    app = FastAPI()
    bridge = MagicMock()
    config = ConfigStore(db_path=workspace_tmp / "bad_read.db")
    danmu_app = MagicMock()
    danmu_app.config = config

    danmu_app.apply_danmu_read_config = lambda patch: _apply_custom_tts_patch(config, patch)
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


def test_danmu_read_probe_route():
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
    assert res.status_code == 200
    assert res.json()["ok"] is True
    bridge.danmu_app.run_danmu_read_probe.assert_called_once_with(
        api_key_override="sk-test-tts",
        provider_override="custom_openai",
        endpoint_override="https://tts.example.com/v1",
        model_id_override="probe-model",
    )


def test_export_danmu_read_config_empty_key(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "e.db")
    data = export_danmu_read_config(store)
    assert data["api_key"] == ""
    assert data["use_custom_model"] is False


def test_normalize_put_payload_accepts_custom_field_aliases():
    out = normalize_put_payload(
        {
            "provider": "custom_openai",
            "custom_endpoint": "https://tts.example.com/v1",
            "custom_model_id": "my-tts",
        }
    )
    assert out["endpoint"] == "https://tts.example.com/v1"
    assert out["model_id"] == "my-tts"


def test_normalize_probe_payload_accepts_custom_field_aliases():
    out = normalize_probe_payload(
        {
            "provider": "custom_openai",
            "custom_endpoint": "https://tts.example.com/v1",
            "custom_model_id": "probe-model",
        }
    )
    assert out["endpoint_override"] == "https://tts.example.com/v1"
    assert out["model_id_override"] == "probe-model"


def test_danmu_read_probe_route_custom_field_aliases():
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
            "provider": "custom_openai",
            "custom_endpoint": "https://tts.example.com/v1",
            "custom_model_id": "probe-model",
        },
    )
    assert res.status_code == 200
    bridge.danmu_app.run_danmu_read_probe.assert_called_once_with(
        api_key_override=None,
        provider_override="custom_openai",
        endpoint_override="https://tts.example.com/v1",
        model_id_override="probe-model",
    )
