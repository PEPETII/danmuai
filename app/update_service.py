"""Velopack update operations for tray / Web API (Velopack installs only)."""

from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.velopack_config import UPDATE_FEED_URL

_lock = threading.Lock()
_state: dict[str, Any] = {
    "last_check": None,
    "pending_update": None,
    "last_error": None,
    "download_phase": "idle",
    "download_progress": 0,
    "package_size_bytes": 0,
    "download_thread": None,
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
    download_phase: str = "idle"
    download_progress: int = 0
    package_size_bytes: int = 0
    downloaded_bytes: int = 0
    downloading: bool = False

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
            "download_phase": self.download_phase,
            "download_progress": self.download_progress,
            "package_size_bytes": self.package_size_bytes,
            "downloaded_bytes": self.downloaded_bytes,
            "downloading": self.downloading,
        }


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _is_velopack_install() -> bool:
    if not _is_frozen():
        return False
    exe_path = getattr(sys, "executable", "") or ""
    if not exe_path:
        return False
    resolved = Path(exe_path).resolve()
    return resolved.parent.name.lower() == "current" and (resolved.parent.parent / "Update.exe").is_file()


_cached_manager = None


def _manager():
    global _cached_manager
    with _lock:
        if _cached_manager is not None:
            return _cached_manager
        import velopack

        _cached_manager = velopack.UpdateManager(UPDATE_FEED_URL)
        return _cached_manager


def _current_version(manager) -> str:
    try:
        return str(manager.get_current_version() or "")
    except Exception:
        from app.version import __version__

        return __version__


def _latest_version_from_info(info: Any) -> str:
    if info is None:
        return ""
    full = getattr(info, "TargetFullRelease", None)
    if full is not None:
        version = getattr(full, "Version", None)
        if version:
            return str(version)
    legacy = getattr(info, "target_full_release", None)
    if legacy:
        return str(legacy)
    return ""


def _estimate_package_size(info: Any) -> int:
    if info is None:
        return 0
    deltas = getattr(info, "DeltasToTarget", None) or []
    if deltas:
        total = 0
        for delta in deltas:
            total += int(getattr(delta, "Size", 0) or 0)
        if total > 0:
            return total
    full = getattr(info, "TargetFullRelease", None)
    if full is not None:
        return int(getattr(full, "Size", 0) or 0)
    return 0


def _downloaded_bytes(package_size: int, progress: int) -> int:
    if package_size <= 0 or progress <= 0:
        return 0
    return int(package_size * progress / 100)


def _take_snapshot() -> dict[str, Any]:
    """Acquire _lock and return a consistent snapshot of _state fields used by _enrich_status."""
    with _lock:
        return {
            "download_phase": str(_state.get("download_phase") or "idle"),
            "download_progress": int(_state.get("download_progress") or 0),
            "package_size_bytes": int(_state.get("package_size_bytes") or 0),
            "last_error": _state.get("last_error"),
        }


def _enrich_status(status: UpdateStatus, snapshot: dict[str, Any] | None = None) -> UpdateStatus:
    if snapshot is None:
        snapshot = _take_snapshot()
    phase = snapshot["download_phase"]
    progress = snapshot["download_progress"]
    package_size = snapshot["package_size_bytes"]
    last_error = snapshot.get("last_error")

    status.download_phase = phase
    status.download_progress = progress
    status.package_size_bytes = package_size
    status.downloaded_bytes = _downloaded_bytes(package_size, progress)
    status.downloading = phase == "downloading"

    if phase == "ready":
        status.download_ready = True
        status.download_progress = 100
        status.downloaded_bytes = package_size if package_size > 0 else 0
    elif phase == "error" and last_error:
        status.error = str(last_error)
        if not status.message:
            status.message = str(last_error)

    return status


