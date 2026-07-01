"""Windows .key ACL hardening for ConfigStore."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config_store import _restrict_key_file_permissions


def test_windows_key_acl_uses_icacls(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config_store.os.name", "nt")
    monkeypatch.setenv("USERNAME", "TestUser")
    key_path = tmp_path / ".key"
    key_path.write_bytes(b"fernet-key-bytes")

    with patch("app.config_store.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        _restrict_key_file_permissions(key_path)

    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert args[0] == "icacls"
    assert str(key_path) in args
    assert "/inheritance:r" in args
    assert "TestUser:F" in args


def test_windows_key_acl_logs_failure(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr("app.config_store.os.name", "nt")
    monkeypatch.setenv("USERNAME", "TestUser")
    key_path = tmp_path / ".key"
    key_path.write_bytes(b"fernet-key-bytes")

    with patch("app.config_store.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stderr="denied")
        with caplog.at_level("WARNING", logger="app.config_store"):
            _restrict_key_file_permissions(key_path)

    assert any("权限" in rec.getMessage() or "permissions" in rec.getMessage().lower() for rec in caplog.records)


def test_non_windows_uses_chmod(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config_store.os.name", "posix")
    key_path = tmp_path / ".key"
    key_path.write_bytes(b"fernet-key-bytes")

    with patch("app.config_store.os.chmod") as mock_chmod:
        _restrict_key_file_permissions(key_path)

    mock_chmod.assert_called_once_with(key_path, 0o600)
