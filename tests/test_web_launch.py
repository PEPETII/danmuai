"""Main flow tests: webview / browser launch and recovery."""

import time
from unittest.mock import MagicMock

from main import DanmuApp

from tests.conftest import make_minimal_danmu_app
from tests.fakes import FakeConfig


class _FakeSignal:
    def connect(self, *_args, **_kwargs):
        return None


class _FakeTranslator:
    language_changed = _FakeSignal()


def test_tray_double_click_opens_settings(qapp):
    from app.tray import TrayManager
    from PyQt6.QtWidgets import QSystemTrayIcon

    app = make_minimal_danmu_app()
    show_settings = MagicMock()
    object.__setattr__(app, "show_settings", show_settings)
    tray = TrayManager(app)
    tray._on_activated(QSystemTrayIcon.ActivationReason.DoubleClick)
    show_settings.assert_called_once()


def test_tray_single_click_opens_settings(qapp, monkeypatch):
    """W-OPEN-CONSOLE-RECOVERY-002: tray left-click opens settings."""
    from app.tray import TrayManager
    from PyQt6.QtWidgets import QSystemTrayIcon

    monkeypatch.setattr("app.tray.Translator.instance", lambda: _FakeTranslator())
    app = make_minimal_danmu_app()
    show_settings = MagicMock()
    object.__setattr__(app, "show_settings", show_settings)
    tray = TrayManager(app)
    tray._on_activated(QSystemTrayIcon.ActivationReason.Trigger)
    show_settings.assert_called_once()


def test_tray_uninstall_keeps_user_data_without_second_delete_confirm(qapp, monkeypatch):
    from app.tray import TrayManager
    from PyQt6.QtWidgets import QMessageBox

    app = make_minimal_danmu_app()
    monkeypatch.setattr("app.tray.Translator.instance", lambda: _FakeTranslator())
    tray = TrayManager(app)

    monkeypatch.setattr(
        "app.uninstall_service.get_status",
        lambda: type(
            "S",
            (),
            {"supported": True, "message": "ready", "error": None},
        )(),
    )
    request_calls = []
    monkeypatch.setattr(
        "app.uninstall_service.request_uninstall",
        lambda *, delete_user_data=False: request_calls.append(delete_user_data)
        or type("S", (), {"ok": True, "message": "started", "error": None})(),
    )

    answers = iter(
        [
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.No,
        ]
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: next(answers))
    info = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: info.append(args))

    tray._on_uninstall()

    assert request_calls == [False]
    assert len(info) == 1


def test_tray_uninstall_delete_user_data_requires_second_confirm(qapp, monkeypatch):
    from app.tray import TrayManager
    from PyQt6.QtWidgets import QMessageBox

    app = make_minimal_danmu_app()
    monkeypatch.setattr("app.tray.Translator.instance", lambda: _FakeTranslator())
    tray = TrayManager(app)

    monkeypatch.setattr(
        "app.uninstall_service.get_status",
        lambda: type(
            "S",
            (),
            {"supported": True, "message": "ready", "error": None},
        )(),
    )
    request_calls = []
    monkeypatch.setattr(
        "app.uninstall_service.request_uninstall",
        lambda *, delete_user_data=False: request_calls.append(delete_user_data)
        or type("S", (), {"ok": True, "message": "started", "error": None})(),
    )

    answers = iter(
        [
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Yes,
            QMessageBox.StandardButton.Yes,
        ]
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)

    tray._on_uninstall()

    assert request_calls == [True]


def test_schedule_webview_skipped_when_startup_terminal_failed(monkeypatch):

    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    object.__setattr__(app, "webview_shell", None)
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._bind_failed.set()
    object.__setattr__(app, "web_server", server)

    scheduled = []
    monkeypatch.setattr(
        "main.QTimer.singleShot",
        lambda ms, cb: scheduled.append(ms),
    )

    app._schedule_webview_attach("/")
    assert scheduled == []


def test_schedule_webview_runs_when_startup_slow(monkeypatch):
    import threading

    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    object.__setattr__(app, "webview_shell", None)
    object.__setattr__(app, "tray", MagicMock())
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)

    def _sleep() -> None:
        time.sleep(5.0)

    server._thread = threading.Thread(target=_sleep, daemon=True)
    server._thread.start()

    scheduled = []
    monkeypatch.setattr(
        "main.QTimer.singleShot",
        lambda ms, cb: scheduled.append(ms),
    )
    try:
        object.__setattr__(app, "web_server", server)
        app._schedule_webview_attach("/")
        assert scheduled == [800]
    finally:
        server._bind_failed.set()
        server._thread.join(timeout=1.0)


