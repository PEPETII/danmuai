import logging

from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

logger = logging.getLogger(__name__)


def resolve_screen_index(config=None) -> int:
    screens = QApplication.screens()
    if not screens:
        return 0
    raw = config.get_int("screen_index", 0) if config is not None else 0
    return max(0, min(raw, len(screens) - 1))


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
    except Exception as exc:
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


def _grab_screen(config) -> QPixmap | None:
    """截取选定显示器（全屏或子区域）。"""
    screens = QApplication.screens()
    if not screens:
        return None
    target_screen = screens[resolve_screen_index(config)]
    geo = target_screen.geometry()
    x, y, width, height = grab_rect_screen_local(config, geo)
    return target_screen.grabWindow(0, x, y, width, height)


def _grab_window(config) -> tuple[QPixmap | None, str]:
    """截取选定窗口的客户区。返回 (pixmap, reason) 用于诊断。"""
    hwnd = config.get_int("capture_window_hwnd", 0)
    if hwnd <= 0:
        return None, "hwnd_not_set"
    from app.window_capture import grab_window
    pixmap = grab_window(hwnd)
    if pixmap is None:
        return None, "grab_returned_none"
    return pixmap, ""


class ScreenCapturer:
    def __init__(self, config=None):
        self.config = config
        self._last_logged_mode: str | None = None
        self._fallback_count: int = 0

    def grab(self) -> QPixmap | None:
        mode = self.config.get("capture_mode", "screen") if self.config else "screen"
        if mode == "window":
            hwnd = self.config.get_int("capture_window_hwnd", 0) if self.config else 0
            pixmap, reason = _grab_window(self.config)
            if pixmap is not None and not pixmap.isNull():
                if self._last_logged_mode != f"window:{hwnd}":
                    self._last_logged_mode = f"window:{hwnd}"
                    self._fallback_count = 0
                    logger.info("捕获模式: window hwnd=%s size=%sx%s", hwnd, pixmap.width(), pixmap.height())
                return pixmap
            if reason == "":
                reason = "null_pixmap"
            self._fallback_count += 1
            if self._fallback_count <= 3 or self._fallback_count % 20 == 0:
                logger.info(
                    "窗口捕获失败，回退到屏幕捕获 hwnd=%s reason=%s fallback_count=%d",
                    hwnd, reason, self._fallback_count,
                )
            self._last_logged_mode = "screen:fallback"
            return _grab_screen(self.config)
        if self._last_logged_mode != "screen":
            self._last_logged_mode = "screen"
            self._fallback_count = 0
            logger.info("捕获模式: screen")
        return _grab_screen(self.config)
