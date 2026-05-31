"""读弹幕 Web API 与 DanmuApp façade。"""

from unittest.mock import MagicMock

from app.config_store import ConfigStore
from app.danmu_read_service import export_danmu_read_config
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
        json={"api_key": "sk-test-tts"},
    )
    assert res.status_code == 200
    assert res.json()["ok"] is True
    bridge.danmu_app.run_danmu_read_probe.assert_called_once_with(
        api_key_override="sk-test-tts"
    )


def test_export_danmu_read_config_empty_key(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "e.db")
    data = export_danmu_read_config(store)
    assert data["api_key"] == ""
