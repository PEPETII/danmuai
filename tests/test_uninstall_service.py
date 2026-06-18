"""Tests for Velopack uninstall helpers."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

from app import uninstall_service


def test_request_uninstall_source_mode_returns_unsupported(monkeypatch):
    monkeypatch.setattr(uninstall_service, "_is_frozen", lambda: False)
    status = uninstall_service.request_uninstall()
    assert status.ok is True
    assert status.supported is False


def test_request_uninstall_launches_update_and_sets_marker(monkeypatch, tmp_path):
    appdata = tmp_path / "Roaming"
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.setattr(uninstall_service, "_is_frozen", lambda: True)
    monkeypatch.setattr(uninstall_service, "_locate_update_exe", lambda: tmp_path / "Update.exe")
    monkeypatch.setattr(sys, "executable", str(tmp_path / "current" / "DanmuAI.exe"))

    popen = MagicMock()
    monkeypatch.setattr("app.uninstall_service.subprocess.Popen", popen)

    status = uninstall_service.request_uninstall(delete_user_data=True)

    assert status.ok is True
    assert status.supported is True
    assert status.delete_user_data_requested is True
    marker = appdata / "DanmuAI" / ".delete_data_on_uninstall"
    assert marker.exists()
    popen.assert_called_once_with(
        [str(tmp_path / "Update.exe"), "uninstall", "--silent"],
        cwd=str(tmp_path),
    )


def test_delete_user_data_if_requested_removes_appdata(monkeypatch, tmp_path):
    appdata = tmp_path / "Roaming"
    data_dir = appdata / "DanmuAI"
    data_dir.mkdir(parents=True)
    (data_dir / "config.db").write_text("db", encoding="utf-8")
    (data_dir / ".delete_data_on_uninstall").write_text("1", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    uninstall_service.delete_user_data_if_requested()

    assert not data_dir.exists()
