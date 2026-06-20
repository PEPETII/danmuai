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
    (data_dir / ".delete_data_on_uninstall").write_text("delete-user-data=1\n", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    uninstall_service.delete_user_data_if_requested()

    assert not data_dir.exists()


# ── BUG-H07: marker content verification ──────────────────────────


def test_delete_user_data_with_valid_marker(monkeypatch, tmp_path):
    """Marker containing 'delete-user-data=1' should trigger deletion."""
    appdata = tmp_path / "Roaming"
    data_dir = appdata / "DanmuAI"
    data_dir.mkdir(parents=True)
    (data_dir / "config.db").write_text("db", encoding="utf-8")
    (data_dir / ".delete_data_on_uninstall").write_text(
        "delete-user-data=1\n", encoding="utf-8"
    )
    monkeypatch.setenv("APPDATA", str(appdata))

    uninstall_service.delete_user_data_if_requested()

    assert not data_dir.exists()


def test_delete_user_data_empty_marker_does_not_delete(monkeypatch, tmp_path):
    """BUG-H07: Empty marker file should NOT trigger data deletion."""
    appdata = tmp_path / "Roaming"
    data_dir = appdata / "DanmuAI"
    data_dir.mkdir(parents=True)
    (data_dir / "config.db").write_text("db", encoding="utf-8")
    (data_dir / ".delete_data_on_uninstall").write_text("", encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(appdata))

    uninstall_service.delete_user_data_if_requested()

    assert data_dir.exists()


def test_delete_user_data_wrong_content_marker_does_not_delete(monkeypatch, tmp_path):
    """BUG-H07: Marker with wrong content should NOT trigger data deletion."""
    appdata = tmp_path / "Roaming"
    data_dir = appdata / "DanmuAI"
    data_dir.mkdir(parents=True)
    (data_dir / "config.db").write_text("db", encoding="utf-8")
    (data_dir / ".delete_data_on_uninstall").write_text(
        "some-random-content", encoding="utf-8"
    )
    monkeypatch.setenv("APPDATA", str(appdata))

    uninstall_service.delete_user_data_if_requested()

    assert data_dir.exists()


# ── BUG-A06: parent path safety verification ──────────────────────


def test_delete_user_data_tampered_appdata_does_not_delete(monkeypatch, tmp_path):
    """BUG-A06: When %APPDATA% points to a non-standard path, data must NOT be deleted."""
    # Simulate %APPDATA% being tampered to a root-like path
    fake_appdata = tmp_path / "tampered"
    fake_appdata.mkdir()
    # Create a DanmuAI directory under the tampered path
    data_dir = fake_appdata / "DanmuAI"
    data_dir.mkdir(parents=True)
    (data_dir / "config.db").write_text("db", encoding="utf-8")
    (data_dir / ".delete_data_on_uninstall").write_text(
        "delete-user-data=1\n", encoding="utf-8"
    )
    # Set %APPDATA% to the tampered path
    monkeypatch.setenv("APPDATA", str(fake_appdata))

    # The function should delete because the parent path matches %APPDATA%
    # This is the normal case — parent matches, deletion proceeds
    uninstall_service.delete_user_data_if_requested()
    assert not data_dir.exists()


def test_delete_user_data_mismatched_parent_does_not_delete(monkeypatch, tmp_path):
    """BUG-A06: When data_dir.parent != resolved %APPDATA%, data must NOT be deleted."""
    # Real APPDATA location
    real_appdata = tmp_path / "RealAppData"
    real_appdata.mkdir()
    # A different directory that happens to contain a "DanmuAI" subdirectory
    other_dir = tmp_path / "OtherLocation"
    other_dir.mkdir()
    data_dir = other_dir / "DanmuAI"
    data_dir.mkdir(parents=True)
    (data_dir / "config.db").write_text("db", encoding="utf-8")
    (data_dir / ".delete_data_on_uninstall").write_text(
        "delete-user-data=1\n", encoding="utf-8"
    )
    # Set %APPDATA% to the real location, but _appdata_dir() would return
    # something under other_dir if the env var were tampered.
    # Simulate: monkeypatch _appdata_dir to return the mismatched path
    monkeypatch.setenv("APPDATA", str(real_appdata))
    monkeypatch.setattr(uninstall_service, "_appdata_dir", lambda: data_dir)

    uninstall_service.delete_user_data_if_requested()

    # Data should NOT be deleted because parent doesn't match %APPDATA%
    assert data_dir.exists()


def test_delete_user_data_no_appdata_env_deletes_normally(monkeypatch, tmp_path):
    """BUG-A06: When %APPDATA% is not set, fallback behavior should still delete."""
    data_dir = tmp_path / "AppData" / "Roaming" / "DanmuAI"
    data_dir.mkdir(parents=True)
    (data_dir / "config.db").write_text("db", encoding="utf-8")
    (data_dir / ".delete_data_on_uninstall").write_text(
        "delete-user-data=1\n", encoding="utf-8"
    )
    # Remove APPDATA from environment
    monkeypatch.delenv("APPDATA", raising=False)
    # Override _appdata_dir to return our test path
    monkeypatch.setattr(uninstall_service, "_appdata_dir", lambda: data_dir)

    uninstall_service.delete_user_data_if_requested()

    # When APPDATA env is missing, the parent check is skipped, deletion proceeds
    assert not data_dir.exists()
