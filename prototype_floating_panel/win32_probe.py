"""Win32 探针：读取/设置窗口 exstyle、HWND_TOPMOST、DPI、命中测试。

仅用于最小验证原型，不进 production。
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

if sys.platform == "win32":
    _GWL_EXSTYLE = -20
    _GWL_STYLE = -16
    _WS_EX_LAYERED = 0x00080000
    _WS_EX_TRANSPARENT = 0x00000020
    _WS_EX_NOACTIVATE = 0x08000000
    _WS_CAPTION = 0x00C00000
    _HWND_TOPMOST = wintypes.HWND(-1)
    _SWP_NOMOVE = 0x0002
    _SWP_NOSIZE = 0x0001
    _SWP_NOACTIVATE = 0x0010
    _SWP_SHOWWINDOW = 0x0040

    try:
        _SetWindowLong = ctypes.windll.user32.SetWindowLongPtrW
        _GetWindowLong = ctypes.windll.user32.GetWindowLongPtrW
    except AttributeError:
        _SetWindowLong = ctypes.windll.user32.SetWindowLongW
        _GetWindowLong = ctypes.windll.user32.GetWindowLongW

    _SetWindowPos = ctypes.windll.user32.SetWindowPos
    _GetDpiForWindow = ctypes.windll.user32.GetDpiForWindow
    _GetDpiForWindow.restype = ctypes.c_uint
    _GetDpiForWindow.argtypes = [wintypes.HWND]
    _GetWindowRect = ctypes.windll.user32.GetWindowRect
    _GetForegroundWindow = ctypes.windll.user32.GetForegroundWindow
    _IsTopLevelWindow = ctypes.windll.user32.IsTopLevelWindow


def get_exstyle(hwnd: int) -> int:
    if sys.platform != "win32" or not hwnd:
        return -1
    return int(_GetWindowLong(hwnd, _GWL_EXSTYLE))


def get_style(hwnd: int) -> int:
    if sys.platform != "win32" or not hwnd:
        return -1
    return int(_GetWindowLong(hwnd, _GWL_STYLE))


def has_layered(hwnd: int) -> bool:
    return bool(get_exstyle(hwnd) & _WS_EX_LAYERED)


def has_transparent(hwnd: int) -> bool:
    return bool(get_exstyle(hwnd) & _WS_EX_TRANSPARENT)


def has_noactivate(hwnd: int) -> bool:
    return bool(get_exstyle(hwnd) & _WS_EX_NOACTIVATE)


def has_caption(hwnd: int) -> bool:
    return bool(get_style(hwnd) & _WS_CAPTION)


def apply_click_through(hwnd: int) -> int:
    """设置 WS_EX_LAYERED | WS_EX_TRANSPARENT，返回新 exstyle。"""
    if sys.platform != "win32" or not hwnd:
        return -1
    ex = get_exstyle(hwnd)
    new_ex = ex | _WS_EX_LAYERED | _WS_EX_TRANSPARENT
    _SetWindowLong(hwnd, _GWL_EXSTYLE, new_ex)
    return new_ex


def strip_click_through(hwnd: int) -> int:
    """移除 WS_EX_TRANSPARENT（保留 LAYERED），返回新 exstyle。"""
    if sys.platform != "win32" or not hwnd:
        return -1
    ex = get_exstyle(hwnd)
    new_ex = (ex | _WS_EX_LAYERED) & ~_WS_EX_TRANSPARENT
    _SetWindowLong(hwnd, _GWL_EXSTYLE, new_ex)
    return new_ex


def set_topmost(hwnd: int) -> bool:
    if sys.platform != "win32" or not hwnd:
        return False
    return bool(_SetWindowPos(
        hwnd, _HWND_TOPMOST, 0, 0, 0, 0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
    ))


def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if sys.platform != "win32" or not hwnd:
        return None

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]

    rect = _RECT()
    if not _GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))


def get_dpi(hwnd: int) -> int:
    if sys.platform != "win32" or not hwnd:
        return -1
    return int(_GetDpiForWindow(hwnd))


def get_foreground() -> int:
    if sys.platform != "win32":
        return 0
    return int(_GetForegroundWindow())


# 用于 WindowFromPoint 测试 click-through
class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


_WindowFromPoint = ctypes.windll.user32.WindowFromPoint
_WindowFromPoint.restype = wintypes.HWND
_WindowFromPoint.argtypes = [_POINT]


def window_from_point(x: int, y: int) -> int:
    """返回屏幕坐标 (x, y) 处最顶层的窗口 HWND（用于验证 click-through）。

    如果 click-through 生效，传入面板透明区域的坐标，应返回面板下方的窗口，
    而不是面板自身的 HWND。
    """
    if sys.platform != "win32":
        return 0
    pt = _POINT(x, y)
    return int(_WindowFromPoint(pt))


_ScreenToClient = ctypes.windll.user32.ScreenToClient
_ScreenToClient.restype = ctypes.c_bool
_ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(_POINT)]


_GetCursorPos = ctypes.windll.user32.GetCursorPos
_GetCursorPos.argtypes = [ctypes.POINTER(_POINT)]


def get_cursor_pos() -> tuple[int, int] | None:
    if sys.platform != "win32":
        return None
    pt = _POINT()
    if not _GetCursorPos(ctypes.byref(pt)):
        return None
    return (int(pt.x), int(pt.y))
