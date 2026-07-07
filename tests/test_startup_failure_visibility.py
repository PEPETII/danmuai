"""BUG-001: DanmuApp construction failure must show a user-visible dialog."""

from __future__ import annotations

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_show_fatal_startup_error_calls_message_box(monkeypatch):
    from app.main_launch import show_fatal_startup_error

    logged: list[str] = []
    monkeypatch.setattr(
        "app.main_launch._log_unhandled_exception",
        lambda message: logged.append(message),
    )
    critical = MagicMock()
    monkeypatch.setattr("app.main_launch.QMessageBox.critical", critical)

    exc = RuntimeError("config db corrupt")
    show_fatal_startup_error(exc)

    assert len(logged) == 1
    assert "config db corrupt" in logged[0]
    critical.assert_called_once()
    assert critical.call_args[0][2] == "应用启动失败: config db corrupt"


def test_main_shows_dialog_when_danmu_app_init_fails(monkeypatch):
    import main

    events: list[tuple] = []
    primary = object()

    class FakeGuard:
        def bind_activate(self, handler):
            events.append(("bind_activate", handler))

        def try_acquire(self):
            return SimpleNamespace(kind=primary, became_primary=True)

        def release(self):
            events.append(("release", None))

    class FakeApp:
        def setQuitOnLastWindowClosed(self, value):
            events.append(("set_quit_on_last_window_closed", value))

        def exec(self):
            events.append(("exec", None))
            return 0

    def fake_danmu_app(*args, **kwargs):
        raise RuntimeError("config db corrupt")

    def fake_exit(code):
        events.append(("exit", code))
        return code

    show_error = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "app.single_instance",
        SimpleNamespace(
            SingleInstanceAcquireKind=SimpleNamespace(
                ACTIVATED_EXISTING=object(),
                ACTIVATION_FAILED=object(),
                PRIMARY=primary,
            ),
            SingleInstanceGuard=FakeGuard,
        ),
    )
    monkeypatch.setattr(main.multiprocessing, "freeze_support", lambda: None)
    monkeypatch.setattr(main, "check_deprecated_launch_args", lambda: None)
    monkeypatch.setattr(main, "global_exception_hook", object())
    monkeypatch.setattr(main, "QApplication", lambda _argv: FakeApp())
    monkeypatch.setattr(main, "DanmuApp", fake_danmu_app)
    monkeypatch.setattr(main, "web_launch_mode_from_argv", lambda: "webview")
    monkeypatch.setattr(main, "show_fatal_startup_error", show_error)
    monkeypatch.setattr(main, "register_unhandled_exception_notifier", lambda _n: None)
    monkeypatch.setattr(main.sys, "exit", fake_exit)
    monkeypatch.setattr("app.velopack_runtime.run_startup_apply_if_needed", lambda: None)
    monkeypatch.setattr("app.startup_trace.mark_app_start", lambda: None)
    monkeypatch.setattr("app.startup_trace.log_startup", lambda *_a, **_k: None)

    assert main.main() == 1
    show_error.assert_called_once()
    assert isinstance(show_error.call_args[0][0], RuntimeError)
    assert str(show_error.call_args[0][0]) == "config db corrupt"
    assert ("exit", 1) in events
    assert ("release", None) in events
    assert all(event[0] != "exec" for event in events)


def test_release_startup_failure_releases_resources(qapp):
    from unittest.mock import MagicMock

    from main import DanmuApp
    from PyQt6.QtCore import QObject

    del qapp
    app = DanmuApp.__new__(DanmuApp)
    QObject.__init__(app)
    hotkey = MagicMock()
    tray = MagicMock()
    overlay = MagicMock()
    config = MagicMock()
    ai_worker = MagicMock()
    history_writer = MagicMock()
    object.__setattr__(app, "hotkey", hotkey)
    object.__setattr__(app, "tray", tray)
    object.__setattr__(app, "overlay", overlay)
    object.__setattr__(app, "config", config)
    object.__setattr__(app, "ai_worker", ai_worker)
    object.__setattr__(app, "history_writer", history_writer)

    DanmuApp.release_startup_failure(app)

    hotkey.unregister.assert_called_once()
    tray.hide.assert_called_once()
    overlay.hide.assert_called_once()
    config.close.assert_called_once()
    ai_worker.close.assert_called_once()
    history_writer.stop.assert_called_once()


def test_fatal_startup_error_releases_resources(monkeypatch, qapp):
    from main import DanmuApp

    del qapp
    release_called = []

    def fake_release(self):
        release_called.append(True)

    monkeypatch.setattr(
        "app.main_lifecycle_mixin.DanmuAppLifecycleMixin.release_startup_failure",
        fake_release,
    )
    monkeypatch.setattr("app.startup_trace.log_startup", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        DanmuApp,
        "_init_runtime_bridge_state",
        lambda self, mode: object.__setattr__(self, "web_server", None),
    )
    monkeypatch.setattr(DanmuApp, "_init_core_subsystems", lambda self, log: None)
    monkeypatch.setattr(DanmuApp, "_init_request_pipeline_state", lambda self: None)
    monkeypatch.setattr(DanmuApp, "_init_runtime_tracking_state", lambda self: None)
    monkeypatch.setattr(DanmuApp, "_init_startup_services", lambda self, log: None)

    def raise_web_stack(_self, _log):
        raise OSError("port in use")

    monkeypatch.setattr(DanmuApp, "_start_web_console_stack", raise_web_stack)

    with pytest.raises(OSError, match="port in use"):
        DanmuApp()

    assert release_called == [True]
