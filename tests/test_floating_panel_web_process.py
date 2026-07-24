"""PanelProcess lifecycle tests (mock webview / process factory)."""

from __future__ import annotations

import queue
import threading
import time
from types import SimpleNamespace

from app.floating_panel_web import panel_process as panel_process_mod
from app.floating_panel_web.panel_process import MAX_RESTARTS, PanelProcess


class _FakeProcess:
    def __init__(self, *, die_after: float | None = None) -> None:
        self._alive = True
        self.terminated = False
        self.killed = False
        self.exitcode = None
        if die_after is not None:
            threading.Timer(die_after, self._die).start()

    def _die(self) -> None:
        self._alive = False
        self.exitcode = 1

    def start(self) -> None:
        self._alive = True

    def is_alive(self) -> bool:
        return self._alive

    def terminate(self) -> None:
        self.terminated = True
        self._alive = False
        self.exitcode = -15

    def kill(self) -> None:
        self.killed = True
        self._alive = False
        self.exitcode = -9

    def join(self, timeout: float | None = None) -> None:
        del timeout
        return None


def _factory_loaded(html_url, width, height, x, y, click_through):
    del html_url, width, height, x, y
    rq: queue.Queue = queue.Queue()
    rq.put("loaded")
    rq.put("hwnd:12345")
    proc = _FakeProcess()
    # capture click_through for assertions via proc attribute
    proc.click_through = click_through  # type: ignore[attr-defined]
    return rq, proc


def test_start_receives_loaded_signal():
    proc_holder: dict[str, _FakeProcess] = {}

    def factory(*args):
        rq, proc = _factory_loaded(*args)
        proc_holder["p"] = proc
        return rq, proc

    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=factory,
        load_timeout_sec=2.0,
    )
    assert panel.start("http://127.0.0.1/static/floating_panel/index.html") is True
    assert panel.is_alive() is True
    assert panel._hwnd == 12345


def test_start_timeout_25s():
    def factory(*_args):
        return queue.Queue(), _FakeProcess()

    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=factory,
        load_timeout_sec=0.2,
    )
    assert panel.start("http://example") is False
    assert panel.is_alive() is False


def test_stop_terminates_process():
    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=_factory_loaded,
        load_timeout_sec=2.0,
    )
    assert panel.start("http://example") is True
    panel.stop()
    assert panel.is_alive() is False


def test_stop_kill_after_terminate_timeout():
    class StickyProcess(_FakeProcess):
        def terminate(self) -> None:
            self.terminated = True
            # stay alive until kill

        def join(self, timeout: float | None = None) -> None:
            del timeout
            return None

    def factory(*args):
        rq: queue.Queue = queue.Queue()
        rq.put("loaded")
        return rq, StickyProcess()

    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=factory,
        load_timeout_sec=2.0,
    )
    assert panel.start("http://example") is True
    sticky = panel._process
    panel.stop()
    assert sticky.terminated is True
    assert sticky.killed is True
    assert panel.is_alive() is False


def test_restart_resets_restart_count():
    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=_factory_loaded,
        load_timeout_sec=2.0,
    )
    panel._restart_count = 2
    assert panel.start("http://example") is True
    assert panel.restart_count == 0
    panel._restart_count = 2
    assert panel.restart() is True
    assert panel.restart_count == 0


def test_webview2_unavailable_returns_false():
    panel = PanelProcess(
        webview2_checker=lambda: False,
        process_factory=_factory_loaded,
    )
    assert panel.start("http://example") is False


def test_max_restarts_reached_falls_back():
    def factory_fail(*_args):
        return queue.Queue(), _FakeProcess()

    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=factory_fail,
        load_timeout_sec=0.05,
    )
    for _ in range(MAX_RESTARTS):
        assert panel.start("http://example") is False
    assert panel.fallback_to_qpainter_called is True


def test_click_through_disabled_by_default():
    captured: dict[str, bool] = {}

    def factory(html_url, width, height, x, y, click_through):
        captured["click_through"] = click_through
        rq: queue.Queue = queue.Queue()
        rq.put("loaded")
        return rq, _FakeProcess()

    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=factory,
        load_timeout_sec=2.0,
    )
    assert panel.start("http://example") is True
    assert captured["click_through"] is False


def test_click_through_enabled_when_config_on():
    captured: dict[str, bool] = {}

    def factory(html_url, width, height, x, y, click_through):
        del html_url, width, height, x, y
        captured["click_through"] = click_through
        rq: queue.Queue = queue.Queue()
        rq.put("loaded")
        rq.put("hwnd:12345")
        return rq, _FakeProcess()

    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=factory,
        load_timeout_sec=2.0,
    )
    assert panel.start("http://example", click_through=True) is True
    assert captured["click_through"] is True
    assert panel._last_click_through is True


def test_set_click_through_restarts_with_new_flag():
    """Flag change restarts child so on_loaded applies WS_EX_TRANSPARENT in-process."""
    starts: list[bool] = []
    urls: list[str] = []

    def factory(html_url, width, height, x, y, click_through):
        del width, height, x, y
        urls.append(html_url)
        starts.append(bool(click_through))
        rq: queue.Queue = queue.Queue()
        rq.put("loaded")
        rq.put("hwnd:12345")
        return rq, _FakeProcess()

    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=factory,
        load_timeout_sec=2.0,
    )
    assert panel.start("http://example?ws_token=abc&click_through=1", click_through=True) is True
    assert starts == [True]

    panel.set_click_through(False)
    assert panel._last_click_through is False
    assert starts == [True, False]
    assert urls[1] == "http://example?ws_token=abc&click_through=0"
    assert panel.is_alive() is True

    panel.set_click_through(False)
    assert starts == [True, False]

    panel.set_click_through(True)
    assert panel._last_click_through is True
    assert starts == [True, False, True]


def test_set_click_through_without_alive_process_only_stores_state():
    panel = PanelProcess(webview2_checker=lambda: True)
    panel._last_html_url = "http://example"
    panel._hwnd = 0
    panel.set_click_through(True)
    assert panel._last_click_through is True
    assert panel.is_alive() is False


def test_webview_drag_region_targets_panel():
    fake_webview = SimpleNamespace(DRAG_REGION_SELECTOR=".pywebview-drag-region")

    panel_process_mod._configure_webview_drag_region(fake_webview)

    assert fake_webview.DRAG_REGION_SELECTOR == "#panel"
