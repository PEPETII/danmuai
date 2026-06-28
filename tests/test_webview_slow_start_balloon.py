"""WebView2 慢启动反馈：验证模态 QMessageBox 已替换为非阻塞 tray.showMessage 气泡。

验证：
- _SLOW_START_PROMPT_SEC = 3.0（从 5.0 下调）
- _DISABLE_SLOW_START_PROMPT = False（不再禁用）
- _maybe_prompt_slow_webview_start 调用 tray.showMessage（非 QMessageBox.exec）
- 气泡不阻塞 poll_handshake
"""

import time
from unittest.mock import MagicMock, patch

import pytest

import app.webview_shell as wv_mod


def test_slow_start_prompt_sec_is_3():
    """慢启动阈值应从 5.0 下调到 3.0，更早提示。"""
    assert wv_mod._SLOW_START_PROMPT_SEC == 3.0


def test_disable_slow_start_prompt_is_false():
    """_DISABLE_SLOW_START_PROMPT 应为 False（不再禁用中间提示）。"""
    assert wv_mod._DISABLE_SLOW_START_PROMPT is False


def _make_mock_shell(attach_started_at=None, started=False, server_ok=True):
    """构造测试用 mock shell 对象。"""
    if attach_started_at is None:
        attach_started_at = time.monotonic() - 5.0  # 5s 前开始 attach

    tray_icon = MagicMock()
    danmu_app = MagicMock()
    danmu_app.tray.tray = tray_icon

    bridge = MagicMock()
    bridge.danmu_app = danmu_app

    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.startup_ok = server_ok
    server._slow_webview_prompt_shown = False
    server._browser_launch_opened = False
    server.bridge = bridge

    proc = MagicMock()
    proc.is_alive.return_value = True

    shell = MagicMock()
    shell._started = started
    shell._attach_started_at = attach_started_at
    shell.server = server
    shell._process = proc

    return shell, tray_icon


def test_slow_start_uses_tray_balloon_not_messagebox(qapp):
    """慢启动提示应调用 tray.showMessage，不使用模态 QMessageBox。"""
    from PyQt6.QtWidgets import QSystemTrayIcon

    shell, tray_icon = _make_mock_shell()

    with patch.object(QSystemTrayIcon, "isSystemTrayAvailable", return_value=True):
        with patch("app.webview_shell.QMessageBox", create=True) as mock_box:
            wv_mod._maybe_prompt_slow_webview_start(shell, "/")

    # tray.showMessage 应被调用
    tray_icon.showMessage.assert_called_once()
    # QMessageBox.exec 不应被调用
    mock_box.assert_not_called()

    # server._slow_webview_prompt_shown 应被标记
    assert shell.server._slow_webview_prompt_shown is True


def test_slow_start_skipped_when_already_started(qapp):
    """shell._started=True 时不应弹出气泡。"""
    shell, tray_icon = _make_mock_shell(started=True)

    wv_mod._maybe_prompt_slow_webview_start(shell, "/")

    tray_icon.showMessage.assert_not_called()
    assert shell.server._slow_webview_prompt_shown is False


def test_slow_start_skipped_when_within_threshold(qapp):
    """attach 开始后未满 _SLOW_START_PROMPT_SEC 时不应弹出。"""
    # 1s 前开始 attach，阈值是 3.0s
    shell, tray_icon = _make_mock_shell(
        attach_started_at=time.monotonic() - 1.0
    )

    wv_mod._maybe_prompt_slow_webview_start(shell, "/")

    tray_icon.showMessage.assert_not_called()
    assert shell.server._slow_webview_prompt_shown is False


def test_slow_start_skipped_when_already_shown(qapp):
    """_slow_webview_prompt_shown=True 时不应重复弹出。"""
    shell, tray_icon = _make_mock_shell()
    shell.server._slow_webview_prompt_shown = True

    wv_mod._maybe_prompt_slow_webview_start(shell, "/")

    tray_icon.showMessage.assert_not_called()


def test_slow_start_skipped_when_process_dead(qapp):
    """pywebview 进程已退出时不应弹出。"""
    shell, tray_icon = _make_mock_shell()
    shell._process.is_alive.return_value = False

    wv_mod._maybe_prompt_slow_webview_start(shell, "/")

    tray_icon.showMessage.assert_not_called()
