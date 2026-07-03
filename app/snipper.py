"""区域裁剪入口：屏幕/窗口截图与坐标转换。

坐标系统：region_w/h > 0 时按**屏内相对坐标**裁剪（不是绝对屏幕坐标）。
与 POST/GET /api/capture-region/* 配合：Web 端框选区域后写入 config，本模块读取并裁剪。

W-PERF-HIGH-001：主线程 ``build_capture_plan`` 解析屏几何；worker 线程 ``execute_capture`` 执行 grab。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapturePlan:
    """Immutable capture target resolved on the main thread."""

    mode: str  # "screen" | "window"
    screen_index: int
    grab_x: int
    grab_y: int
    grab_w: int
    grab_h: int
    hwnd: int = 0


def resolve_screen_index_with_meta(config=None) -> tuple[int, bool]:
    """返回 (有效 screen_index, 是否因屏数变化被 clamp)。"""
    screens = QApplication.screens()
    if not screens:
        return 0, False
    raw = config.get_int("screen_index", 0) if config is not None else 0
    clamped = max(0, min(raw, len(screens) - 1))
    return clamped, raw != clamped


def resolve_screen_index(config=None) -> int:
    index, _ = resolve_screen_index_with_meta(config)
    return index


def resolve_capture_rect(config, screen_geometry) -> tuple[int, int, int, int]:
    """Return absolute desktop coordinates for the configured capture region."""
    full = (
        screen_geometry.x(),
        screen_geometry.y(),
        screen_geometry.width(),
        screen_geometry.height(),
    )
    if config is None:
        return full

    try:
        if hasattr(config, "get_region"):
            rel_x, rel_y, width, height = config.get_region()
        else:
            rel_x = config.get_int("region_x", 0)
            rel_y = config.get_int("region_y", 0)
            width = config.get_int("region_w", 0)
            height = config.get_int("region_h", 0)
    except (AttributeError, TypeError, ValueError) as exc:
        logger.info("识图区域回退全屏: reason=region_read_error error=%s", exc)
        return full

    try:
        rel_x = int(rel_x)
        rel_y = int(rel_y)
        width = int(width)
        height = int(height)
    except (TypeError, ValueError):
        logger.info(
            "识图区域回退全屏: reason=invalid_region_type region_x=%r region_y=%r "
            "region_w=%r region_h=%r",
            rel_x,
            rel_y,
            width,
            height,
        )
        return full

    if width <= 0 or height <= 0:
        logger.info(
            "识图区域回退全屏: reason=non_positive_size region_x=%s region_y=%s "
            "region_w=%s region_h=%s",
            rel_x,
            rel_y,
            width,
            height,
        )
        return full

    left = max(0, rel_x)
    top = max(0, rel_y)
    right = min(screen_geometry.width(), rel_x + width)
    bottom = min(screen_geometry.height(), rel_y + height)
    if right <= left or bottom <= top:
        logger.info(
            "识图区域回退全屏: reason=empty_intersection region_x=%s region_y=%s "
            "region_w=%s region_h=%s screen_w=%s screen_h=%s",
            rel_x,
            rel_y,
            width,
            height,
            screen_geometry.width(),
            screen_geometry.height(),
        )
        return full

    return (
        screen_geometry.x() + left,
        screen_geometry.y() + top,
        right - left,
        bottom - top,
    )


def grab_rect_screen_local(config, screen_geometry) -> tuple[int, int, int, int]:
    """Map virtual-desktop capture rect to QScreen.grabWindow-local x/y."""
    abs_x, abs_y, width, height = resolve_capture_rect(config, screen_geometry)
    return (
        abs_x - screen_geometry.x(),
        abs_y - screen_geometry.y(),
        width,
        height,
    )


def build_capture_plan(config) -> CapturePlan | None:
    """Resolve capture geometry on the main thread (no pixel grab)."""
    screens = QApplication.screens()
    if not screens:
        return None
    screen_index = resolve_screen_index(config)
    if screen_index >= len(screens):
        screen_index = 0
    geo = screens[screen_index].geometry()
    grab_x, grab_y, grab_w, grab_h = grab_rect_screen_local(config, geo)
    mode = config.get("capture_mode", "screen") if config is not None else "screen"
    hwnd = 0
    if mode == "window" and config is not None:
        hwnd = config.get_int("capture_window_hwnd", 0)
    return CapturePlan(
        mode=mode,
        screen_index=screen_index,
        grab_x=grab_x,
        grab_y=grab_y,
        grab_w=grab_w,
        grab_h=grab_h,
        hwnd=hwnd,
    )


def _grab_screen_from_plan(plan: CapturePlan) -> QPixmap | None:
    screens = QApplication.screens()
    if not screens or plan.screen_index >= len(screens):
        return None
    target_screen = screens[plan.screen_index]
    return target_screen.grabWindow(
        0, plan.grab_x, plan.grab_y, plan.grab_w, plan.grab_h
    )


def _grab_window_by_hwnd(hwnd: int) -> tuple[QPixmap | None, str]:
    """截取选定窗口的客户区。返回 (pixmap, reason) 用于诊断。"""
    if hwnd <= 0:
        return None, "hwnd_not_set"
    from app.window_capture import grab_window

    pixmap = grab_window(hwnd)
    if pixmap is None:
        return None, "grab_returned_none"
    return pixmap, ""


def execute_capture(plan: CapturePlan) -> QPixmap | None:
    """Execute pixel grab on a capture worker thread."""
    if plan.mode == "window" and plan.hwnd > 0:
        pixmap, reason = _grab_window_by_hwnd(plan.hwnd)
        if pixmap is not None and not pixmap.isNull():
            return pixmap
        if reason == "":
            reason = "null_pixmap"
        logger.info(
            "窗口捕获失败，回退到屏幕捕获 hwnd=%s reason=%s",
            plan.hwnd,
            reason,
        )
    return _grab_screen_from_plan(plan)


class ScreenCapturer:
    def __init__(self, config=None):
        self.config = config
        self._last_logged_mode: str | None = None
        self._fallback_count: int = 0

    def build_plan(self) -> CapturePlan | None:
        if self.config is None:
            return None
        return build_capture_plan(self.config)

    def grab(self) -> QPixmap | None:
        plan = self.build_plan()
        if plan is None:
            return None
        mode = plan.mode
        if mode == "window":
            hwnd = plan.hwnd
            pixmap, reason = _grab_window_by_hwnd(hwnd)
            if pixmap is not None and not pixmap.isNull():
                if self._last_logged_mode != f"window:{hwnd}":
                    self._last_logged_mode = f"window:{hwnd}"
                    self._fallback_count = 0
                    logger.info(
                        "捕获模式: window hwnd=%s size=%sx%s",
                        hwnd,
                        pixmap.width(),
                        pixmap.height(),
                    )
                return pixmap
            if reason == "":
                reason = "null_pixmap"
            self._fallback_count += 1
            if self._fallback_count <= 3 or self._fallback_count % 20 == 0:
                logger.info(
                    "窗口捕获失败，回退到屏幕捕获 hwnd=%s reason=%s fallback_count=%d",
                    hwnd,
                    reason,
                    self._fallback_count,
                )
            self._last_logged_mode = "screen:fallback"
            return _grab_screen_from_plan(plan)
        if self._last_logged_mode != "screen":
            self._last_logged_mode = "screen"
            self._fallback_count = 0
            logger.info("捕获模式: screen")
        return _grab_screen_from_plan(plan)
