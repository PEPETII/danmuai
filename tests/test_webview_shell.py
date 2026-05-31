"""Tests for pywebview shell helpers."""

import sys
from unittest.mock import MagicMock, patch

from app.webview_shell import (
    _SIGNAL_CREATED,
    _SIGNAL_LOADED,
    WebViewShell,
    _webview_worker,
    notify_web_console_failure,
    preferred_webview_gui,
    wait_for_http_server,
)


def test_preferred_webview_gui_windows():
    with patch.object(sys, "platform", "win32"):
        assert preferred_webview_gui() == "edgechromium"


def test_wait_for_http_server_success():
    class FakeResp:
        status = 200

        def read(self):
            return b'{"token":"abc","base_url":"http://127.0.0.1:18765"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        assert wait_for_http_server("http://127.0.0.1:18765", timeout=1.0) is True


def test_wait_for_http_server_rejects_missing_token():
    class FakeResp:
        status = 200

        def read(self):
            return b'{"base_url":"http://127.0.0.1:18765"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        assert wait_for_http_server("http://127.0.0.1:18765", timeout=0.5) is False


def test_webview_shell_url_hash_path():
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    shell = WebViewShell(server)
    assert shell._url("/#settings") == "http://127.0.0.1:18765/#settings"
    assert shell._url("#settings") == "http://127.0.0.1:18765/#settings"


def test_webview_shell_open_delegates_to_start_when_not_running(monkeypatch):
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.bridge.danmu_app.logger = MagicMock()
    shell = WebViewShell(server)
    shell._started = False
    shell._process = None

    called = []

    def fake_start(path):
        called.append(path)
        return False

    monkeypatch.setattr(shell, "start", fake_start)

    shell.open("/#settings")
    assert called == ["/#settings"]


def test_webview_shell_is_handshake_pending():
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    shell = WebViewShell(server)
    assert shell.is_handshake_pending() is False

    shell._process = MagicMock()
    shell._process.is_alive.return_value = True
    assert shell.is_handshake_pending() is True

    shell._started = True
    assert shell.is_handshake_pending() is False


def test_attach_webview_shell_reuses_pending_without_second_process(monkeypatch):
    from PyQt6.QtCore import QTimer
    from app.webview_shell import attach_webview_shell

    danmu = MagicMock()
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    existing = WebViewShell(server)
    existing._process = MagicMock()
    existing._process.is_alive.return_value = True
    existing._nav_queue = MagicMock()
    existing._got_created = True
    danmu.webview_shell = existing

    begin_calls = []
    monkeypatch.setattr(existing, "begin_start", lambda path: begin_calls.append(path) or True)
    monkeypatch.setattr(QTimer, "singleShot", lambda _ms, fn: fn())

    shell = attach_webview_shell(danmu, server, initial_path="/#settings")

    assert shell is existing
    assert begin_calls == []
    existing._nav_queue.put.assert_called_once_with("http://127.0.0.1:18765/#settings")


def test_webview_shell_open_uses_nav_queue_when_running():
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    shell = WebViewShell(server)
    shell._started = True
    shell._process = MagicMock()
    shell._process.is_alive.return_value = True
    shell._nav_queue = MagicMock()

    shell.open("/#settings")

    shell._nav_queue.put.assert_called_once_with("http://127.0.0.1:18765/#settings")


def test_webview_worker_puts_created_before_start(monkeypatch):
    ready_puts = []
    loaded_handler = []

    class FakeReadyQueue:
        def put(self, value):
            ready_puts.append(value)

    class FakeEventSlot:
        def __init__(self):
            self._handlers = []

        def __iadd__(self, handler):
            self._handlers.append(handler)
            if handler.__name__ == "on_loaded":
                loaded_handler.append(handler)
            return self

    class FakeWindow:
        events = type("E", (), {"loaded": FakeEventSlot(), "closing": FakeEventSlot()})()

        def show(self):
            pass

    fake_webview = MagicMock()
    fake_webview.create_window.return_value = FakeWindow()
    start_called = []

    def fake_start(**_kwargs):
        start_called.append(True)
        assert ready_puts == [_SIGNAL_CREATED]
        loaded_handler[0](FakeWindow())

    fake_webview.start.side_effect = fake_start
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    nav_queue = MagicMock()
    _webview_worker("http://127.0.0.1:18765/", "DanmuAI", "edgechromium", FakeReadyQueue(), nav_queue)

    assert ready_puts == [_SIGNAL_CREATED, _SIGNAL_LOADED]
    assert start_called


