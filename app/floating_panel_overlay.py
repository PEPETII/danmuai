"""侧边悬浮窗渲染层：右侧透明置顶窄窗，圆角卡片 + 预渲染 QPixmap。

W-FP-V3-002：仅保留现有外观，运动学改为持续向上滚动。
"""
from __future__ import annotations

import logging
import sys
import time
from typing import TYPE_CHECKING

from PyQt6.QtCore import QElapsedTimer, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

from app.danmu_pool import is_formula_danmu_text
from app.floating_panel_engine import FloatingPanelEngine, FloatingPanelItem
from app.win32_overlay_zorder import apply_overlay_exstyles, reassert_hwnd_topmost

if TYPE_CHECKING:
    from app.config_store import ConfigStore

_FRAME_DT = 1.0 / 60.0
_INTERVAL_MS = 16
_DT_CAP_SEC = 0.1
_CARD_RADIUS = 10.0
_CARD_H_PAD = 12.0
_CARD_V_PAD = 8.0
_TEXT_FILL = QColor(255, 255, 255)
_TEXT_OUTLINE = QColor(0, 0, 0, 200)
_OUTLINE_WIDTH = 3
_CARD_BG = QColor(20, 20, 28, 170)
_FAST_DANMU_RENDER_MIN_LEN = 36
_FAST_OUTLINE_OFFSETS = (
    (-2, 0),
    (2, 0),
    (0, -2),
    (0, 2),
    (-1, -1),
    (1, 1),
    (-1, 1),
    (1, -1),
)

_fp_overlay_logger = logging.getLogger("danmu.floating_panel_overlay")


def _use_fast_danmu_render(content: str) -> bool:
    """长文本/CJK 走 drawText 描边，避免 QPainterPath.addText 阻塞主线程。"""
    if len(content) >= _FAST_DANMU_RENDER_MIN_LEN:
        return True
    return any(ord(ch) > 127 for ch in content)


