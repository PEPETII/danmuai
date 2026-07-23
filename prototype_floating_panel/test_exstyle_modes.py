"""测试不同 exstyle 修改对透明度的影响：
1. 仅添加 WS_EX_TRANSPARENT（LAYERED 已由 pywebview 设置）
2. 重新调用 SetLayeredWindowAttributes 恢复 chroma key
3. 测试 click-through 是否仍生效
"""
from __future__ import annotations

import ctypes
import multiprocessing
import os
import queue
import sys
import threading
import time
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))


# Win32 常量
_GWL_EXSTYLE = -20
_WS_EX_LAYERED = 0x00080000
_WS_EX_TRANSPARENT = 0x00000020
_LWA_COLORKEY = 0x00000001
_LWA_ALPHA = 0x00000002

_SetWindowLong = ctypes.windll.user32.SetWindowLongPtrW
_GetWindowLong = ctypes.windll.user32.GetWindowLongPtrW
_SetLayeredWindowAttributes = ctypes.windll.user32.SetLayeredWindowAttributes
_SetLayeredWindowAttributes.restype = ctypes.c_bool
_SetLayeredWindowAttributes.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_byte, ctypes.c_uint32]


def panel_worker(html_url, ready_q, result_q, *, width, height, x, y, mode):
    """子进程：启动 pywebview，根据 mode 应用不同的 exstyle 修改。"""
    multiprocessing.freeze_support()
    import webview

    window = webview.create_window(
        title="ExstyleTest",
        url=html_url,
        width=width,
        height=height,
        x=x,
        y=y,
        frameless=True,
        easy_drag=False,
        on_top=True,
        transparent=True,
        hidden=False,
    )

    hwnd_holder = {"hwnd": 0}

    def get_hwnd():
        try:
            from webview.platforms.winforms import BrowserView
            bv = BrowserView.instances.get(window.uid)
            if bv is not None:
                return int(bv.Handle.ToInt32())
        except Exception:
            pass
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "ExstyleTest")
            if hwnd:
                return int(hwnd)
        except Exception:
            pass
        return 0

    def on_loaded():
        hwnd = get_hwnd()
        hwnd_holder["hwnd"] = hwnd
        ready_q.put("loaded")
        ready_q.put(f"hwnd:{hwnd}")

    window.events.loaded += on_loaded

    def probe():
        deadline = time.monotonic() + 15.0
        hwnd = 0
        while time.monotonic() < deadline:
            hwnd = hwnd_holder["hwnd"]
            if hwnd:
                break
            time.sleep(0.2)
        if not hwnd:
            result_q.put("probe-no-hwnd")
            return
        time.sleep(1.0)

        from prototype_floating_panel.win32_probe import (
            get_window_rect, get_exstyle, has_layered, has_transparent,
        )

        rect = get_window_rect(hwnd)
        result_q.put(f"hwnd:{hwnd}")
        result_q.put(f"rect:{rect}")
        result_q.put(f"initial-exstyle:0x{get_exstyle(hwnd):08x}")
        result_q.put(f"initial-layered:{has_layered(hwnd)}")
        result_q.put(f"initial-transparent:{has_transparent(hwnd)}")

        # 根据 mode 应用不同的修改
        if mode == "transparent-only":
            # 仅添加 WS_EX_TRANSPARENT，不动 LAYERED
            ex = get_exstyle(hwnd)
            new_ex = ex | _WS_EX_TRANSPARENT
            _SetWindowLong(hwnd, _GWL_EXSTYLE, new_ex)
            result_q.put(f"after-transparent-only-exstyle:0x{get_exstyle(hwnd):08x}")
        elif mode == "transparent-plus-colorkey":
            # 添加 WS_EX_TRANSPARENT，然后重新设置 chroma key（红色 0x000000FF）
            ex = get_exstyle(hwnd)
            new_ex = ex | _WS_EX_TRANSPARENT
            _SetWindowLong(hwnd, _GWL_EXSTYLE, new_ex)
            # 重新设 chroma key：颜色 0x000000FF (BGR: 0xFF0000?)，需要确认
            # COLORREF 格式：0x00BBGGRR，红色 = 0x000000FF
            ok = _SetLayeredWindowAttributes(hwnd, 0x000000FF, 0, _LWA_COLORKEY)
            result_q.put(f"after-plus-colorkey-exstyle:0x{get_exstyle(hwnd):08x}")
            result_q.put(f"set-colorkey-ok:{ok}")
        elif mode == "no-modification":
            # 不修改 exstyle，仅作为对照
            result_q.put("no-modification-applied")
        elif mode == "transparent-alpha-255":
            # 添加 WS_EX_TRANSPARENT，用 LWA_ALPHA alpha=255（不实际透明，但启用 layered）
            ex = get_exstyle(hwnd)
            new_ex = ex | _WS_EX_TRANSPARENT
            _SetWindowLong(hwnd, _GWL_EXSTYLE, new_ex)
            ok = _SetLayeredWindowAttributes(hwnd, 0, 255, _LWA_ALPHA)
            result_q.put(f"after-alpha-255-exstyle:0x{get_exstyle(hwnd):08x}")
            result_q.put(f"set-alpha-255-ok:{ok}")

        result_q.put("ready-for-screenshot")
        time.sleep(8.0)
        result_q.put("probe-done")

    threading.Thread(target=probe, daemon=True).start()
    webview.start(debug=False, gui="edgechromium")


