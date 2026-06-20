"""Main entry single-instance branching tests."""

import sys
from types import SimpleNamespace


def test_main_exits_on_activation_failed_after_retries(monkeypatch):
    """BUG-A09: ACTIVATION_FAILED retries exhausted → sys.exit(2)."""
    import main

    events = []
    activated_existing = object()
    activation_failed = object()
    primary = object()

    class FakeGuard:
        def bind_activate(self, handler):
            events.append(("bind_activate", handler.__name__))

        def try_acquire(self):
            return SimpleNamespace(kind=activation_failed, became_primary=False)

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
                ACTIVATED_EXISTING=activated_existing,
                ACTIVATION_FAILED=activation_failed,
                PRIMARY=primary,
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
    monkeypatch.setattr("time.sleep", lambda _: None)

    assert main.main() == 2
    assert ("exit", 2) in events
    assert all(event[0] != "danmu_init" for event in events)


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


def test_main_retries_activation_failed_then_activates_existing(monkeypatch):
    """BUG-A09: ACTIVATION_FAILED → retry → ACTIVATED_EXISTING → sys.exit(0)."""
    import main

    events = []
    activated_existing = object()
    activation_failed = object()
    primary = object()
    try_acquire_calls = 0

    class FakeGuard:
        def bind_activate(self, handler):
            events.append(("bind_activate", handler.__name__))

        def try_acquire(self):
            nonlocal try_acquire_calls
            try_acquire_calls += 1
            if try_acquire_calls == 1:
                return SimpleNamespace(kind=activation_failed, became_primary=False)
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
                ACTIVATED_EXISTING=activated_existing,
                ACTIVATION_FAILED=activation_failed,
                PRIMARY=primary,
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
    monkeypatch.setattr("time.sleep", lambda _: None)

    assert main.main() == 0
    assert ("exit", 0) in events
    assert all(event[0] != "danmu_init" for event in events)
    assert try_acquire_calls == 2
