from __future__ import annotations

import threading
from types import SimpleNamespace

from app.main_floating_panel_mixin import DanmuAppFloatingPanelMixin


class _JoinableProcess:
    def __init__(self, position=(100, 200)):
        self.position = position
        self._alive = True
        self._join_event = threading.Event()

    def current_position(self):
        return self.position

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):
        if timeout is None:
            self._join_event.wait()
        else:
            self._join_event.wait(timeout)

    def terminate(self):
        self._alive = False
        self._join_event.set()

    def kill(self):
        self.terminate()

    def die(self):
        self._alive = False
        self._join_event.set()


class _PanelProcessStub:
    def __init__(self):
        self._process = _JoinableProcess()
        self._restart_count = 0
        self._fallback_to_qpainter_called = False
        self._unexpected_exit_handling = False
        self._lifecycle_state = "running"
        self._on_unexpected_exit = None
        self.restart_calls = 0
        self.stopped = 0

    def is_alive(self):
        return self._process is not None and self._process.is_alive()

    @property
    def fallback_to_qpainter_called(self):
        return self._fallback_to_qpainter_called

    @property
    def restart_count(self):
        return self._restart_count

    def set_on_unexpected_exit(self, callback):
        self._on_unexpected_exit = callback

    def note_child_died(self):
        if self._unexpected_exit_handling:
            return False
        self._unexpected_exit_handling = True
        try:
            self.restart_calls += 1
            if self.restart_calls > 3:
                self._fallback_to_qpainter_called = True
                self._lifecycle_state = "fallback"
                return False
            self._process = _JoinableProcess()
            self._lifecycle_state = "running"
            return True
        finally:
            self._unexpected_exit_handling = False

    def stop(self):
        self.stopped += 1
        if self._process is not None:
            self._process.terminate()
        self._process = None
        self._lifecycle_state = "stopped"


class _Overlay:
    def __init__(self):
        self.shown = 0

    def show_for_screen(self, _screen_index):
        self.shown += 1


class _Engine:
    running = True


class _Config:
    def get(self, key, default=""):
        defaults = {
            "floating_panel_use_web": "1",
            "floating_panel_click_through": "1",
        }
        return defaults.get(key, default)


def _app(panel_process):
    app = DanmuAppFloatingPanelMixin()
    app.config = _Config()
    app.engine = _Engine()
    app.logger = SimpleNamespace(info=lambda *a, **k: None, debug=lambda *a, **k: None)
    app._panel_process = panel_process
    app._panel_web_active = True
    app._panel_bridge = SimpleNamespace(enqueue_message=lambda *_a, **_k: None)
    app._panel_position_timer = SimpleNamespace(start=lambda: None, stop=lambda: None)
    app.floating_panel_overlay = _Overlay()
    app._floating_panel_v2_enabled = lambda: True
    app._ensure_panel_web_components()
    return app


def test_child_exit_recovery_restarts_panel_without_visibility_sync():
    panel = _PanelProcessStub()
    app = _app(panel)
    pushed = {"count": 0}
    app._push_panel_config = lambda: pushed.__setitem__("count", pushed["count"] + 1)

    app._on_panel_child_unexpected_exit()

    assert panel.restart_calls == 1
    assert app._panel_web_active is True
    assert pushed["count"] == 1


def test_child_exit_recovery_falls_back_to_qpainter_after_limit():
    panel = _PanelProcessStub()
    panel.restart_calls = 3
    app = _app(panel)
    overlay = app.floating_panel_overlay

    app._on_panel_child_unexpected_exit()

    assert panel.restart_calls == 4
    assert app._panel_web_active is False
    assert overlay.shown == 1
    assert panel.stopped == 1
