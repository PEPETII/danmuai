"""Platform-specific filesystem locations for DanmuAI."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "DanmuAI"
CONFIG_DIR_ENV = "DANMUAI_CONFIG_DIR"


def user_data_dir(app_name: str = APP_NAME) -> Path:
    """Return the per-user data directory used for config, keys, and logs."""
    override = os.environ.get(CONFIG_DIR_ENV, "").strip()
    if override:
        return Path(override).expanduser()

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / app_name

    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "").strip()
        base = Path(appdata) if appdata else Path.home() / "AppData" / "Roaming"
        return base / app_name

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg_config_home).expanduser() if xdg_config_home else Path.home() / ".config"
    return base / app_name


def startup_log_path(app_name: str = APP_NAME) -> Path:
    return user_data_dir(app_name) / "startup.log"
