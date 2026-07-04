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


def test_server_name_includes_username(monkeypatch):
    """BUG-006: same APPDATA but different USERNAME must yield different server names."""
    import sys
    from types import SimpleNamespace

    # app.single_instance imports PyQt6.QtNetwork at module load time; stub it
    # so the test can run without the QtNetwork DLL (the function under test
    # only needs hashlib + os).
    monkeypatch.setitem(
        sys.modules,
        "PyQt6.QtNetwork",
        SimpleNamespace(QLocalServer=object(), QLocalSocket=object()),
    )
    from app.single_instance import _server_name

    monkeypatch.setenv("APPDATA", "C:\\Users\\Shared\\AppData\\Roaming")
    monkeypatch.setenv("USERNAME", "Alice")
    monkeypatch.delenv("USER", raising=False)
    name_alice = _server_name()

    monkeypatch.setenv("USERNAME", "Bob")
    name_bob = _server_name()

    assert name_alice != name_bob
    assert name_alice.startswith("DanmuAI-")
    assert name_bob.startswith("DanmuAI-")
    assert len(name_alice) == len("DanmuAI-") + 16
    assert len(name_bob) == len("DanmuAI-") + 16


def test_server_name_stable_for_same_user(monkeypatch):
    """BUG-006: same USERNAME + APPDATA must yield stable server name across calls."""
    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules,
        "PyQt6.QtNetwork",
        SimpleNamespace(QLocalServer=object(), QLocalSocket=object()),
    )
    from app.single_instance import _server_name

    monkeypatch.setenv("APPDATA", "C:\\Users\\Alice\\AppData\\Roaming")
    monkeypatch.setenv("USERNAME", "Alice")
    monkeypatch.delenv("USER", raising=False)

    assert _server_name() == _server_name()


def test_server_name_falls_back_to_user_env(monkeypatch):
    """BUG-006: when USERNAME is missing, fall back to USER env (POSIX-style)."""
    import sys
    from types import SimpleNamespace

    monkeypatch.setitem(
        sys.modules,
        "PyQt6.QtNetwork",
        SimpleNamespace(QLocalServer=object(), QLocalSocket=object()),
    )
    from app.single_instance import _server_name

    monkeypatch.setenv("APPDATA", "/home/alice/.config")
    monkeypatch.delenv("USERNAME", raising=False)
    monkeypatch.setenv("USER", "alice")

    name = _server_name()
    assert name.startswith("DanmuAI-")
    # Must differ from the empty-username fallback.
    monkeypatch.delenv("USER", raising=False)
    assert name != _server_name()
