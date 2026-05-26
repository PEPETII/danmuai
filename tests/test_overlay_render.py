"""DanmuOverlay render loop lifecycle and adaptive timer."""

import pytest
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine, DanmuItem
from app.overlay import _INTERVAL_MAX_MS, DanmuOverlay, overlay_font_family, overlay_window_flags
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication


@pytest.fixture()
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


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
    engine.overlay = overlay
    return store, engine, overlay


def _show_overlay(overlay, qapp):
    overlay.show()
    qapp.processEvents()


def _seed_visible_item(engine):
    engine.tracks[0].add(DanmuItem(content="live", x=500.0, width=100.0, y=engine.tracks[0].y))


def test_overlay_timer_not_started_on_init(overlay_stack):
    _, _, overlay = overlay_stack
    assert not overlay.timer.isActive()


def test_stop_render_loop_halts_timer(overlay_stack, qapp):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 800, 600)
    _show_overlay(overlay, qapp)
    engine.running = True
    _seed_visible_item(engine)
    overlay.start_render_loop()
    assert overlay.timer.isActive()
    overlay.stop_render_loop()
    qapp.processEvents()
    assert not overlay.timer.isActive()


def test_hide_event_stops_timer(overlay_stack, qapp):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 800, 600)
    _show_overlay(overlay, qapp)
    engine.running = True
    _seed_visible_item(engine)
    overlay.start_render_loop()
    assert overlay.timer.isActive()
    overlay.hide()
    qapp.processEvents()
    assert not overlay.timer.isActive()


def test_tick_stops_when_no_items(overlay_stack):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 800, 600)
    overlay.show()
    overlay._timer_interval_ms = _INTERVAL_MAX_MS
    overlay.timer.start(_INTERVAL_MAX_MS)
    overlay._tick()
    assert not overlay.timer.isActive()


def test_add_text_ensures_render_loop_when_visible(overlay_stack, monkeypatch):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 800, 600)
    overlay.show()
    engine.running = True
    assert not overlay.timer.isActive()
    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 50.0)
    item = engine.add_text("hello")
    assert item is not None
    assert overlay.timer.isActive()


def test_target_interval_always_60fps_when_animating(overlay_stack, qapp):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 1920, 1080)
    _show_overlay(overlay, qapp)
    overlay._screen_width = 1920.0
    engine.tracks[0].add(DanmuItem(content="a", x=500.0, width=100.0))
    assert overlay._target_interval_ms() == _INTERVAL_MAX_MS
    for i in range(5):
        engine.tracks[0].add(
            DanmuItem(content=f"m{i}", x=300.0 + i * 20, width=80.0, y=engine.tracks[0].y)
        )
    assert overlay._target_interval_ms() == _INTERVAL_MAX_MS


def test_target_interval_accel_forces_60fps(overlay_stack, qapp):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 1920, 1080)
    _show_overlay(overlay, qapp)
    engine.trigger_acceleration(30)
    assert overlay._target_interval_ms() == _INTERVAL_MAX_MS


def test_target_interval_fade_zone_forces_60fps(overlay_stack, qapp):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 1920, 1080)
    _show_overlay(overlay, qapp)
    overlay._screen_width = 1920.0
    engine.tracks[0].add(DanmuItem(content="fade", x=1900.0, width=100.0))
    assert engine.items_in_fade_zone()
    assert overlay._target_interval_ms() == _INTERVAL_MAX_MS


def test_union_dirty_rect_smaller_than_widget(overlay_stack, qapp):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 1920, 1080)
    _show_overlay(overlay, qapp)
    overlay._screen_width = 1920.0
    item = DanmuItem(content="narrow", x=400.0, width=120.0, y=engine.tracks[0].y)
    engine.tracks[0].add(item)
    overlay.prepare_item_pixmap(item)
    dirty = overlay._union_dirty_rect(16.0)
    assert dirty is not None
    assert dirty.width() < overlay.width()
    assert dirty.height() < overlay.height()


def test_prepare_item_pixmap_before_paint(overlay_stack):
    _, engine, overlay = overlay_stack
    item = DanmuItem(content="cached", width=120.0)
    assert item._pixmap is None
    overlay.prepare_item_pixmap(item)
    assert item._pixmap is not None


def test_tick_stops_when_only_far_off_right_pending(overlay_stack, qapp):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 1920, 1080)
    overlay.show()
    overlay._screen_width = 1920.0
    engine.set_screen_width(1920.0)
    engine.tracks[0].add(DanmuItem(content="far", x=2500.0, width=80.0))
    overlay.timer.start(_INTERVAL_MAX_MS)
    overlay._tick()
    assert not overlay.timer.isActive()


def test_dt_motion_matches_legacy_per_frame(overlay_stack):
    _, engine, _ = overlay_stack
    engine.set_screen_width(1000.0)
    engine.reload_tracks()
    engine.tracks[0].add(DanmuItem(content="moving", x=500.0, width=100.0, speed=2.0))
    old_x = engine.tracks[0].items[0].x
    engine.update(speed_factor=1.0, dt_sec=1.0 / 60.0)
    new_x = engine.tracks[0].items[0].x
    assert new_x == pytest.approx(old_x - 2.0)


def test_overlay_window_flags_omit_bypass_on_macos(monkeypatch):
    monkeypatch.setattr("app.overlay.sys.platform", "darwin")
    flags = overlay_window_flags()

    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert not flags & Qt.WindowType.BypassWindowManagerHint
    assert overlay_font_family() == "PingFang SC"
