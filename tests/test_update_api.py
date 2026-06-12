"""Velopack update API and service — source mode contracts."""

from unittest.mock import MagicMock, patch

from app import update_service


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


def test_update_routes_registered():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.web_api import update as update_api_mod

    api = FastAPI()

    @api.get("/api/update/status")
    def _status():
        return update_api_mod.get_update_status()

    @api.post("/api/update/check")
    def _check():
        return update_api_mod.post_update_check()

    client = TestClient(api)
    assert client.get("/api/update/status").status_code == 200
    assert client.post("/api/update/check").status_code == 200


def test_update_check_frozen_mock():
    mock_mgr = MagicMock()
    mock_mgr.get_current_version.return_value = "0.3.0"
    mock_mgr.check_for_updates.return_value = None
    with patch.object(update_service, "_is_frozen", return_value=True):
        with patch.object(update_service, "_manager", return_value=mock_mgr):
            st = update_service.check_for_updates()
    assert st.ok is True
    assert st.update_available is False
