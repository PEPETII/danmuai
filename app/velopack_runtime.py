"""Velopack startup hook — must run before QApplication (frozen builds only)."""

from __future__ import annotations

import sys


def run_startup_apply_if_needed() -> None:
    """Apply pending Velopack updates before Qt initializes.

    Source runs skip entirely. Import or runtime errors are logged, not swallowed.
    """
    if not getattr(sys, "frozen", False):
        return

    from app.startup_trace import log_startup

    log_startup("velopack.begin")
    try:
        import velopack
    except ImportError as exc:
        log_startup("velopack.skip", reason="import_error", detail=str(exc))
        return

    try:
        from app.uninstall_service import delete_user_data_if_requested

        app = velopack.App()
        app.on_before_uninstall_fast_callback(delete_user_data_if_requested)
        app.run()
        log_startup("velopack.done")
    except Exception as exc:
        log_startup("velopack.error", detail=str(exc))
        return
