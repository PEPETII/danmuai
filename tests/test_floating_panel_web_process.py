"""PanelProcess lifecycle tests (mock webview / process factory)."""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

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


def test_click_through_enabled_by_default(monkeypatch):
    calls: list[bool] = []

    def fake_apply(hwnd, *, click_through=True):
        calls.append(bool(click_through))

    monkeypatch.setattr(
        "app.win32_overlay_zorder.apply_overlay_exstyles",
        fake_apply,
        raising=False,
    )

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
    assert captured["click_through"] is True


def test_start_url_contains_click_through_state():
    captured: dict[str, str] = {}

    def factory(html_url, width, height, x, y, click_through):
        del width, height, x, y, click_through
        captured["url"] = html_url
        rq: queue.Queue = queue.Queue()
        rq.put("loaded")
        rq.put("hwnd:12345")
        return rq, _FakeProcess()

    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=factory,
        load_timeout_sec=2.0,
    )
    assert panel.start("http://example/panel?ws_token=abc", click_through=False) is True
    assert "ws_token=abc" in captured["url"]
    assert "click_through=0" in captured["url"]


def test_set_click_through_same_state_hot_updates_hwnd_without_restart(monkeypatch):
    calls: list[tuple[int, bool]] = []

    def fake_apply(hwnd, *, click_through=True):
        calls.append((int(hwnd), bool(click_through)))

    monkeypatch.setattr(
        "app.win32_overlay_zorder.apply_overlay_exstyles",
        fake_apply,
        raising=False,
    )
    monkeypatch.setattr(
        "app.win32_overlay_zorder.reassert_hwnd_topmost",
        lambda hwnd: True,
        raising=False,
    )

    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=_factory_loaded,
        load_timeout_sec=2.0,
    )
    assert panel.start("http://example/panel?click_through=1", click_through=False) is True
    process_before = panel._process
    assert panel.set_click_through(False) is True
    assert panel._process is process_before
    assert calls == [(12345, False)]
    assert "click_through=0" in panel._last_html_url


def test_set_click_through_restarts_when_transparency_mode_changes():
    created: list[bool] = []

    def factory(html_url, width, height, x, y, click_through):
        del html_url, width, height, x, y
        created.append(bool(click_through))
        rq: queue.Queue = queue.Queue()
        rq.put("loaded")
        rq.put("hwnd:12345")
        return rq, _FakeProcess()

    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=factory,
        load_timeout_sec=2.0,
    )
    assert panel.start("http://example/panel?click_through=1", click_through=True) is True
    process_before = panel._process
    assert panel.set_click_through(False) is True
    assert panel._process is not process_before
    assert created == [True, False]
    assert "click_through=0" in panel._last_html_url


def test_webview_worker_disables_easy_drag_uses_explicit_region():
    import inspect
    import re

    source = inspect.getsource(panel_process_mod._webview_worker)
    assert re.search(r"easy_drag\s*=\s*False", source)
    assert not re.search(r"easy_drag\s*=\s*True", source)
    assert "resolve_root_hwnd" in source
    assert "window.native" in source or 'getattr(window, "native"' in source
    assert 'create_kwargs["transparent"] = True' in source


def test_web_panel_marks_panel_as_pywebview_drag_region():
    html_path = Path(__file__).resolve().parents[1] / "web" / "static" / "floating_panel" / "index.html"
    html = html_path.read_text(encoding="utf-8")
    assert 'id="panel"' in html
    assert "pywebview-drag-region" in html


def test_web_panel_interactive_css_and_js_for_drag():
    root = Path(__file__).resolve().parents[1] / "web" / "static" / "floating_panel"
    css = (root / "style.css").read_text(encoding="utf-8")
    js = (root / "app.js").read_text(encoding="utf-8")
    assert "is-interactive" in css
    assert "pointer-events: auto" in css
    assert "applyClickThroughFromUrl" in js
    assert 'classList.toggle("is-interactive"' in js


@pytest.mark.skip(reason="可选功能")
def test_click_through_enabled_when_config_on():
    panel = PanelProcess(
        webview2_checker=lambda: True,
        process_factory=_factory_loaded,
        load_timeout_sec=2.0,
    )
    assert panel.start("http://example", click_through=True) is True
