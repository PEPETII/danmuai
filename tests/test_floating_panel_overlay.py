"""W-FP-V3-002：FloatingPanelOverlay 渲染与计时器生命周期测试。"""
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
    overlay._tick_dt_sec = lambda: 0.5
    for _ in range(50):
        overlay._tick()
        if engine.visible_count() == 0:
            break
    qapp.processEvents()
    assert engine.visible_count() == 0
    assert not overlay.is_render_active()


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


def test_show_for_screen_reasserts_topmost(fp_v2_setup, qapp, monkeypatch):
    _, _, overlay = fp_v2_setup
    calls: list[str] = []
    monkeypatch.setattr(
        overlay,
        "reassert_topmost_zorder",
        lambda: calls.append("topmost"),
    )
    overlay.show_for_screen(0)
    qapp.processEvents()
    assert calls.count("topmost") >= 1


def test_show_event_reasserts_topmost(fp_v2_setup, qapp, monkeypatch):
    _, _, overlay = fp_v2_setup
    calls: list[str] = []
    monkeypatch.setattr(
        overlay,
        "reassert_topmost_zorder",
        lambda: calls.append("topmost"),
    )
    overlay.show()
    qapp.processEvents()
    assert calls == ["topmost"]


def test_show_for_screen_no_screens_logs_warning(fp_v2_setup, qapp, monkeypatch, caplog):
    """W-COMPAT-SCREEN-RECOVERY-001: empty screens → warning + unavailable flag."""
    import logging

    _, _, overlay = fp_v2_setup
    monkeypatch.setattr("app.floating_panel_overlay.QApplication.screens", lambda: [])

    with caplog.at_level(logging.WARNING, logger="danmu.floating_panel_overlay"):
        overlay.show_for_screen(0)
        qapp.processEvents()

    assert overlay._screen_unavailable is True
    assert not overlay.isVisible()
    assert any("no screens available" in r.message for r in caplog.records)


def test_bubble_pixmap_includes_tail_and_shadow_extent(fp_v2_setup):
    """W-FP-BUBBLE-001: pixmap is larger than content body by fixed tail+shadow pads."""
    from app.floating_panel_overlay import _bubble_extra_height, _bubble_extra_width

    _, _, overlay = fp_v2_setup
    content_w, content_h = 120, 36
    pm = overlay._render_card_pixmap("bubble hi", content_w, content_h)
    assert pm is not None
    dpr = pm.devicePixelRatio() or 1.0
    logical_w = pm.width() / dpr
    logical_h = pm.height() / dpr
    assert logical_w >= content_w + _bubble_extra_width() - 0.5
    assert logical_h >= content_h + _bubble_extra_height() - 0.5
    # Has alpha channel usage (transparent margins around bubble)
    assert pm.hasAlphaChannel()


def test_prepare_item_pixmap_stays_within_panel_budget(fp_v2_setup, qapp):
    """W-FP-BUBBLE-001: total bubble width respects panel width minus side margins."""
    _, engine, overlay = fp_v2_setup
    overlay.resize(360, 400)
    qapp.processEvents()
    long = "这是一条很长很长很长很长很长很长很长很长的气泡测试文本用于宽度上限"
    item = overlay.add_danmu_text(long)
    assert item is not None
    assert item.pixmap is not None
    dpr = item.pixmap.devicePixelRatio() or 1.0
    logical_w = item.pixmap.width() / dpr
    # paintEvent uses panel_w - pm_w - 4 with min x=4 → total budget panel_w - 8
    assert logical_w <= float(overlay.width()) - 8.0 + 0.5
    assert engine.visible_count() == 1