def test_schedule_webview_attach_retries_after_handshake_failure(monkeypatch):

    from main import _WEBVIEW_ATTACH_RETRY_MS

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    object.__setattr__(app, "webview_shell", None)
    server = MagicMock()
    server.startup_ok = True
    server.base_url = "http://127.0.0.1:18765"
    server._browser_launch_opened = False
    object.__setattr__(app, "web_server", server)

    attach_count = [0]
    destroy_count = [0]

    class FakeShell:
        def destroy(self):
            destroy_count[0] += 1

        def is_running(self):
            return False

        def is_handshake_pending(self):
            return False

    def fake_attach(danmu, srv, *, initial_path="/", on_handshake_failed=None):
        attach_count[0] += 1
        shell = FakeShell()
        danmu.webview_shell = shell
        if attach_count[0] == 1 and on_handshake_failed is not None:
            on_handshake_failed()
        return shell

    def fake_single_shot(ms, cb):
        if ms == _WEBVIEW_ATTACH_RETRY_MS:
            cb()

    monkeypatch.setattr("app.webview_shell.attach_webview_shell", fake_attach)
    monkeypatch.setattr("main.QTimer.singleShot", fake_single_shot)
    monkeypatch.setattr("app.webview_shell.wait_for_http_server", lambda *a, **k: True)
    monkeypatch.setattr(
        "app.web_console.clear_startup_attach_error_if_needed",
        lambda _s: None,
    )

    app._schedule_webview_attach("/", attempt=1)

    assert attach_count[0] == 2
    assert destroy_count[0] == 1




def test_webview_recovers_after_delayed_server_ready(monkeypatch):
    """BUG-004 sub-scenario: slow startup; HTTP becomes ready within retry window."""
    import threading

    from app.web_console import (
        WebConsoleBridge,
        WebConsoleServer,
        classify_web_console_startup,
    )

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    object.__setattr__(app, "webview_shell", None)
    object.__setattr__(
        app,
        "set_web_error_status",
        DanmuApp.set_web_error_status.__get__(app, DanmuApp),
    )
    object.__setattr__(
        app,
        "_set_error_status_safe",
        DanmuApp._set_error_status_safe.__get__(app, DanmuApp),
    )
    object.__setattr__(
        app,
        "_ensure_web_runtime_state",
        DanmuApp._ensure_web_runtime_state.__get__(app, DanmuApp),
    )

    bridge = WebConsoleBridge.__new__(WebConsoleBridge)
    bridge.danmu_app = app
    server = WebConsoleServer(bridge)
    server._thread = threading.Thread(target=time.sleep, args=(30.0,), daemon=True)
    server._thread.start()
    server._startup_error_from_attach = True
    app.set_web_error_status("Web 控制台未就绪", is_error=True)

    assert classify_web_console_startup(server) == "slow"

    http_checks: list[int] = []

    def _wait_for_http(url: str, timeout: float) -> bool:
        http_checks.append(1)
        return len(http_checks) >= 2

    attach_calls: list[tuple] = []
    notified: list[str] = []
    scheduled: list[tuple] = []

    monkeypatch.setattr("app.webview_shell.wait_for_http_server", _wait_for_http)
    monkeypatch.setattr(
        "app.webview_shell.attach_webview_shell",
        lambda *args, **kwargs: attach_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure",
        lambda danmu, key, **kw: notified.append(key),
    )
    monkeypatch.setattr(
        "main.QTimer.singleShot",
        lambda ms, cb: scheduled.append((ms, cb)),
    )

    try:
        object.__setattr__(app, "web_server", server)
        app._open_web_console_when_ready("/", use_browser=False, attempt=0)

        safety = 0
        while scheduled and not attach_calls and safety < 50:
            safety += 1
            pending = scheduled[:]
            scheduled.clear()
            for _ms, cb in pending:
                cb()

        assert attach_calls, "expected attach_webview_shell after delayed HTTP ready"
        assert len(attach_calls) == 1
        assert app.web_runtime_state.is_error is False
        assert app.web_runtime_state.error_message == ""
        assert server._startup_error_from_attach is False
        assert notified == []
    finally:
        server._bind_failed.set()
        server._thread.join(timeout=1.0)


def test_webview_does_not_recover_when_bind_failed(monkeypatch):
    """Port conflict / bind failure: no in-process webview recovery (restart required)."""

    from app.web_console import WebConsoleBridge, WebConsoleServer, classify_web_console_startup

    app = make_minimal_danmu_app()
    object.__setattr__(app, "webview_shell", None)
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._bind_failed.set()
    object.__setattr__(app, "web_server", server)

    assert classify_web_console_startup(server) == "failed"

    attach_calls: list[tuple] = []
    notified: list[str] = []
    monkeypatch.setattr(
        "app.webview_shell.attach_webview_shell",
        lambda *args, **kwargs: attach_calls.append(1),
    )
    monkeypatch.setattr(
        "app.webview_shell.wait_for_http_server",
        lambda url, timeout: True,
    )
    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure",
        lambda danmu, key, **kw: notified.append(key),
    )

    app._open_web_console_when_ready("/")
    assert attach_calls == []
    assert notified == ["web_console.startup_failed"]


