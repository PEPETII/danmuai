"""Screen enumeration for web console."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.web_console_support import (
    enumerate_screens,
    is_empty_screens_fallback,
    resolve_screens_for_api,
    screens_for_api,
    try_cache_screens,
)
from PyQt6.QtWidgets import QApplication


@pytest.fixture
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_enumerate_screens_returns_at_least_one(qapp):
    screens = enumerate_screens()
    assert len(screens) >= 1
    assert screens[0]["index"] == 0
    assert "label" in screens[0]


def test_is_empty_screens_fallback_detects_placeholder():
    fallback = [{"index": 0, "label": "显示器 1", "width": 0, "height": 0}]
    assert is_empty_screens_fallback(fallback) is True
    real = [
        {"index": 0, "label": "显示器 1 — 1920×1080", "width": 1920, "height": 1080},
        {"index": 1, "label": "显示器 2 — 1920×1080", "width": 1920, "height": 1080},
    ]
    assert is_empty_screens_fallback(real) is False


def test_resolve_screens_for_api_prefers_live_when_cache_is_fallback():
    fallback = [{"index": 0, "label": "显示器 1", "width": 0, "height": 0}]
    live = [
        {"index": 0, "label": "显示器 1 — 1920×1080", "width": 1920, "height": 1080},
        {"index": 1, "label": "显示器 2 — 1920×1080", "width": 1920, "height": 1080},
    ]
    resolved = resolve_screens_for_api(fallback, live)
    assert len(resolved) == 2
    assert resolved == live


def test_try_cache_screens_skips_fallback(monkeypatch):
    bridge = MagicMock()
    bridge.cached_screens = []
    calls = {"n": 0}

    def fake_enumerate():
        calls["n"] += 1
        if calls["n"] == 1:
            return [{"index": 0, "label": "显示器 1", "width": 0, "height": 0}]
        return [
            {"index": 0, "label": "显示器 1 — 1920×1080", "width": 1920, "height": 1080},
            {"index": 1, "label": "显示器 2 — 1920×1080", "width": 1920, "height": 1080},
        ]

    monkeypatch.setattr("app.web_console_support.enumerate_screens", fake_enumerate)
    assert try_cache_screens(bridge) is False
    assert bridge.cached_screens == []
    assert try_cache_screens(bridge) is True
    assert len(bridge.cached_screens) == 2


def test_screens_cached_after_qt_event_loop_starts(qapp, monkeypatch):
    import time

    from app.web_console_support import schedule_screen_cache

    bridge = MagicMock()
    bridge.cached_screens = []
    calls = {"n": 0}

    def fake_enumerate():
        calls["n"] += 1
        if calls["n"] < 2:
            return [{"index": 0, "label": "显示器 1", "width": 0, "height": 0}]
        return [
            {"index": 0, "label": "显示器 1 — 1920×1080", "width": 1920, "height": 1080},
            {"index": 1, "label": "显示器 2 — 1920×1080", "width": 1920, "height": 1080},
        ]

    monkeypatch.setattr("app.web_console_support.enumerate_screens", fake_enumerate)
    monkeypatch.setattr(
        "app.web_console_support._SCREEN_CACHE_RETRY_DELAYS_MS",
        (10, 10, 10),
    )

    schedule_screen_cache(bridge)
    for _ in range(100):
        qapp.processEvents()
        if len(bridge.cached_screens) >= 2:
            break
        time.sleep(0.02)
    assert len(bridge.cached_screens) == 2


def test_screens_for_api_skips_enumerate_when_cache_valid(monkeypatch):
    bridge = MagicMock()
    bridge.cached_screens = [
        {"index": 0, "label": "显示器 1 — 1920×1080", "width": 1920, "height": 1080},
    ]
    calls = {"n": 0}

    def fake_enumerate():
        calls["n"] += 1
        return [{"index": 0, "label": "should-not-run", "width": 1, "height": 1}]

    monkeypatch.setattr("app.web_console_support.enumerate_screens", fake_enumerate)
    result = screens_for_api(bridge)
    assert calls["n"] == 0
    assert result == bridge.cached_screens
