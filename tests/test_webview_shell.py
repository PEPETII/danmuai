"""Tests for pywebview shell helpers."""

import queue
import sys
import time
from unittest.mock import MagicMock, patch

from app.webview_shell import (
    _SIGNAL_CREATED,
    _SIGNAL_LOADED,
    WebViewShell,
    _fallback_to_system_browser,
    _maybe_prompt_slow_webview_start,
    _tray_icon_for_notify,
    _webview_worker,
    notify_web_console_failure,
    preferred_webview_gui,
    wait_for_http_server,
)
from main import DanmuApp


def test_preferred_webview_gui_windows():
    with patch.object(sys, "platform", "win32"):
        assert preferred_webview_gui() == "edgechromium"


def test_wait_for_http_server_success():
    class FakeResp:
        status = 200

        def read(self):
            return b'{"running":false,"danmu_count":0}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    with patch("urllib.request.urlopen", return_value=FakeResp()):
        assert wait_for_http_server("http://127.0.0.1:18765", timeout=1.0) is True


def test_wait_for_http_server_rejects_invalid_json():
    class FakeResp:
        status = 200

        def read(self):
            return b"not-json"

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
    from app.webview_shell import attach_webview_shell
    from PyQt6.QtCore import QTimer

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


def test_tray_icon_for_notify_tolerates_partial_danmu_app():
    """Partial DanmuApp (no QObject __init__) must not break deferred failure UI."""
    app = DanmuApp.__new__(DanmuApp)
    assert _tray_icon_for_notify(app) is None


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


def test_ensure_server_ready_false_defers_without_notify(monkeypatch):
    from app import webview_shell

    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.startup_ok = False
    server.wait_ready.return_value = False
    server.bridge.danmu_app.logger = MagicMock()

    notified = []
    monkeypatch.setattr(
        webview_shell,
        "notify_web_console_failure",
        lambda app, key, **kw: notified.append((key, kw)),
    )
    monkeypatch.setattr(webview_shell, "wait_for_http_server", lambda url, timeout: False)
    monkeypatch.setattr(webview_shell, "_server_ready_probe_sec", lambda: 0.5)

    started = time.monotonic()
    assert webview_shell._ensure_server_ready(server) is False
    assert time.monotonic() - started < 2.0
    assert notified == []
    server.wait_ready.assert_called_once()
    assert server.wait_ready.call_args.kwargs["timeout"] == 0.5


def test_fallback_to_system_browser_only_once(monkeypatch):
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server._browser_launch_opened = False
    server.bridge.danmu_app.logger = MagicMock()
    browser_calls = []
    skipped = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )
    monkeypatch.setattr(
        "app.webview_shell.log_startup",
        lambda event, **kw: skipped.append((event, kw)) if event.endswith(".skipped") else None,
    )
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    _fallback_to_system_browser(server, "/", "first")
    _fallback_to_system_browser(server, "/#settings", "second")

    assert browser_calls == ["/"]
    assert server._browser_launch_opened is True
    assert any(e == "webview.fallback_browser.skipped" for e, _ in skipped)


def test_begin_start_retries_when_spawn_fails(monkeypatch):
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.bridge.danmu_app.logger = MagicMock()
    shell = WebViewShell(server)
    start_calls = []

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            self._alive = True

        def start(self):
            start_calls.append(True)
            if len(start_calls) <= 2:
                self._alive = False

        def is_alive(self):
            return self._alive

        def terminate(self):
            self._alive = False

        def join(self, timeout=0):
            return None

    class FakeQueue:
        def __init__(self):
            self._signals = []

        def get_nowait(self):
            if not self._signals:
                raise queue.Empty()
            return self._signals.pop(0)

        def put(self, item):
            pass

    queues = []

    class FakeContext:
        def Queue(self):
            q = FakeQueue()
            queues.append(q)
            return q

        def Process(self, *args, **kwargs):
            return FakeProcess()

    monkeypatch.setattr(
        "app.webview_shell.multiprocessing.get_context",
        lambda _name: FakeContext(),
    )
    monkeypatch.setattr(
        "app.webview_shell._ensure_server_ready",
        lambda _server: True,
    )
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    assert shell.begin_start("/") is True
    assert len(start_calls) == 1

    assert shell.poll_handshake("/") == "pending"
    assert len(start_calls) == 2

    assert shell.poll_handshake("/") == "pending"
    assert len(start_calls) == 3

    assert shell._ready_queue is not None
    shell._ready_queue._signals.extend([_SIGNAL_CREATED, _SIGNAL_LOADED])
    assert shell.poll_handshake("/") == "success"
    assert shell._started is True
    assert shell.handshake_failed is False


