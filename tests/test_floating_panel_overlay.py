"""W-FP-V3-002 / W-FP-BUBBLE-001 / W-FP-STYLE-QT-001：FloatingPanelOverlay 渲染与计时器。"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import Qt

from app.config_store import ConfigStore
from app.floating_panel_engine import FloatingPanelEngine
from app.floating_panel_overlay import FloatingPanelOverlay, _PANEL_INSET
from app.floating_panel_style import (
    CLASSIC_CARD_COLORS,
    WECHAT_CARD_COLORS,
    WECHAT_TEXT_COLOR,
    classic_factory_defaults,
    wechat_factory_defaults,
)


@pytest.fixture()
def fp_v2_setup(qapp, workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "fp_overlay.db")
    store.set("floating_panel_max_items", "12")
    store.set("floating_panel_font_size", "20")
    store.set("floating_panel_opacity", "85")
    store.set("danmu_render_mode", "floating_panel")
    # wechat 工厂默认（含 bubble 样式字段）
    for k, v in wechat_factory_defaults().items():
        store.set(k, v)
    engine = FloatingPanelEngine(store)
    overlay = FloatingPanelOverlay(store, engine)
    engine.set_panel_height(400.0)
    overlay.resize(360, 400)
    qapp.processEvents()
    return store, engine, overlay


def _settle_ticks(overlay: FloatingPanelOverlay, engine: FloatingPanelEngine, n: int = 40) -> None:
    """Advance engine until idle (entry/push animations done)."""
    overlay._tick_dt_sec = lambda: 0.05
    for _ in range(n):
        if not engine.needs_render_tick():
            break
        overlay._tick()


def test_add_danmu_text_starts_render(fp_v2_setup, qapp):
    _, engine, overlay = fp_v2_setup
    overlay.show()
    qapp.processEvents()
    item = overlay.add_danmu_text("overlay hello")
    assert item is not None
    assert engine.visible_count() == 1
    assert item.pixmap is not None


def test_timer_stops_when_idle_settled(fp_v2_setup, qapp):
    """堆积引擎：条目静止后 needs_render_tick=False，timer 必须停止（条目可仍可见）。"""
    _, engine, overlay = fp_v2_setup
    overlay.show()
    qapp.processEvents()
    overlay.add_danmu_text("once")
    assert engine.visible_count() == 1
    _settle_ticks(overlay, engine)
    qapp.processEvents()
    assert engine.visible_count() == 1
    assert not engine.needs_render_tick()
    assert not overlay.is_render_active()


def test_timer_stops_when_queue_empty(fp_v2_setup, qapp):
    """清空后 timer 停止（不再依赖持续上滚滚出队列）。"""
    _, engine, overlay = fp_v2_setup
    overlay.show()
    qapp.processEvents()
    overlay.add_danmu_text("once")
    _settle_ticks(overlay, engine)
    engine.clear()
    overlay._tick()
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
    """wechat/bubble：pixmap 大于 content body（含左尾 + 阴影垫）。"""
    _, _, overlay = fp_v2_setup
    assert overlay.current_style().shape == "bubble"
    content_w, content_h = 120, 36
    pm = overlay._render_card_pixmap("bubble hi", content_w, content_h, style_index=0)
    assert pm is not None
    dpr = pm.devicePixelRatio() or 1.0
    logical_w = pm.width() / dpr
    logical_h = pm.height() / dpr
    assert logical_w >= content_w + overlay._extra_width() - 0.5
    assert logical_h >= content_h + overlay._extra_height() - 0.5
    assert pm.hasAlphaChannel()


def test_card_pixmap_has_alpha_no_tail_budget(fp_v2_setup, qapp):
    """classic/card：无尾巴，pixmap 仍含 alpha 与阴影预算。"""
    store, engine, _old = fp_v2_setup
    for k, v in classic_factory_defaults().items():
        store.set(k, v)
    overlay = FloatingPanelOverlay(store, engine)
    overlay.resize(360, 400)
    qapp.processEvents()
    assert overlay.current_style().shape == "card"
    assert overlay._tail_w() == 0.0
    content_w, content_h = 100, 32
    pm = overlay._render_card_pixmap("card hi", content_w, content_h, style_index=0)
    dpr = pm.devicePixelRatio() or 1.0
    logical_w = pm.width() / dpr
    assert logical_w >= content_w - 0.5
    assert logical_w < content_w + 40  # no large left tail
    assert pm.hasAlphaChannel()


def test_prepare_item_pixmap_stays_within_panel_budget(fp_v2_setup, qapp):
    """总气泡宽度尊重面板宽度减去左右 inset。"""
    _, engine, overlay = fp_v2_setup
    overlay.resize(360, 400)
    qapp.processEvents()
    long = "这是一条很长很长很长很长很长很长很长很长的气泡测试文本用于宽度上限"
    item = overlay.add_danmu_text(long)
    assert item is not None
    assert item.pixmap is not None
    dpr = item.pixmap.devicePixelRatio() or 1.0
    logical_w = item.pixmap.width() / dpr
    assert logical_w <= float(overlay.width()) - _PANEL_INSET * 2.0 + 0.5
    assert engine.visible_count() == 1


def test_paint_left_aligns_items(fp_v2_setup, qapp, monkeypatch):
    """paintEvent 左对齐：drawPixmap x 恒为 _PANEL_INSET，禁止右对齐公式。"""
    _, engine, overlay = fp_v2_setup
    overlay.resize(360, 400)
    overlay.show()
    qapp.processEvents()
    item = overlay.add_danmu_text("align me")
    assert item is not None
    _settle_ticks(overlay, engine)
    drawn: list[tuple[int, int]] = []
    real_draw = None

    from PyQt6.QtGui import QPainter

    orig = QPainter.drawPixmap

    def spy_draw(self, *args, **kwargs):
        # drawPixmap(int x, int y, QPixmap) overload used by overlay
        if len(args) >= 3 and isinstance(args[0], int) and isinstance(args[1], int):
            drawn.append((args[0], args[1]))
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(QPainter, "drawPixmap", spy_draw)
    overlay.repaint()
    qapp.processEvents()
    assert drawn, "paintEvent should draw at least one pixmap"
    for x, _y in drawn:
        assert x == int(_PANEL_INSET)
    # 显式禁止右对齐：x 不得接近 panel_w - pm_w
    dpr = item.pixmap.devicePixelRatio() or 1.0
    pm_w = item.pixmap.width() / dpr
    right_aligned_x = float(overlay.width()) - pm_w - 4.0
    assert int(_PANEL_INSET) != int(right_aligned_x) or pm_w > overlay.width() - 16


def test_style_index_color_stable_across_rerender(fp_v2_setup, qapp):
    """同一 style_index 在 apply_config 重渲染后颜色索引稳定（不重抽）。"""
    store, engine, overlay = fp_v2_setup
    # equal 调色板 4 色
    store.set("floating_panel_card_colors", '["#FFECD2","#DDF5D7","#DDEBFF","#FFDDE8"]')
    store.set("floating_panel_card_color_mode", "equal")
    overlay.apply_config()
    items = []
    for i in range(4):
        it = overlay.add_danmu_text(f"color-{i}", skip_dedup=True)
        assert it is not None
        items.append(it)
    indices = [it.style_index for it in items]
    # style_index 在创建时固定且递增
    assert indices == sorted(indices) or len(set(indices)) == 4
    for it in items:
        assert it.style_index == items[items.index(it)].style_index
    before = [it.style_index for it in engine.visible_items()]
    store.set("floating_panel_font_size", "22")
    overlay.apply_config()
    after = [it.style_index for it in engine.visible_items()]
    assert before == after
    assert engine.visible_count() == 4


def test_apply_config_preserves_visible_items(fp_v2_setup, qapp):
    """热更新不清空正常可见条，但会刷新 pixmap/高度。"""
    store, engine, overlay = fp_v2_setup
    overlay.show()
    qapp.processEvents()
    a = overlay.add_danmu_text("keep-a", skip_dedup=True)
    b = overlay.add_danmu_text("keep-b", skip_dedup=True)
    assert a is not None and b is not None
    _settle_ticks(overlay, engine)
    old_h = a.height
    old_pm_id = id(a.pixmap)
    store.set("floating_panel_font_size", "28")
    store.set("floating_panel_padding_y", "14")
    overlay.apply_config()
    texts = [it.content for it in engine.visible_items()]
    assert "keep-a" in texts and "keep-b" in texts
    assert engine.visible_count() == 2
    # pixmap 应被重新生成
    assert a.pixmap is not None
    assert id(a.pixmap) != old_pm_id or a.height != old_h


def test_wechat_default_warm_first_color(fp_v2_setup):
    st = fp_v2_setup[2].current_style()
    assert st.card_colors[0].upper() == WECHAT_CARD_COLORS[0].upper()
    assert st.text_colors[0].upper() == WECHAT_TEXT_COLOR.upper()
    assert st.shape == "bubble"


def test_classic_four_colors_available(fp_v2_setup, qapp):
    store, engine, _ = fp_v2_setup
    for k, v in classic_factory_defaults().items():
        store.set(k, v)
    overlay = FloatingPanelOverlay(store, engine)
    qapp.processEvents()
    st = overlay.current_style()
    assert st.shape == "card"
    assert tuple(c.upper() for c in st.card_colors) == tuple(c.upper() for c in CLASSIC_CARD_COLORS)


def test_paint_uses_clip_rect(fp_v2_setup, qapp, monkeypatch):
    """paintEvent 必须 setClipRect 容器矩形。"""
    _, engine, overlay = fp_v2_setup
    overlay.resize(360, 400)
    overlay.show()
    qapp.processEvents()
    overlay.add_danmu_text("clip me")
    _settle_ticks(overlay, engine)
    clips: list[object] = []
    from PyQt6.QtGui import QPainter

    orig = QPainter.setClipRect

    def spy_clip(self, *args, **kwargs):
        clips.append(args[0] if args else None)
        return orig(self, *args, **kwargs)

    monkeypatch.setattr(QPainter, "setClipRect", spy_clip)
    overlay.repaint()
    qapp.processEvents()
    assert clips, "paintEvent must establish a clip rect"
