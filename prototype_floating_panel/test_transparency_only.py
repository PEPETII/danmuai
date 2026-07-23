"""透明度隔离测试：
1. 启动 pywebview 子进程（transparent=True），不做任何 exstyle 修改
2. 截屏验证透明是否生效
3. 再应用 click-through，再截屏验证透明是否被破坏
"""
from __future__ import annotations

import multiprocessing
import os
import queue
import sys
import threading
import time
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))


def panel_worker(
    html_url: str,
    ready_queue: multiprocessing.Queue,
    result_queue: multiprocessing.Queue,
    *,
    width: int,
    height: int,
    x: int,
    y: int,
):
    """子进程：仅启动 pywebview，不修改 exstyle。"""
    multiprocessing.freeze_support()
    try:
        import webview
    except ImportError as exc:
        ready_queue.put(f"import-failed: {exc}")
        return

    result_queue.put(f"webview_version:{getattr(webview, '__version__', '?')}")

    create_kwargs = dict(
        title="TransparencyTest",
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
    try:
        window = webview.create_window(**create_kwargs)
    except (TypeError, ValueError) as exc:
        result_queue.put(f"create-fallback:{exc}")
        create_kwargs.pop("transparent", None)
        window = webview.create_window(**create_kwargs)

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
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, "TransparencyTest")
            if hwnd:
                return int(hwnd)
        except Exception:
            pass
        return 0

    def on_loaded():
        hwnd = get_hwnd()
        hwnd_holder["hwnd"] = hwnd
        ready_queue.put("loaded")
        ready_queue.put(f"hwnd:{hwnd}")

    window.events.loaded += on_loaded

    def probe_thread():
        # 等 loaded
        deadline = time.monotonic() + 15.0
        hwnd = 0
        while time.monotonic() < deadline:
            hwnd = hwnd_holder["hwnd"]
            if hwnd:
                break
            time.sleep(0.2)
        if not hwnd:
            result_queue.put("probe-no-hwnd")
            return
        result_queue.put(f"probe-hwnd:{hwnd}")

        from prototype_floating_panel.win32_probe import (
            get_exstyle, has_layered, has_transparent, get_window_rect, get_dpi,
        )

        time.sleep(1.0)  # 让窗口稳定
        ex = get_exstyle(hwnd)
        result_queue.put(f"phase1-exstyle:0x{ex:08x}")
        result_queue.put(f"phase1-layered:{has_layered(hwnd)}")
        result_queue.put(f"phase1-transparent:{has_transparent(hwnd)}")
        rect = get_window_rect(hwnd)
        result_queue.put(f"phase1-rect:{rect}")
        result_queue.put(f"phase1-dpi:{get_dpi(hwnd)}")
        # 不修改 exstyle，等主进程截屏
        result_queue.put("phase1-ready-for-screenshot")
        # 等主进程截屏完成
        time.sleep(5.0)
        result_queue.put("phase1-done")

    threading.Thread(target=probe_thread, daemon=True).start()

    try:
        webview.start(debug=False, gui="edgechromium")
    except Exception as exc:
        result_queue.put(f"webview-start-fail:{exc}")


def take_screenshot_region(rect, path):
    """截取窗口区域的屏幕截图。"""
    try:
        from PIL import ImageGrab
        left, top, right, bottom = rect
        # 扩大一点边界，确保捕获完整窗口
        img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
        img.save(str(path))
        # 分析像素
        import numpy as np
        arr = np.array(img)
        # 取中心区域
        h, w = arr.shape[:2]
        center = arr[h//4:h*3//4, w//4:w*3//4]
        # 统计非白像素占比
        non_white = ((center[:,:,0] < 250) | (center[:,:,1] < 250) | (center[:,:,2] < 250)).sum()
        total = center.shape[0] * center.shape[1]
        ratio = non_white / total
        return {
            "size": (w, h),
            "non_white_ratio": float(ratio),
            "mean_color": arr.mean(axis=(0,1)).tolist(),
            "center_mean": center.mean(axis=(0,1)).tolist(),
        }
    except Exception as exc:
        return {"err": str(exc)}


def main():
    print("=" * 70, flush=True)
    print("[main] 透明度隔离测试：不应用 click-through，仅看透明是否生效", flush=True)

    # 启动 FastAPI
    from prototype_floating_panel.run_prototype import start_fastapi_server
    server, t, base_url, ws_state = start_fastapi_server(port=18799)
    print(f"[main] FastAPI ready: {base_url}", flush=True)

    # HTML 不带 ws_url，避免 WS 干扰
    html_url = f"{base_url}/"

    # 取屏幕右下角位置
    try:
        from PyQt6.QtWidgets import QApplication
        qt_app = QApplication.instance() or QApplication(sys.argv)
        screen = qt_app.primaryScreen().geometry()
        x = screen.right() - 380
        y = screen.bottom() - 640
        screen_w = screen.width()
        screen_h = screen.height()
    except Exception:
        x, y = 100, 100
        screen_w = screen_h = 0

    # 启动子进程
    ctx = multiprocessing.get_context("spawn")
    ready_q = ctx.Queue()
    result_q = ctx.Queue()
    proc = ctx.Process(
        target=panel_worker,
        args=(html_url, ready_q, result_q),
        kwargs={"width": 360, "height": 600, "x": x, "y": y},
        name="TransparencyTest",
        daemon=True,
    )
    proc.start()
    print(f"[main] panel pid={proc.pid}", flush=True)

    # 等 loaded
    logs = []
    loaded = False
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            msg = ready_q.get(timeout=0.5)
            if msg == "loaded":
                loaded = True
            logs.append(f"[ready] {msg}")
            if loaded and msg.startswith("hwnd:"):
                break
        except queue.Empty:
            try:
                r = result_q.get(timeout=0.05)
                logs.append(r)
            except queue.Empty:
                pass

    # 等 phase1-ready
    phase1_ready = False
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        try:
            r = result_q.get(timeout=0.5)
            logs.append(r)
            if r == "phase1-ready-for-screenshot":
                phase1_ready = True
                break
        except queue.Empty:
            pass

    print(f"[main] phase1_ready={phase1_ready}", flush=True)

    # 截屏（不应用 click-through）
    if phase1_ready:
        # 解析 rect
        rect = None
        for log in logs:
            if log.startswith("phase1-rect:"):
                rect_str = log.split(":", 1)[1].strip("()")
                rect = tuple(int(v.strip()) for v in rect_str.split(","))
                break
        print(f"[main] phase1 rect={rect}", flush=True)
        if rect:
            shot1 = take_screenshot_region(rect, THIS_DIR / "screenshot_phase1_no_clickthrough.png")
            print(f"[main] phase1 screenshot: {shot1}", flush=True)

    # 让子进程继续存活一会儿再终止
    time.sleep(5.0)
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=3.0)

    server.should_exit = True
    t.join(timeout=3.0)

    # 输出结果
    print("\n" + "=" * 70, flush=True)
    print("Phase 1 探针输出：", flush=True)
    for log in logs:
        print(f"  {log}", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