def test_begin_start_spawn_retries_exhausted_falls_back_once(monkeypatch):
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.bridge.danmu_app.logger = MagicMock()
    server._browser_launch_opened = False
    shell = WebViewShell(server)

    class FakeProcess:
        def start(self):
            pass

        def is_alive(self):
            return False

        def terminate(self):
            pass

        def join(self, timeout=0):
            return None

    class FakeContext:
        def Queue(self):
            return MagicMock()

        def Process(self, *args, **kwargs):
            return FakeProcess()

    fallbacks = []
    monkeypatch.setattr(
        "app.webview_shell.multiprocessing.get_context",
        lambda _name: FakeContext(),
    )
    monkeypatch.setattr(
        "app.webview_shell._ensure_server_ready",
        lambda _server: True,
    )
    monkeypatch.setattr(
        "app.webview_shell._fallback_to_system_browser",
        lambda s, p, r: fallbacks.append(r),
    )
    monkeypatch.setattr(shell, "_terminate", lambda: None)
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    assert shell.begin_start("/") is True
    for _ in range(5):
        if shell.poll_handshake("/") == "failure":
            break
    assert shell.handshake_failed is True
    assert len(fallbacks) == 1


def test_fail_start_is_idempotent(monkeypatch):
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.bridge.danmu_app.logger = MagicMock()
    shell = WebViewShell(server)
    shell._handshake_failed = True

    fallbacks = []
    monkeypatch.setattr(
        "app.webview_shell._fallback_to_system_browser",
        lambda s, p, r: fallbacks.append(r),
    )
    monkeypatch.setattr(shell, "_terminate", lambda: None)
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    assert shell._fail_start("again", "/") is False
    assert fallbacks == []


def _slow_pending_shell(*, attach_elapsed_sec: float = 11.0):
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.startup_ok = True
    server._slow_webview_prompt_shown = False
    server._browser_launch_opened = False
    server.bridge.danmu_app.logger = MagicMock()
    shell = WebViewShell(server)
    shell._process = MagicMock()
    shell._process.is_alive.return_value = True
    shell._attach_started_at = time.monotonic() - attach_elapsed_sec
    shell._handshake_deadline = time.monotonic() + 20.0
    shell._ready_queue = MagicMock()
    shell._ready_queue.get_nowait.side_effect = queue.Empty()
    return server, shell


def _patch_message_box(monkeypatch, *, click_yes: bool):
    yes_btn = MagicMock(name="yes_btn")
    no_btn = MagicMock(name="no_btn")
    fake_box = MagicMock()
    fake_box.addButton.side_effect = [yes_btn, no_btn]
    fake_box.clickedButton.return_value = yes_btn if click_yes else no_btn
    mock_cls = MagicMock(return_value=fake_box)
    mock_cls.Icon = MagicMock()
    mock_cls.Icon.Question = 0
    mock_cls.ButtonRole = MagicMock()
    mock_cls.ButtonRole.YesRole = 0
    mock_cls.ButtonRole.NoRole = 1
    monkeypatch.setattr("PyQt6.QtWidgets.QMessageBox", mock_cls)
    return fake_box


def test_slow_start_prompt_disabled_no_browser(monkeypatch):
    server, shell = _slow_pending_shell()
    _patch_message_box(monkeypatch, click_yes=True)
    browser_calls = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append((srv, p)),
    )

    _maybe_prompt_slow_webview_start(shell, "/")

    assert server._slow_webview_prompt_shown is False
    assert server._browser_launch_opened is False
    assert browser_calls == []


def test_slow_start_prompt_disabled_no_dialog(monkeypatch):
    server, shell = _slow_pending_shell()
    _patch_message_box(monkeypatch, click_yes=False)
    browser_calls = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )

    _maybe_prompt_slow_webview_start(shell, "/")

    assert server._slow_webview_prompt_shown is False
    assert browser_calls == []
    assert server._browser_launch_opened is False


