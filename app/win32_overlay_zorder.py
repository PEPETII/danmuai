"""Win32 HWND_TOPMOST 重申与独占全屏风险探测（弹幕 Overlay / 悬浮窗共用）。"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

if sys.platform == "win32":
    _GWL_EXSTYLE = -20
    _WS_EX_LAYERED = 0x00080000
    _WS_EX_TRANSPARENT = 0x00000020
    _HWND_TOPMOST = wintypes.HWND(-1)
    _SWP_NOMOVE = 0x0002
    _SWP_NOSIZE = 0x0001
    _SWP_NOACTIVATE = 0x0010
    _SWP_SHOWWINDOW = 0x0040
    _SetWindowPos = ctypes.windll.user32.SetWindowPos
    _GWL_STYLE = -16
    _WS_CAPTION = 0x00C00000
    _GetForegroundWindow = ctypes.windll.user32.GetForegroundWindow
    _GetWindowRect = ctypes.windll.user32.GetWindowRect
    try:
        _SetWindowLong = ctypes.windll.user32.SetWindowLongPtrW
        _GetWindowLong = ctypes.windll.user32.GetWindowLongPtrW
    except AttributeError:
        _SetWindowLong = ctypes.windll.user32.SetWindowLongW
        _GetWindowLong = ctypes.windll.user32.GetWindowLongW

    class _RECT(ctypes.Structure):
        _fields_ = [
            ("left", ctypes.c_long),
            ("top", ctypes.c_long),
            ("right", ctypes.c_long),
            ("bottom", ctypes.c_long),
        ]


def apply_overlay_exstyles(hwnd: int, *, click_through: bool = True) -> None:
    """Win32：WS_EX_LAYERED + 可选 WS_EX_TRANSPARENT（Qt 透明 Overlay / 桌宠共用）。"""
    if sys.platform != "win32" or not hwnd:
        return
    ex_style = _GetWindowLong(hwnd, _GWL_EXSTYLE)
    if click_through:
        new_style = ex_style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT
    else:
        # WS_EX_LAYERED 为 Qt 逐像素 alpha 所必需；去掉 TRANSPARENT 以接收鼠标
        new_style = (ex_style | _WS_EX_LAYERED) & ~_WS_EX_TRANSPARENT
    _SetWindowLong(hwnd, _GWL_EXSTYLE, new_style)


def stack_hwnd_above(hwnd: int, above_hwnd: int) -> None:
    """Win32：将 hwnd 置于 above_hwnd 之上（不移动、不激活）。"""
    if sys.platform != "win32" or not hwnd or not above_hwnd:
        return
    _SetWindowPos(
        hwnd,
        above_hwnd,
        0,
        0,
        0,
        0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE,
    )


def reassert_hwnd_topmost(hwnd: int) -> bool:
    """Win32：SetWindowPos(HWND_TOPMOST) 恢复置顶，不抢焦点、不改尺寸位置。

    返回 True 表示成功或无需操作（非 win32 / hwnd 为 0）；
    返回 False 表示 SetWindowPos 调用失败（返回 0），调用方可累计失败次数告警。
    """
    if sys.platform != "win32" or not hwnd:
        return True
    result = _SetWindowPos(
        hwnd,
        _HWND_TOPMOST,
        0,
        0,
        0,
        0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW,
    )
    return bool(result)


def _read_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    if sys.platform != "win32" or not hwnd:
        return None
    rect = _RECT()
    if not _GetWindowRect(hwnd, ctypes.byref(rect)):
        return None
    return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))


def probe_exclusive_fullscreen_risk(
    *,
    overlay_hwnd: int,
    screen_x: int,
    screen_y: int,
    screen_w: int,
    screen_h: int,
    own_hwnds: tuple[int, ...] = (),
) -> bool:
    """启发式：前台窗口几乎铺满目标屏且不是本应用 HWND → 疑似独占全屏压制 overlay。"""
    if sys.platform != "win32" or not overlay_hwnd or screen_w <= 0 or screen_h <= 0:
        return False
    fg = int(_GetForegroundWindow())
    if not fg:
        return False
    skip = {int(h) for h in own_hwnds if h}
    skip.add(int(overlay_hwnd))
    if fg in skip:
        return False
    bounds = _read_window_rect(fg)
    if bounds is None:
        return False
    left, top, right, bottom = bounds
    fg_w = right - left
    fg_h = bottom - top
    if fg_w < int(screen_w * 0.95) or fg_h < int(screen_h * 0.95):
        return False
    # 前台窗与目标屏几何大致重合（允许少量偏差）
    if abs(left - screen_x) > 8 or abs(top - screen_y) > 8:
        return False
    # 普通最大化窗口仍带标题栏，不应误报为独占全屏
    style = int(_GetWindowLong(fg, _GWL_STYLE))
    if style & _WS_CAPTION:
        return False
    return True
