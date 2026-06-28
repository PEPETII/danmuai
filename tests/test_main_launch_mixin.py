"""Tests for DanmuAppLaunchMixin restore and settings paths."""

from unittest.mock import MagicMock

from app.main_launch_mixin import DanmuAppLaunchMixin


class FakeApp(DanmuAppLaunchMixin):
    def __init__(self):
        self.webview_shell = None
        self.web_server = None


def test_restore_main_window_delegates_to_shell():
    app = FakeApp()
    app.webview_shell = MagicMock()
    app.restore_main_window()
    app.webview_shell.restore_window.assert_called_once()


def test_restore_main_window_silent_when_no_shell():
    app = FakeApp()
    app.restore_main_window()


def test_show_settings_calls_restore_then_opens_console():
    app = FakeApp()
    app.webview_shell = MagicMock()
    app.web_server = MagicMock()

    open_calls = []

    def mock_open(path):
        open_calls.append(path)

    app._open_web_console = mock_open

    app.show_settings()

    app.webview_shell.restore_window.assert_called_once()
    assert open_calls == ["/#settings"]


def test_show_settings_skips_console_when_no_server():
    app = FakeApp()
    app.webview_shell = MagicMock()
    app.web_server = None

    open_calls = []

    def mock_open(path):
        open_calls.append(path)

    app._open_web_console = mock_open

    app.show_settings()

    app.webview_shell.restore_window.assert_called_once()
    assert open_calls == []