def grab_region(rect, path):
    from PIL import ImageGrab
    left, top, right, bottom = rect
    img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    img.save(str(path))
    return img


def run_test(mode: str):
    """运行一个 mode 的测试。"""
    print(f"\n{'=' * 70}\n[main] 测试 mode={mode}\n{'=' * 70}", flush=True)

    from prototype_floating_panel.run_prototype import start_fastapi_server
    server, t, base_url, ws_state = start_fastapi_server(port=18799)
    html_url = f"{base_url}/"

    try:
        from PyQt6.QtWidgets import QApplication
        qt_app = QApplication.instance() or QApplication(sys.argv)
        screen = qt_app.primaryScreen().geometry()
        x = screen.right() - 380
        y = screen.bottom() - 640
    except Exception:
        x, y = 100, 100

    target_rect = (x, y, x + 360, y + 600)
    img_before = grab_region(target_rect, THIS_DIR / f"before_{mode}.png")
    print(f"[main] before screenshot saved (mode={mode})", flush=True)

    ctx = multiprocessing.get_context("spawn")
    ready_q = ctx.Queue()
    result_q = ctx.Queue()
    proc = ctx.Process(
        target=panel_worker,
        args=(html_url, ready_q, result_q),
        kwargs={"width": 360, "height": 600, "x": x, "y": y, "mode": mode},
        daemon=True,
    )
    proc.start()
    print(f"[main] panel pid={proc.pid}", flush=True)

    logs = []
    ready = False
    rect = None
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            r = result_q.get(timeout=0.5)
            logs.append(r)
            if r.startswith("rect:"):
                rect_str = r.split(":", 1)[1].strip("()")
                rect = tuple(int(v.strip()) for v in rect_str.split(","))
            if r == "ready-for-screenshot":
                ready = True
                break
        except queue.Empty:
            try:
                r = ready_q.get(timeout=0.05)
                logs.append(f"[ready] {r}")
            except queue.Empty:
                pass

    print(f"[main] ready={ready} rect={rect}", flush=True)
    time.sleep(1.0)

    if ready:
        img_after = grab_region(target_rect, THIS_DIR / f"after_{mode}.png")

        # 像素对比
        import numpy as np
        arr1 = np.array(img_before)
        arr2 = np.array(img_after)
        diff = np.abs(arr1.astype(int) - arr2.astype(int))
        identical = (diff.sum(axis=2) == 0).sum()
        total = arr1.shape[0] * arr1.shape[1]
        identical_ratio = identical / total
        diff_mask = diff.sum(axis=2) > 30
        diff_ratio = diff_mask.sum() / total

        print(f"[main] mode={mode} 结果：", flush=True)
        print(f"  完全相同像素占比：{identical_ratio:.4f}", flush=True)
        print(f"  显著差异像素占比：{diff_ratio:.4f}", flush=True)
        if identical_ratio > 0.7:
            print(f"  → **透明生效**", flush=True)
        elif identical_ratio > 0.4:
            print(f"  → **部分透明**", flush=True)
        else:
            print(f"  → **透明失效**", flush=True)

    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=3.0)
    server.should_exit = True
    t.join(timeout=3.0)
    time.sleep(0.5)

    print(f"\n[main] mode={mode} 探针日志：", flush=True)
    for log in logs:
        print(f"  {log}", flush=True)

    return {"mode": mode, "identical_ratio": identical_ratio, "diff_ratio": diff_ratio} if ready else {"mode": mode, "error": "not-ready"}


def main():
    results = []
    # 测试不同 mode
    for mode in ["no-modification", "transparent-only", "transparent-plus-colorkey", "transparent-alpha-255"]:
        try:
            r = run_test(mode)
            results.append(r)
        except Exception as exc:
            print(f"[main] mode={mode} failed: {exc!r}", flush=True)
            results.append({"mode": mode, "error": str(exc)})

    print("\n" + "=" * 70, flush=True)
    print("[main] 汇总结果：", flush=True)
    for r in results:
        print(f"  {r}", flush=True)


if __name__ == "__main__":
    main()