def get_status() -> UpdateStatus:
    frozen = _is_velopack_install()
    from app.version import __version__

    if not frozen:
        return UpdateStatus(
            ok=True,
            frozen=False,
            current_version=__version__,
            message="当前运行不是 Velopack 安装版；应用内更新已跳过",
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
            phase = str(_state.get("download_phase") or "idle")
            latest = _latest_version_from_info(pending_info)
            download_ready = phase == "ready" or pending
            update_available = bool(pending_info) and phase not in {"ready", "downloading"}
            message = ""
            if pending or phase == "ready":
                message = "已下载更新，可重启安装"
            snapshot = {
                "download_phase": phase,
                "download_progress": int(_state.get("download_progress") or 0),
                "package_size_bytes": int(_state.get("package_size_bytes") or 0),
                "last_error": _state.get("last_error"),
            }
        return _enrich_status(
            UpdateStatus(
                ok=True,
                frozen=True,
                current_version=current or __version__,
                latest_version=latest,
                update_available=update_available,
                download_ready=download_ready,
                pending_restart=pending,
                message=message,
            ),
            snapshot,
        )
    except Exception as exc:
        return _enrich_status(
            UpdateStatus(
                ok=False,
                frozen=True,
                current_version=__version__,
                error=str(exc),
            ),
        )


def check_for_updates() -> UpdateStatus:
    if not _is_velopack_install():
        return UpdateStatus(
            ok=False,
            frozen=False,
            message="仅安装版支持检查更新",
            error="not_frozen",
        )
    try:
        mgr = _manager()
        info = mgr.check_for_updates()
        package_size = _estimate_package_size(info)
        with _lock:
            _state["pending_update"] = info
            _state["last_check"] = info
            _state["last_error"] = None
            if info is not None:
                _state["package_size_bytes"] = package_size
                if _state.get("download_phase") not in {"downloading", "ready"}:
                    _state["download_phase"] = "idle"
                    _state["download_progress"] = 0
        current = _current_version(mgr)
        if info is None:
            return _enrich_status(
                UpdateStatus(
                    ok=True,
                    frozen=True,
                    current_version=current,
                    latest_version=current,
                    update_available=False,
                    message="已是最新版本",
                )
            )
        latest = _latest_version_from_info(info)
        return _enrich_status(
            UpdateStatus(
                ok=True,
                frozen=True,
                current_version=current,
                latest_version=latest,
                update_available=True,
                package_size_bytes=package_size,
                message=f"发现新版本 {latest}",
            )
        )
    except Exception as exc:
        with _lock:
            _state["last_error"] = str(exc)
        st = get_status()
        st.ok = False
        st.error = str(exc)
        return st


def _run_download_thread(info: Any) -> None:
    try:
        mgr = _manager()

        def on_progress(pct: int) -> None:
            with _lock:
                _state["download_progress"] = int(pct)

        mgr.download_updates(info, progress_callback=on_progress)
        with _lock:
            _state["download_phase"] = "ready"
            _state["download_progress"] = 100
            _state["last_error"] = None
    except Exception as exc:
        with _lock:
            _state["download_phase"] = "error"
            _state["last_error"] = str(exc)


def _read_phase_and_guard(
    update_info: Any,
) -> tuple[UpdateStatus | None, dict[str, Any] | None]:
    """Acquire _lock, read phase+snapshot, check downloading/ready guards.

    Returns (early_return_status, snapshot):
    - ``early_return_status`` is not None → caller must return it immediately.
    - ``snapshot`` is populated only when no early return (caller continues).
    - ``update_info`` is used for ``_latest_version_from_info()`` in the 'ready' guard;
      pass ``None`` if version string is not yet available (first guard call).
    """
    with _lock:
        phase = str(_state.get("download_phase") or "idle")
        snapshot: dict[str, Any] = {
            "download_phase": phase,
            "download_progress": int(_state.get("download_progress") or 0),
            "package_size_bytes": int(_state.get("package_size_bytes") or 0),
            "last_error": _state.get("last_error"),
        }

        if phase == "downloading":
            active_thread = _state.get("download_thread")
            if active_thread is not None and active_thread.is_alive():
                return (
                    _enrich_status(
                        UpdateStatus(
                            ok=True,
                            frozen=True,
                            downloading=True,
                            message="正在下载更新…",
                        ),
                        snapshot,
                    ),
                    None,
                )

        if phase == "ready":
            return (
                _enrich_status(
                    UpdateStatus(
                        ok=True,
                        frozen=True,
                        latest_version=_latest_version_from_info(update_info),
                        update_available=True,
                        download_ready=True,
                        message="更新已下载，请重启应用以完成安装",
                    ),
                    snapshot,
                ),
                None,
            )

        return None, snapshot


def download_updates(*, wait: bool = False) -> UpdateStatus:
    if not _is_velopack_install():
        return UpdateStatus(ok=False, frozen=False, error="not_frozen")

    # First guard: check current phase before any I/O
    early, _snapshot = _read_phase_and_guard(None)
    if early is not None:
        return early

    # Extract pending_update info (only needed on first pass)
    with _lock:
        info = _state.get("pending_update")

    # check_for_updates() acquires its own lock; call outside ours
    if info is None:
        check = check_for_updates()
        if not check.update_available:
            return check
        with _lock:
            info = _state.get("pending_update")

    if info is None:
        return UpdateStatus(ok=False, frozen=True, error="no_update_info")

    package_size = _estimate_package_size(info)

    # Second guard: re-check phase before starting download thread
    early, snapshot = _read_phase_and_guard(info)
    if early is not None:
        return early

    # Atomic state transition + thread creation under lock
    with _lock:
        _state["download_phase"] = "downloading"
        _state["download_progress"] = 0
        _state["package_size_bytes"] = package_size
        _state["last_error"] = None
        thread = threading.Thread(target=_run_download_thread, args=(info,), daemon=True)
        _state["download_thread"] = thread

    # Start thread outside the lock (blocking)
    thread.start()

    if wait:
        thread.join()
        with _lock:
            phase = str(_state.get("download_phase") or "idle")
            last_error = _state.get("last_error")
        if phase == "error":
            st = get_status()
            st.ok = False
            st.error = str(last_error or "download_failed")
            return st
        if phase == "ready":
            mgr = _manager()
            return _enrich_status(
                UpdateStatus(
                    ok=True,
                    frozen=True,
                    current_version=_current_version(mgr),
                    latest_version=_latest_version_from_info(info),
                    update_available=True,
                    download_ready=True,
                    message="更新已下载，请重启应用以完成安装",
                )
            )
        st = get_status()
        st.ok = False
        st.error = "download_incomplete"
        return st

    return _enrich_status(
        UpdateStatus(
            ok=True,
            frozen=True,
            latest_version=_latest_version_from_info(info),
            update_available=True,
            downloading=True,
            package_size_bytes=package_size,
            message="正在下载更新…",
        )
    )


def apply_updates_and_restart() -> UpdateStatus:
    if not _is_velopack_install():
        return UpdateStatus(ok=False, frozen=False, error="not_frozen")
    with _lock:
        info = _state.get("pending_update")
        phase = str(_state.get("download_phase") or "idle")
        if info is None:
            return UpdateStatus(
                ok=False,
                frozen=True,
                error="no_downloaded_update",
                message="请先检查并下载更新",
            )
        if phase == "downloading":
            return UpdateStatus(
                ok=False,
                frozen=True,
                error="download_in_progress",
                message="更新仍在下载中，请稍候",
            )
        _state["download_phase"] = "applying"
    try:
        mgr = _manager()
        mgr.apply_updates_and_restart(info)
        return UpdateStatus(ok=True, frozen=True, message="正在重启…", download_phase="applying")
    except Exception as exc:
        with _lock:
            _state["download_phase"] = "error"
            _state["last_error"] = str(exc)
        st = get_status()
        st.ok = False
        st.error = str(exc)
        return st
