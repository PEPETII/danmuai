"""Tests for GET /api/version and app-update-state API."""

from unittest.mock import MagicMock

from app.version import __version__
from app.web_api.routes import register_web_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.test_web_console import FakeConfig


def test_get_api_version():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.get("/api/version")
    assert res.status_code == 200
    assert res.json() == {"current_version": __version__}


def test_app_update_state_get_default():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.get("/api/app-update-state")
    assert res.status_code == 200
    assert res.json() == {"dismissedLatestVersion": ""}


def test_app_update_state_put_roundtrip():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)

    def _check_token(authorization: str | None = None) -> None:
        if authorization != "Bearer test-token":
            from fastapi import HTTPException

            raise HTTPException(status_code=401, detail="unauthorized")

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    payload = {"dismissedLatestVersion": "0.3.0"}
    res = client.put(
        "/api/app-update-state",
        json=payload,
        headers={"Authorization": "Bearer test-token"},
    )
    assert res.status_code == 200
    assert res.json() == {"ok": True}

    res = client.get("/api/app-update-state")
    assert res.status_code == 200
    assert res.json() == payload


def test_app_update_state_put_rejects_invalid_version():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    res = client.put(
        "/api/app-update-state",
        json={"dismissedLatestVersion": "not-a-version"},
    )
    assert res.status_code == 400
