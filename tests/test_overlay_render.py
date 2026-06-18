"""DanmuOverlay render loop lifecycle and adaptive timer."""

from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore
from app.danmu_engine import FADE_IN_PX, DanmuEngine, DanmuItem
from app.overlay import _INTERVAL_MAX_MS, DanmuOverlay, _use_fast_danmu_render
from PyQt6.QtCore import QRect
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


def test_show_for_screen_invalid_index_starts_render_with_content(
    overlay_stack, qapp, monkeypatch
):
    _, engine, overlay = overlay_stack
    mock_screen = MagicMock()
    mock_screen.geometry.return_value = QRect(0, 0, 1920, 1080)
    monkeypatch.setattr("app.overlay.QApplication.screens", lambda: [mock_screen])
    engine.running = True
    _seed_visible_item(engine)
    before_tracks = len(engine.tracks)

    overlay.show_for_screen(99)
    qapp.processEvents()

    assert overlay.isVisible()
    assert len(engine.tracks) == before_tracks
    overlay.ensure_render_loop()
    assert overlay.timer.isActive()


def test_show_event_starts_loop_when_content_queued_while_hidden(overlay_stack, qapp):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 800, 600)
    engine.running = True
    _seed_visible_item(engine)
    assert not overlay.isVisible()

    _show_overlay(overlay, qapp)

    assert overlay.timer.isActive()


def test_start_render_loop_noop_when_overlay_hidden(overlay_stack):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 800, 600)
    engine.running = True
    _seed_visible_item(engine)

    overlay.start_render_loop()

    assert not overlay.isVisible()
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
    item = DanmuItem(content="fade", x=1900.0, width=100.0)
    engine.tracks[0].add(item)
    engine._refresh_item_visibility(item)
    assert engine.items_in_fade_zone()
    assert engine.needs_render_tick()
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


def test_use_fast_danmu_render_for_long_formula_lines():
    short_ascii = "hi"
    short_cjk = "短弹幕"
    short_emoji = "😀短弹幕"
    long_line = "x" * 40
    assert _use_fast_danmu_render(short_ascii) is False
    assert _use_fast_danmu_render(short_cjk) is True
    assert _use_fast_danmu_render(short_emoji) is True
    assert _use_fast_danmu_render(long_line) is True


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


def test_global_opacity_factor_clamps(overlay_stack):
    store, _, overlay = overlay_stack
    store.set("opacity", "0")
    assert overlay._global_opacity_factor() == 0.0
    store.set("opacity", "50")
    assert overlay._global_opacity_factor() == pytest.approx(0.5)
    store.set("opacity", "100")
    assert overlay._global_opacity_factor() == 1.0
    store.set("opacity", "150")
    assert overlay._global_opacity_factor() == 1.0
    store.set("opacity", "")
    assert overlay._global_opacity_factor() == 1.0


def test_apply_display_settings_detects_font_family_change(overlay_stack):
    """danmu_font_family 变化时 display_settings_dirty 为 True，apply 后清除。"""
    store, _, overlay = overlay_stack
    overlay._sync_applied_display_settings_markers()
    assert overlay.display_settings_dirty() is False

    store.set("danmu_font_family", "SimHei")
    assert overlay.display_settings_dirty() is True
    overlay.apply_display_settings()
    assert overlay.display_settings_dirty() is False


def test_apply_display_settings_uses_imported_font_family(
    overlay_stack, workspace_tmp, monkeypatch
):
    """W-FONT-002：导入字体 family 经 apply_display_settings 生效。"""
    from pathlib import Path

    import pytest
    from app import font_registry as fr_mod
    from app.font_registry import FontRegistry

    fixture = Path(__file__).parent / "fixtures" / "minimal.ttf"
    if not fixture.is_file():
        pytest.skip("tests/fixtures/minimal.ttf missing")

    fonts_dir = workspace_tmp / "fonts"
    fonts_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(fr_mod, "FONTS_DIR", fonts_dir)

    store, _, overlay = overlay_stack
    reg = FontRegistry(store)
    record = reg.import_bytes(fixture.read_bytes(), "overlay.ttf")
    family = record["family"]

    store.set("danmu_font_family", family)
    overlay.apply_display_settings()
    assert overlay.font.family() == family


