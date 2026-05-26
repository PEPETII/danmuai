"""Resolve bundled resource paths for dev runs and PyInstaller builds."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

from app.platform_paths import startup_log_path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Repo root in dev; PyInstaller extract dir when frozen."""
    if is_frozen():
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def resource_path(*parts: str) -> Path:
    return project_root().joinpath(*parts)


def frozen_log_path() -> Path:
    return startup_log_path()


def append_frozen_log(message: str) -> None:
    """Best-effort diagnostics when console=False (PyInstaller)."""
    if not is_frozen():
        return
    try:
        path = frozen_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"[{stamp}] {message}\n")
    except OSError:
        pass
