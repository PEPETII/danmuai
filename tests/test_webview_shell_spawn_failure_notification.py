"""Tests for BUG-05: webview shell spawn failure user notification.

Covers the two failure exit points where notify_web_console_failure must be called:
1. begin_start() spawn OSError exhausted (webview_shell.py L431)
2. attach_webview_shell._begin retry exhausted (webview_shell.py L663)
"""

import queue
from unittest.mock import MagicMock, patch

from app.webview_shell import (
    WebViewShell,
    attach_webview_shell,
    notify_web_console_failure,
)


def _make_oserror_spawn_context(*, fail_times: int = 3):
    """Build a fake multiprocessing context where Process.start raises OSError
    after *fail_times* successful calls (0 = always fail)."""

    class FakeProcess:
        def __init__(self, *args, **kwargs):
            self._alive = True
            self._start_calls = 0

        def start(self):
            self._start_calls += 1
            if self._start_calls > fail_times:
                raise OSError(f"WebView2 not found (attempt {self._start_calls})")
            self._alive = True

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

    class FakeContext:
        def Queue(self):
            return FakeQueue()

        def Process(self, *args, **kwargs):
            return FakeProcess()

    return FakeContext()


def _make_server_and_shell():
    """Create a minimal server + shell pair for testing."""
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.bridge.danmu_app.logger = MagicMock()
    server._startup_failure_user_notified = False
    shell = WebViewShell(server)
    return server, shell


# ── Test 1: begin_start spawn OSError notifies user ──────────────────────


def test_begin_start_spawn_oserror_notifies_user(monkeypatch):
    """When all spawn attempts raise OSError, notify_web_console_failure is called."""
    server, shell = _make_server_and_shell()

    # Always-fail spawn context
    monkeypatch.setattr(
        "app.webview_shell.multiprocessing.get_context",
        lambda _name: _make_oserror_spawn_context(fail_times=0),
    )
    monkeypatch.setattr(
        "app.webview_shell._ensure_server_ready",
        lambda _server: True,
    )
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    notified = []

    def _fake_notify(app, key, *, detail=""):
        notified.append((key, detail))

    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure", _fake_notify
    )

    result = shell.begin_start("/")

    assert result is False
    assert len(notified) == 1
    assert notified[0][0] == "web_console.pywebview_failed"
    assert "WebView2" in notified[0][1] or "OSError" in notified[0][1]


# ── Test 2: begin_start notification is idempotent ───────────────────────


def test_begin_start_spawn_notification_idempotent(monkeypatch):
    """Calling begin_start multiple times only triggers one notification."""
    server, shell = _make_server_and_shell()

    monkeypatch.setattr(
        "app.webview_shell.multiprocessing.get_context",
        lambda _name: _make_oserror_spawn_context(fail_times=0),
    )
    monkeypatch.setattr(
        "app.webview_shell._ensure_server_ready",
        lambda _server: True,
    )
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    notified = []

    def _fake_notify(app, key, *, detail=""):
        notified.append(key)

    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure", _fake_notify
    )

    # First call — should notify
    assert shell.begin_start("/") is False
    assert len(notified) == 1

    # Second call — _startup_failure_user_notified already True, should NOT notify
    assert shell.begin_start("/") is False
    assert len(notified) == 1


# ── Test 3: begin_start notification content ─────────────────────────────


def test_begin_start_spawn_notification_content(monkeypatch):
    """Notification carries the correct reason_key and OSError detail."""
    server, shell = _make_server_and_shell()

    monkeypatch.setattr(
        "app.webview_shell.multiprocessing.get_context",
        lambda _name: _make_oserror_spawn_context(fail_times=0),
    )
    monkeypatch.setattr(
        "app.webview_shell._ensure_server_ready",
        lambda _server: True,
    )
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    captured_app = []
    captured_key = []
    captured_detail = []

    def _fake_notify(app, key, *, detail=""):
        captured_app.append(app)
        captured_key.append(key)
        captured_detail.append(detail)

    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure", _fake_notify
    )

    shell.begin_start("/")

    assert captured_key == ["web_console.pywebview_failed"]
    assert captured_app[0] is server.bridge.danmu_app
    assert len(captured_detail[0]) > 0  # non-empty detail string


