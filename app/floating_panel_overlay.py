"""侧边悬浮窗渲染层：透明置顶窄窗，样式契约驱动的 card/bubble 预渲染。

W-FP-V3-002：历史运动学为持续向上滚动。
W-FP-BUBBLE-001：暖色圆角气泡试做（固定常量）。
W-FP-STYLE-QT-001：从 FloatingPanelStyle 读取规范化样式；左对齐堆积；严格 clip。
"""
from __future__ import annotations

import logging
import sys
import time
from typing import TYPE_CHECKING

from PyQt6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PyQt6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QTextLayout,
    QTextOption,
)
from PyQt6.QtWidgets import QApplication, QWidget

from app.floating_panel_engine import FloatingPanelEngine, FloatingPanelItem
from app.floating_panel_style import (
    FloatingPanelStyleSnapshot,
    WECHAT_CARD_COLORS,
    WECHAT_TEXT_COLOR,
    style_snapshot_from_mapping,
)
from app.win32_overlay_zorder import apply_overlay_exstyles, reassert_hwnd_topmost

if TYPE_CHECKING:
    from app.config_store import ConfigStore

_FRAME_DT = 1.0 / 60.0
_INTERVAL_MS = 16
_DT_CAP_SEC = 0.1

# 面板内边距：条目左对齐起点与右侧预算（非业务皮肤常量）
_PANEL_INSET = 4.0
_FAST_DANMU_RENDER_MIN_LEN = 36
# 单条卡片内文本最多行数（不进 ConfigStore）
FLOATING_PANEL_TEXT_MAX_LINES = 2
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


def _hex_to_qcolor(value: str, *, alpha_override: int | None = None) -> QColor:
    """Parse #RRGGBB / #RRGGBBAA into QColor; invalid → dark text."""
    raw = str(value or "").strip()
    if raw.startswith("#"):
        raw = raw[1:]
    if len(raw) == 6:
        try:
            r = int(raw[0:2], 16)
            g = int(raw[2:4], 16)
            b = int(raw[4:6], 16)
            a = 255 if alpha_override is None else max(0, min(255, int(alpha_override)))
            return QColor(r, g, b, a)
        except ValueError:
            pass
    elif len(raw) == 8:
        try:
            r = int(raw[0:2], 16)
            g = int(raw[2:4], 16)
            b = int(raw[4:6], 16)
            a_hex = int(raw[6:8], 16)
            a = a_hex if alpha_override is None else max(0, min(255, int(alpha_override)))
            return QColor(r, g, b, a)
        except ValueError:
            pass
    if alpha_override is None:
        return QColor(40, 28, 18, 255)
    return QColor(40, 28, 18, max(0, min(255, int(alpha_override))))


def _pick_palette_color(
    colors: tuple[str, ...] | list[str],
    mode: str,
    weights: dict[str, float] | None,
    style_index: int,
    *,
    fallback: str,
) -> str:
    """Deterministic color from palette + style_index (no global random)."""
    palette = [str(c) for c in (colors or ()) if str(c).strip()]
    if not palette:
        return fallback
    idx = int(style_index) % len(palette)
    if str(mode or "").strip().lower() != "weighted" or not weights:
        return palette[idx]

    w_list: list[float] = []
    for c in palette:
        try:
            w = float((weights or {}).get(c, 0.0))
        except (TypeError, ValueError):
            w = 0.0
        w_list.append(max(0.0, w))
    total = sum(w_list)
    if total <= 0.0:
        return palette[idx]
    # Stable pseudo-slot from style_index into [0, total)
    slot = ((int(style_index) * 2654435761) & 0xFFFFFFFF) / 4294967296.0 * total
    acc = 0.0
    for c, w in zip(palette, w_list):
        acc += w
        if slot < acc:
            return c
    return palette[-1]


def _use_fast_danmu_render(content: str) -> bool:
    """长文本/CJK 走 drawText 描边，避免 QPainterPath.addText 阻塞主线程。"""
    if len(content) >= _FAST_DANMU_RENDER_MIN_LEN:
        return True
    return any(ord(ch) > 127 for ch in content)



