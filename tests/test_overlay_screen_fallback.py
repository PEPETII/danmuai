"""BUG-003: show_for_screen() must not silently return when the target screen
is unavailable — it should log a warning and, when possible, fall back to the
primary screen instead of leaving the overlay invisible with stale geometry.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine
from app.overlay import DanmuOverlay
from PyQt6.QtCore import QRect


@pytest.fixture()
def overlay_stack(qapp, workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "4")
    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    overlay = DanmuOverlay(store, engine)
    return store, engine, overlay


def test_show_for_screen_no_screens_logs_warning(overlay_stack, qapp, monkeypatch, caplog):
    """Empty screens list → log warning and return without crashing."""
    _, engine, overlay = overlay_stack
    monkeypatch.setattr("app.overlay.QApplication.screens", lambda: [])

    with caplog.at_level(logging.WARNING, logger="danmu.overlay"):
        overlay.show_for_screen(0)
        qapp.processEvents()

    assert not overlay.isVisible()
    assert any("no screens available" in r.message for r in caplog.records)


def test_show_for_screen_invalid_geometry_single_screen_stays_hidden(
    overlay_stack, qapp, monkeypatch, caplog
):
    """Single screen with 0x0 geometry → log warning, stay hidden, engine unchanged.

    Preserves BUG-016 invariant: engine width must not be overwritten with invalid
    geometry when there is no healthy fallback screen.
    """
    _, engine, overlay = overlay_stack
    mock_screen = MagicMock()
    mock_screen.geometry.return_value = QRect(0, 0, 0, 0)
    monkeypatch.setattr("app.overlay.QApplication.screens", lambda: [mock_screen])
    engine.set_screen_width(1920.0)
    overlay._screen_width = 1920.0

    with caplog.at_level(logging.WARNING, logger="danmu.overlay"):
        overlay.show_for_screen(0)
        qapp.processEvents()

    assert overlay._screen_width == 1920.0
    assert engine.screen_width == 1920.0
    assert any("invalid geometry" in r.message for r in caplog.records)


def test_show_for_screen_falls_back_to_primary(overlay_stack, qapp, monkeypatch, caplog):
    """Target screen (index 1) invalid → fall back to primary screen (index 0)."""
    _, engine, overlay = overlay_stack
    primary = MagicMock()
    primary.geometry.return_value = QRect(0, 0, 1920, 1080)
    disconnected = MagicMock()
    disconnected.geometry.return_value = QRect(1920, 0, 0, 0)
    monkeypatch.setattr(
        "app.overlay.QApplication.screens", lambda: [primary, disconnected]
    )

    with caplog.at_level(logging.WARNING, logger="danmu.overlay"):
        overlay.show_for_screen(1)
        qapp.processEvents()

    # Overlay shown on the primary screen geometry.
    assert overlay.isVisible()
    assert overlay._screen_width == 1920.0
    assert engine.screen_width == 1920.0
    assert any("falling back to primary" in r.message for r in caplog.records)


def test_show_for_screen_no_fallback_when_primary_also_invalid(
    overlay_stack, qapp, monkeypatch, caplog
):
    """Both target and primary invalid → log warning and stay hidden."""
    _, engine, overlay = overlay_stack
    bad0 = MagicMock()
    bad0.geometry.return_value = QRect(0, 0, 0, 0)
    bad1 = MagicMock()
    bad1.geometry.return_value = QRect(1920, 0, 0, 0)
    monkeypatch.setattr("app.overlay.QApplication.screens", lambda: [bad0, bad1])
    engine.set_screen_width(1920.0)
    overlay._screen_width = 1920.0

    with caplog.at_level(logging.WARNING, logger="danmu.overlay"):
        overlay.show_for_screen(1)
        qapp.processEvents()

    assert not overlay.isVisible()
    assert overlay._screen_width == 1920.0
    assert engine.screen_width == 1920.0
    assert any("primary screen also invalid" in r.message for r in caplog.records)
