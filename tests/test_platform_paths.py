import sys
from pathlib import Path

from app.platform_paths import CONFIG_DIR_ENV, startup_log_path, user_data_dir


def test_user_data_dir_macos(monkeypatch, tmp_path):
    monkeypatch.delenv(CONFIG_DIR_ENV, raising=False)
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    assert user_data_dir() == tmp_path / "Library" / "Application Support" / "DanmuAI"


def test_user_data_dir_windows_uses_appdata(monkeypatch, tmp_path):
    monkeypatch.delenv(CONFIG_DIR_ENV, raising=False)
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))

    assert user_data_dir() == tmp_path / "Roaming" / "DanmuAI"


def test_user_data_dir_env_override(monkeypatch, tmp_path):
    override = tmp_path / "custom-config"
    monkeypatch.setenv(CONFIG_DIR_ENV, str(override))
    monkeypatch.setattr(sys, "platform", "darwin")

    assert user_data_dir() == override
    assert startup_log_path() == override / "startup.log"
