"""Win32 HWND_TOPMOST 重申与独占全屏风险探测（弹幕 Overlay / 悬浮窗共用）。"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

if sys.platform == "win32":
    _GWL_EXSTYLE = -20
    _WS_EX_LAYERED = 0x00080000
    _WS_EX_TRANSPARENT = 0x00000020
    _LWA_COLORKEY = 0x00000001
    # pywebview winforms transparent: BackColor/TransparencyKey = RGB(255,0,0)
    # COLORREF layout is 0x00BBGGRR → pure red = 0x000000FF
    _PYWEBVIEW_TRANSPARENT_COLORREF = 0x000000FF
    _HWND_TOPMOST = wintypes.HWND(-1)
    _SWP_NOMOVE = 0x0002
    _SWP_NOSIZE = 0x0001
    _SWP_NOZORDER = 0x0004
    _SWP_NOACTIVATE = 0x0010
    _SWP_SHOWWINDOW = 0x0040
    _SWP_FRAMECHANGED = 0x0020
    _GA_ROOT = 2
    _SetWindowPos = ctypes.windll.user32.SetWindowPos
    _GetAncestor = ctypes.windll.user32.GetAncestor
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


def resolve_root_hwnd(hwnd: int) -> int:
    """Return top-level HWND for Win32 style/z-order ops (GA_ROOT)."""
    if sys.platform != "win32" or not hwnd:
        return int(hwnd or 0)
    try:
        root = int(_GetAncestor(int(hwnd), _GA_ROOT) or 0)
    except Exception:
        root = 0
    return root or int(hwnd)


def apply_overlay_exstyles(hwnd: int, *, click_through: bool = True) -> None:
    """Win32：WS_EX_LAYERED + 可选 WS_EX_TRANSPARENT（Qt 透明 Overlay / 桌宠共用）。

    Always operates on the top-level root HWND and refreshes the frame with
    SWP_FRAMECHANGED so hit-testing picks up the new extended styles.
    """
    if sys.platform != "win32" or not hwnd:
        return
    root = resolve_root_hwnd(hwnd)
    if not root:
        return
    ex_style = _GetWindowLong(root, _GWL_EXSTYLE)
    if click_through:
        new_style = ex_style | _WS_EX_LAYERED | _WS_EX_TRANSPARENT
    else:
        # WS_EX_LAYERED 为 Qt 逐像素 alpha 所必需；去掉 TRANSPARENT 以接收鼠标
        new_style = (ex_style | _WS_EX_LAYERED) & ~_WS_EX_TRANSPARENT
    _SetWindowLong(root, _GWL_EXSTYLE, new_style)
    # Force non-client/frame recalculation so hit-testing uses the new exstyle.
    # Keep Z-order unchanged here; callers reassert HWND_TOPMOST separately.
    _SetWindowPos(
        root,
        0,
        0,
        0,
        0,
        0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
    )


def reassert_webview_panel_colorkey(hwnd: int) -> bool:
    """恢复 pywebview EdgeChromium 透明色键（纯红 chroma key）。

    pywebview 在 transparent=True 时设置 TransparencyKey=RGB(255,0,0)。
    仅 SetWindowLong(WS_EX_LAYERED) 而不重设 LWA_COLORKEY 时，Windows 常把
    窗口填成不透明白底。返回 True 表示 API 调用成功。
    """
    if sys.platform != "win32" or not hwnd:
        return False
    try:
        # Pass plain int; wrapping HWND() makes some ctypes arg paths awkward
        # and unit tests that monkeypatch the API expect int-like hwnd.
        return bool(
            _SetLayeredWindowAttributes(
                int(hwnd),
                int(_PYWEBVIEW_TRANSPARENT_COLORREF),
                0,
                int(_LWA_COLORKEY),
            )
        )
    except Exception:
        return False


def apply_webview_panel_exstyles(hwnd: int, *, click_through: bool = True) -> None:
    """WebView2/pywebview 浮动面板：LAYERED + 可选点击穿透 + 恢复 chroma key。"""
    if sys.platform != "win32" or not hwnd:
        return
    apply_overlay_exstyles(hwnd, click_through=click_through)
    reassert_webview_panel_colorkey(hwnd)


def stack_hwnd_above(hwnd: int, above_hwnd: int) -> None:
    """Win32：将 hwnd 置于 above_hwnd 之上（不移动、不激活）。"""
    if sys.platform != "win32" or not hwnd or not above_hwnd:
        return
    root = resolve_root_hwnd(hwnd)
    above = resolve_root_hwnd(above_hwnd)
    if not root or not above:
        return
    _SetWindowPos(
        root,
        above,
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
    root = resolve_root_hwnd(hwnd)
    if not root:
        return True
    result = _SetWindowPos(
        root,
        _HWND_TOPMOST,
        0,
        0,
        0,
        0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE | _SWP_SHOWWINDOW | _SWP_FRAMECHANGED,
    )
    return bool(result)


def get_foreground_hwnd() -> int:
    """Win32：当前前台窗口 HWND；非 win32 或无效时返回 0。"""
    if sys.platform != "win32":
        return 0
    return int(_GetForegroundWindow())


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
    foreground_hwnd: int | None = None,
) -> bool:
    """启发式：前台窗口几乎铺满目标屏且不是本应用 HWND → 疑似独占全屏压制 overlay。"""
    if sys.platform != "win32" or not overlay_hwnd or screen_w <= 0 or screen_h <= 0:
        return False
    fg = int(foreground_hwnd) if foreground_hwnd is not None else int(_GetForegroundWindow())
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