def test_apply_display_settings_refreshes_pixmap_on_font_change(overlay_stack):
    store, engine, overlay = overlay_stack
    item = DanmuItem(content="resize_me", width=0.0)
    engine.tracks[0].add(item)
    overlay.prepare_item_pixmap(item)
    old_width = item.width

    store.set("font_size", "48")
    overlay.apply_display_settings()

    assert overlay.font.pointSize() == 48
    assert item.width > old_width
    assert item._pixmap is not None


def test_apply_display_settings_retruncates_on_max_chars_change(overlay_stack):
    store, engine, overlay = overlay_stack
    long_text = "这是一段超过八个字的中文测试文案"
    store.set("danmu_max_chars", "80")
    item = DanmuItem(content=long_text, width=0.0)
    engine.tracks[0].add(item)
    overlay.prepare_item_pixmap(item)

    store.set("danmu_max_chars", "8")
    overlay.apply_display_settings()

    assert len(item.content) <= 11
    assert item.content.endswith("...")


def test_apply_display_settings_keeps_formula_pool_line_untruncated(overlay_stack):
    store, engine, overlay = overlay_stack
    long_line = "这是一句保存于公式化弹幕库的超长句子应完整上屏展示"
    store.set_custom_danmu_pool([long_line])
    store.set("danmu_max_chars", "80")
    item = DanmuItem(content=long_line, width=0.0)
    engine.tracks[0].add(item)
    overlay.prepare_item_pixmap(item)

    store.set("danmu_max_chars", "8")
    overlay.apply_display_settings()

    assert item.content == long_line


def test_apply_display_settings_keeps_meme_barrage_line_untruncated(overlay_stack):
    store, engine, overlay = overlay_stack
    long_line = "瓦批的一天：查看商店，练呲水枪，打开麻麻模拟器，启动！"
    store.meme_barrage_library_insert_many(
        [(long_line, None, None)],
        collected_at=0.0,
        max_rows=10_000,
    )
    store.set("danmu_max_chars", "80")
    item = DanmuItem(content=long_line, width=0.0)
    engine.tracks[0].add(item)
    overlay.prepare_item_pixmap(item)

    store.set("danmu_max_chars", "8")
    overlay.apply_display_settings()

    assert item.content == long_line


def test_item_paint_opacity_includes_global(overlay_stack):
    store, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 1920, 1080)
    overlay._screen_width = 1920.0
    item = DanmuItem(content="opaque", x=500.0, width=100.0, y=engine.tracks[0].y)
    engine.tracks[0].add(item)

    store.set("opacity", "100")
    full = overlay._item_opacity(item) * overlay._global_opacity_factor()

    store.set("opacity", "50")
    half = overlay._item_opacity(item) * overlay._global_opacity_factor()

    assert full == pytest.approx(1.0)
    assert half == pytest.approx(0.5)


def test_add_text_far_offscreen_defers_pixmap(overlay_stack, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: (a + b) / 2)
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 1920, 1080)
    overlay._screen_width = 1920.0
    engine.set_screen_width(1920.0)

    item = engine.add_text("deferred-pixmap", skip_dedup=True)
    assert item is not None
    assert item.x >= 1920.0
    assert item._pixmap is None


def test_prepare_pixmaps_near_visible_before_paint_band(overlay_stack):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 1920, 1080)
    overlay._screen_width = 1920.0
    sw = 1920.0
    item = DanmuItem(
        content="approaching",
        x=sw + FADE_IN_PX + 50.0,
        width=120.0,
        y=engine.tracks[0].y,
    )
    engine.tracks[0].add(item)
    assert item._pixmap is None

    overlay._prepare_pixmaps_near_visible()
    assert item._pixmap is not None


def test_paint_event_prepares_late_pixmap(overlay_stack, qapp):
    _, engine, overlay = overlay_stack
    overlay.setGeometry(0, 0, 1920, 1080)
    overlay._screen_width = 1920.0
    item = DanmuItem(content="late", x=500.0, width=100.0, y=engine.tracks[0].y)
    engine.tracks[0].add(item)
    assert item._pixmap is None

    event = MagicMock()
    event.region.return_value.boundingRect.return_value = QRect(0, 0, 1920, 1080)
    overlay.paintEvent(event)
    assert item._pixmap is not None

