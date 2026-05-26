from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication


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
    except Exception:
        return full

    try:
        rel_x = int(rel_x)
        rel_y = int(rel_y)
        width = int(width)
        height = int(height)
    except (TypeError, ValueError):
        return full

    if width <= 0 or height <= 0:
        return full

    left = max(0, rel_x)
    top = max(0, rel_y)
    right = min(screen_geometry.width(), rel_x + width)
    bottom = min(screen_geometry.height(), rel_y + height)
    if right <= left or bottom <= top:
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


class ScreenCapturer:
    def __init__(self, config=None):
        self.config = config

    def grab(self) -> QPixmap | None:
        screens = QApplication.screens()
        if not screens:
            return None

        target_screen = screens[resolve_screen_index(self.config)]
        geo = target_screen.geometry()
        x, y, width, height = grab_rect_screen_local(self.config, geo)
        pixmap = target_screen.grabWindow(0, x, y, width, height)
        if pixmap is None:
            return None
        if hasattr(pixmap, "isNull") and pixmap.isNull():
            return None
        return pixmap