# ── Test 4: attach_webview_shell retry exhausted notifies ────────────────


def test_attach_begin_retry_exhausted_notifies_user(monkeypatch):
    """When attach _begin exhausts all deferred retries, user is notified."""
    from PyQt6.QtCore import QTimer

    danmu = MagicMock()
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.bridge.danmu_app.logger = MagicMock()
    server._startup_failure_user_notified = False
    server._browser_launch_opened = False

    # begin_start always returns False
    notified = []

    def _fake_notify(app, key, *, detail=""):
        notified.append(key)

    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure", _fake_notify
    )
    monkeypatch.setattr(
        "app.web_console.classify_web_console_startup",
        lambda _srv: "starting",  # not "failed" → enters deferred retry path
    )
    monkeypatch.setattr("app.webview_shell.log_startup", lambda *a, **kw: None)

    # Simulate QTimer.singleShot synchronously so _begin runs inline
    timer_calls = []

    def _fake_singleShot(ms, fn):
        timer_calls.append((ms, fn))
        fn()  # execute immediately to exhaust retries in one call stack

    monkeypatch.setattr(QTimer, "singleShot", _fake_singleShot)

    attach_webview_shell(danmu, server, initial_path="/")

    # After 40 deferred attempts + final exhaustion, notification should fire
    assert any(k == "web_console.startup_failed" for k in notified), (
        f"Expected web_console.startup_failed notification, got: {notified}"
    )


# ── Test 5: attach still pending does NOT notify early ───────────────────


def test_attach_begin_retry_still_pending_no_notify(monkeypatch):
    """While defer_attempt < 40 and classify != 'failed', no notification."""
    from PyQt6.QtCore import QTimer

    danmu = MagicMock()
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server.bridge.danmu_app.logger = MagicMock()
    server._startup_failure_user_notified = False

    notified = []

    def _fake_notify(app, key, *, detail=""):
        notified.append(key)

    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure", _fake_notify
    )
    monkeypatch.setattr(
        "app.web_console.classify_web_console_startup",
        lambda _srv: "starting",
    )
    monkeypatch.setattr("app.webview_shell.log_startup", lambda *a, **kw: None)

    # Only run ONE timer tick — should re-schedule, not notify
    timer_calls = []

    def _fake_singleShot_once(ms, fn):
        timer_calls.append((ms, fn))
        # Do NOT execute — simulates async scheduling

    monkeypatch.setattr(QTimer, "singleShot", _fake_singleShot_once)

    attach_webview_shell(danmu, server, initial_path="/")

    # The first _begin scheduled a retry; no notification yet
    assert notified == []
    assert len(timer_calls) >= 1


# ── Test 6: notify receives correct danmu_app reference ──────────────────


def test_notify_called_with_correct_danmu_app_on_spawn_fail(monkeypatch):
    """The danmu_app passed to notify is server.bridge.danmu_app, not some other object."""
    server, shell = _make_server_and_shell()
    expected_app = server.bridge.danmu_app

    monkeypatch.setattr(
        "app.webview_shell.multiprocessing.get_context",
        lambda _name: _make_oserror_spawn_context(fail_times=0),
    )
    monkeypatch.setattr(
        "app.webview_shell._ensure_server_ready",
        lambda _server: True,
    )
    monkeypatch.setattr("app.webview_shell.append_frozen_log", lambda _msg: None)

    received_apps = []

    def _fake_notify(app, key, *, detail=""):
        received_apps.append(app)

    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure", _fake_notify
    )

    shell.begin_start("/")

    assert len(received_apps) == 1
    assert received_apps[0] is expected_app
