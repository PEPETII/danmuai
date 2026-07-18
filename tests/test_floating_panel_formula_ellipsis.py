"""公式化弹幕在悬浮窗卡片内省略号渲染。"""
from __future__ import annotations

from app.config_store import ConfigStore
from app.floating_panel_engine import FloatingPanelEngine
from app.floating_panel_overlay import (
    FLOATING_PANEL_TEXT_MAX_LINES,
    FloatingPanelOverlay,
    fit_floating_panel_text,
)


def test_formula_text_uses_elided_render(workspace_tmp, qapp, monkeypatch):
    store = ConfigStore(db_path=workspace_tmp / "fp_formula.db")
    store.set("danmu_pool_use_custom", "1")
    store.set("custom_danmu_pool_enabled", "1")
    monkeypatch.setattr(
        "app.danmu_pool.is_formula_danmu_text",
        lambda _cfg, text: text.startswith("formula:"),
    )
    engine = FloatingPanelEngine(store)
    engine.set_panel_height(400.0)
    overlay = FloatingPanelOverlay(store, engine)
    overlay.resize(280, 400)
    qapp.processEvents()

    long_text = "formula:" + ("很长的一句公式化弹幕" * 8)
    item = overlay.add_danmu_text(long_text, skip_dedup=True)
    assert item is not None
    assert item.pixmap is not None

    assert overlay._font is not None and overlay._font_metrics is not None
    pad_x = float(overlay._style.padding_x)
    pad_y = float(overlay._style.padding_y)
    panel_w = float(overlay.width() or overlay._panel_width)
    max_total_w = max(1.0, panel_w - 4.0 * 2.0)
    max_content_w = max(1.0, max_total_w - overlay._extra_width())
    max_text_w = max(1.0, max_content_w - pad_x * 2.0)
    lines, _w, text_h = fit_floating_panel_text(
        long_text,
        overlay._font,
        overlay._font_metrics,
        max_text_w,
    )
    assert len(lines) <= FLOATING_PANEL_TEXT_MAX_LINES
    assert any(("…" in line) or ("..." in line) for line in lines)
    line_h = float(overlay._font_metrics.height())
    assert text_h <= line_h * FLOATING_PANEL_TEXT_MAX_LINES + 0.5
    # 高度允许两行（不再锁死单行）
    one_line_total = line_h + pad_y * 2.0 + overlay._extra_height()
    two_line_cap = line_h * FLOATING_PANEL_TEXT_MAX_LINES + pad_y * 2.0 + overlay._extra_height()
    assert item.height <= two_line_cap + 1.0
    assert item.height >= one_line_total - 1.0
    dpr = item.pixmap.devicePixelRatio() or 1.0
    pm_w = item.pixmap.width() / dpr
    assert pm_w <= panel_w + 1.0
