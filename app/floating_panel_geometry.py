"""Floating panel geometry shared by the WebView and QPainter paths."""

from __future__ import annotations

from typing import Any


def optional_panel_position(config: Any) -> tuple[int, int] | None:
    """Read a saved absolute origin, preserving valid zero/negative values."""
    values: list[int] = []
    for key in ("floating_panel_x", "floating_panel_y"):
        raw = config.get(key, "")
        text = str(raw or "").strip().lower()
        if not text or text in {"null", "none"}:
            return None
        try:
            values.append(int(text))
        except (TypeError, ValueError):
            return None
    return values[0], values[1]


def _screen_rect(screen: Any, *, use_available_geometry: bool) -> tuple[int, int, int, int]:
    getter = getattr(screen, "availableGeometry", None) if use_available_geometry else None
    if not callable(getter):
        getter = getattr(screen, "geometry")
    rect = getter()
    x = int(rect.x())
    y = int(rect.y())
    width = max(0, int(rect.width()))
    height = max(0, int(rect.height()))
    if (width <= 0 or height <= 0) and use_available_geometry:
        fallback = getattr(screen, "geometry", None)
        if callable(fallback):
            rect = fallback()
            x = int(rect.x())
            y = int(rect.y())
            width = max(0, int(rect.width()))
            height = max(0, int(rect.height()))
    return x, y, width, height


def _intersection_area(
    left: int,
    top: int,
    right: int,
    bottom: int,
    screen_rect: tuple[int, int, int, int],
) -> int:
    sx, sy, sw, sh = screen_rect
    overlap_w = max(0, min(right, sx + sw) - max(left, sx))
    overlap_h = max(0, min(bottom, sy + sh) - max(top, sy))
    return overlap_w * overlap_h


def compute_panel_geometry(
    screens: list[Any],
    *,
    config: Any,
    width: int,
    x_offset: int,
    y_offset: int,
    preferred_screen_index: int,
    use_available_geometry: bool,
    fallback_height: int = 600,
) -> tuple[int, int, int, int]:
    """Return ``(width, height, x, y)`` with saved-position recovery.

    Coordinates are Qt/pywebview logical coordinates.  A saved origin selects
    the monitor it overlaps; a removed/off-screen monitor falls back to the
    preferred screen and clamps the panel wholly inside its usable bounds.
    """
    width = max(200, min(800, int(width)))
    x_offset = max(0, min(400, int(x_offset)))
    y_offset = max(0, min(400, int(y_offset)))
    if not screens:
        saved = optional_panel_position(config)
        x, y = saved if saved is not None else (x_offset, y_offset)
        return width, max(160, int(fallback_height)), x, y

    rects = [
        _screen_rect(screen, use_available_geometry=use_available_geometry)
        for screen in screens
    ]
    valid_rects = [rect for rect in rects if rect[2] > 0 and rect[3] > 0]
    if not valid_rects:
        saved = optional_panel_position(config)
        x, y = saved if saved is not None else (x_offset, y_offset)
        return width, max(160, int(fallback_height)), x, y

    preferred = max(0, min(int(preferred_screen_index), len(rects) - 1))
    selected_index = preferred
    if rects[selected_index][2] <= 0 or rects[selected_index][3] <= 0:
        selected_index = next(
            index
            for index, rect in enumerate(rects)
            if rect[2] > 0 and rect[3] > 0
        )
    saved = optional_panel_position(config)
    if saved is not None:
        saved_x, saved_y = saved
        best_area = 0
        for index, rect in enumerate(rects):
            sx, sy, sw, sh = rect
            if sw <= 0 or sh <= 0:
                continue
            panel_height = max(160, sh - y_offset * 2)
            area = _intersection_area(
                saved_x,
                saved_y,
                saved_x + width,
                saved_y + panel_height,
                rect,
            )
            if area > best_area:
                best_area = area
                selected_index = index

    sx, sy, sw, sh = rects[selected_index]
    panel_height = max(160, sh - y_offset * 2)
    if saved is None:
        x = sx + sw - width - x_offset
        y = sy + y_offset
    else:
        x, y = saved
    max_x = max(sx, sx + sw - width)
    max_y = max(sy, sy + sh - panel_height)
    x = max(sx, min(int(x), max_x))
    y = max(sy, min(int(y), max_y))
    return width, panel_height, x, y
