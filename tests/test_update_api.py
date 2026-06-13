"""Velopack update API and service — source mode contracts."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app import update_service
from app.web_api.routes import register_web_routes
from tests.fakes import FakeConfig

_TEST_TOKEN = "Bearer test-token"


def _strict_check_token(authorization: str | None = None) -> None:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="unauthorized")
    if authorization != _TEST_TOKEN:
        raise HTTPException(status_code=403, detail="invalid token")


def _make_client():
    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = FakeConfig()
    register_web_routes(app, bridge, _strict_check_token)
    return TestClient(app)


def test_update_status_source_mode():
    st = update_service.get_status()
    d = st.to_dict()
    assert d["ok"] is True
    assert d["frozen"] is False
    assert d["current_version"]


def test_update_check_source_mode():
    st = update_service.check_for_updates()
    d = st.to_dict()
    assert d["frozen"] is False
    assert d["ok"] is False
    assert d["error"] == "not_frozen"


def test_update_check_frozen_mock():
    mock_mgr = MagicMock()
    mock_mgr.get_current_version.return_value = "0.3.0"
    mock_mgr.check_for_updates.return_value = None
    with patch.object(update_service, "_is_frozen", return_value=True):
        with patch.object(update_service, "_manager", return_value=mock_mgr):
            st = update_service.check_for_updates()
    assert st.ok is True
    assert st.update_available is False


def test_update_channels_public_without_token():
    client = _make_client()
    res = client.get("/api/update/channels")
    assert res.status_code == 200
    body = res.json()
    assert "github_releases_url" in body
    assert "current_version" in body
    assert "latest_version" in body
    assert "update_available" in body
    assert "release_url" in body
    assert "feed_url" in body
    assert "message" in body
    assert isinstance(body["update_available"], bool)


def test_update_channels_readonly_never_calls_velopack_check():
    from app.release_channels import LATEST_PUBLISHED_VERSION

    with patch.object(update_service, "get_status") as mock_status:
        with patch.object(update_service, "check_for_updates") as mock_check:
            client = _make_client()
            res = client.get("/api/update/channels")
    mock_status.assert_not_called()
    mock_check.assert_not_called()
    assert res.status_code == 200
    body = res.json()
    assert body["latest_version"] == LATEST_PUBLISHED_VERSION


@pytest.mark.parametrize("frozen", [False, True])
def test_update_channels_frozen_still_skips_velopack_check(frozen):
    from app.release_channels import LATEST_PUBLISHED_VERSION

    with patch.object(update_service, "get_status") as mock_status:
        with patch.object(update_service, "check_for_updates") as mock_check:
            mock_status.return_value = update_service.UpdateStatus(
                ok=True,
                frozen=frozen,
                current_version="0.3.0",
            )
            client = _make_client()
            res = client.get("/api/update/channels")
    mock_check.assert_not_called()
    assert res.status_code == 200
    body = res.json()
    assert body["latest_version"] == LATEST_PUBLISHED_VERSION


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/update/status"),
        ("post", "/api/update/check"),
        ("post", "/api/update/download"),
        ("post", "/api/update/restart"),
    ],
)
def test_update_routes_reject_missing_token(method, path):
    client = _make_client()
    res = getattr(client, method)(path)
    assert res.status_code == 401


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/update/status"),
        ("post", "/api/update/check"),
        ("post", "/api/update/download"),
        ("post", "/api/update/restart"),
    ],
)
def test_update_routes_reject_wrong_token(method, path):
    client = _make_client()
    res = getattr(client, method)(
        path,
        headers={"Authorization": "Bearer wrong-token"},
    )
    assert res.status_code == 403


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/api/update/status"),
        ("post", "/api/update/check"),
        ("post", "/api/update/download"),
        ("post", "/api/update/restart"),
    ],
)
def test_update_routes_accept_valid_token(method, path):
    client = _make_client()
    res = getattr(client, method)(
        path,
        headers={"Authorization": _TEST_TOKEN},
    )
    assert res.status_code == 200