def fit_floating_panel_text(
    text: str,
    font: QFont,
    metrics: QFontMetrics,
    max_text_w: float,
    *,
    max_lines: int = FLOATING_PANEL_TEXT_MAX_LINES,
) -> tuple[list[str], float, float]:
    """Wrap card text to at most ``max_lines``; elide remainder on the last line.

    Measure and draw must both call this helper so height and glyphs stay in sync.

    Returns ``(lines, used_width, text_block_height)``.
    """
    raw = str(text or "")
    max_w = max(1, int(max_text_w))
    line_h = float(metrics.height())
    max_lines = max(1, int(max_lines))
    if not raw:
        return [""], 0.0, line_h

    natural_w = float(metrics.horizontalAdvance(raw))
    if natural_w <= float(max_w):
        return [raw], natural_w, line_h

    option = QTextOption()
    option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
    option.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

    layout = QTextLayout(raw, font)
    layout.setTextOption(option)
    layout.beginLayout()
    lines: list[str] = []
    used_w = 0.0
    try:
        while True:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(float(max_w))
            start = int(line.textStart())
            if len(lines) + 1 >= max_lines:
                remaining = raw[start:]
                elided = metrics.elidedText(
                    remaining,
                    Qt.TextElideMode.ElideRight,
                    max_w,
                )
                lines.append(elided)
                used_w = max(used_w, float(metrics.horizontalAdvance(elided)))
                break
            length = int(line.textLength())
            segment = raw[start : start + length]
            lines.append(segment)
            used_w = max(used_w, float(line.naturalTextWidth()))
    finally:
        layout.endLayout()

    if not lines:
        elided = metrics.elidedText(raw, Qt.TextElideMode.ElideRight, max_w)
        lines = [elided]
        used_w = float(metrics.horizontalAdvance(elided))

    height = line_h * float(len(lines))
    return lines, min(float(max_w), used_w), height


