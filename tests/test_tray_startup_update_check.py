"""Tray startup auto update check — silent failure and session remind-later."""

from unittest.mock import MagicMock, patch

from app.tray import TrayManager
from app.update_service import UpdateStatus


def _make_minimal_tray_manager(qapp):
    from app.tray import _UpdateCheckBridge
    from PyQt6.QtWidgets import QSystemTrayIcon

    mgr = TrayManager.__new__(TrayManager)
    mgr.app = MagicMock()
    mgr.tray = QSystemTrayIcon()
    mgr._update_progress = None
    mgr._update_poll_timer = None
    mgr._update_check_in_flight = False
    mgr._startup_update_check_scheduled = False
    mgr._startup_update_prompt_suppressed = False
    mgr._update_check_bridge = _UpdateCheckBridge()
    mgr._update_check_bridge.done.connect(mgr._on_check_update_done)
    return mgr


def test_schedule_startup_update_check_only_once(qapp):
    mgr = _make_minimal_tray_manager(qapp)
    with patch.object(mgr, "_run_startup_update_check") as mock_run:
        mgr.schedule_startup_update_check()
        mgr.schedule_startup_update_check()
    assert mock_run.call_count == 0
    assert mgr._startup_update_check_scheduled is True


def test_startup_check_done_silent_on_failure(qapp):
    mgr = _make_minimal_tray_manager(qapp)
    result = UpdateStatus(ok=False, frozen=False, error="network", message="timeout")

    with patch("app.tray.QMessageBox") as mock_box:
        mgr._on_check_update_done(result, "检查更新", True, True)
        mock_box.warning.assert_not_called()

    assert mgr._update_check_in_flight is False


def test_startup_check_done_silent_when_up_to_date(qapp):
    mgr = _make_minimal_tray_manager(qapp)
    result = UpdateStatus(ok=True, frozen=True, update_available=False, message="已是最新")

    with patch("app.tray.QMessageBox") as mock_box:
        mgr._on_check_update_done(result, "检查更新", True, True)
        mock_box.warning.assert_not_called()
        mock_box.information.assert_not_called()


def test_startup_check_shows_prompt_when_update_available(qapp):
    mgr = _make_minimal_tray_manager(qapp)
    result = UpdateStatus(
        ok=True,
        frozen=True,
        current_version="0.3.0",
        latest_version="0.4.0",
        update_available=True,
    )

    with patch.object(mgr, "_show_startup_update_prompt") as mock_prompt:
        mgr._on_check_update_done(result, "检查更新", True, True)
        mock_prompt.assert_called_once_with(result, "检查更新")


def test_startup_remind_later_suppresses_repeat_prompt(qapp):
    mgr = _make_minimal_tray_manager(qapp)
    mgr._startup_update_prompt_suppressed = True
    result = UpdateStatus(
        ok=True,
        frozen=True,
        latest_version="0.4.0",
        update_available=True,
    )

    with patch.object(mgr, "_show_startup_update_prompt") as mock_prompt:
        mgr._on_check_update_done(result, "检查更新", True, True)
        mock_prompt.assert_not_called()
