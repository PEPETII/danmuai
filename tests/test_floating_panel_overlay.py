"""W-FP-V2-001：FloatingPanelOverlay 渲染与生命周期测试。"""
from __future__ import annotations

import pytest
from app.config_store import ConfigStore
from app.floating_panel_engine import FloatingPanelEngine
from app.floating_panel_overlay import FloatingPanelOverlay


@pytest.fixture()
def fp_v2_setup(qapp, workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "fp_overlay.db")
    store.set("floating_panel_max_items", "12")
    store.set("floating_panel_font_size", "20")
    store.set("floating_panel_opacity", "85")
    store.set("danmu_render_mode", "floating_panel")
    engine = FloatingPanelEngine(store)
    overlay = FloatingPanelOverlay(store, engine)
    engine.set_panel_height(400.0)
    overlay.resize(360, 400)
    qapp.processEvents()
    return store, engine, overlay


def test_add_danmu_text_starts_render(fp_v2_setup, qapp):
    _, engine, overlay = fp_v2_setup
    overlay.show()
    qapp.processEvents()
    item = overlay.add_danmu_text("overlay hello")
    assert item is not None
    assert engine.visible_count() == 1
    assert item.pixmap is not None


def test_timer_stops_when_queue_empty(fp_v2_setup, qapp):
    _, engine, overlay = fp_v2_setup
    overlay.show()
    qapp.processEvents()
    overlay.add_danmu_text("once")
    for _ in range(200):
        overlay._tick()
        if not engine.needs_render_tick():
            break
    qapp.processEvents()
    assert not overlay.is_render_active() or engine.visible_count() == 0


def test_reset_session_state_clears_and_hides(fp_v2_setup, qapp):
    _, engine, overlay = fp_v2_setup
    overlay.show()
    qapp.processEvents()
    overlay.add_danmu_text("temp")
    overlay.reset_session_state()
    qapp.processEvents()
    assert engine.visible_count() == 0
    assert not overlay.isVisible()


def test_window_flags_transparent_for_mouse(fp_v2_setup):
    _, _, overlay = fp_v2_setup
    from PyQt6.QtCore import Qt

    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_show_for_screen_positions_panel(fp_v2_setup, qapp):
    _, _, overlay = fp_v2_setup
    overlay.show_for_screen(0)
    qapp.processEvents()
    assert overlay.isVisible()
    assert overlay.width() >= 200