class FloatingPanelOverlay(QWidget):
    """右侧窄窗悬浮弹幕；始终鼠标穿透。"""

    def __init__(self, config: "ConfigStore", engine: FloatingPanelEngine):
        super().__init__()
        self.config = config
        self.engine = engine

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.BypassWindowManagerHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setStyleSheet("background: transparent;")

        self._opacity_pct = 85
        self._panel_width = 360
        self._x_offset = 20
        self._y_offset = 80
        self._font: QFont | None = None
        self._font_metrics: QFontMetrics | None = None
        self._tick_clock = QElapsedTimer()
        self._last_tick_valid = False
        self.last_tick_dt_sec: float = _FRAME_DT
        self._screen_unavailable: bool = False

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)

        self._apply_config()

    def _apply_config(self) -> None:
        def _int(key: str, default: int, lo: int, hi: int) -> int:
            raw = self.config.get(key, "")
            try:
                return max(lo, min(int(raw or default), hi))
            except (TypeError, ValueError):
                return default

        self._opacity_pct = _int("floating_panel_opacity", 85, 0, 100)
        self._panel_width = _int("floating_panel_width", 360, 200, 800)
        self._x_offset = _int("floating_panel_x_offset", 20, 0, 400)
        self._y_offset = _int("floating_panel_y_offset", 80, 0, 400)
        size = _int("floating_panel_font_size", 20, 12, 48)
        from app.config_defaults import DEFAULT_DANMU_FONT_FAMILY

        family = str(
            self.config.get("floating_panel_font_family", DEFAULT_DANMU_FONT_FAMILY)
            or DEFAULT_DANMU_FONT_FAMILY
        ).strip()
        bold = str(self.config.get("floating_panel_font_bold", "1") or "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )
        self._font = QFont(family, size)
        self._font.setBold(bold)
        self._font_metrics = QFontMetrics(self._font)
        self.engine.apply_config()

    def apply_config(self) -> None:
        self._apply_config()
        for item in self.engine.visible_items():
            self._prepare_item_pixmap(item)
        self.engine.relayout_vertical_gaps()
        if self.isVisible():
            self.update()

    def is_render_active(self) -> bool:
        return self.timer.isActive()

    def active_count(self) -> int:
        return self.engine.active_count()

    def _apply_win32_click_through(self) -> None:
        if sys.platform != "win32":
            return
        apply_overlay_exstyles(int(self.winId()), click_through=True)

    def reassert_topmost_zorder(self) -> None:
        """Win32：恢复 HWND_TOPMOST，不抢焦点。"""
        if not self.isVisible():
            return
        self.raise_()
        try:
            hwnd = int(self.winId())
        except (RuntimeError, ValueError, TypeError):
            return
        reassert_hwnd_topmost(hwnd)

    def _estimate_item_height(self) -> float:
        if self._font_metrics is None:
            return 40.0
        return float(self._font_metrics.height()) + _CARD_V_PAD * 2

    def estimate_item_height(self) -> float:
        """供主链路 peek 阶段估算竖向准入，避免访问私有方法。"""
        return self._estimate_item_height()

    def add_danmu_text(
        self,
        content: str,
        persona: str = "",
        *,
        batch_id: int = 0,
        scene_generation: int = 0,
        skip_dedup: bool = False,
        pre_resolved: bool = False,
    ) -> FloatingPanelItem | None:
        item = self.engine.add_text(
            content,
            persona,
            item_height=self._estimate_item_height(),
            batch_id=batch_id,
            scene_generation=scene_generation,
            skip_dedup=skip_dedup,
            pre_resolved=pre_resolved,
        )
        if item is None:
            return None
        self._prepare_item_pixmap(item)
        self.ensure_render_loop()
        return item

    def _prepare_item_pixmap(self, item: FloatingPanelItem) -> None:
        if self._font is None or self._font_metrics is None:
            return
        text_w = self._font_metrics.horizontalAdvance(item.content)
        card_w = min(float(self.width() or self._panel_width) - 8.0, text_w + _CARD_H_PAD * 2)
        card_h = float(self._font_metrics.height()) + _CARD_V_PAD * 2
        self.engine.update_item_height(item, card_h)
        item.pixmap = self._render_card_pixmap(item.content, int(card_w), int(card_h))

    def _render_card_pixmap(self, text: str, width: int, height: int) -> QPixmap:
        dpr = self.devicePixelRatio() or 1.0
        w_px = max(1, int(width * dpr))
        h_px = max(1, int(height * dpr))
        pm = QPixmap(w_px, h_px)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            rect = QRectF(0, 0, width, height)
            path = QPainterPath()
            path.addRoundedRect(rect, _CARD_RADIUS, _CARD_RADIUS)
            painter.fillPath(path, _CARD_BG)
            painter.setFont(self._font)
            baseline_y = _CARD_V_PAD + self._font_metrics.ascent()
            text_x = _CARD_H_PAD
            max_text_w = max(1, int(width - _CARD_H_PAD * 2))
            draw_text = text
            if is_formula_danmu_text(self.config, text):
                draw_text = self._font_metrics.elidedText(
                    text,
                    Qt.TextElideMode.ElideRight,
                    max_text_w,
                )
            if _use_fast_danmu_render(draw_text):
                # 快路径：drawText + 8 方向偏移描边，避免 QPainterPath.addText 对 CJK 的路径计算开销
                outline_pen = QPen(_TEXT_OUTLINE)
                outline_pen.setWidth(_OUTLINE_WIDTH)
                for dx, dy in _FAST_OUTLINE_OFFSETS:
                    painter.setPen(outline_pen)
                    painter.drawText(int(text_x + dx), int(baseline_y + dy), draw_text)
                painter.setPen(QPen(_TEXT_FILL))
                painter.drawText(int(text_x), int(baseline_y), draw_text)
            else:
                # 慢路径：QPainterPath.addText 描边 + 填充（短 ASCII 文本）
                text_path = QPainterPath()
                text_path.addText(text_x, baseline_y, self._font, draw_text)
                pen = QPen(_TEXT_OUTLINE)
                pen.setWidth(_OUTLINE_WIDTH)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(pen)
                painter.drawPath(text_path)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(_TEXT_FILL)
                painter.drawPath(text_path)
        finally:
            painter.end()
        return pm

    def show_for_screen(self, screen_index: int = 0) -> None:
        screens = QApplication.screens()
        if not screens:
            self._screen_unavailable = True
            _fp_overlay_logger.warning(
                "show_for_screen: no screens available; floating panel stays hidden"
            )
            return
        screen_index = max(0, min(int(screen_index), len(screens) - 1))
        geo = screens[screen_index].geometry()
        if geo.width() <= 0 or geo.height() <= 0:
            _fp_overlay_logger.warning(
                "show_for_screen: screen %d has invalid geometry %dx%d; "
                "falling back to primary screen",
                screen_index, geo.width(), geo.height(),
            )
            if screen_index != 0:
                screen_index = 0
                geo = screens[0].geometry()
            if geo.width() <= 0 or geo.height() <= 0:
                self._screen_unavailable = True
                _fp_overlay_logger.warning(
                    "show_for_screen: primary screen also invalid %dx%d; "
                    "floating panel stays hidden",
                    geo.width(), geo.height(),
                )
                return
        self._screen_unavailable = False
        panel_h = max(160, geo.height() - self._y_offset * 2)
        x = geo.x() + geo.width() - self._panel_width - self._x_offset
        y = geo.y() + self._y_offset
        self.setGeometry(x, y, self._panel_width, panel_h)
        self.engine.set_panel_height(float(panel_h))
        self.show()
        self._apply_win32_click_through()
        self.reassert_topmost_zorder()
        if self.engine.running:
            self.ensure_render_loop()

    def start_render_loop(self) -> None:
        if not self.isVisible():
            return
        self._last_tick_valid = False
        if not self.timer.isActive():
            self.timer.start(_INTERVAL_MS)
        self._tick()

    def stop_render_loop(self, *, repaint: bool = False) -> None:
        was_active = self.timer.isActive()
        self.timer.stop()
        self._last_tick_valid = False
        if repaint and was_active and self.isVisible():
            self.update()

    def ensure_render_loop(self) -> None:
        if self.isVisible() and self.engine.needs_render_tick():
            self.start_render_loop()

    def reset_session_state(self) -> None:
        self.stop_render_loop()
        self.engine.clear()
        self.hide()
        self.update()

    def _tick_dt_sec(self) -> float:
        if not self._last_tick_valid:
            self._tick_clock.start()
            self._last_tick_valid = True
            return _FRAME_DT
        dt = self._tick_clock.restart() / 1000.0
        if dt <= 0.0:
            return _FRAME_DT
        return min(dt, _DT_CAP_SEC)

    def _tick(self) -> None:
        if not self.isVisible():
            self.stop_render_loop()
            return
        if not self.engine.needs_render_tick():
            self.stop_render_loop(repaint=True)
            return
        dt = self._tick_dt_sec()
        self.last_tick_dt_sec = dt
        self.engine.update(dt, time.monotonic())
        self.update()
        if not self.engine.needs_render_tick():
            self.stop_render_loop(repaint=True)

    def hideEvent(self, event) -> None:
        self.stop_render_loop()
        super().hideEvent(event)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.reassert_topmost_zorder()
        self._apply_win32_click_through()
        if self.engine.running:
            self.ensure_render_loop()

    def paintEvent(self, event) -> None:
        items = self.engine.visible_items()
        if not items:
            return
        global_alpha = max(0.0, min(1.0, self._opacity_pct / 100.0))
        if global_alpha <= 0.0:
            return
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
            panel_w = float(self.width())
            for item in items:
                alpha = item.opacity * global_alpha
                if alpha <= 0.0 or item.pixmap is None:
                    continue
                pm: QPixmap = item.pixmap
                x = max(4.0, panel_w - float(pm.width() / (pm.devicePixelRatio() or 1.0)) - 4.0)
                painter.setOpacity(alpha)
                painter.drawPixmap(int(x), int(item.current_y), pm)
            painter.setOpacity(1.0)
        finally:
            painter.end()
