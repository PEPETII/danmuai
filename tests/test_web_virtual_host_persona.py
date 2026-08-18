from __future__ import annotations

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


def test_virtual_host_persona_api_delegates_to_danmu_app_facade():
    app = MagicMock()
    app.get_virtual_host_persona_config.return_value = {
        "system_prompt": "系统",
        "voice_dialogue_prompt": "语音",
        "defaults": {"system_prompt": "默认系统", "voice_dialogue_prompt": "默认语音"},
    }
    app.apply_virtual_host_persona_config.return_value = {
        "system_prompt": "新系统",
        "voice_dialogue_prompt": "新语音",
        "defaults": {"system_prompt": "默认系统", "voice_dialogue_prompt": "默认语音"},
    }

    assert virtual_host_api.get_persona_config(app)["system_prompt"] == "系统"
    assert virtual_host_api.save_persona_config(
        app,
        {"system_prompt": "新系统", "voice_dialogue_prompt": "新语音"},
    )["voice_dialogue_prompt"] == "新语音"
    app.apply_virtual_host_persona_config.assert_called_once_with(
        {"system_prompt": "新系统", "voice_dialogue_prompt": "新语音"},
        reset=False,
    )


def test_virtual_host_persona_get_uses_public_facade():
    client, bridge = _client()
    bridge.danmu_app.get_virtual_host_persona_config.return_value = {
        "system_prompt": "系统",
        "voice_dialogue_prompt": "语音",
        "defaults": {"system_prompt": "默认系统", "voice_dialogue_prompt": "默认语音"},
    }

    response = client.get("/api/virtual-host/persona")

    assert response.status_code == 200
    assert response.json()["system_prompt"] == "系统"
    bridge.danmu_app.get_virtual_host_persona_config.assert_called_once_with()


def test_virtual_host_persona_put_requires_auth_and_applies_patch():
    client, bridge = _client()
    bridge.danmu_app.apply_virtual_host_persona_config.return_value = {
        "system_prompt": "保存后",
        "voice_dialogue_prompt": "语音保存后",
        "defaults": {"system_prompt": "默认系统", "voice_dialogue_prompt": "默认语音"},
    }

    assert client.put(
        "/api/virtual-host/persona",
        json={"system_prompt": "保存后", "voice_dialogue_prompt": "语音保存后"},
    ).status_code == 401

    response = client.put(
        "/api/virtual-host/persona",
        json={"system_prompt": "保存后", "voice_dialogue_prompt": "语音保存后"},
        headers={"Authorization": "Bearer virtual-host-secret"},
    )

    assert response.status_code == 200
    assert response.json()["system_prompt"] == "保存后"
    bridge.danmu_app.apply_virtual_host_persona_config.assert_called_once_with(
        {"system_prompt": "保存后", "voice_dialogue_prompt": "语音保存后"},
        reset=False,
    )


def test_virtual_host_persona_put_reset_query_param():
    client, bridge = _client()
    bridge.danmu_app.apply_virtual_host_persona_config.return_value = {
        "system_prompt": "默认系统",
        "voice_dialogue_prompt": "默认语音",
        "defaults": {"system_prompt": "默认系统", "voice_dialogue_prompt": "默认语音"},
    }

    response = client.put(
        "/api/virtual-host/persona",
        params={"reset": "true"},
        json={},
        headers={"Authorization": "Bearer virtual-host-secret"},
    )

    assert response.status_code == 200
    bridge.danmu_app.apply_virtual_host_persona_config.assert_called_once_with({}, reset=True)


def test_virtual_host_persona_put_maps_validation_error_to_400():
    client, bridge = _client()
    bridge.danmu_app.apply_virtual_host_persona_config.side_effect = ValueError("prompt_too_long")

    response = client.put(
        "/api/virtual-host/persona",
        json={"system_prompt": "x"},
        headers={"Authorization": "Bearer virtual-host-secret"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "prompt_too_long"
