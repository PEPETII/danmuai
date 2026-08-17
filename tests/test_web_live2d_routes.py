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
        if authorization != "Bearer live2d-secret":
            raise HTTPException(status_code=401)

    register_web_routes(app, bridge, check_token)
    return TestClient(app), bridge


def test_live2d_model_snapshot_uses_public_facade():
    client, bridge = _client()
    bridge.danmu_app.get_live2d_model_snapshot.return_value = {
        "configured": False,
        "status": "unconfigured",
        "capabilities": {},
    }

    response = client.get("/api/live2d/model")

    assert response.status_code == 200
    assert response.json()["status"] == "unconfigured"
    bridge.danmu_app.get_live2d_model_snapshot.assert_called_once_with()


def test_live2d_write_routes_require_auth_and_invoke_main_facade():
    client, bridge = _client()
    bridge.danmu_app.import_live2d_model_via_dialog.return_value = {
        "configured": True,
        "status": "ready",
    }
    bridge.danmu_app.import_live2d_model_file_via_dialog.return_value = {
        "configured": True,
        "status": "ready",
    }
    bridge.danmu_app.clear_live2d_model.return_value = {
        "configured": False,
        "status": "unconfigured",
    }

    assert client.post("/api/live2d/import-model").status_code == 401

    imported = client.post(
        "/api/live2d/import-model",
        headers={"Authorization": "Bearer live2d-secret"},
    )
    imported_file = client.post(
        "/api/live2d/import-model-file",
        headers={"Authorization": "Bearer live2d-secret"},
    )
    cleared = client.post(
        "/api/live2d/clear-model",
        headers={"Authorization": "Bearer live2d-secret"},
    )

    assert imported.status_code == 200
    assert imported.json()["status"] == "ready"
    assert imported_file.status_code == 200
    assert imported_file.json()["status"] == "ready"
    assert cleared.status_code == 200
    assert cleared.json()["status"] == "unconfigured"
    assert bridge.invoke_on_main.call_count == 3
    bridge.danmu_app.import_live2d_model_via_dialog.assert_called_once_with()
    bridge.danmu_app.import_live2d_model_file_via_dialog.assert_called_once_with()
    bridge.danmu_app.clear_live2d_model.assert_called_once_with()


def test_live2d_runtime_routes_require_auth_and_use_public_facades():
    client, bridge = _client()
    bridge.danmu_app.start_live2d_model.return_value = {
        "status": "ready",
        "runtime_status": "running",
        "model_url": "/api/live2d/resource/model.json",
    }
    bridge.danmu_app.stop_live2d_model.return_value = {
        "status": "ready",
        "runtime_status": "stopped",
    }

    assert client.post("/api/live2d/start").status_code == 401
    started = client.post(
        "/api/live2d/start",
        headers={"Authorization": "Bearer live2d-secret"},
    )
    stopped = client.post(
        "/api/live2d/stop",
        headers={"Authorization": "Bearer live2d-secret"},
    )

    assert started.status_code == 200
    assert started.json()["runtime_status"] == "running"
    assert stopped.status_code == 200
    assert stopped.json()["runtime_status"] == "stopped"
    bridge.danmu_app.start_live2d_model.assert_called_once_with()
    bridge.danmu_app.stop_live2d_model.assert_called_once_with()


def test_live2d_resource_route_returns_proxy_bytes_without_exposing_model_path():
    client, bridge = _client()
    bridge.danmu_app.get_live2d_model_resource.return_value = (
        b'{"FileReferences":{}}',
        "application/json",
    )

    response = client.get("/api/live2d/resource/model.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.content == b'{"FileReferences":{}}'
    bridge.danmu_app.get_live2d_model_resource.assert_called_once_with("model.json")


def test_live2d_start_maps_not_ready_to_conflict():
    client, bridge = _client()
    bridge.danmu_app.start_live2d_model.side_effect = ValueError("model_not_ready")

    response = client.post(
        "/api/live2d/start",
        headers={"Authorization": "Bearer live2d-secret"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "model_not_ready"
