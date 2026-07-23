"""子进程：pywebview 透明无边框置顶窗口 + Win32 探针。

通过 multiprocessing.spawn 启动；通过 Queue 与主进程通信。
模拟生产 webview_shell.py 的架构（spawn 子进程 + ready/nav queue）。
"""
from __future__ import annotations

import multiprocessing
import os
import queue
import threading
import time
from typing import Any


def _webview_worker(
    html_url: str,
    ready_queue: multiprocessing.Queue,
    result_queue: multiprocessing.Queue,
    *,
    width: int,
    height: int,
    x: int,
    y: int,
) -> None:
    """子进程主入口：webview.start() 阻塞调用。"""
    multiprocessing.freeze_support()
    try:
        import webview
    except ImportError as exc:
        ready_queue.put(f"import-failed: {exc}")
        return

    print(f"[panel_window] webview version: {getattr(webview, '__version__', '?')}", flush=True)
    result_queue.put(f"webview_version:{getattr(webview, '__version__', '?')}")

    # 创建窗口：transparent + frameless + on_top
    # 注意：pywebview 5.x 的 edgechromium 后端支持 transparent=True
    # 实测：background_color 不接受 8 位 hex（#RRGGBBAA），transparent=True 时省略
    create_kwargs = dict(
        title="DanmuAI Floating Panel Prototype",
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
        # 某些 pywebview 版本不接受 transparent 参数，降级
        result_queue.put(f"create-fallback:{exc}")
        create_kwargs.pop("transparent", None)
        window = webview.create_window(**create_kwargs)

    hwnd_holder: dict[str, int] = {"hwnd": 0}

    def get_hwnd() -> int:
        """通过 pywebview 内部 BrowserView 获取 HWND。"""
        try:
            from webview.platforms.winforms import BrowserView
            bv = BrowserView.instances.get(window.uid)
            if bv is not None:
                return int(bv.Handle.ToInt32())
        except Exception as exc:
            print(f"[panel_window] get_hwnd via BrowserView failed: {exc}", flush=True)
        # 回退：用 FindWindowW 按标题查找
        try:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, "DanmuAI Floating Panel Prototype")
            if hwnd:
                return int(hwnd)
        except Exception:
            pass
        return 0

    def on_loaded():
        # 窗口加载完成，尝试获取 HWND（Windows）
        hwnd = get_hwnd()
        hwnd_holder["hwnd"] = hwnd
        print(f"[panel_window] loaded; hwnd={hwnd}", flush=True)
        ready_queue.put("loaded")
        ready_queue.put(f"hwnd:{hwnd}")

    def on_closing():
        print("[panel_window] closing", flush=True)
        try:
            result_queue.put("closing")
        except Exception:
            pass
        return True

    window.events.loaded += on_loaded
    window.events.closing += on_closing

    # Win32 探针线程：在 webview.start() 之前启动
    def win32_probe_thread():
        # 等 loaded 信号（轮询 hwnd_holder，不消费 ready_queue 避免与主进程 race）
        deadline = time.monotonic() + 15.0
        hwnd = 0
        while time.monotonic() < deadline:
            hwnd = hwnd_holder["hwnd"]
            if hwnd:
                break
            time.sleep(0.2)
        if not hwnd:
            result_queue.put("probe-timeout-waiting-hwnd")
            return
        result_queue.put(f"probe-hwnd-found:{hwnd}")

        # 模拟 win32_overlay_zorder 的探针
        from prototype_floating_panel.win32_probe import (
            get_exstyle, has_layered, has_transparent, has_caption,
            apply_click_through, set_topmost, get_window_rect, get_dpi,
            get_foreground, get_style,
        )

        # 1. 初始 exstyle 探测（WebView2 初始化后的原始状态）
        time.sleep(0.5)  # 等窗口完全 ready
        initial_ex = get_exstyle(hwnd)
        initial_style = get_style(hwnd)
        result_queue.put(f"initial-exstyle:0x{initial_ex:08x}")
        result_queue.put(f"initial-style:0x{initial_style:08x}")
        result_queue.put(f"initial-layered:{has_layered(hwnd)}")
        result_queue.put(f"initial-transparent:{has_transparent(hwnd)}")
        result_queue.put(f"initial-caption:{has_caption(hwnd)}")
        result_queue.put(f"initial-dpi:{get_dpi(hwnd)}")
        rect = get_window_rect(hwnd)
        result_queue.put(f"initial-rect:{rect}")
        result_queue.put(f"initial-foreground:{get_foreground()} hwnd={hwnd} match={get_foreground()==hwnd}")

        # 2. 设 HWND_TOPMOST（此时未应用 click-through，evaluate_js 可正常工作）
        topmost_ok = set_topmost(hwnd)
        result_queue.put(f"after-set-topmost:{topmost_ok}")

        # 3. 持续 10 秒监测 exstyle 是否被 WebView2 重置（此时无 WS_EX_TRANSPARENT）
        exstyle_changes: list[str] = []
        last_ex = initial_ex
        for i in range(20):  # 每 0.5s 一次，共 10s
            time.sleep(0.5)
            cur_ex = get_exstyle(hwnd)
            if cur_ex != last_ex:
                exstyle_changes.append(f"t={i*0.5:.1f}s 0x{last_ex:08x}->0x{cur_ex:08x} transparent={has_transparent(hwnd)}")
                last_ex = cur_ex
        if exstyle_changes:
            result_queue.put(f"exstyle-changed:{len(exstyle_changes)}")
            for ch in exstyle_changes:
                result_queue.put(f"  {ch}")
        else:
            result_queue.put("exstyle-stable:10s")

        # 4. 测试 JS 交互：测量卡片 + 启动动画探针
        # 关键：必须在 apply_click_through 之前执行，因为 WS_EX_TRANSPARENT 会使窗口
        # 无法接收鼠标消息，导致 pywebview 的 evaluate_js（依赖窗口消息派发）失效。
        # 注意：pywebview 5.4 的 evaluate_js 不接受 sync kwarg（默认同步）
        # 注意：evaluate_js 可能会 hang（WinForms Invoke 死锁），用线程+超时保护
        def safe_eval(script: str, timeout: float = 5.0) -> str:
            result_box: list = [None]
            error_box: list = [None]
            def _call():
                try:
                    r = window.evaluate_js(script)
                    result_box[0] = r if r is not None else "null"
                except Exception as exc:
                    error_box[0] = str(exc)
            t = threading.Thread(target=_call, daemon=True)
            t.start()
            t.join(timeout=timeout)
            if t.is_alive():
                return f"TIMEOUT({timeout}s)"
            if error_box[0] is not None:
                return f"ERR:{error_box[0]}"
            return str(result_box[0]) if result_box[0] is not None else "null"

        measure = safe_eval(
            "JSON.stringify(window.__measureFirstCard ? window.__measureFirstCard() : {err:'no-fn'})"
        )
        result_queue.put(f"js-measure:{measure}")

        anim_start = safe_eval(
            "window.__startAnimationProbe ? window.__startAnimationProbe() : 'no-fn'"
        )
        result_queue.put(f"js-anim-start:{anim_start}")
        time.sleep(1.0)
        frame = safe_eval(
            "window.__panelState ? window.__panelState.animationFrame : -1"
        )
        result_queue.put(f"js-anim-frame-after-1s:{frame}")

        # 6. 探测 transparent 是否仍生效：通过 JS 检查 body 计算样式
        bg = safe_eval("getComputedStyle(document.body).backgroundColor")
        result_queue.put(f"js-body-bg:{bg}")
        panel_bg = safe_eval("getComputedStyle(document.getElementById('panel')).backgroundColor")
        result_queue.put(f"js-panel-bg:{panel_bg}")

        # 7. 检查 WS 连接状态
        ws_state = safe_eval(
            "JSON.stringify({clients: window.__ws ? 1 : 0, "
            "readyState: window.__ws ? window.__ws.readyState : -1, "
            "received: window.__panelState ? window.__panelState.wsReceived : -1, "
            "lastMsg: window.__panelState ? window.__panelState.lastWmMsg : null})"
        )
        result_queue.put(f"js-ws-state:{ws_state}")

        # 8. 测试 probe-target 显示（验证 JS 交互链路）
        r = safe_eval("window.__showProbeTarget(true)")
        result_queue.put(f"js-probe-show:{r}")

        # 9. 测试添加卡片
        add_result = safe_eval(
            "(window.addCard ? (window.addCard('测试用户','这是一条通过 JS API 添加的卡片'), 'ok') : 'no-fn')"
        )
        result_queue.put(f"js-add-card:{add_result}")
        time.sleep(0.5)
        cards_count = safe_eval("document.querySelectorAll('.card').length")
        result_queue.put(f"js-cards-count:{cards_count}")

        # 10. 测量首张卡片的实际渲染
        first_card = safe_eval(
            "(function(){var c=document.querySelector('.card');if(!c)return 'no-card';"
            "var r=c.getBoundingClientRect();"
            "var s=getComputedStyle(c);"
            "return JSON.stringify({w:r.width,h:r.height,bg:s.backgroundColor,"
            "shadow:s.boxShadow.substring(0,100),radius:s.borderRadius,"
            "transform:s.transform,opacity:s.opacity});})()"
        )
        result_queue.put(f"js-first-card:{first_card}")

        # 11. 探测透明效果：检查 body 在屏幕上的实际像素（通过 canvas 截屏不可行，
        # 但可以检查 body computed style）
        body_alpha = safe_eval(
            "(function(){var s=getComputedStyle(document.body);"
            "return JSON.stringify({bg:s.backgroundColor,color:s.color,"
            "html_bg:getComputedStyle(document.documentElement).backgroundColor});})()"
        )
        result_queue.put(f"js-body-alpha:{body_alpha}")

        # 12. 应用 click-through（WS_EX_TRANSPARENT | WS_EX_LAYERED）
        # 关键：必须在所有 evaluate_js 调用之后执行，否则窗口无法接收消息，evaluate_js 失效
        new_ex = apply_click_through(hwnd)
        result_queue.put(f"after-click-through-exstyle:0x{new_ex:08x}")
        result_queue.put(f"after-click-through-transparent:{has_transparent(hwnd)}")
        time.sleep(0.5)  # 等系统应用 exstyle

        # 13. 验证 click-through：在面板透明区域取 WindowFromPoint
        from prototype_floating_panel.win32_probe import window_from_point
        rect = get_window_rect(hwnd)
        if rect:
            left, top, right, bottom = rect
            # 取面板四个角附近（透明区域，无卡片）
            test_points = [
                ("top-left", left + 5, top + 5),
                ("top-right", right - 5, top + 5),
                ("bottom-left", left + 5, bottom - 5),
                ("bottom-right", right - 5, bottom - 5),
                ("center", (left + right) // 2, (top + bottom) // 2),
            ]
            for name, px, py in test_points:
                hit_hwnd = window_from_point(px, py)
                is_panel = (hit_hwnd == hwnd)
                result_queue.put(
                    f"click-through-{name}:point=({px},{py}) hwnd={hit_hwnd} is_panel={is_panel}"
                )
            # 汇总：如果所有点都不命中面板，click-through 完全生效
            click_through_pass = all(
                window_from_point(px, py) != hwnd for _, px, py in test_points
            )
            result_queue.put(f"click-through-summary:pass={click_through_pass}")

        # 14. 验证 click-through 后 exstyle 是否稳定（5s）
        ct_changes: list[str] = []
        last_ct_ex = new_ex
        for i in range(10):
            time.sleep(0.5)
            cur_ex = get_exstyle(hwnd)
            if cur_ex != last_ct_ex:
                ct_changes.append(f"t={i*0.5:.1f}s 0x{last_ct_ex:08x}->0x{cur_ex:08x}")
                last_ct_ex = cur_ex
        if ct_changes:
            result_queue.put(f"click-through-exstyle-changed:{len(ct_changes)}")
            for ch in ct_changes:
                result_queue.put(f"  {ch}")
        else:
            result_queue.put("click-through-exstyle-stable:5s")

        # 15. 信号完成
        result_queue.put("probe-done")

        # 9. 重新断言 topmost（验证 WebView2 是否会重置 z-order）
        time.sleep(1.0)
        topmost_again = set_topmost(hwnd)
        result_queue.put(f"reassert-topmost:{topmost_again}")
        foreground_now = get_foreground()
        result_queue.put(f"final-foreground:{foreground_now} hwnd={hwnd} match={foreground_now==hwnd}")

        # 10. 多屏信息（验证多屏支持）
        try:
            import ctypes
            _EnumDisplayMonitors = ctypes.windll.user32.EnumDisplayMonitors
            _GetMonitorInfoW = ctypes.windll.user32.GetMonitorInfoW
            class _MONITORINFO(ctypes.Structure):
                _fields_ = [
                    ("cbSize", ctypes.c_uint32),
                    ("rcMonitor", ctypes.c_long * 4),
                    ("rcWork", ctypes.c_long * 4),
                    ("dwFlags", ctypes.c_uint32),
                ]
            monitors = []
            def _cb(hmon, hdc, lprect, lparam):
                mi = _MONITORINFO()
                mi.cbSize = ctypes.sizeof(_MONITORINFO)
                if _GetMonitorInfoW(hmon, ctypes.byref(mi)):
                    monitors.append({
                        "handle": int(hmon),
                        "rect": tuple(mi.rcMonitor),
                        "work": tuple(mi.rcWork),
                        "primary": bool(mi.dwFlags & 1),
                    })
                return 1
            CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p)
            _EnumDisplayMonitors(0, 0, CMPFUNC(_cb), 0)
            result_queue.put(f"monitors-count:{len(monitors)}")
            for i, m in enumerate(monitors):
                result_queue.put(f"monitor-{i}:{m}")
        except Exception as exc:
            result_queue.put(f"monitors-error:{exc}")

        # 让窗口继续存活 5 秒供主进程进一步测试
        time.sleep(5.0)
        result_queue.put("probe-exit")

    threading.Thread(target=win32_probe_thread, daemon=True).start()

    # 启动 webview（阻塞）
    try:
        webview.start(debug=False, gui="edgechromium")
    except Exception as exc:
        result_queue.put(f"webview-start-fail:{exc}")


def launch_panel(
    html_url: str,
    *,
    width: int = 360,
    height: int = 600,
    x: int = 100,
    y: int = 100,
) -> tuple[multiprocessing.Process, multiprocessing.Queue, multiprocessing.Queue]:
    """启动子进程；返回 (process, ready_queue, result_queue)。"""
    ctx = multiprocessing.get_context("spawn")
    ready_queue: multiprocessing.Queue = ctx.Queue()
    result_queue: multiprocessing.Queue = ctx.Queue()
    proc = ctx.Process(
        target=_webview_worker,
        args=(html_url, ready_queue, result_queue),
        kwargs={"width": width, "height": height, "x": x, "y": y},
        name="PanelWebView",
        daemon=True,
    )
    proc.start()
    return proc, ready_queue, result_queue
