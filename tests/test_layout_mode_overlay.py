"""layout_mode 缩小时 DanmuEngine 轨道重载与 Overlay 重绘清理。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine, DanmuItem, layout_height_ratio
from app.overlay import DanmuOverlay
from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import QApplication


@pytest.fixture()
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _engine_fullscreen(workspace_tmp) -> DanmuEngine:
    store = ConfigStore(db_path=workspace_tmp / "layout_overlay.db")
    store.set("layout_mode", "fullscreen")
    store.set("danmu_lines", "0")
    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks(preserve_visible=False)
    return engine


def _add_with_y(track, content: str, x: float, y: float) -> DanmuItem:
    item = DanmuItem(content=content, x=x, width=100.0)
    track.add(item)
    item.y = y
    return item


def test_reload_tracks_clip_drops_lower_half_y(workspace_tmp):
    engine = _engine_fullscreen(workspace_tmp)
    _add_with_y(engine.tracks[-1], "lower", 500.0, 700.0)
    _add_with_y(engine.tracks[0], "upper", 500.0, 100.0)

    engine.config.set("layout_mode", "1/2")
    engine.reload_tracks(preserve_visible=True, clip_to_drawable=True)

    drawable = engine.drawable_height()
    assert drawable == pytest.approx(540.0)
    for track in engine.tracks:
        for item in track.items:
            assert item.y < drawable
    contents = {item.content for track in engine.tracks for item in track.items}
    assert "upper" in contents
    assert "lower" not in contents


def test_layout_shrink_avoids_bottom_track_pileup(workspace_tmp):
    engine = _engine_fullscreen(workspace_tmp)
    lower_ys = [600.0, 700.0, 800.0]
    for i, y in enumerate(lower_ys):
        _add_with_y(engine.tracks[-1], f"low{i}", 400.0 + i * 80, y)

    engine.config.set("layout_mode", "1/2")
    engine.reload_tracks(preserve_visible=True, clip_to_drawable=True)

    per_track = [len(t.items) for t in engine.tracks]
    assert max(per_track, default=0) <= 1
    assert sum(per_track) == 0


def test_reload_tracks_without_clip_still_pileup(workspace_tmp):
    """对照：未 clip 时下半屏条目会挤到同一轨道（回归保护）。"""
    engine = _engine_fullscreen(workspace_tmp)
    for y in (600.0, 700.0, 800.0):
        _add_with_y(engine.tracks[-1], f"x{y}", 500.0, y)

    engine.config.set("layout_mode", "1/2")
    engine.reload_tracks(preserve_visible=True, clip_to_drawable=False)

    max_on_track = max(len(t.items) for t in engine.tracks)
    assert max_on_track >= 3


def test_show_for_screen_shrink_requests_tall_update(qapp, workspace_tmp, monkeypatch):
    store = ConfigStore(db_path=workspace_tmp / "overlay_shrink.db")
    store.set("layout_mode", "fullscreen")
    store.set("danmu_lines", "4")
    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks(preserve_visible=False)
    overlay = DanmuOverlay(store, engine)
    overlay._last_layout_ratio = layout_height_ratio(store)

    updates: list[QRect] = []
    original_update = overlay.update

    def _capture_update(rect=None):
        if isinstance(rect, QRect):
            updates.append(rect)
        return original_update(rect)

    monkeypatch.setattr(overlay, "update", _capture_update)

    fake_screen = MagicMock()
    fake_screen.geometry.return_value = QRect(0, 0, 1920, 1080)
    monkeypatch.setattr(
        QApplication,
        "screens",
        lambda: [fake_screen],
    )

    store.set("layout_mode", "1/2")
    overlay.show_for_screen(0, reload_tracks=True)

    assert overlay._clear_drawable_on_next_paint is True
    assert updates
    assert max(r.height() for r in updates) >= int(1080 * 0.5)


def test_paint_event_clears_clip_when_flag_set(qapp, workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "paint_clear.db")
    store.set("layout_mode", "1/2")
    engine = DanmuEngine(store)
    engine.set_screen_width(800.0)
    engine.set_screen_height(600.0)
    engine.reload_tracks(preserve_visible=False)
    overlay = DanmuOverlay(store, engine)
    overlay.setGeometry(0, 0, 800, 600)
    overlay.show()
    overlay._clear_drawable_on_next_paint = True

    modes: list = []
    fills: list = []

    from PyQt6.QtGui import QPainter

    original_set_mode = QPainter.setCompositionMode
    original_fill = QPainter.fillRect

    def _track_mode(self, mode):
        modes.append(mode)
        return original_set_mode(self, mode)

    def _track_fill(self, rect, color):
        fills.append(rect)
        return original_fill(self, rect, color)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(QPainter, "setCompositionMode", _track_mode)
    monkeypatch.setattr(QPainter, "fillRect", _track_fill)
    try:
        overlay.repaint()
        qapp.processEvents()
    finally:
        monkeypatch.undo()

    assert not overlay._clear_drawable_on_next_paint
    from PyQt6.QtGui import QPainter as QP

    assert QP.CompositionMode.CompositionMode_Clear in modes
    assert fills
