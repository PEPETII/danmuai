"""Qt 透明置顶弹幕叠加层：60fps 脏区重绘 + Win32 鼠标穿透。

架构：
- DanmuOverlay 全屏透明 QWidget，DanmuEngine.update 驱动位置；本模块只负责绘制。
- 有动画/淡入淡出/加速时 16ms PreciseTimer；无内容时停表省电（needs_render_tick）。
- Win32：在 show 后对原生 HWND 叠加 WS_EX_LAYERED | WS_EX_TRANSPARENT，点击落到下层窗口。
- 淡入（右侧 FADE_IN_PX）/ 淡出（左侧 FADE_OUT_PX）分段 alpha；弹幕文本预渲染为 QPixmap 描边+填充。

调用方：DanmuApp.start() → show_for_screen + start_render_loop；engine.add_text → measure_item_width；
接近可视区时由 overlay._prepare_pixmaps_near_visible / paintEvent 延迟预渲染 QPixmap。
"""
import logging
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
    normalize_danmu_display_text,
    normalize_layout_mode,
    resolve_danmu_max_chars,
)
from app.env_config import get as get_env
from app.win32_overlay_zorder import apply_overlay_exstyles, reassert_hwnd_topmost

_FRAME_DT = 1.0 / 60.0
_INTERVAL_MS = 16
# Back-compat aliases for tests / docs
_INTERVAL_MAX_MS = _INTERVAL_MS
_INTERVAL_IDLE_MS = _INTERVAL_MS
_INTERVAL_MED_MS = _INTERVAL_MS
_DT_CAP_SEC = 0.1
_OPACITY_CACHE_BUCKET = 4.0
_DIRTY_MARGIN_PX = 12
_PRERENDER_AHEAD_PX = FADE_IN_PX + 80.0
_FAST_DANMU_RENDER_MIN_LEN = 8
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
_overlay_logger = logging.getLogger("danmu.overlay")
_overlay_profile_flag: bool | None = None


def overlay_profile_enabled() -> bool:
    global _overlay_profile_flag
    if _overlay_profile_flag is None:
        value = get_env("DANMU_OVERLAY_PROFILE").strip().lower()
        _overlay_profile_flag = value in ("1", "true", "yes", "on")
    return _overlay_profile_flag


def _use_fast_danmu_render(content: str) -> bool:
    """长文本/CJK/emoji 走 drawText 描边，避免 QPainterPath.addText 阻塞主线程。

    CJK 和 emoji 字符即使文本较短，QPainterPath.addText 仍然很慢，
    因此对这些字符始终走 fast 路径。
    """
    if len(content) >= _FAST_DANMU_RENDER_MIN_LEN:
        return True
    # S-021: short CJK/emoji strings still hit the slow QPainterPath path by length alone.
    return any(ord(ch) > 127 for ch in content)


def _paint_danmu_text(
    painter: QPainter,
    *,
    content: str,
    font: QFont,
    color: QColor,
    text_x: int,
    baseline_y: int,
    fast: bool,
) -> None:
    if fast:
        outline_pen = QPen(QColor(0, 0, 0, 200))
        for dx, dy in _FAST_OUTLINE_OFFSETS:
            painter.setPen(outline_pen)
            painter.drawText(text_x + dx, baseline_y + dy, content)
        painter.setPen(QPen(color))
        painter.drawText(text_x, baseline_y, content)
        return

    path = QPainterPath()
    path.addText(text_x, baseline_y, font, content)
    outline_pen = QPen(QColor(0, 0, 0, 200))
    outline_pen.setWidth(4)
    outline_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    outline_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(outline_pen)
    painter.drawPath(path)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    painter.drawPath(path)