def test_browser_mode_opens_browser_when_server_slow(monkeypatch):
    import threading

    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)

    def _sleep() -> None:
        time.sleep(5.0)

    server._thread = threading.Thread(target=_sleep, daemon=True)
    server._thread.start()

    browser_calls = []
    scheduled = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )
    monkeypatch.setattr(
        "app.webview_shell.wait_for_http_server",
        lambda url, timeout: False,
    )
    monkeypatch.setattr(
        "main.QTimer.singleShot",
        lambda ms, cb: scheduled.append(ms),
    )
    try:
        object.__setattr__(app, "web_server", server)
        app._open_web_console_when_ready("/", use_browser=True, attempt=0)
        assert browser_calls == ["/"]
        assert server._browser_launch_opened is True
        assert scheduled == [500]

        app._open_web_console_when_ready("/", use_browser=True, attempt=1)
        assert browser_calls == ["/"]
    finally:
        server._bind_failed.set()
        server._thread.join(timeout=1.0)


def test_browser_mode_opens_browser_when_server_ready(monkeypatch):

    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server.startup_ok = True
    object.__setattr__(app, "web_server", server)

    browser_calls = []
    scheduled = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )
    monkeypatch.setattr(
        "main.QTimer.singleShot",
        lambda ms, cb: scheduled.append(ms),
    )

    app._open_web_console_when_ready("/", use_browser=True, attempt=0)
    assert browser_calls == ["/"]
    assert scheduled == []




def test_browser_mode_skips_browser_on_terminal_failure(monkeypatch):

    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._bind_failed.set()
    object.__setattr__(app, "web_server", server)

    browser_calls = []
    notified = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )
    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure",
        lambda danmu, key, **kw: notified.append(key),
    )

    app._open_web_console_when_ready("/", use_browser=True, attempt=0)
    assert browser_calls == []
    assert notified == ["web_console.startup_failed"]


def test_browser_mode_open_web_console_dedupes_browser(monkeypatch):

    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "browser")
    object.__setattr__(app, "webview_shell", None)
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server.startup_ok = True
    server._browser_launch_opened = True
    object.__setattr__(app, "web_server", server)

    browser_calls = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )

    app._open_web_console("/#settings")
    assert browser_calls == []


def test_browser_mode_start_without_api_key_dedupes_with_timer_path(monkeypatch):
    import threading

    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "browser")
    object.__setattr__(app, "webview_shell", None)
    object.__setattr__(app, "config", FakeConfig({}))
    object.__setattr__(app, "tray", MagicMock())
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._thread = threading.Thread(target=time.sleep, args=(5.0,), daemon=True)
    server._thread.start()
    object.__setattr__(app, "web_server", server)
    object.__setattr__(
        app,
        "_set_error_status_safe",
        DanmuApp._set_error_status_safe.__get__(app, DanmuApp),
    )

    browser_calls = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )
    monkeypatch.setattr(
        "app.webview_shell.wait_for_http_server",
        lambda url, timeout: False,
    )
    monkeypatch.setattr(
        "main.QTimer.singleShot",
        lambda ms, cb: None,
    )

    try:
        DanmuApp.start(app)
        app._open_web_console_when_ready("/#settings", use_browser=True, attempt=0)
        assert browser_calls == ["/#settings"]
        assert server._browser_launch_opened is True
    finally:
        server._bind_failed.set()
        server._thread.join(timeout=1.0)


def test_browser_mode_opens_browser_after_5s_when_server_slow(monkeypatch):
    import threading

    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._thread = threading.Thread(target=time.sleep, args=(5.0,), daemon=True)
    server._thread.start()
    object.__setattr__(app, "web_server", server)

    browser_calls = []
    scheduled = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )
    monkeypatch.setattr(
        "app.webview_shell.wait_for_http_server",
        lambda url, timeout: False,
    )
    monkeypatch.setattr(
        "main.QTimer.singleShot",
        lambda ms, cb: scheduled.append(ms),
    )

    try:
        app._open_web_console_when_ready("/", use_browser=True, attempt=0)
        assert browser_calls == ["/"]
        assert server._browser_launch_opened is True

        scheduled.clear()
        app._open_web_console_when_ready("/", use_browser=True, attempt=10)
        assert browser_calls == ["/"]
        assert scheduled == [500]
    finally:
        server._bind_failed.set()
        server._thread.join(timeout=1.0)

