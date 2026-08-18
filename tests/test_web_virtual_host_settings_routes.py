from __future__ import annotations

from unittest.mock import MagicMock

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


def test_virtual_host_settings_get_uses_public_facade():
    client, bridge = _client()
    bridge.danmu_app.get_virtual_host_settings.return_value = {
        "dialogue_enabled": False,
        "danmu_adapter_enabled": True,
        "runtime_status": "stopped",
        "runtime_generation": 1,
    }

    response = client.get("/api/virtual-host/settings")

    assert response.status_code == 200
    assert response.json() == {
        "dialogue_enabled": False,
        "danmu_adapter_enabled": True,
        "runtime_status": "stopped",
        "runtime_generation": 1,
    }
    bridge.danmu_app.get_virtual_host_settings.assert_called_once_with()


def test_virtual_host_settings_put_requires_auth_and_applies_patch():
    client, bridge = _client()
    bridge.danmu_app.apply_virtual_host_settings.return_value = {
        "dialogue_enabled": True,
        "danmu_adapter_enabled": False,
        "runtime_status": "running",
        "runtime_generation": 3,
    }

    assert client.put("/api/virtual-host/settings", json={"dialogue_enabled": True}).status_code == 401

    response = client.put(
        "/api/virtual-host/settings",
        json={"dialogue_enabled": True},
        headers={"Authorization": "Bearer virtual-host-secret"},
    )

    assert response.status_code == 200
    assert response.json()["dialogue_enabled"] is True
    assert response.json()["danmu_adapter_enabled"] is False
    bridge.danmu_app.apply_virtual_host_settings.assert_called_once_with({"dialogue_enabled": True})


def test_virtual_host_settings_put_maps_mutual_exclusive_error_to_400():
    client, bridge = _client()
    bridge.danmu_app.apply_virtual_host_settings.side_effect = ValueError(
        "virtual_host_modes_mutually_exclusive"
    )

    response = client.put(
        "/api/virtual-host/settings",
        json={"dialogue_enabled": True, "danmu_adapter_enabled": True},
        headers={"Authorization": "Bearer virtual-host-secret"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "virtual_host_modes_mutually_exclusive"