class FloatingPanelOverlay(QWidget):
    """右侧窄窗悬浮弹幕；始终鼠标穿透；条目左对齐堆积。"""

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

        self._style: FloatingPanelStyleSnapshot = style_snapshot_from_mapping(None)
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

    # ------------------------------------------------------------------
    # Style / geometry helpers
    # ------------------------------------------------------------------

    def current_style(self) -> FloatingPanelStyleSnapshot:
        return self._style

    def _tail_w(self) -> float:
        st = self._style
        if st.shape == "bubble" and st.tail_enabled and st.tail_width > 0:
            return float(st.tail_width)
        return 0.0

    def _tail_h(self) -> float:
        st = self._style
        if st.shape == "bubble" and st.tail_enabled and st.tail_height > 0:
            return float(st.tail_height)
        return 0.0

    def _shadow_pads(self) -> tuple[float, float, float, float]:
        """Return (pad_left_beyond_tail, pad_top, pad_right, pad_bottom) for shadow extent."""
        st = self._style
        if not st.shadow_enabled:
            return (0.0, 1.0, 1.0, 1.0)
        blur = max(0.0, float(st.shadow_blur))
        # Approximate blur soft edge + solid offset extent
        soft = max(1.0, blur * 0.5) if blur > 0 else 1.0
        dx = float(st.shadow_offset_x)
        dy = float(st.shadow_offset_y)
        pad_left = max(0.0, -dx) + (soft if dx < 0 else 0.0)
        pad_right = max(0.0, dx) + soft + 2.0
        pad_top = max(0.0, -dy) + soft
        pad_bottom = max(0.0, dy) + soft + 1.0
        return (pad_left, max(1.0, pad_top), pad_right, max(1.0, pad_bottom))

    def _extra_width(self) -> float:
        """Horizontal extent beyond content body: left tail + shadow pads."""
        pad_left, _pt, pad_right, _pb = self._shadow_pads()
        return self._tail_w() + pad_left + pad_right

    def _extra_height(self) -> float:
        """Vertical extent beyond content body: top/bottom shadow pads."""
        _pl, pad_top, _pr, pad_bottom = self._shadow_pads()
        return pad_top + pad_bottom

    def _body_path(self, body: QRectF) -> QPainterPath:
        """Rounded body; bubble + tail_enabled → left-pointing tail.

        支持 round（平滑水滴尾巴）与 sharp（锐利三角），位置由 tail_offset_y 控制。
        """
        st = self._style
        radius = float(max(0, st.radius))
        path = QPainterPath()
        path.addRoundedRect(body, radius, radius)
        tail_w = self._tail_w()
        tail_h = self._tail_h()
        if st.shape != "bubble" or tail_w <= 0.0 or tail_h <= 0.0:
            return path
        tail_style = str(st.tail_style or "round").strip().lower()
        offset_pct = max(0, min(100, int(st.tail_offset_y))) / 100.0
        cy = body.top() + body.height() * offset_pct
        tip = QPointF(body.left() - tail_w, cy)
        base_x = body.left() + 1.0
        half_h = tail_h * 0.5
        tail = QPainterPath()
        if tail_style == "sharp":
            tail.moveTo(tip)
            tail.lineTo(QPointF(base_x, cy - half_h))
            tail.lineTo(QPointF(base_x, cy + half_h))
            tail.closeSubpath()
        else:
            # round：贝塞尔曲线水滴尾巴，模拟 blivechat 聊天气泡
            ctrl_in = tail_w * 0.55
            ctrl_out = tail_w * 0.25
            tail.moveTo(QPointF(base_x, cy - half_h))
            tail.cubicTo(
                QPointF(base_x + ctrl_in, cy - half_h),
                QPointF(body.left() + ctrl_out, cy - half_h * 0.35),
                tip,
            )
            tail.cubicTo(
                QPointF(body.left() + ctrl_out, cy + half_h * 0.35),
                QPointF(base_x + ctrl_in, cy + half_h),
                QPointF(base_x, cy + half_h),
            )
            tail.closeSubpath()
        return path.united(tail)

    def _apply_config(self) -> None:
        def _int(key: str, default: int, lo: int, hi: int) -> int:
            raw = self.config.get(key, "")
            try:
                return max(lo, min(int(raw or default), hi))
            except (TypeError, ValueError):
                return default

        # 布局偏移仍由 ConfigStore 直接读取（非样式契约字段）
        self._x_offset = _int("floating_panel_x_offset", 20, 0, 400)
        self._y_offset = _int("floating_panel_y_offset", 80, 0, 400)

        # 规范化样式快照（缺失字段回退 wechat 工厂）
        self._style = style_snapshot_from_mapping(self.config)
        st = self._style
        self._opacity_pct = max(0, min(100, int(st.panel_opacity)))
        self._panel_width = max(200, min(800, int(st.width)))

        family = str(st.font_family or "Microsoft YaHei").strip() or "Microsoft YaHei"
        size = max(12, min(48, int(st.font_size)))
        self._font = QFont(family, size)
        self._font.setBold(bool(st.font_bold))
        self._font_metrics = QFontMetrics(self._font)
        self.engine.apply_config()

    def apply_config(self) -> None:
        """热更新样式/字体/几何：重算可见条 pixmap 与堆积目标，不清空正常可见弹幕。"""
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

    def _apply_win32_click_through(self, *, _defer_attempt: int = 0) -> None:
        if sys.platform != "win32":
            return
        try:
            hwnd = int(self.winId())
        except (RuntimeError, ValueError, TypeError):
            return
        if not hwnd:
            try:
                still_visible = self.isVisible()
            except (RuntimeError, ValueError, TypeError):
                return
            if _defer_attempt < 3 and still_visible:
                QTimer.singleShot(
                    0,
                    lambda attempt=_defer_attempt + 1: self._apply_win32_click_through(
                        _defer_attempt=attempt
                    ),
                )
            return
        apply_overlay_exstyles(hwnd, click_through=True)

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
        st = self._style
        if self._font_metrics is None:
            return 40.0 + self._extra_height()
        content_font = QFont(self._font)
        content_font.setPointSize(max(6, min(72, int(st.content_size))))
        content_metrics = QFontMetrics(content_font)
        line_spacing = max(1.0, float(st.content_line_height) / 100.0)
        content_h = float(content_metrics.height()) * line_spacing + float(st.padding_y) * 2
        return content_h + self._extra_height()

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
        st = self._style
        panel_w = float(self.width() or self._panel_width)
        # 左对齐：两侧 inset 后整颗气泡（主体 + 尾 + 阴影）不得超过面板宽度
        max_total_w = max(1.0, panel_w - _PANEL_INSET * 2.0)
        max_content_w = max(1.0, max_total_w - self._extra_width())
        pad_x = float(st.padding_x)
        pad_y = float(st.padding_y)
        max_text_w = max(1.0, max_content_w - pad_x * 2.0)
        lines, text_w, text_h = fit_floating_panel_text(
            item.content,
            self._font,
            self._font_metrics,
            max_text_w,
        )
        # 多行时铺满可用内容宽，保证 _render 用同一 max_text_w 再 fit
        if len(lines) > 1:
            content_w = max_content_w
        else:
            content_w = min(max_content_w, text_w + pad_x * 2.0)
        content_h = float(text_h) + pad_y * 2.0
        total_h = content_h + self._extra_height()
        self.engine.update_item_height(item, total_h)
        item.pixmap = self._render_card_pixmap(
            item.content,
            int(content_w),
            int(content_h),
            style_index=int(item.style_index),
        )

    def _render_card_pixmap(
        self,
        text: str,
        width: int,
        height: int,
        *,
        style_index: int = 0,
    ) -> QPixmap:
        """Render card/bubble pixmap from current style.

        ``width`` / ``height`` are the **content body** size (text + padding).
        Returned pixmap is larger by tail + shadow pads so nothing is clipped.
        Colors are fixed by ``style_index`` (no re-sample during animation).
        """
        st = self._style
        content_w = max(1, int(width))
        content_h = max(1, int(height))
        pad_left_shadow, pad_top, pad_right, pad_bottom = self._shadow_pads()
        tail_w = self._tail_w()
        left_origin = tail_w + pad_left_shadow
        total_w = content_w + int(self._extra_width())
        total_h = content_h + int(pad_top + pad_bottom)
        dpr = self.devicePixelRatio() or 1.0
        w_px = max(1, int(total_w * dpr))
        h_px = max(1, int(total_h * dpr))
        pm = QPixmap(w_px, h_px)
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

            body = QRectF(
                left_origin,
                pad_top,
                float(content_w),
                float(content_h),
            )
            shape_path = self._body_path(body)

            # Card fill color (style_index fixed) × card_opacity
            card_hex = _pick_palette_color(
                st.card_colors,
                st.card_color_mode,
                st.card_color_weights,
                style_index,
                fallback=WECHAT_CARD_COLORS[0],
            )
            card_alpha = int(round(255 * max(0, min(100, st.card_opacity)) / 100.0))
            card_color = _hex_to_qcolor(card_hex, alpha_override=card_alpha)

            # Shadow (approximate blur via multi-pass soft offset)
            if st.shadow_enabled:
                shadow_alpha = int(round(255 * max(0, min(100, st.shadow_opacity)) / 100.0))
                shadow_base = _hex_to_qcolor(st.shadow_color, alpha_override=shadow_alpha)
                dx = float(st.shadow_offset_x)
                dy = float(st.shadow_offset_y)
                blur = max(0, int(st.shadow_blur))
                if blur <= 0:
                    shadow_path = QPainterPath(shape_path)
                    shadow_path.translate(dx, dy)
                    painter.fillPath(shadow_path, shadow_base)
                else:
                    # Soft shadow: concentric offsets with decreasing alpha
                    steps = min(4, max(1, blur // 2))
                    for i in range(steps, 0, -1):
                        frac = i / float(steps)
                        soft = QPainterPath(shape_path)
                        soft.translate(dx * frac, dy * frac)
                        a = max(1, int(shadow_base.alpha() * (0.35 + 0.65 * (1.0 - frac * 0.5)) / steps * 1.2))
                        c = QColor(shadow_base.red(), shadow_base.green(), shadow_base.blue(), min(255, a))
                        painter.fillPath(soft, c)
                    solid = QPainterPath(shape_path)
                    solid.translate(dx, dy)
                    painter.fillPath(solid, shadow_base)

            painter.fillPath(shape_path, card_color)

            # Border on top of fill
            if st.border_enabled and st.border_width > 0:
                border_alpha = int(round(255 * max(0, min(100, st.border_opacity)) / 100.0))
                border_color = _hex_to_qcolor(st.border_color, alpha_override=border_alpha)
                border_pen = QPen(border_color)
                border_pen.setWidth(max(1, int(st.border_width)))
                border_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                border_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                painter.setPen(border_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(shape_path)

            if self._font is None or self._font_metrics is None:
                return pm

            text_hex = _pick_palette_color(
                st.text_colors,
                st.text_color_mode,
                st.text_color_weights,
                style_index,
                fallback=WECHAT_TEXT_COLOR,
            )
            text_fill = _hex_to_qcolor(text_hex)
            pad_x = float(st.padding_x)
            pad_y = float(st.padding_y)
            painter.setFont(self._font)

            # 用户名与内容分离（参考 blivechat 的 author-name / message 层级）
            username_on = bool(st.username_enabled)
            username_text = str(st.username_text or "弹幕") if username_on else ""
            username_sep = str(st.username_separator or "：") if username_on else ""
            full_text = text
            username_w = 0.0
            username_font = None
            username_metrics = None
            if username_text:
                username_font = QFont(self._font)
                username_font.setPointSize(max(6, min(72, int(st.username_size))))
                username_font.setBold(int(st.username_weight) >= 600)
                username_font.setWeight(max(1, min(99, int(st.username_weight))))
                username_metrics = QFontMetrics(username_font)
                username_w = float(username_metrics.horizontalAdvance(username_text + username_sep))

            content_font = QFont(self._font)
            content_font.setPointSize(max(6, min(72, int(st.content_size))))
            content_font.setBold(int(st.content_weight) >= 600)
            content_font.setWeight(max(1, min(99, int(st.content_weight))))
            content_metrics = QFontMetrics(content_font)
            line_spacing = max(1.0, float(st.content_line_height) / 100.0)

            text_x = body.left() + pad_x
            max_text_w = max(1.0, float(content_w) - pad_x * 2.0)
            content_max_w = max(1.0, max_text_w - username_w - float(st.gap_username_content))
            lines, _used_w, _text_h = fit_floating_panel_text(
                full_text,
                content_font,
                content_metrics,
                content_max_w,
            )
            line_h = float(content_metrics.height()) * line_spacing
            ascent = float(content_metrics.ascent())
            joined = "\n".join(lines)

            # 用户名颜色（与内容文字使用不同层级）
            username_color = _hex_to_qcolor(st.username_color)

            outline_on = bool(st.outline_enabled) and st.outline_width > 0
            outline_color = _hex_to_qcolor(st.outline_color)
            outline_w = max(1, int(st.outline_width)) if outline_on else 0

            # 单行且开启用户名时，将用户名与首行内容在同一基线绘制
            def _draw_text_line(
                painter_: QPainter,
                font_: QFont,
                metrics_: QFontMetrics,
                line_text: str,
                x: float,
                baseline_y: float,
                fill_: QColor,
                do_outline: bool,
            ) -> None:
                painter_.setFont(font_)
                if do_outline:
                    outline_pen_ = QPen(outline_color)
                    outline_pen_.setWidth(outline_w)
                    for odx, ody in _FAST_OUTLINE_OFFSETS:
                        painter_.setPen(outline_pen_)
                        painter_.drawText(int(x + odx), int(baseline_y + ody), line_text)
                painter_.setPen(QPen(fill_))
                painter_.drawText(int(x), int(baseline_y), line_text)

            if _use_fast_danmu_render(joined):
                for i, line_text in enumerate(lines):
                    baseline_y = body.top() + pad_y + ascent + i * line_h
                    if i == 0 and username_text:
                        ux = text_x
                        _draw_text_line(
                            painter, username_font, username_metrics,
                            username_text + username_sep, ux, baseline_y, username_color, outline_on,
                        )
                        cx = ux + username_w + float(st.gap_username_content)
                        _draw_text_line(
                            painter, content_font, content_metrics,
                            line_text, cx, baseline_y, text_fill, outline_on,
                        )
                    else:
                        _draw_text_line(
                            painter, content_font, content_metrics,
                            line_text, text_x, baseline_y, text_fill, outline_on,
                        )
            else:
                for i, line_text in enumerate(lines):
                    baseline_y = body.top() + pad_y + ascent + i * line_h
                    if i == 0 and username_text:
                        ux = text_x
                        up = QPainterPath()
                        up.addText(ux, baseline_y, username_font, username_text + username_sep)
                        if outline_on:
                            pen = QPen(outline_color)
                            pen.setWidth(outline_w)
                            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                            painter.setPen(pen)
                            painter.drawPath(up)
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(username_color)
                        painter.drawPath(up)

                        cp = QPainterPath()
                        cp.addText(ux + username_w + float(st.gap_username_content), baseline_y, content_font, line_text)
                        if outline_on:
                            pen = QPen(outline_color)
                            pen.setWidth(outline_w)
                            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                            painter.setPen(pen)
                            painter.drawPath(cp)
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(text_fill)
                        painter.drawPath(cp)
                    else:
                        tp = QPainterPath()
                        tp.addText(text_x, baseline_y, content_font, line_text)
                        if outline_on:
                            pen = QPen(outline_color)
                            pen.setWidth(outline_w)
                            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
                            painter.setPen(pen)
                            painter.drawPath(tp)
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(text_fill)
                        painter.drawPath(tp)
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
            # 严格裁剪于容器矩形：部分越顶/越底像素不得显示
            clip = QRectF(0.0, 0.0, float(self.width()), float(self.height()))
            painter.setClipRect(clip)
            # 左对齐：统一左侧内缩，禁止 panel_w - pm_w 右对齐
            left_x = _PANEL_INSET
            for item in items:
                alpha = item.opacity * global_alpha
                if alpha <= 0.0 or item.pixmap is None:
                    continue
                pm: QPixmap = item.pixmap
                painter.setOpacity(alpha)
                painter.drawPixmap(int(left_x), int(item.current_y), pm)
            painter.setOpacity(1.0)
        finally:
            painter.end()
