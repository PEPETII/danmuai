"""BUG-002: 托盘更新检查必须走后台线程，不在主线程同步 HTTP。

验证：
- _on_check_update 启动后台线程，不阻塞主线程
- _update_check_in_flight 防重入
- 结果经 QTimer.singleShot 回主线程处理
- _on_check_update_done 重置 _update_check_in_flight
"""

from unittest.mock import MagicMock, patch

import pytest

from app.tray import TrayManager


def _make_minimal_tray_manager(qapp):
    """构造一个绕过 __init__ 的 TrayManager，仅装测试所需属性。"""
    from PyQt6.QtWidgets import QSystemTrayIcon

    from app.tray import _UpdateCheckBridge

    mgr = TrayManager.__new__(TrayManager)
    mgr.app = MagicMock()
    mgr.tray = QSystemTrayIcon()
    mgr._update_progress = None
    mgr._update_poll_timer = None
    mgr._update_check_in_flight = False
    mgr._update_check_bridge = _UpdateCheckBridge()
    mgr._update_check_bridge.done.connect(mgr._on_check_update_done)
    return mgr


def test_on_check_update_sets_in_flight_flag(qapp):
    """BUG-002: _on_check_update 应立即设置 _update_check_in_flight = True。"""
    mgr = _make_minimal_tray_manager(qapp)

    with patch("app.update_service.check_for_updates") as mock_check:
        mock_check.return_value = MagicMock(ok=False, message="test error")
        mgr._on_check_update()

        # 立即检查：flag 应为 True（后台线程尚未完成）
        assert mgr._update_check_in_flight is True

    # 等待后台线程完成并投递 QTimer.singleShot 回调
    import time

    time.sleep(0.3)
    qapp.processEvents()
    assert mgr._update_check_in_flight is False


def test_on_check_update_prevents_reentry(qapp):
    """BUG-002: _update_check_in_flight=True 时二次调用应被拒绝。"""
    mgr = _make_minimal_tray_manager(qapp)
    mgr._update_check_in_flight = True

    call_count = MagicMock()
    with patch("app.update_service.check_for_updates", side_effect=call_count):
        mgr._on_check_update()
        # 不应启动新的检查
        call_count.assert_not_called()


def test_on_check_update_starts_background_thread(qapp):
    """BUG-002: _on_check_update 应启动 daemon 线程而非主线程同步调用。"""
    mgr = _make_minimal_tray_manager(qapp)

    thread_holder: dict = {}

    def _fake_check():
        import threading

        thread_holder["current"] = threading.current_thread()
        return MagicMock(ok=True, update_available=False, message="已是最新版本")

    with patch("app.update_service.check_for_updates", side_effect=_fake_check):
        mgr._on_check_update()
        # 等待后台线程完成（给一点时间）
        import time

        time.sleep(0.2)
        qapp.processEvents()

    # check_for_updates 应在非主线程中执行
    assert "current" in thread_holder
    import threading

    assert thread_holder["current"] is not threading.main_thread()


def test_on_check_update_done_resets_flag(qapp):
    """BUG-002: _on_check_update_done 应重置 _update_check_in_flight = False。"""
    mgr = _make_minimal_tray_manager(qapp)

    # 模拟后台线程已完成，结果为「无更新」
    result = MagicMock(ok=True, update_available=False, message="已是最新版本")

    with patch("app.tray.QMessageBox"):
        mgr._update_check_in_flight = True
        mgr._on_check_update_done(result, "检查更新")

    assert mgr._update_check_in_flight is False


def test_on_check_update_done_handles_error(qapp):
    """BUG-002: check_for_updates 失败时 _on_check_update_done 应显示错误对话框。"""
    mgr = _make_minimal_tray_manager(qapp)

    result = MagicMock(ok=False, message="网络错误", error="timeout")

    with patch("app.tray.QMessageBox") as mock_box:
        mgr._on_check_update_done(result, "检查更新")
        mock_box.warning.assert_called_once()

    assert mgr._update_check_in_flight is False
