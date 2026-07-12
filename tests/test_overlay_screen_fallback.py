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
from main import DanmuApp
from PyQt6.QtCore import QRect

from tests.conftest import FakeTimer, bind_minimal_danmu_app


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
    assert overlay._overlay_screen_unavailable is True
    assert any("no screens available" in r.message for r in caplog.records)


def test_show_for_screen_invalid_geometry_sets_unavailable_flag(
    overlay_stack, qapp, monkeypatch, caplog
):
    """Single screen with 0x0 geometry → unavailable flag set."""
    _, _, overlay = overlay_stack
    mock_screen = MagicMock()
    mock_screen.geometry.return_value = QRect(0, 0, 0, 0)
    monkeypatch.setattr("app.overlay.QApplication.screens", lambda: [mock_screen])

    with caplog.at_level(logging.WARNING, logger="danmu.overlay"):
        overlay.show_for_screen(0)
        qapp.processEvents()

    assert overlay._overlay_screen_unavailable is True


def test_show_for_screen_recovers_after_screen_added(overlay_stack, qapp, monkeypatch):
    """Empty screens then recovery → overlay becomes visible and clears flag."""
    _, engine, overlay = overlay_stack
    mock_screen = MagicMock()
    mock_screen.geometry.return_value = QRect(0, 0, 1920, 1080)
    screens: list = []

    monkeypatch.setattr("app.overlay.QApplication.screens", lambda: screens)

    overlay.show_for_screen(0)
    qapp.processEvents()
    assert overlay._overlay_screen_unavailable is True
    assert not overlay.isVisible()

    screens.append(mock_screen)
    overlay.show_for_screen(0)
    qapp.processEvents()
    assert overlay._overlay_screen_unavailable is False
    assert overlay.isVisible()
    assert engine.screen_width == 1920.0


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


def _bind_display_warning_facade(app) -> None:
    for name in (
        "_active_overlay_layer",
        "_overlay_own_hwnds",
        "_update_overlay_compat_warning",
        "_ensure_web_runtime_state",
        "_danmu_render_mode",
        "_overlay_display_enabled",
        "_floating_panel_v2_enabled",
    ):
        method = getattr(DanmuApp, name)
        object.__setattr__(app, name, method.__get__(app, DanmuApp))


def test_status_snapshot_reports_screens_unavailable_warning(
    overlay_stack, qapp, monkeypatch
):
    """Empty screens → overlay_compat_warning populated in status snapshot."""
    store, engine, overlay = overlay_stack
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=store, engine=engine, overlay=overlay)
    _bind_display_warning_facade(app)
    app._topmost_health_timer = FakeTimer()
    engine.running = True
    overlay._overlay_screen_unavailable = True

    monkeypatch.setattr("app.main_screen_topology_mixin.sys.platform", "win32")
    monkeypatch.setattr("app.main_screen_topology_mixin.QApplication.screens", lambda: [])

    app._update_overlay_compat_warning()
    runtime = app._ensure_web_runtime_state()
    warning = str(getattr(runtime, "overlay_compat_warning", "") or "")
    assert warning
    assert "显示器" in warning or "display" in warning.lower()