def test_slow_start_prompt_disabled_before_threshold(monkeypatch):
    server, shell = _slow_pending_shell(attach_elapsed_sec=5.0)
    fake_box = _patch_message_box(monkeypatch, click_yes=True)

    _maybe_prompt_slow_webview_start(shell, "/")

    fake_box.exec.assert_not_called()
    assert server._slow_webview_prompt_shown is False


def test_slow_start_prompt_disabled_with_browser_opened(monkeypatch):
    server, shell = _slow_pending_shell()
    server._browser_launch_opened = True
    fake_box = _patch_message_box(monkeypatch, click_yes=True)

    _maybe_prompt_slow_webview_start(shell, "/")

    fake_box.exec.assert_not_called()


def test_slow_start_prompt_disabled_http_not_ready(monkeypatch):
    server, shell = _slow_pending_shell()
    server.startup_ok = False
    fake_box = _patch_message_box(monkeypatch, click_yes=True)
    monkeypatch.setattr(
        "app.webview_shell.wait_for_http_server",
        lambda *a, **k: False,
    )

    _maybe_prompt_slow_webview_start(shell, "/")

    fake_box.exec.assert_not_called()
    assert server._slow_webview_prompt_shown is False


def test_slow_start_prompt_disabled_no_dialog_at_all(monkeypatch):
    server, shell = _slow_pending_shell()
    fake_box = _patch_message_box(monkeypatch, click_yes=False)

    _maybe_prompt_slow_webview_start(shell, "/")
    _maybe_prompt_slow_webview_start(shell, "/")

    fake_box.exec.assert_not_called()
    assert server._slow_webview_prompt_shown is False


def test_poll_handshake_slow_prompt_disabled_stays_pending(monkeypatch):
    server, shell = _slow_pending_shell()
    _patch_message_box(monkeypatch, click_yes=True)
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: None,
    )
    terminate_calls = []
    monkeypatch.setattr(shell, "_terminate", lambda: terminate_calls.append(True))

    result = shell.poll_handshake("/")

    assert result == "pending"
    assert shell._started is False
    assert terminate_calls == []
    assert server._browser_launch_opened is False


def test_webview_shell_restore_window_when_running():
    from app.webview_shell import _RESTORE_WINDOW_MARKER

    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    shell = WebViewShell(server)
    shell._started = True
    shell._process = MagicMock()
    shell._process.is_alive.return_value = True
    shell._nav_queue = MagicMock()

    shell.restore_window()

    shell._nav_queue.put.assert_called_once_with(_RESTORE_WINDOW_MARKER)


def test_webview_shell_restore_window_when_not_running():
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    shell = WebViewShell(server)
    shell._started = False
    shell._process = None
    shell._nav_queue = MagicMock()

    shell.restore_window()

    shell._nav_queue.put.assert_not_called()


def test_nav_poll_loop_restore_marker(monkeypatch):
    import threading
    from app.webview_shell import _nav_poll_loop, _RESTORE_WINDOW_MARKER

    window = MagicMock()
    nav_queue = MagicMock()

    responses = [_RESTORE_WINDOW_MARKER, Exception("stop")]

    def fake_get(timeout):
        resp = responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        return resp

    nav_queue.get.side_effect = fake_get

    stop_event = threading.Event()

    def fake_is_set():
        return len(responses) == 0

    monkeypatch.setattr(stop_event, "is_set", fake_is_set)
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    _nav_poll_loop(window, nav_queue, stop_event)

    window.show.assert_called_once()
    window.restore.assert_called_once()
    window.activate.assert_called_once()


def test_terminate_kills_stubborn_process():
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    shell = WebViewShell(server)

    class StubbornProcess:
        def __init__(self) -> None:
            self._alive = True
            self.terminate_calls = 0
            self.kill_calls = 0

        def is_alive(self) -> bool:
            return self._alive

        def terminate(self) -> None:
            self.terminate_calls += 1

        def kill(self) -> None:
            self.kill_calls += 1
            self._alive = False

        def join(self, timeout: float = 0) -> None:
            return None

    proc = StubbornProcess()
    shell._process = proc
    shell._terminate()

    assert proc.terminate_calls == 1
    assert proc.kill_calls == 1
    assert proc.is_alive() is False
    assert shell._process is None
