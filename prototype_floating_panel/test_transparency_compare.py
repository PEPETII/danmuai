"""严格的透明度对比测试：
1. 截屏（无窗口）→ desktop_before.png
2. 启动 pywebview 透明窗口
3. 截屏（有窗口）→ desktop_after.png
4. 对比窗口区域：相同 → 透明生效；不同 → 透明失效
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


def panel_worker(html_url, ready_q, result_q, *, width, height, x, y):
    multiprocessing.freeze_support()
    import webview

    create_kwargs = dict(
        title="TransparencyCompare",
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
            hwnd = ctypes.windll.user32.FindWindowW(None, "TransparencyCompare")
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

        from prototype_floating_panel.win32_probe import get_window_rect, get_exstyle
        time.sleep(1.0)
        rect = get_window_rect(hwnd)
        ex = get_exstyle(hwnd)
        result_q.put(f"hwnd:{hwnd}")
        result_q.put(f"rect:{rect}")
        result_q.put(f"exstyle:0x{ex:08x}")
        result_q.put("ready-for-comparison")
        # 等主进程完成对比
        time.sleep(8.0)
        result_q.put("probe-done")

    threading.Thread(target=probe, daemon=True).start()
    webview.start(debug=False, gui="edgechromium")


def grab_region(rect, path):
    """截取指定区域。"""
    from PIL import ImageGrab
    left, top, right, bottom = rect
    img = ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True)
    img.save(str(path))
    return img


def main():
    print("=" * 70, flush=True)
    print("[main] 透明度对比测试", flush=True)

    # 启动 FastAPI（HTML 不带 ws_url，使用 demo 模式自动加 5 条测试卡片）
    from prototype_floating_panel.run_prototype import start_fastapi_server
    server, t, base_url, ws_state = start_fastapi_server(port=18799)
    print(f"[main] FastAPI ready: {base_url}", flush=True)
    html_url = f"{base_url}/"

    # 取屏幕右下角位置
    try:
        from PyQt6.QtWidgets import QApplication
        qt_app = QApplication.instance() or QApplication(sys.argv)
        screen = qt_app.primaryScreen().geometry()
        x = screen.right() - 380
        y = screen.bottom() - 640
    except Exception:
        x, y = 100, 100

    # 目标窗口区域
    target_rect = (x, y, x + 360, y + 600)

    # Phase 1: 截屏桌面（无窗口）
    print(f"[main] Phase 1: 截屏桌面（无窗口），rect={target_rect}", flush=True)
    img_before = grab_region(target_rect, THIS_DIR / "desktop_before.png")

    # Phase 2: 启动窗口
    print("[main] Phase 2: 启动 pywebview 透明窗口", flush=True)
    ctx = multiprocessing.get_context("spawn")
    ready_q = ctx.Queue()
    result_q = ctx.Queue()
    proc = ctx.Process(
        target=panel_worker,
        args=(html_url, ready_q, result_q),
        kwargs={"width": 360, "height": 600, "x": x, "y": y},
        daemon=True,
    )
    proc.start()
    print(f"[main] panel pid={proc.pid}", flush=True)

    # 等 ready
    logs = []
    ready_for_cmp = False
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        try:
            r = result_q.get(timeout=0.5)
            logs.append(r)
            if r == "ready-for-comparison":
                ready_for_cmp = True
                break
        except queue.Empty:
            try:
                r = ready_q.get(timeout=0.05)
                logs.append(f"[ready] {r}")
            except queue.Empty:
                pass

    print(f"[main] ready_for_comparison={ready_for_cmp}", flush=True)
    time.sleep(1.0)  # 让 demo 卡片动画完成

    # Phase 3: 截屏（有窗口）
    if ready_for_cmp:
        print(f"[main] Phase 3: 截屏（有窗口），rect={target_rect}", flush=True)
        img_after = grab_region(target_rect, THIS_DIR / "desktop_after.png")

        # Phase 4: 像素对比
        print("[main] Phase 4: 像素对比", flush=True)
        try:
            import numpy as np
            arr1 = np.array(img_before)
            arr2 = np.array(img_after)
            print(f"[main] before shape={arr1.shape}, after shape={arr2.shape}", flush=True)

            # 计算像素差异
            diff = np.abs(arr1.astype(int) - arr2.astype(int))
            max_diff = diff.max()
            mean_diff = diff.mean()
            # 完全相同的像素占比
            identical = (diff.sum(axis=2) == 0).sum()
            total = arr1.shape[0] * arr1.shape[1]
            identical_ratio = identical / total

            print(f"[main] 像素差异：max={max_diff}, mean={mean_diff:.2f}", flush=True)
            print(f"[main] 完全相同像素占比：{identical_ratio:.4f} ({identical}/{total})", flush=True)

            # 找到有差异的区域（卡片所在位置）
            diff_mask = diff.sum(axis=2) > 30  # 显著差异
            diff_ratio = diff_mask.sum() / total
            print(f"[main] 显著差异像素占比（>30）：{diff_ratio:.4f}", flush=True)

            # 如果透明生效：
            # - 显著差异应该只在卡片区域（约 10-30%）
            # - 其他区域应该完全相同（透明显示桌面）
            # 如果透明失效：
            # - 几乎所有区域都有差异（窗口背景覆盖了桌面）

            if diff_ratio < 0.4:
                print("[main] 结论：**透明生效**（差异主要在卡片区域）", flush=True)
            elif diff_ratio < 0.7:
                print("[main] 结论：**部分透明**（部分区域显示桌面，部分被覆盖）", flush=True)
            else:
                print("[main] 结论：**透明失效**（窗口背景覆盖了大部分桌面）", flush=True)

            # 保存差异图
            diff_img = np.zeros_like(arr2)
            diff_img[diff_mask] = [255, 0, 0]  # 差异区域用红色标记
            from PIL import Image
            Image.fromarray(diff_img).save(str(THIS_DIR / "diff.png"))
            print(f"[main] 差异图已保存: {THIS_DIR / 'diff.png'}", flush=True)

        except Exception as exc:
            print(f"[main] 对比失败: {exc!r}", flush=True)

    # 收尾
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=3.0)
    server.should_exit = True
    t.join(timeout=3.0)

    print("\n" + "=" * 70, flush=True)
    print("探针日志：", flush=True)
    for log in logs:
        print(f"  {log}", flush=True)


if __name__ == "__main__":
    main()
