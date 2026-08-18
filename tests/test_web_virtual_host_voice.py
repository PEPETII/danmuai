from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.web_api import virtual_host as virtual_host_api
from app.web_api.routes import register_web_routes
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient


def _client():
    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    def check_token(authorization: str | None = None) -> None:
        if authorization != "Bearer virtual-host-secret":
            raise HTTPException(status_code=401)

    register_web_routes(app, bridge, check_token)
    return TestClient(app), bridge


def _voice_status(**overrides):
    payload = {
        "dialogue_enabled": True,
        "danmu_adapter_enabled": False,
        "runtime_status": "running",
        "runtime_generation": 2,
        "armed": False,
        "phase": "idle",
        "turn_id": None,
        "turn_status": None,
        "asr_status": None,
        "llm_status": None,
        "tts_status": None,
        "playback_status": None,
        "failure_reason": None,
        "cancel_reason": None,
        "blocking_error": None,
        "mic_mode_enabled": True,
        "mic_capture_running": True,
        "mic_capture_ready": True,
        "mic_error": None,
    }
    payload.update(overrides)
    return payload


def test_virtual_host_voice_api_delegates_to_danmu_app_facade():
    app = MagicMock()
    app.get_virtual_host_voice_status.return_value = _voice_status()
    app.start_virtual_host_voice.return_value = _voice_status(armed=True, phase="listening")
    app.stop_virtual_host_voice.return_value = _voice_status()
    app.cancel_virtual_host_voice.return_value = _voice_status(cancel_reason="user_cancelled")

    assert virtual_host_api.get_voice_status(app) == app.get_virtual_host_voice_status.return_value
    assert virtual_host_api.start_voice_session(app)["armed"] is True
    assert virtual_host_api.stop_voice_session(app)["armed"] is False
    assert virtual_host_api.cancel_voice_session(app)["cancel_reason"] == "user_cancelled"


def test_virtual_host_voice_status_get_uses_public_facade():
    client, bridge = _client()
    bridge.danmu_app.get_virtual_host_voice_status.return_value = _voice_status(phase="listening")

    response = client.get("/api/virtual-host/voice/status")

    assert response.status_code == 200
    assert response.json()["phase"] == "listening"
    bridge.danmu_app.get_virtual_host_voice_status.assert_called_once_with()


def test_virtual_host_voice_start_requires_auth_and_applies_facade():
    client, bridge = _client()
    bridge.danmu_app.start_virtual_host_voice.return_value = _voice_status(
        armed=True,
        phase="listening",
    )

    assert client.post("/api/virtual-host/voice/start").status_code == 401

    response = client.post(
        "/api/virtual-host/voice/start",
        headers={"Authorization": "Bearer virtual-host-secret"},
    )

    assert response.status_code == 200
    assert response.json()["armed"] is True
    bridge.danmu_app.start_virtual_host_voice.assert_called_once_with()


def test_virtual_host_voice_stop_and_cancel_require_auth():
    client, bridge = _client()
    bridge.danmu_app.stop_virtual_host_voice.return_value = _voice_status()
    bridge.danmu_app.cancel_virtual_host_voice.return_value = _voice_status(
        cancel_reason="user_cancelled",
    )

    assert client.post("/api/virtual-host/voice/stop").status_code == 401
    assert client.post("/api/virtual-host/voice/cancel").status_code == 401

    stop = client.post(
        "/api/virtual-host/voice/stop",
        headers={"Authorization": "Bearer virtual-host-secret"},
    )
    cancel = client.post(
        "/api/virtual-host/voice/cancel",
        headers={"Authorization": "Bearer virtual-host-secret"},
    )

    assert stop.status_code == 200
    assert cancel.status_code == 200
    bridge.danmu_app.stop_virtual_host_voice.assert_called_once_with()
    bridge.danmu_app.cancel_virtual_host_voice.assert_called_once_with()


def test_virtual_host_voice_start_maps_value_error_to_400():
    client, bridge = _client()
    bridge.danmu_app.start_virtual_host_voice.side_effect = ValueError("runtime_stopped")

    response = client.post(
        "/api/virtual-host/voice/start",
        headers={"Authorization": "Bearer virtual-host-secret"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "runtime_stopped"


def test_export_voice_status_without_runtime_is_idle():
    from app.virtual_host.voice_status import export_voice_status

    app = SimpleNamespace(
        config=SimpleNamespace(get=lambda key, default="0": default),
        engine=SimpleNamespace(running=False),
        _mic_orchestrator=None,
    )
    payload = export_voice_status(None, app)
    assert payload["phase"] == "idle"
    assert payload["runtime_status"] == "stopped"
    assert payload["blocking_error"] == "dialogue_mode_disabled"
