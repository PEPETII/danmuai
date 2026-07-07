"""Resolve bundled resource paths for dev runs and PyInstaller builds."""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def is_frozen() -> bool:
    # PyInstaller onedir sets sys._MEIPASS; some builds omit sys.frozen.
    return bool(getattr(sys, "frozen", False)) or hasattr(sys, "_MEIPASS")


def project_root() -> Path:
    """Repo root in dev; PyInstaller extract dir when frozen."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return project_root().joinpath(*parts)


def frozen_log_path() -> Path:
    appdata = os.environ.get("APPDATA", "").strip()
    base = Path(appdata) if appdata else Path.home()
    return base / "DanmuAI" / "startup.log"


def app_log_path() -> Path:
    appdata = os.environ.get("APPDATA", "").strip()
    base = Path(appdata) if appdata else Path.home()
    return base / "DanmuAI" / "app.log"


def append_frozen_log(message: str) -> None:
    """Best-effort diagnostics when console=False (PyInstaller)."""
    if not is_frozen():
        return
    try:
        from app.logger import sanitize_log_message

        message = sanitize_log_message(message)
        path = frozen_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except OSError:
        pass
