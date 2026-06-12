"""Velopack update operations for tray / Web API (frozen installs only)."""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from typing import Any

from app.velopack_config import UPDATE_FEED_URL

_lock = threading.Lock()
_state: dict[str, Any] = {
    "last_check": None,
    "pending_update": None,
    "last_error": None,
}


@dataclass
class UpdateStatus:
    ok: bool
    frozen: bool
    current_version: str = ""
    latest_version: str = ""
    update_available: bool = False
    download_ready: bool = False
    pending_restart: bool = False
    feed_url: str = UPDATE_FEED_URL
    message: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "frozen": self.frozen,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "update_available": self.update_available,
            "download_ready": self.download_ready,
            "pending_restart": self.pending_restart,
            "feed_url": self.feed_url,
            "message": self.message,
            "error": self.error,
        }


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _manager():
    import velopack

    return velopack.UpdateManager(UPDATE_FEED_URL)


def _current_version(manager) -> str:
    try:
        return str(manager.get_current_version() or "")
    except Exception:
        from app.version import __version__

        return __version__


def get_status() -> UpdateStatus:
    frozen = _is_frozen()
    from app.version import __version__

    if not frozen:
        return UpdateStatus(
            ok=True,
            frozen=False,
            current_version=__version__,
            message="源码运行模式；Velopack 更新已跳过",
        )

    try:
        mgr = _manager()
        current = _current_version(mgr)
        pending = False
        try:
            pending = bool(mgr.get_update_pending_restart())
        except Exception:
            pending = False
        with _lock:
            pending_info = _state.get("pending_update")
        latest = ""
        if pending_info is not None:
            latest = str(getattr(pending_info, "target_full_release", "") or "")
        return UpdateStatus(
            ok=True,
            frozen=True,
            current_version=current or __version__,
            latest_version=latest,
            update_available=bool(pending_info),
            download_ready=bool(pending_info),
            pending_restart=pending,
            message="已下载更新，可重启安装" if pending else "",
        )
    except Exception as exc:
        return UpdateStatus(
            ok=False,
            frozen=True,
            current_version=__version__,
            error=str(exc),
        )


def check_for_updates() -> UpdateStatus:
    if not _is_frozen():
        return UpdateStatus(
            ok=False,
            frozen=False,
            message="仅安装版支持检查更新",
            error="not_frozen",
        )
    try:
        mgr = _manager()
        info = mgr.check_for_updates()
        with _lock:
            _state["pending_update"] = info
            _state["last_check"] = info
            _state["last_error"] = None
        current = _current_version(mgr)
        if info is None:
            return UpdateStatus(
                ok=True,
                frozen=True,
                current_version=current,
                latest_version=current,
                update_available=False,
                message="已是最新版本",
            )
        latest = str(getattr(info, "target_full_release", "") or "")
        return UpdateStatus(
            ok=True,
            frozen=True,
            current_version=current,
            latest_version=latest,
            update_available=True,
            message=f"发现新版本 {latest}",
        )
    except Exception as exc:
        with _lock:
            _state["last_error"] = str(exc)
        st = get_status()
        st.ok = False
        st.error = str(exc)
        return st


def download_updates() -> UpdateStatus:
    if not _is_frozen():
        return UpdateStatus(ok=False, frozen=False, error="not_frozen")
    with _lock:
        info = _state.get("pending_update")
    if info is None:
        check = check_for_updates()
        if not check.update_available:
            return check
        with _lock:
            info = _state.get("pending_update")
    if info is None:
        return UpdateStatus(ok=False, frozen=True, error="no_update_info")
    try:
        mgr = _manager()
        mgr.download_updates(info)
        return UpdateStatus(
            ok=True,
            frozen=True,
            current_version=_current_version(mgr),
            latest_version=str(getattr(info, "target_full_release", "") or ""),
            update_available=True,
            download_ready=True,
            message="更新已下载，请重启应用以完成安装",
        )
    except Exception as exc:
        st = get_status()
        st.ok = False
        st.error = str(exc)
        return st


def apply_updates_and_restart() -> UpdateStatus:
    if not _is_frozen():
        return UpdateStatus(ok=False, frozen=False, error="not_frozen")
    with _lock:
        info = _state.get("pending_update")
    if info is None:
        return UpdateStatus(
            ok=False,
            frozen=True,
            error="no_downloaded_update",
            message="请先检查并下载更新",
        )
    try:
        mgr = _manager()
        mgr.apply_updates_and_restart(info)
        return UpdateStatus(ok=True, frozen=True, message="正在重启…")
    except Exception as exc:
        st = get_status()
        st.ok = False
        st.error = str(exc)
        return st
