"""Main entry single-instance branching tests."""

import sys
from types import SimpleNamespace


def test_main_continues_startup_when_activation_failed(monkeypatch):
    import main

    events = []
    activated_existing = object()
    activation_failed = object()

    class FakeGuard:
        def bind_activate(self, handler):
            events.append(("bind_activate", handler.__name__))

        def try_acquire(self):
            return SimpleNamespace(kind=activation_failed, became_primary=False)

    class FakeApp:
        def setQuitOnLastWindowClosed(self, value):
            events.append(("set_quit_on_last_window_closed", value))

        def exec(self):
            events.append(("exec", None))
            return 91

    class FakeDanmuApp:
        def __init__(self, web_launch_mode):
            events.append(("danmu_init", web_launch_mode))

        def show_settings(self):
            events.append(("show_settings", None))

    def fake_exit(code):
        events.append(("exit", code))
        return code

    monkeypatch.setitem(
        sys.modules,
        "app.single_instance",
        SimpleNamespace(
            SingleInstanceAcquireKind=SimpleNamespace(
                ACTIVATED_EXISTING=activated_existing
            ),
            SingleInstanceGuard=FakeGuard,
        ),
    )
    monkeypatch.setattr(
        main.multiprocessing,
        "freeze_support",
        lambda: events.append(("freeze_support", None)),
    )
    monkeypatch.setattr(
        main,
        "check_deprecated_launch_args",
        lambda: events.append(("check_args", None)),
    )
    monkeypatch.setattr(main, "global_exception_hook", object())
    monkeypatch.setattr(main, "QApplication", lambda _argv: FakeApp())
    monkeypatch.setattr(main, "DanmuApp", FakeDanmuApp)
    monkeypatch.setattr(main, "web_launch_mode_from_argv", lambda: "webview")
    monkeypatch.setattr(main.sys, "exit", fake_exit)
    monkeypatch.setattr(
        "app.velopack_runtime.run_startup_apply_if_needed",
        lambda: events.append(("apply_updates", None)),
    )
    monkeypatch.setattr(
        "app.startup_trace.mark_app_start",
        lambda: events.append(("mark_app_start", None)),
    )
    monkeypatch.setattr(
        "app.startup_trace.log_startup",
        lambda name, **kwargs: events.append(("log", name, kwargs)),
    )

    assert main.main() == 91
    assert ("exec", None) in events
    assert ("exit", 91) in events
    assert ("danmu_init", "webview") in events
    assert ("bind_activate", "show_settings") in events
    assert (
        "log",
        "single_instance.done",
        {"acquired": False, "activated_existing": False},
    ) in events


def test_main_exits_silently_when_existing_instance_activated(monkeypatch):
    import main

    events = []
    activated_existing = object()

    class FakeGuard:
        def bind_activate(self, handler):
            events.append(("bind_activate", handler.__name__))

        def try_acquire(self):
            return SimpleNamespace(kind=activated_existing, became_primary=False)

    class FakeApp:
        def setQuitOnLastWindowClosed(self, value):
            events.append(("set_quit_on_last_window_closed", value))

    def fake_exit(code):
        events.append(("exit", code))
        return code

    monkeypatch.setitem(
        sys.modules,
        "app.single_instance",
        SimpleNamespace(
            SingleInstanceAcquireKind=SimpleNamespace(
                ACTIVATED_EXISTING=activated_existing
            ),
            SingleInstanceGuard=FakeGuard,
        ),
    )
    monkeypatch.setattr(main.multiprocessing, "freeze_support", lambda: None)
    monkeypatch.setattr(main, "check_deprecated_launch_args", lambda: None)
    monkeypatch.setattr(main, "global_exception_hook", object())
    monkeypatch.setattr(main, "QApplication", lambda _argv: FakeApp())
    monkeypatch.setattr(main, "DanmuApp", lambda *args, **kwargs: events.append(("danmu_init", None)))
    monkeypatch.setattr(main, "web_launch_mode_from_argv", lambda: "webview")
    monkeypatch.setattr(main.sys, "exit", fake_exit)
    monkeypatch.setattr("app.velopack_runtime.run_startup_apply_if_needed", lambda: None)
    monkeypatch.setattr("app.startup_trace.mark_app_start", lambda: None)
    monkeypatch.setattr(
        "app.startup_trace.log_startup",
        lambda name, **kwargs: events.append(("log", name, kwargs)),
    )

    assert main.main() == 0
    assert ("exit", 0) in events
    assert (
        "log",
        "single_instance.done",
        {"acquired": False, "activated_existing": True},
    ) in events
    assert all(event[0] != "danmu_init" for event in events)