class DanmuOverlay(QWidget):
    """透明置顶弹幕渲染适配层：测量宽度、预渲染 pixmap、60fps 脏区绘制。

    不调度 AI、不消费回复队列、不写 ConfigStore；_target_interval_ms 在无动画或不可见时返回 0 以停表省电。
    """

    def __init__(self, config: ConfigStore, engine: DanmuEngine):
        super().__init__()
        self.config = config
        self.engine = engine

        # Frameless+TopMost+Tool：无边框置顶且不占任务栏；BypassWindowManagerHint 减少 WM 抢焦点
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
        self._sync_applied_display_settings_markers()

        self._screen_width: float = 0.0
        self._timer_interval_ms = _INTERVAL_MS
        self._tick_clock = QElapsedTimer()
        self._last_tick_valid = False
        self.last_tick_dt_sec: float = _FRAME_DT
        self._profile_last_log_at: float = 0.0
        self._last_layout_ratio: float = layout_height_ratio(config)
        self._clear_drawable_on_next_paint: bool = False
        # BUG-004: 连续 SetWindowPos 失败计数；成功即清零，达 3 次触发兼容性告警
        self._topmost_fail_streak: int = 0
        # W-COMPAT-SCREEN-RECOVERY-001: screens 为空或 geometry 无效时供 mixin 推送 Web 告警
        self._overlay_screen_unavailable: bool = False
        # 待渲染队列：只含 _pixmap is None 且尚未过屏的 item，避免每帧 O(n) 全量扫描
        self._pending_render: list[DanmuItem] = []

        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.timer.timeout.connect(self._tick)

    def _config_font_size(self) -> int:
        from app.config_defaults import DEFAULT_FONT_SIZE

        size = self.config.get_int("font_size", DEFAULT_FONT_SIZE)
        return max(12, min(72, size))

    def _config_danmu_font_family(self) -> str:
        from app.config_defaults import DEFAULT_DANMU_FONT_FAMILY

        raw = self.config.get("danmu_font_family", DEFAULT_DANMU_FONT_FAMILY) or DEFAULT_DANMU_FONT_FAMILY
        return str(raw).strip() or DEFAULT_DANMU_FONT_FAMILY

    def _sync_applied_display_settings_markers(self) -> None:
        self._applied_font_size = self._config_font_size()
        self._applied_danmu_max_chars = resolve_danmu_max_chars(self.config)
        self._applied_danmu_font_family = self._config_danmu_font_family()
        self._applied_danmu_font_bold = str(
            self.config.get("danmu_font_bold", "1") or "1"
        ).strip().lower() not in ("0", "false", "no")

    def display_settings_dirty(self) -> bool:
        """True when font_size or danmu_max_chars in config differs from last apply."""
        if self._config_font_size() != getattr(self, "_applied_font_size", -1):
            return True
        if resolve_danmu_max_chars(self.config) != getattr(
            self, "_applied_danmu_max_chars", -1
        ):
            return True
        if self._config_danmu_font_family() != getattr(self, "_applied_danmu_font_family", ""):
            return True
        current_bold = str(
            self.config.get("danmu_font_bold", "1") or "1"
        ).strip().lower() not in ("0", "false", "no")
        if current_bold != getattr(self, "_applied_danmu_font_bold", True):
            return True
        return False

    def apply_display_settings(self) -> None:
        """Re-read font_size / danmu_max_chars and rebuild on-screen item metrics and pixmaps."""
        self._apply_font_from_config()
        # 重置待渲染队列：apply 后所有 item 都需要重新渲染
        self._pending_render.clear()
        for track in self.engine.tracks:
            for item in track.items:
                item.content = normalize_danmu_display_text(item.content, self.config)
                item._pixmap = None
                item._opacity_cache_bucket = None
                item._cached_opacity = None
                self.measure_item_width(item)
                self.prepare_item_pixmap(item)
                self.engine._refresh_item_visibility(item)
                self.engine._update_item_motion_tick_state(item)
        self._sync_applied_display_settings_markers()
        if self.isVisible():
            dirty = self._union_dirty_rect(self._motion_margin_px())
            if dirty is not None:
                self.update(dirty)
            self.ensure_render_loop()

    def _apply_font_from_config(self) -> None:
        family = self._config_danmu_font_family()
        size = self._config_font_size()
        bold = str(self.config.get("danmu_font_bold", "1") or "1").strip().lower() not in (
            "0",
            "false",
            "no",
        )
        self.font = QFont(family, size)
        self.font.setBold(bold)
        self.font_metrics = QFontMetrics(self.font)

    def _apply_win32_click_through(self):
        """Win32 原生层点击穿透：在 Qt 已设 WA_TransparentForMouseEvents 后再 OR 扩展样式位。

        WS_EX_LAYERED：分层窗口，与 WA_TranslucentBackground 配合 alpha 合成。
        WS_EX_TRANSPARENT：命中测试穿透，鼠标事件交给下层游戏/桌面；缺一则可能挡操作。
        须在 show() 后调用（winId() 有效）。仅 win32 执行。
        """
        if sys.platform != "win32":
            return
        apply_overlay_exstyles(int(self.winId()), click_through=True)

    def reassert_topmost_zorder(self) -> bool:
        """Win32：Alt+Tab / 其它置顶窗抢栈后，用 SetWindowPos 恢复 HWND_TOPMOST（不抢焦点）。

        返回 True 表示成功或无需操作；False 表示 SetWindowPos 失败。连续 3 次失败
        记 warning 日志，调用方（_update_overlay_compat_warning）据此推送兼容性告警。
        """
        if not self.isVisible():
            return True
        self.raise_()
        try:
            hwnd = int(self.winId())
        except (RuntimeError, ValueError, TypeError):
            return True
        success = reassert_hwnd_topmost(hwnd)
        if success:
            self._topmost_fail_streak = 0
        else:
            self._topmost_fail_streak += 1
            if self._topmost_fail_streak == 3:
                _overlay_logger.warning(
                    "topmost reassert failed %d times; overlay may be blocked "
                    "by exclusive fullscreen or another topmost window",
                    self._topmost_fail_streak,
                )
        return success

    def _has_animatable_content(self) -> bool:
        """是否仍需 60fps：引擎内加速剩余、淡入淡出区或屏上可见条任一成立。"""
        return self.engine.needs_render_tick()

    def start_render_loop(self) -> None:
        """启动 16ms QTimer 渲染循环；不可见时跳过。"""
        if not self.isVisible():
            return
        self._last_tick_valid = False
        if not self.timer.isActive():
            self.timer.start(self._timer_interval_ms)
        self._tick()

    def stop_render_loop(self, *, repaint: bool = False) -> None:
        """停止 QTimer；repaint=True 时刷新一帧清除残影。"""
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
        return QRectF(item.x, item.y, w, h)

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

    def _prepare_pixmaps_near_visible(self) -> None:
        """Lazy pixmap: pre-render items approaching the visible band, not at add_text time.

        优先遍历 _pending_render 队列（O(待渲染)）；队列为空时回退全量扫描（兜底直接入轨的 item）。
        """
        sw = self._screen_width or float(self.width())
        if sw <= 0:
            return
        threshold = sw + FADE_IN_PX + _PRERENDER_AHEAD_PX

        if self._pending_render:
            still_pending: list[DanmuItem] = []
            for item in self._pending_render:
                if item._pixmap is not None:
                    continue
                if item.x + item.width <= 0:
                    continue
                if item.x < threshold:
                    self.prepare_item_pixmap(item)
                    continue
                still_pending.append(item)
            self._pending_render = still_pending
            return

        # 兜底：队列为空时全量扫描（reload_tracks / 测试直接入轨等场景）
        for track in self.engine.tracks:
            for item in track.items:
                if item._pixmap is not None:
                    continue
                if item.x >= threshold:
                    continue
                if item.x + item.width <= 0:
                    continue
                self.prepare_item_pixmap(item)

    def _collect_dirty_candidates_and_bounds(
        self, margin: float
    ) -> tuple[list[DanmuItem], QRectF | None]:
        """One pass: paint-band + dirty-margin filter, candidates list, pre-motion bounds."""
        candidates: list[DanmuItem] = []
        pre_bounds: QRectF | None = None
        for track in self.engine.tracks:
            for item in track.items:
                if not self._item_in_paint_band(item):
                    continue
                if not self._item_intersects_dirty(item, margin):
                    continue
                candidates.append(item)
                rect = self._item_paint_rect(item)
                pre_bounds = rect if pre_bounds is None else pre_bounds.united(rect)
        return candidates, pre_bounds

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
        """Snapshot dirty bounds before/after motion; pre_bounds merged into candidate collect."""
        candidates, pre_bounds = self._collect_dirty_candidates_and_bounds(margin)

        before_visible = self.engine.visible_display_count()
        self.engine.update(dt_sec=self.last_tick_dt_sec)
        after_visible = self.engine.visible_display_count()

        post_bounds: QRectF | None = None
        for item in candidates:
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
        """单帧：算 dt → 运动前/后脏区并集 → engine.update → 仅 update(dirty rect)。

        脏区在位移 margin 内 union，避免长弹幕拖影；屏外条目仍由 engine 更新但不 paint。
        无 animatable 内容时 stop_render_loop，避免空转 QTimer。
        """
        if not self.isVisible():
            return
        if not self._has_animatable_content():
            self.stop_render_loop(repaint=True)
            return

        dt = self._tick_dt_sec()
        self.last_tick_dt_sec = dt
        margin = self._motion_margin_px()
        self._prepare_pixmaps_near_visible()
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
        self.reassert_topmost_zorder()
        # HWND 变化后须重设 Win32 穿透，不能仅依赖 show_for_screen 一次性设置。
        self._apply_win32_click_through()
        if self.engine.running:
            self.ensure_render_loop()

    def measure_item_width(self, item):
        item.width = float(self.font_metrics.horizontalAdvance(item.content))

    def prepare_item_pixmap(self, item: DanmuItem) -> None:
        """预渲染弹幕为带描边的 QPixmap，paintEvent 只 drawPixmap + 透明度，减轻每帧文本布局。"""
        if item.width <= 0:
            self.measure_item_width(item)
        if item._pixmap is None:
            fast = _use_fast_danmu_render(item.content)
            item._pixmap = self._render_item_pixmap(item, fast=fast)
        item._opacity_cache_bucket = None
        item._cached_opacity = None

    def _render_item_pixmap(self, item, *, fast: bool | None = None) -> QPixmap:
        if fast is None:
            fast = _use_fast_danmu_render(item.content)
        w = int(item.width) + 10
        h = self.font_metrics.height() + 10
        dpr = self.devicePixelRatio()
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.GlobalColor.transparent)

        painter = QPainter(pm)
        painter.setFont(self.font)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        baseline_y = self.font_metrics.ascent() + 5
        text_x = 5
        _paint_danmu_text(
            painter,
            content=item.content,
            font=self.font,
            color=item.color,
            text_x=text_x,
            baseline_y=baseline_y,
            fast=fast,
        )
        painter.end()
        return pm

    def _item_opacity(self, item) -> float:
        """右侧 FADE_IN_PX 渐入、左侧 FADE_OUT_PX 渐出；取 min 并分桶缓存避免每帧重算。"""
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

    def _global_opacity_factor(self) -> float:
        """Config opacity 0–100% → draw alpha multiplier (100 = fully opaque)."""
        pct = self.config.get_int("opacity", 100)
        return max(0.0, min(1.0, pct / 100.0))

    def paintEvent(self, event):
        """Qt 绘制回调：CompositionMode_Clear 清除残影（layout_mode 缩小时），底→顶遍历轨道绘制弹幕。

        clip 区域与 _drawable_height_px 交集限定绘制范围；_clear_drawable_on_next_paint 标记
        用于 layout_mode 切换后首帧全清，避免旧弹幕残影。
        """
        clip = event.region().boundingRect()
        drawable_h = self._drawable_height_px()
        clip = clip.intersected(QRect(0, 0, self.width(), drawable_h))
        if clip.isEmpty():
            return
        painter = QPainter(self)
        painter.setClipRect(clip)
        if self._clear_drawable_on_next_paint:
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(clip, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            self._clear_drawable_on_next_paint = False
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        for track in self.engine.tracks:
            for item in track.items:
                if not self._item_in_paint_band(item):
                    continue
                if item._pixmap is None:
                    self.prepare_item_pixmap(item)

                item_rect = self._item_paint_rect(item)
                if not clip.intersects(item_rect.toRect()):
                    continue

                opacity = self._item_opacity(item) * self._global_opacity_factor()
                if opacity <= 0.0:
                    continue

                painter.setOpacity(opacity)
                painter.drawPixmap(QPointF(item.x, item.y), item._pixmap)
        painter.setOpacity(1.0)

    def _drawable_height_px(self) -> int:
        ratio = layout_height_ratio(self.config)
        return max(1, int(round(self.engine.screen_height * ratio)))

    def show_for_screen(self, screen_index: int = 0, *, reload_tracks: bool | None = None):
        """对齐指定显示器 geometry，同步 engine 屏宽高；几何或 layout 变时 reload_tracks。

        reload_tracks=None 时仅在 geo_key 变化时重载轨道，避免配置刷新时清空可见弹幕。
        show 后必须 _apply_win32_click_through，否则 Windows 上可能拦截点击。
        """
        screens = QApplication.screens()
        if not screens:
            self._overlay_screen_unavailable = True
            _overlay_logger.warning(
                "show_for_screen: no screens available; overlay stays hidden"
            )
            return
        screen_index = max(0, min(int(screen_index), len(screens) - 1))
        if screen_index < len(screens):
            geo = screens[screen_index].geometry()
            if geo.width() <= 0 or geo.height() <= 0:
                _overlay_logger.warning(
                    "show_for_screen: screen %d has invalid geometry %dx%d; "
                    "falling back to primary screen",
                    screen_index, geo.width(), geo.height(),
                )
                if screen_index != 0:
                    screen_index = 0
                    geo = screens[0].geometry()
                if geo.width() <= 0 or geo.height() <= 0:
                    self._overlay_screen_unavailable = True
                    _overlay_logger.warning(
                        "show_for_screen: primary screen also invalid %dx%d; "
                        "overlay stays hidden",
                        geo.width(), geo.height(),
                    )
                    return
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
            old_ratio = self._last_layout_ratio
            new_ratio = layout_height_ratio(self.config)
            shrink = new_ratio < old_ratio - 1e-9
            should_reload = reload_tracks if reload_tracks is not None else geo_changed
            if should_reload:
                self.engine.reload_tracks(
                    preserve_visible=True,
                    clip_to_drawable=shrink,
                )
                if shrink:
                    previous_h = int(round(float(geo.height()) * old_ratio))
                    new_h = self._drawable_height_px()
                    repaint_h = max(previous_h, new_h, 1)
                    self._clear_drawable_on_next_paint = True
                    self.update(QRect(0, 0, self.width(), repaint_h))
            self._last_layout_ratio = new_ratio
        self._overlay_screen_unavailable = False
        self._apply_font_from_config()
        self.show()
        self._apply_win32_click_through()
