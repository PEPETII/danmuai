"""Minimal Win32 helpers for topmost / click-through (POC only)."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

if sys.platform == "win32":
    _GWL_EXSTYLE = -20
    _WS_EX_LAYERED = 0x00080000
    _WS_EX_TRANSPARENT = 0x00000020
    _WS_EX_NOACTIVATE = 0x08000000
    _HWND_TOPMOST = wintypes.HWND(-1)
    _HWND_NOTOPMOST = wintypes.HWND(-2)
    _SWP_NOMOVE = 0x0002
    _SWP_NOSIZE = 0x0001
    _SWP_NOACTIVATE = 0x0010
    _SWP_SHOWWINDOW = 0x0040
    _SetWindowPos = ctypes.windll.user32.SetWindowPos
    try:
        _SetWindowLong = ctypes.windll.user32.SetWindowLongPtrW
        _GetWindowLong = ctypes.windll.user32.GetWindowLongPtrW
    except AttributeError:
        _SetWindowLong = ctypes.windll.user32.SetWindowLongW
        _GetWindowLong = ctypes.windll.user32.GetWindowLongW


def apply_exstyles(hwnd: int, *, click_through: bool) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    ex_style = _GetWindowLong(hwnd, _GWL_EXSTYLE)
    if click_through:
        new_style = ex_style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT
    else:
        new_style = (ex_style | _WS_EX_LAYERED) & ~_WS_EX_TRANSPARENT
    _SetWindowLong(hwnd, _GWL_EXSTYLE, new_style)


def reassert_topmost(hwnd: int, *, topmost: bool = True) -> bool:
    if sys.platform != "win32" or not hwnd:
        return True
    insert_after = _HWND_TOPMOST if topmost else _HWND_NOTOPMOST
    result = _SetWindowPos(
        hwnd,
        insert_after,
        0,
        0,
        0,
        0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
    )
    return bool(result)
