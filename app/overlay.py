import ctypes
import logging
import os
import sys
import time

from PyQt6.QtCore import QElapsedTimer, QPointF, QRect, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtWidgets import QApplication, QWidget

from app.api_schedule import ENGINE_BASE_FPS
from app.config_store import ConfigStore
from app.danmu_engine import (
    FADE_IN_PX,
    FADE_OUT_PX,
    DanmuEngine,
    DanmuItem,
    layout_height_ratio,
    normalize_layout_mode,
)

if sys.platform == "win32":
    _GWL_EXSTYLE = -20
    _WS_EX_LAYERED = 0x00080000
    _WS_EX_TRANSPARENT = 0x00000020
    try:
        _SetWindowLong = ctypes.windll.user32.SetWindowLongPtrW
        _GetWindowLong = ctypes.windll.user32.GetWindowLongPtrW
    except AttributeError:
        _SetWindowLong = ctypes.windll.user32.SetWindowLongW
        _GetWindowLong = ctypes.windll.user32.GetWindowLongW

_FRAME_DT = 1.0 / 60.0
_INTERVAL_MS = 16
# Back-compat aliases for tests / docs
_INTERVAL_MAX_MS = _INTERVAL_MS
_INTERVAL_IDLE_MS = _INTERVAL_MS
_INTERVAL_MED_MS = _INTERVAL_MS
_DT_CAP_SEC = 0.1
_OPACITY_CACHE_BUCKET = 4.0
_Y_OFFSET = 30
_DIRTY_MARGIN_PX = 12
_overlay_logger = logging.getLogger("danmu.overlay")
_overlay_profile_flag: bool | None = None


def overlay_profile_enabled() -> bool:
    global _overlay_profile_flag
    if _overlay_profile_flag is None:
        value = os.environ.get("DANMU_OVERLAY_PROFILE", "").strip().lower()
        _overlay_profile_flag = value in ("1", "true", "yes", "on")
    return _overlay_profile_flag


