"""Pure helpers for Live2D desktop window interaction."""

from __future__ import annotations

from PyQt6.QtCore import QPoint


def compute_window_drag_target(
    origin_global: QPoint,
    origin_window: QPoint,
    current_global: QPoint,
) -> QPoint:
    """Map a stable global drag delta onto the window position captured at press."""

    return origin_window + (current_global - origin_global)


__all__ = ["compute_window_drag_target"]
