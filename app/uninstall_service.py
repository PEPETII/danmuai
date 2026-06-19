"""Velopack uninstall helpers.

Default behavior keeps `%APPDATA%/DanmuAI/` untouched. Optional data deletion is
opt-in and must be requested before launching `Update.exe uninstall --silent`.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

APPDATA_DIR_NAME = "DanmuAI"
DELETE_MARKER_NAME = ".delete_data_on_uninstall"


@dataclass
class UninstallStatus:
    ok: bool
    frozen: bool
    supported: bool
    delete_user_data_requested: bool = False
    update_exe_path: str = ""
    message: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "frozen": self.frozen,
            "supported": self.supported,
            "delete_user_data_requested": self.delete_user_data_requested,
            "update_exe_path": self.update_exe_path,
            "message": self.message,
            "error": self.error,
        }


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _appdata_dir() -> Path:
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APPDATA_DIR_NAME
    return Path.home() / "AppData" / "Roaming" / APPDATA_DIR_NAME


def _delete_marker_path() -> Path:
    return _appdata_dir() / DELETE_MARKER_NAME


def _locate_update_exe() -> Path | None:
    if not _is_frozen():
        return None
    exe_path = Path(sys.executable).resolve()
    candidates = (
        exe_path.parent / "Update.exe",
        exe_path.parent.parent / "Update.exe",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _set_delete_user_data_requested(enabled: bool) -> None:
    marker = _delete_marker_path()
    if enabled:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("delete-user-data=1\n", encoding="utf-8")
    elif marker.exists():
        marker.unlink()


def delete_user_data_if_requested() -> None:
    marker = _delete_marker_path()
    if not marker.exists():
        return
    data_dir = _appdata_dir()
    if data_dir.name != APPDATA_DIR_NAME:
        return
    shutil.rmtree(data_dir, ignore_errors=True)


def get_status() -> UninstallStatus:
    update_exe = _locate_update_exe()
    frozen = _is_frozen()
    requested = _delete_marker_path().exists()
    if not frozen:
        return UninstallStatus(
            ok=True,
            frozen=False,
            supported=False,
            delete_user_data_requested=requested,
            message="源码运行模式不支持 Velopack 卸载。",
        )
    if update_exe is None:
        return UninstallStatus(
            ok=False,
            frozen=True,
            supported=False,
            delete_user_data_requested=requested,
            error="update_exe_missing",
            message="未找到 Velopack Update.exe，无法触发卸载。",
        )
    return UninstallStatus(
        ok=True,
        frozen=True,
        supported=True,
        delete_user_data_requested=requested,
        update_exe_path=str(update_exe),
        message="已就绪，可触发 Velopack 卸载。",
    )


def request_uninstall(*, delete_user_data: bool = False) -> UninstallStatus:
    status = get_status()
    if not status.ok or not status.supported:
        return status
    _set_delete_user_data_requested(delete_user_data)
    update_exe = status.update_exe_path
    subprocess.Popen(
        [update_exe, "uninstall", "--silent"],
        cwd=str(Path(update_exe).parent),
    )
    status.message = "已启动卸载程序。"
    status.delete_user_data_requested = delete_user_data
    return status