class DanmuOverlay(QWidget):
    def __init__(self, config: ConfigStore, engine: DanmuEngine):
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

        self._apply_font_from_config()

        self._screen_width: float = 0.0
        self._timer_interval_ms = _INTERVAL_MS
        self._tick_clock = QElapsedTimer()
        self._last_tick_valid = False
        self.last_tick_dt_sec: float = _FRAME_DT
        self._profile_last_log_at: float = 0.0

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)

    def _apply_font_from_config(self) -> None:
        from app.config_defaults import DEFAULT_FONT_SIZE

        size = self.config.get_int("font_size", DEFAULT_FONT_SIZE)
        size = max(12, min(72, size))
        self.font = QFont("Microsoft YaHei", size)
        self.font.setBold(True)
        self.font_metrics = QFontMetrics(self.font)

    def _apply_win32_click_through(self):
        if sys.platform != "win32":
            return
        hwnd = int(self.winId())
        ex_style = _GetWindowLong(hwnd, _GWL_EXSTYLE)
        _SetWindowLong(hwnd, _GWL_EXSTYLE,
                       ex_style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT)

    def _has_animatable_content(self) -> bool:
        return self.engine.needs_render_tick()

    def start_render_loop(self) -> None:
        if not self.isVisible():
            return
        self._last_tick_valid = False
        if not self.timer.isActive():
            self.timer.start(self._timer_interval_ms)
        self._tick()

    def stop_render_loop(self, *, repaint: bool = False) -> None:
        was_active = self.timer.isActive()
        self.timer.stop()
        self._last_tick_valid = False
        if repaint and was_active and self.isVisible():
            self.update()

    def ensure_render_loop(self) -> None:
        if self.isVisible() and self._has_animatable_content():
            self.start_render_loop()

    def _tick_dt_sec(self) -> float:
        if not self._last_tick_valid:
            self._tick_clock.start()
            self._last_tick_valid = True
            return _FRAME_DT
        dt = self._tick_clock.restart() / 1000.0
        if dt <= 0.0:
            return _FRAME_DT
        return min(dt, _DT_CAP_SEC)

    def _target_interval_ms(self, visible: int | None = None) -> int:
        del visible
        if not self.isVisible():
            return 0
        if not self._has_animatable_content():
            return 0
        return _INTERVAL_MS

    def _sync_timer_interval(self, visible: int | None = None) -> None:
        target = self._target_interval_ms(visible)
        if target <= 0:
            self.stop_render_loop(repaint=True)
            return
        if target != self._timer_interval_ms:
            self._timer_interval_ms = target
            if self.timer.isActive():
                self.timer.stop()
                self.timer.start(target)

    def _motion_margin_px(self) -> float:
        dt = self.last_tick_dt_sec if self.last_tick_dt_sec > 0 else _FRAME_DT
        return max(_DIRTY_MARGIN_PX, dt * ENGINE_BASE_FPS * 6.0)

    def _item_paint_size(self, item: DanmuItem) -> tuple[float, float]:
        pm = item._pixmap
        if pm is not None and not pm.isNull():
            dpr = pm.devicePixelRatio()
            return pm.width() / dpr, pm.height() / dpr
        return item.width + 10.0, float(self.font_metrics.height() + 10)

    def _item_paint_rect(self, item: DanmuItem) -> QRectF:
        w, h = self._item_paint_size(item)
        return QRectF(item.x, item.y + _Y_OFFSET, w, h)

    def _item_intersects_dirty(self, item: DanmuItem, margin: float) -> bool:
        sw = self._screen_width or float(self.width())
        if sw <= 0:
            return True
        left = item.x - margin
        right = item.x + item.width + margin + FADE_IN_PX
        return right > 0 and left < sw + FADE_IN_PX

    def _item_in_paint_band(self, item: DanmuItem) -> bool:
        """Skip fully off-screen items in dirty union / paint (still updated in engine)."""
        sw = self._screen_width or float(self.width())
        if sw <= 0:
            return True
        if item.x >= sw + FADE_IN_PX:
            return False
        if item.x + item.width <= 0:
            return False
        return True

    def _union_dirty_rect(self, margin: float) -> QRect | None:
        bounds: QRectF | None = None
        for track in self.engine.tracks:
            for item in track.items:
                if not self._item_in_paint_band(item):
                    continue
                if not self._item_intersects_dirty(item, margin):
                    continue
                rect = self._item_paint_rect(item)
                if bounds is None:
                    bounds = rect
                else:
                    bounds = bounds.united(rect)
        if bounds is None:
            return None
        m = margin + _DIRTY_MARGIN_PX
        dirty = QRect(
            int(bounds.left()) - int(m),
            int(bounds.top()) - int(m),
            int(bounds.width()) + int(2 * m),
            int(bounds.height()) + int(2 * m),
        )
        return dirty.intersected(self.rect())

    def _tick_dirty_rects(
        self, margin: float
    ) -> tuple[QRect | None, QRect | None, int, int]:
        """Snapshot dirty bounds before/after motion in one margin pass."""
        pre_bounds: QRectF | None = None
        for track in self.engine.tracks:
            for item in track.items:
                if not self._item_in_paint_band(item):
                    continue
                if not self._item_intersects_dirty(item, margin):
                    continue
                rect = self._item_paint_rect(item)
                pre_bounds = rect if pre_bounds is None else pre_bounds.united(rect)

        before_visible = self.engine.visible_display_count()
        self.engine.update(dt_sec=self.last_tick_dt_sec)
        after_visible = self.engine.visible_display_count()

        post_bounds: QRectF | None = None
        for track in self.engine.tracks:
            for item in track.items:
                if not self._item_in_paint_band(item):
                    continue
                if not self._item_intersects_dirty(item, margin):
                    continue
                rect = self._item_paint_rect(item)
                post_bounds = rect if post_bounds is None else post_bounds.united(rect)

        m = margin + _DIRTY_MARGIN_PX

        def _to_qrect(bounds: QRectF | None) -> QRect | None:
            if bounds is None:
                return None
            dirty = QRect(
                int(bounds.left()) - int(m),
                int(bounds.top()) - int(m),
                int(bounds.width()) + int(2 * m),
                int(bounds.height()) + int(2 * m),
            )
            return dirty.intersected(self.rect())

        return _to_qrect(pre_bounds), _to_qrect(post_bounds), before_visible, after_visible

    def _request_paint(
        self,
        before_visible: int,
        after_visible: int,
        pre_dirty: QRect | None = None,
        post_dirty: QRect | None = None,
    ) -> None:
        dirty = pre_dirty
        if post_dirty is not None and not post_dirty.isEmpty():
            dirty = post_dirty if dirty is None else dirty.united(post_dirty)
        if dirty is not None and not dirty.isEmpty():
            self.update(dirty)
        elif before_visible > 0 or after_visible > 0:
            self.update()

    def _maybe_log_tick_profile(
        self,
        *,
        dt: float,
        margin: float,
        dirty_ms: float,
        before_visible: int,
        after_visible: int,
        current_total: int,
    ) -> None:
        if not overlay_profile_enabled():
            return
        now = time.monotonic()
        if now - self._profile_last_log_at < 1.0:
            return
        self._profile_last_log_at = now
        _overlay_logger.debug(
            "overlay_profile dt_ms=%.2f dirty_ms=%.2f visible=%d/%d total=%d margin=%.1f",
            dt * 1000.0,
            dirty_ms * 1000.0,
            after_visible,
            before_visible,
            current_total,
            margin,
        )

    def _tick(self):
        if not self.isVisible():
            return
        if not self._has_animatable_content():
            self.stop_render_loop(repaint=True)
            return

        dt = self._tick_dt_sec()
        self.last_tick_dt_sec = dt
        margin = self._motion_margin_px()
        t_dirty = time.perf_counter() if overlay_profile_enabled() else 0.0
        pre_dirty, post_dirty, before_visible, after_visible = self._tick_dirty_rects(margin)
        dirty_ms = (time.perf_counter() - t_dirty) if overlay_profile_enabled() else 0.0

        if (
            after_visible > 0
            or self.engine._accel_remaining > 0
            or before_visible > 0
            or pre_dirty is not None
            or post_dirty is not None
        ):
            self._request_paint(before_visible, after_visible, pre_dirty, post_dirty)

        self._maybe_log_tick_profile(
            dt=dt,
            margin=margin,
            dirty_ms=dirty_ms,
            before_visible=before_visible,
            after_visible=after_visible,
            current_total=self.engine.current_display_count(),
        )

        if not self._has_animatable_content():
            self.stop_render_loop(repaint=True)
            return

        self._sync_timer_interval(after_visible)

    def hideEvent(self, event):
        self.stop_render_loop()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if self.engine.running:
            self.ensure_render_loop()

    def measure_item_width(self, item):
        item.width = float(self.font_metrics.horizontalAdvance(item.content))

    def prepare_item_pixmap(self, item: DanmuItem) -> None:
        if item.width <= 0:
            self.measure_item_width(item)
        if item._pixmap is None:
            item._pixmap = self._render_item_pixmap(item)
        item._opacity_cache_bucket = None
        item._cached_opacity = None

    def _render_item_pixmap(self, item) -> QPixmap:
        w = int(item.width) + 10
        h = self.font_metrics.height() + 10
        dpr = self.devicePixelRatio()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)

        p = QPainter(pm)
        p.setFont(self.font)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        baseline_y = self.font_metrics.ascent() + 5
        text_x = 5

        path = QPainterPath()
        path.addText(text_x, baseline_y, self.font, item.content)

        outline_pen = QPen(QColor(0, 0, 0, 200))
        outline_pen.setWidth(4)
        outline_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        outline_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(outline_pen)
        p.drawPath(path)

        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(item.color)
        p.drawPath(path)
        p.end()
        return pm

    def _item_opacity(self, item) -> float:
        screen_width = self._screen_width or float(self.width())
        if screen_width <= 0:
            return 1.0

        bucket = int(item.x / _OPACITY_CACHE_BUCKET)
        cached_bucket = getattr(item, "_opacity_cache_bucket", None)
        if cached_bucket == bucket:
            cached = getattr(item, "_cached_opacity", None)
            if cached is not None:
                return cached

        enter_alpha = 1.0
        if item.x > screen_width - FADE_IN_PX:
            enter_alpha = max(0.0, min(1.0, (screen_width - item.x) / FADE_IN_PX))

        exit_alpha = 1.0
        right_edge = item.x + item.width
        if right_edge < FADE_OUT_PX:
            exit_alpha = max(0.0, min(1.0, right_edge / FADE_OUT_PX))

        opacity = min(enter_alpha, exit_alpha)
        item._opacity_cache_bucket = bucket
        item._cached_opacity = opacity
        return opacity

    def paintEvent(self, event):
        clip = event.region().boundingRect()
        drawable_h = self._drawable_height_px()
        clip = clip.intersected(QRect(0, 0, self.width(), drawable_h))
        if clip.isEmpty():
            return
        painter = QPainter(self)
        painter.setClipRect(clip)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        for track in self.engine.tracks:
            for item in track.items:
                if item._pixmap is None or not self._item_in_paint_band(item):
                    continue

                item_rect = self._item_paint_rect(item)
                if not clip.intersects(item_rect.toRect()):
                    continue

                opacity = self._item_opacity(item)
                if opacity <= 0.0:
                    continue

                painter.setOpacity(opacity)
                painter.drawPixmap(QPointF(item.x, item.y + _Y_OFFSET), item._pixmap)
        painter.setOpacity(1.0)

    def _drawable_height_px(self) -> int:
        ratio = layout_height_ratio(self.config)
        return max(1, int(round(self.engine.screen_height * ratio)))

    def show_for_screen(self, screen_index: int = 0, *, reload_tracks: bool | None = None):
        screens = QApplication.screens()
        if screen_index < len(screens):
            geo = screens[screen_index].geometry()
            layout_mode = normalize_layout_mode(self.config.get("layout_mode", "fullscreen"))
            geo_key = (
                screen_index,
                geo.x(),
                geo.y(),
                geo.width(),
                geo.height(),
                layout_mode,
            )
            geo_changed = getattr(self, "_screen_geo_key", None) != geo_key
            self._screen_geo_key = geo_key
            self.setGeometry(geo)
            self._screen_width = float(geo.width())
            self.engine.set_screen_width(self._screen_width)
            self.engine.set_screen_height(float(geo.height()))
            should_reload = reload_tracks if reload_tracks is not None else geo_changed
            if should_reload:
                self.engine.reload_tracks(preserve_visible=True)
        self._apply_font_from_config()
        self.show()
        self._apply_win32_click_through()