def test_webview_worker_start_error_puts_error(monkeypatch):
    ready_puts = []

    class FakeReadyQueue:
        def put(self, value):
            ready_puts.append(value)

    class FakeEventSlot:
        def __iadd__(self, _handler):
            return self

    class FakeWindow:
        events = type("E", (), {"loaded": FakeEventSlot(), "closing": FakeEventSlot()})()

        def show(self):
            pass

    fake_webview = MagicMock()
    fake_webview.create_window.return_value = FakeWindow()
    fake_webview.start.side_effect = RuntimeError("webview boom")
    monkeypatch.setitem(sys.modules, "webview", fake_webview)
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    _webview_worker("http://127.0.0.1:18765/", "DanmuAI", None, FakeReadyQueue(), MagicMock())

    assert ready_puts == [_SIGNAL_CREATED, "webview boom"]


def test_webview_shell_poll_handshake_success(monkeypatch):
    import time

    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.bridge.danmu_app.logger = MagicMock()
    shell = WebViewShell(server)
    shell._process = MagicMock()
    shell._process.is_alive.return_value = True
    shell._handshake_deadline = time.monotonic() + 10.0

    signals = [_SIGNAL_CREATED, _SIGNAL_LOADED]

    class FakeQueue:
        def get_nowait(self):
            return signals.pop(0)

    shell._ready_queue = FakeQueue()
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    assert shell.poll_handshake("/") == "success"
    assert shell._started is True


def test_webview_shell_poll_handshake_error_after_created(monkeypatch):
    import time

    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.bridge.danmu_app.logger = MagicMock()
    shell = WebViewShell(server)
    shell._process = MagicMock()
    shell._process.is_alive.return_value = True
    shell._handshake_deadline = time.monotonic() + 10.0

    signals = [_SIGNAL_CREATED, "webview boom"]

    class FakeQueue:
        def get_nowait(self):
            return signals.pop(0)

    shell._ready_queue = FakeQueue()
    fallbacks = []
    monkeypatch.setattr(
        "app.webview_shell._fallback_to_system_browser",
        lambda s, p, r: fallbacks.append((p, r)),
    )
    monkeypatch.setattr(shell, "_terminate", lambda: None)
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    assert shell.poll_handshake("/#settings") == "failure"
    assert shell._started is False
    assert fallbacks == [("/#settings", "webview boom")]


def test_webview_shell_poll_handshake_load_timeout(monkeypatch):
    import queue
    import time

    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.bridge.danmu_app.logger = MagicMock()
    shell = WebViewShell(server)
    shell._process = MagicMock()
    shell._process.is_alive.return_value = True
    shell._handshake_deadline = time.monotonic() + 10.0

    class FakeQueue:
        def __init__(self):
            self.calls = 0

        def get_nowait(self):
            self.calls += 1
            if self.calls == 1:
                return _SIGNAL_CREATED
            raise queue.Empty()

    shell._ready_queue = FakeQueue()
    fallbacks = []
    monkeypatch.setattr(
        "app.webview_shell._fallback_to_system_browser",
        lambda s, p, r: fallbacks.append(r),
    )
    monkeypatch.setattr(shell, "_terminate", lambda: None)
    monkeypatch.setattr("app.webview_shell._load_timeout_sec", lambda: 0.01)
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    assert shell.poll_handshake("/") == "pending"
    time.sleep(0.02)
    assert shell.poll_handshake("/") == "failure"
    assert shell.handshake_failed is True
    assert fallbacks == ["timeout waiting for pywebview loaded"]


def test_notify_web_console_failure_schedules_ui(qtbot, monkeypatch):
    from PyQt6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    danmu = MagicMock()
    danmu.web_server = MagicMock(base_url="http://127.0.0.1:18765")
    danmu.tray = MagicMock()
    danmu.tray.tray = MagicMock()

    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: warnings.append(args),
    )

    notify_web_console_failure(danmu, "web_console.startup_failed")
    app.processEvents()

    assert warnings


def test_ensure_server_ready_verifies_http_when_startup_ok(monkeypatch):
    from app import webview_shell

    server = MagicMock()
    server.startup_ok = True
    server.base_url = "http://127.0.0.1:18765"
    server.wait_ready = MagicMock()
    monkeypatch.setattr(webview_shell, "wait_for_http_server", lambda url, timeout: True)

    assert webview_shell._ensure_server_ready(server) is True
    server.wait_ready.assert_not_called()


def test_ensure_server_ready_false_notifies_and_optional_browser(monkeypatch):
    from app import webview_shell

    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.startup_ok = False
    server.wait_ready.return_value = False
    server.bridge.danmu_app.logger = MagicMock()

    notified = []
    fallbacks = []
    monkeypatch.setattr(
        webview_shell,
        "notify_web_console_failure",
        lambda app, key, **kw: notified.append((key, kw)),
    )
    monkeypatch.setattr(webview_shell, "wait_for_http_server", lambda url, timeout: timeout == 3.0)
    monkeypatch.setattr(
        webview_shell,
        "_fallback_to_system_browser",
        lambda s, p, r: fallbacks.append((p, r)),
    )

    assert webview_shell._ensure_server_ready(server) is False
    assert notified
    assert fallbacks == []
