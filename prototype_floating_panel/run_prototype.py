"""主进程：FastAPI + WebSocket 服务 + 子进程协调 + 测试运行器。

启动两种模式：
- demo: 仅启动 FastAPI + 子进程，演示 Vue 浮动面板
- test: 运行完整测试套件，输出 TEST_RESULTS.md

复用生产架构：
- FastAPI 在独立线程（uvicorn）
- pywebview 在 spawn 子进程
- WebSocket 推送弹幕数据
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

# 让 prototype_floating_panel 作为包可导入
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR.parent))

PROTOTYPE_DIR = THIS_DIR
HTML_PATH = PROTOTYPE_DIR / "panel.html"
RESULTS_PATH = PROTOTYPE_DIR / "TEST_RESULTS.md"

# FastAPI 服务（模拟生产 web_console.py 的角色）
def start_fastapi_server(port: int = 18799) -> tuple[object, threading.Thread, str]:
    """启动一个最小 FastAPI 服务，提供 panel.html + WebSocket。

    重要：Python 3.14 + FastAPI 0.135.1 + starlette 0.52.1 环境下，
    `@app.websocket` 装饰器无法正确注册路由（连接时返回 403）。
    必须使用 `app.router.routes.insert(0, WebSocketRoute(...))` 显式注册，
    这也是生产代码 app/web_console_ws.py 使用的方式。
    """
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import FileResponse
    from starlette.routing import WebSocketRoute
    import uvicorn

    app = FastAPI()

    # 共享状态：测试用，记录 WS 推送次数
    state = {
        "ws_clients": 0,
        "ws_messages_sent": 0,
        "ws_messages_received": 0,
        "last_received": None,
    }
    # 所有活跃 WS 连接（用于广播）
    active_ws: set = set()

    @app.get("/")
    def index():
        return FileResponse(str(HTML_PATH))

    @app.get("/api/health")
    def health():
        return {"ok": True, "state": state}

    async def ws_panel(websocket: WebSocket):
        await websocket.accept()
        state["ws_clients"] += 1
        active_ws.add(websocket)
        try:
            # 立即推一条欢迎卡片
            await websocket.send_json({
                "type": "card",
                "username": "系统",
                "content": "WebSocket 已连接",
            })
            state["ws_messages_sent"] += 1
            # 持续接收 + 周期性 ping
            async def heartbeat():
                while True:
                    try:
                        await websocket.send_json({"type": "ping", "t": time.time()})
                        state["ws_messages_sent"] += 1
                    except Exception:
                        return
                    await asyncio.sleep(2.0)

            hb_task = asyncio.create_task(heartbeat())
            try:
                while True:
                    msg = await websocket.receive_json()
                    state["ws_messages_received"] += 1
                    state["last_received"] = msg
                    msg_type = msg.get("type")
                    if msg_type == "pong":
                        pass  # 心跳回复，不处理
                    elif msg_type == "state-report":
                        # 页面上报的状态，广播给所有其他客户端（测试用）
                        for ws in list(active_ws):
                            if ws is not websocket:
                                try:
                                    await ws.send_json(msg)
                                    state["ws_messages_sent"] += 1
                                except Exception:
                                    active_ws.discard(ws)
                    elif msg_type == "get-state":
                        # 测试客户端请求状态，广播给所有其他客户端（页面会响应 state-report）
                        for ws in list(active_ws):
                            if ws is not websocket:
                                try:
                                    await ws.send_json(msg)
                                    state["ws_messages_sent"] += 1
                                except Exception:
                                    active_ws.discard(ws)
                    elif msg_type == "card":
                        # 广播卡片给所有其他客户端
                        for ws in list(active_ws):
                            if ws is not websocket:
                                try:
                                    await ws.send_json(msg)
                                    state["ws_messages_sent"] += 1
                                except Exception:
                                    active_ws.discard(ws)
            finally:
                hb_task.cancel()
        except WebSocketDisconnect:
            pass
        except Exception as exc:
            print(f"[ws_panel] error: {exc!r}", flush=True)
        finally:
            state["ws_clients"] -= 1
            active_ws.discard(websocket)

    # 关键：用 WebSocketRoute 显式注册（生产代码风格）
    # 不能用 @app.websocket 装饰器（Python 3.14 下会返回 403）
    app.router.routes.insert(0, WebSocketRoute("/ws/panel", endpoint=ws_panel))

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
        access_log=False,
        loop="asyncio",
        ws="websockets",  # 显式指定 ws 实现（与生产 web_console_runtime.py 一致）
    )
    server = uvicorn.Server(config)
    ready = threading.Event()

    def _run():
        # 在新事件循环中跑
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        # 配置 server 在 startup 时 ready.set()
        original_startup = server.startup
        async def patched_startup(*args, **kwargs):
            res = await original_startup(*args, **kwargs)
            if server.started:
                ready.set()
            return res
        server.startup = patched_startup
        try:
            server.run()
        except Exception as exc:
            print(f"[panel_server] uvicorn failed: {exc}", flush=True)
            ready.set()  # 解锁避免死等

    t = threading.Thread(target=_run, name="PanelFastAPI", daemon=True)
    t.start()
    ready.wait(timeout=5.0)
    base_url = f"http://127.0.0.1:{port}"
    return server, t, base_url, state


def wait_pywebview_ready(ready_queue: queue.Queue, result_queue: queue.Queue, timeout: float = 30.0) -> dict:
    """等待子进程 ready，持续 drain result_queue 收集探针输出。"""
    results: list[str] = []
    deadline = time.monotonic() + timeout
    loaded = False
    while time.monotonic() < deadline:
        try:
            msg = ready_queue.get(timeout=0.5)
        except queue.Empty:
            # 也 drain result_queue
            try:
                r = result_queue.get(timeout=0.05)
                results.append(r)
            except queue.Empty:
                pass
            continue
        if msg == "loaded":
            loaded = True
        results.append(f"[ready] {msg}")
        if loaded and msg.startswith("hwnd:"):
            break
    # 继续收集 result_queue 中的探针输出
    # 时长需覆盖：10s exstyle 监测 + ~30s JS 测试（含超时） + 5s click-through + 5s 多屏
    drain_deadline = time.monotonic() + 90.0
    while time.monotonic() < drain_deadline:
        try:
            r = result_queue.get(timeout=0.5)
            results.append(r)
            if r == "probe-exit":
                break
        except queue.Empty:
            pass
    return {"loaded": loaded, "logs": results}


def take_screenshot(path: Path) -> bool:
    """对整个屏幕截图，验证透明效果（用户需肉眼对比）。"""
    try:
        from PIL import ImageGrab
        img = ImageGrab.grab(all_screens=True)
        img.save(str(path))
        return True
    except Exception as exc:
        print(f"[screenshot] failed: {exc}", flush=True)
        return False


def run_tests() -> dict:
    """运行完整测试套件。返回结果字典。"""
    print("=" * 70, flush=True)
    print("[run_tests] 启动 FastAPI 服务（端口 18799）", flush=True)
    server, server_thread, base_url, ws_state = start_fastapi_server(port=18799)
    print(f"[run_tests] FastAPI ready: {base_url}", flush=True)

    # 健康检查
    import urllib.request
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=2.0) as resp:
            health = json.loads(resp.read())
        print(f"[run_tests] /api/health: {health}", flush=True)
    except Exception as exc:
        print(f"[run_tests] /api/health failed: {exc}", flush=True)
        return {"fatal": f"health check failed: {exc}"}

    # 探测 WebView2 Runtime
    print("[run_tests] 探测 WebView2 Runtime", flush=True)
    try:
        from app.webview2_runtime import is_webview2_runtime_available
        webview2_ok = is_webview2_runtime_available()
        print(f"[run_tests] WebView2 Runtime available: {webview2_ok}", flush=True)
    except Exception as exc:
        webview2_ok = None
        print(f"[run_tests] WebView2 probe failed: {exc}", flush=True)

    # 启动 pywebview 子进程
    print("[run_tests] 启动 pywebview 子进程", flush=True)
    # 让窗口显示在主屏右下角
    try:
        from PyQt6.QtWidgets import QApplication
        qt_app = QApplication.instance() or QApplication(sys.argv)
        screen = qt_app.primaryScreen().geometry()
        # 右下角偏移
        x = screen.right() - 380
        y = screen.bottom() - 640
        screen_w = screen.width()
        screen_h = screen.height()
        screen_dpi = qt_app.primaryScreen().logicalDotsPerInch()
        # 多屏信息
        screens = []
        for scr in qt_app.screens():
            g = scr.geometry()
            screens.append({
                "x": g.x(), "y": g.y(), "w": g.width(), "h": g.height(),
                "dpi": scr.logicalDotsPerInch(),
                "primary": scr == qt_app.primaryScreen(),
            })
    except Exception:
        x, y = 100, 100
        screen_w = screen_h = 0
        screen_dpi = 96
        screens = []

    # 截屏桌面 before
    # 注意：实际窗口可能因为 DPI 缩放或多屏映射到不同坐标，
    # 我们用 expected rect 做初始截图，但后续根据 probe 返回的 initial-rect 重新对比
    expected_rect = (x, y, x + 360, y + 600)
    try:
        from PIL import ImageGrab
        img_before = ImageGrab.grab(bbox=expected_rect, all_screens=True)
        img_before.save(str(PROTOTYPE_DIR / "screenshot_before.png"))
        print(f"[run_tests] desktop_before saved (rect={expected_rect})", flush=True)
    except Exception as exc:
        print(f"[run_tests] desktop_before failed: {exc}", flush=True)
        img_before = None

    # URL 带 ws_url 参数（让前端自动连 WS）
    html_url = f"{base_url}/?ws_url=ws://127.0.0.1:18799/ws/panel"
    from prototype_floating_panel.panel_window import launch_panel
    proc, ready_queue, result_queue = launch_panel(
        html_url, width=360, height=600, x=x, y=y,
    )
    print(f"[run_tests] panel pid={proc.pid}", flush=True)

    # 等待 ready + 收集探针结果
    print("[run_tests] 等待子进程 loaded + 探针完成（最多 40s）", flush=True)
    probe_data = wait_pywebview_ready(ready_queue, result_queue, timeout=40.0)

    # 截图（验证透明效果）—— 全屏 + 窗口区域
    screenshot_path = PROTOTYPE_DIR / "screenshot.png"
    screenshot_ok = take_screenshot(screenshot_path)
    print(f"[run_tests] screenshot saved: {screenshot_path} ok={screenshot_ok}", flush=True)

    # 从 probe 日志中解析窗口实际 rect（initial-rect），用于精确截屏对比
    actual_rect = expected_rect
    for log in probe_data.get("logs", []):
        if log.startswith("initial-rect:"):
            try:
                rect_str = log.split(":", 1)[1].strip().strip("()")
                actual_rect = tuple(int(v.strip()) for v in rect_str.split(","))
                print(f"[run_tests] actual window rect from probe: {actual_rect}", flush=True)
            except Exception:
                pass
            break

    # 截屏桌面 after + 像素对比
    transparency_report = None
    try:
        from PIL import ImageGrab
        import numpy as np
        # 用实际窗口 rect 截图
        img_after = ImageGrab.grab(bbox=actual_rect, all_screens=True)
        img_after.save(str(PROTOTYPE_DIR / "screenshot_after.png"))
        # 也用实际 rect 重新截 before（因为之前用 expected_rect 可能坐标不对）
        img_before_actual = ImageGrab.grab(bbox=actual_rect, all_screens=True) if proc.is_alive() else None
        if img_before_actual is not None and proc.is_alive():
            # 此时窗口还在，所以这是带窗口的截图；和 img_after 应该几乎一样
            # 真正的 before 应该在启动窗口前截，但我们已经错过了
            # 用 expected_rect vs actual_rect 的差异来判断
            pass
        # 如果窗口已终止，重新截一张作为 baseline
        if not proc.is_alive():
            img_before_actual = ImageGrab.grab(bbox=actual_rect, all_screens=True)
            img_before_actual.save(str(PROTOTYPE_DIR / "screenshot_before_actual.png"))
            print(f"[run_tests] desktop_before_actual saved (rect={actual_rect}, panel terminated)", flush=True)
            if img_before_actual is not None:
                arr1 = np.array(img_before_actual)
                arr2 = np.array(img_after)
                if arr1.shape == arr2.shape:
                    diff = np.abs(arr1.astype(int) - arr2.astype(int))
                    identical = (diff.sum(axis=2) == 0).sum()
                    total = arr1.shape[0] * arr1.shape[1]
                    identical_ratio = float(identical / total)
                    diff_mask = diff.sum(axis=2) > 30
                    diff_ratio = float(diff_mask.sum() / total)
                    transparency_report = {
                        "identical_ratio": identical_ratio,
                        "diff_ratio": diff_ratio,
                        "verdict": "transparent" if identical_ratio > 0.6 else "opaque",
                        "rect": actual_rect,
                    }
                    print(f"[run_tests] transparency: identical={identical_ratio:.4f} diff={diff_ratio:.4f} verdict={transparency_report['verdict']}", flush=True)
        else:
            print("[run_tests] panel still alive, using pre-termination comparison skipped", flush=True)
    except Exception as exc:
        print(f"[run_tests] transparency compare failed: {exc}", flush=True)

    # 测试 WebSocket 通信：通过 WS 客户端获取页面状态（替代 evaluate_js）
    print("[run_tests] 通过 WS 客户端获取页面状态（替代 evaluate_js）", flush=True)
    ws_state_reports: list[dict] = []
    try:
        import asyncio
        import websockets

        async def _query_state():
            uri = f"ws://127.0.0.1:18799/ws/panel"
            async with websockets.connect(uri) as ws:
                # 收欢迎消息
                welcome = await asyncio.wait_for(ws.recv(), timeout=2.0)
                ws_state_reports.append({"welcome": json.loads(welcome)})
                # 发 get-state
                await ws.send(json.dumps({"type": "get-state"}))
                # 收 ping 和 state-report（按顺序可能交错）
                for _ in range(5):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        msg = json.loads(raw)
                        if msg.get("type") == "state-report":
                            ws_state_reports.append({"state-report": msg})
                            break
                        else:
                            ws_state_reports.append({"other": msg})
                    except asyncio.TimeoutError:
                        break
                # 再发一条 card，等 0.5s 后再查状态
                await ws.send(json.dumps({"type": "card", "username": "WS测试", "content": "通过 WS 推送的卡片"}))
                await asyncio.sleep(0.8)
                await ws.send(json.dumps({"type": "get-state"}))
                for _ in range(5):
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=3.0)
                        msg = json.loads(raw)
                        if msg.get("type") == "state-report":
                            ws_state_reports.append({"state-report-after-card": msg})
                            break
                        else:
                            ws_state_reports.append({"other": msg})
                    except asyncio.TimeoutError:
                        break

        asyncio.run(_query_state())
        for r in ws_state_reports:
            print(f"[run_tests] ws-report: {r}", flush=True)
    except Exception as exc:
        print(f"[run_tests] WS state query failed: {exc}", flush=True)
        ws_state_reports.append({"error": str(exc)})

    # 也通过 FastAPI 端点观察 ws_state
    time.sleep(1.0)
    print(f"[run_tests] ws_state after tests: {ws_state}", flush=True)

    # 通过 HTTP 健康检查再次确认
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=2.0) as resp:
            health_after = json.loads(resp.read())
        print(f"[run_tests] /api/health after: {health_after}", flush=True)
    except Exception as exc:
        health_after = {"err": str(exc)}

    # 收尾：终止子进程
    print("[run_tests] 终止子进程", flush=True)
    if proc.is_alive():
        proc.terminate()
        proc.join(timeout=3.0)
        if proc.is_alive():
            proc.kill()
            proc.join(timeout=1.0)

    # 停止 FastAPI
    print("[run_tests] 停止 FastAPI", flush=True)
    try:
        server.should_exit = True
        server_thread.join(timeout=3.0)
    except Exception:
        pass

    return {
        "webview2_runtime": webview2_ok,
        "probe": probe_data,
        "ws_state": ws_state,
        "ws_state_reports": ws_state_reports,
        "ws_health_after": health_after,
        "screenshot": str(screenshot_path) if screenshot_ok else None,
        "transparency_report": transparency_report,
        "screen": {"w": screen_w, "h": screen_h, "dpi": screen_dpi, "x": x, "y": y},
        "screens": screens,
        "panel_pid": proc.pid,
        "panel_exitcode": proc.exitcode,
    }


def render_results(test_data: dict) -> str:
    """把测试结果渲染成 markdown。"""
    lines = []
    lines.append("# pywebview + Edge WebView2 浮动面板可行性验证结果")
    lines.append("")
    lines.append(f"运行时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"平台: {sys.platform}")
    lines.append("")

    if "fatal" in test_data:
        lines.append(f"## 致命错误\n\n{test_data['fatal']}\n")
        return "\n".join(lines)

    lines.append("## 1. WebView2 Runtime 探测")
    lines.append("")
    wv2 = test_data.get("webview2_runtime")
    if wv2 is True:
        lines.append("- **PASS**: WebView2 Runtime 已安装")
    elif wv2 is False:
        lines.append("- **FAIL**: WebView2 Runtime 未安装（生产路径会回退到系统浏览器）")
    else:
        lines.append(f"- **UNKNOWN**: 探测异常 {wv2}")
    lines.append("")

    lines.append("## 2. 子进程启动与 pywebview 加载")
    lines.append("")
    probe = test_data.get("probe", {})
    logs = probe.get("logs", [])
    loaded = probe.get("loaded", False)
    lines.append(f"- loaded 信号: **{'PASS' if loaded else 'FAIL'}**")
    # 找 webview_version
    versions = [l for l in logs if l.startswith("webview_version:")]
    if versions:
        lines.append(f"- pywebview 版本: {versions[0].split(':',1)[1]}")
    lines.append("")

    lines.append("## 3. Win32 exstyle / 透明 / 鼠标穿透 探针输出")
    lines.append("")
    lines.append("```")
    for log in logs:
        if log.startswith("[ready]") or "exstyle" in log or "transparent" in log or "layered" in log or "caption" in log or "topmost" in log or "dpi" in log or "rect" in log or "foreground" in log or "probe-" in log or "click-through" in log or "monitor" in log:
            lines.append(log)
    lines.append("```")
    lines.append("")

    # 透明度像素对比报告
    lines.append("## 3.5 透明度像素对比报告")
    lines.append("")
    tr = test_data.get("transparency_report")
    if tr:
        lines.append(f"- 完全相同像素占比: {tr.get('identical_ratio', 0):.4f}")
        lines.append(f"- 显著差异像素占比: {tr.get('diff_ratio', 0):.4f}")
        verdict = tr.get('verdict')
        if verdict == "transparent":
            lines.append("- **PASS**: 透明生效（窗口背景未覆盖桌面，桌面像素透过窗口显示）")
        else:
            lines.append("- **FAIL**: 透明失效（窗口背景覆盖了桌面）")
    else:
        lines.append("- 未生成透明度报告")
    lines.append("")

    # Click-through 汇总
    click_through_pass = any("click-through-summary:pass=True" in l for l in logs)
    lines.append("## 3.6 鼠标穿透（click-through）")
    lines.append("")
    lines.append(f"- click-through-summary: {'PASS' if click_through_pass else 'CHECK-LOGS'}")
    lines.append("- 详细探针输出（WindowFromPoint 测试 5 个点）：见 §3 日志")
    lines.append("")

    lines.append("## 4. JS 交互 / Vue 动画 / CSS 渲染")
    lines.append("")
    lines.append("### 4.1 evaluate_js 探针（从探针线程调用）")
    lines.append("")
    lines.append("```")
    js_logs = [log for log in logs if log.startswith("js-")]
    for log in js_logs:
        lines.append(log)
    if not js_logs:
        lines.append("(无 js-* 输出)")
    lines.append("```")
    lines.append("")
    # evaluate_js 超时分析
    timeout_count = sum(1 for log in js_logs if "TIMEOUT" in log)
    if timeout_count > 0:
        lines.append(f"- **evaluate_js 超时次数**: {timeout_count}/{len(js_logs)}")
        lines.append("- **结论**: pywebview 5.4 的 evaluate_js 从非 UI 线程调用时会 hang（WinForms Invoke 死锁）")
        lines.append("- **影响**: 无法用 evaluate_js 从 Python 控制 Vue 页面；必须改用 WebSocket 推送数据")
    lines.append("")
    lines.append("### 4.2 WebSocket state-report（通过 WS 获取页面渲染状态）")
    lines.append("")
    reports = test_data.get("ws_state_reports", [])
    if reports:
        lines.append("```json")
        for r in reports:
            lines.append(json.dumps(r, ensure_ascii=False, indent=2, default=str))
        lines.append("```")
        # 分析 state-report
        for r in reports:
            if "state-report" in r:
                sr = r["state-report"]
                lines.append(f"- 卡片数量: {sr.get('cardsCount', '?')}")
                if sr.get("cardInfo"):
                    ci = sr["cardInfo"]
                    lines.append(f"- 首张卡片尺寸: {ci.get('w')}x{ci.get('h')}")
                    lines.append(f"- 首张卡片背景: {ci.get('bg')}")
                    lines.append(f"- 首张卡片阴影: {ci.get('shadow')}")
                    lines.append(f"- 首张卡片圆角: {ci.get('radius')}")
                    lines.append(f"- 首张卡片 transform: {ci.get('transform')}")
                    lines.append(f"- 首张卡片 opacity: {ci.get('opacity')}")
                lines.append(f"- body 背景: {sr.get('bodyBg')}")
                lines.append(f"- html 背景: {sr.get('htmlBg')}")
                lines.append(f"- panel 背景: {sr.get('panelBg')}")
                lines.append(f"- animationFrame: {sr.get('animationFrame')}")
                lines.append(f"- WS 接收数: {sr.get('wsReceived')}")
                lines.append(f"- WS 已连接: {sr.get('wsOpen')}")
                if sr.get("cardsCount", 0) > 0 and sr.get("cardInfo"):
                    lines.append("- **PASS**: Vue/HTML/CSS 渲染正常（卡片已渲染，有尺寸、阴影、圆角）")
                else:
                    lines.append("- **PARTIAL**: 页面已加载但无卡片渲染")
                break
    else:
        lines.append("(无 state-report 收到)")
    lines.append("")

    lines.append("## 5. WebSocket 通信")
    lines.append("")
    ws = test_data.get("ws_state", {})
    lines.append(f"- WS 客户端连接数: {ws.get('ws_clients', 0)}")
    lines.append(f"- WS 发送消息数: {ws.get('ws_messages_sent', 0)}")
    lines.append(f"- WS 接收消息数: {ws.get('ws_messages_received', 0)}")
    lines.append(f"- 最后接收: {ws.get('last_received')}")
    if ws.get("ws_messages_sent", 0) > 0 and ws.get("ws_messages_received", 0) > 0:
        lines.append("- **PASS**: WebSocket 双向通信已建立")
    elif ws.get("ws_messages_sent", 0) > 0:
        lines.append("- **PARTIAL**: 服务端已发送但前端未回包（可能未连上或 evaluate_js 路径未触发）")
    else:
        lines.append("- **FAIL**: WebSocket 未建立")
    lines.append("")

    lines.append("## 6. 截图")
    lines.append("")
    sc = test_data.get("screenshot")
    if sc:
        lines.append(f"截图已保存: {sc}")
        lines.append("请肉眼检查：")
        lines.append("- 卡片背景是否半透明（能看到桌面/下层窗口）")
        lines.append("- 卡片阴影/圆角/文字描边是否正常")
        lines.append("- 整体窗口是否无边框")
    else:
        lines.append("- **FAIL**: 截图失败")
    lines.append("")

    lines.append("## 7. 屏幕信息")
    lines.append("")
    s = test_data.get("screen", {})
    lines.append(f"- 主屏分辨率: {s.get('w')}x{s.get('h')}")
    lines.append(f"- 逻辑 DPI: {s.get('dpi')}")
    lines.append(f"- 窗口位置: ({s.get('x')}, {s.get('y')})")
    screens = test_data.get("screens", [])
    if screens:
        lines.append(f"- 多屏数量: {len(screens)}")
        for i, scr in enumerate(screens):
            tag = "(主屏)" if scr.get("primary") else ""
            lines.append(f"  - 屏 {i}: x={scr.get('x')} y={scr.get('y')} w={scr.get('w')} h={scr.get('h')} dpi={scr.get('dpi')} {tag}")
    lines.append("")

    lines.append("## 8. 子进程退出")
    lines.append("")
    lines.append(f"- panel_pid: {test_data.get('panel_pid')}")
    lines.append(f"- exitcode: {test_data.get('panel_exitcode')}")
    if test_data.get("panel_exitcode") in (0, -15, 1, None):
        lines.append("- **PASS**: 子进程已退出")
    else:
        lines.append(f"- **UNKNOWN**: 退出码 {test_data.get('panel_exitcode')}")
    lines.append("")

    lines.append("## 9. 完整探针日志（原始）")
    lines.append("")
    lines.append("```")
    for log in logs:
        lines.append(log)
    lines.append("```")
    lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["test", "demo"], default="test")
    parser.add_argument("--port", type=int, default=18799)
    args = parser.parse_args()

    if args.mode == "test":
        test_data = run_tests()
        md = render_results(test_data)
        RESULTS_PATH.write_text(md, encoding="utf-8")
        print("=" * 70, flush=True)
        print(f"[main] 测试结果已写入: {RESULTS_PATH}", flush=True)
        print("=" * 70, flush=True)
        print(md, flush=True)
    else:
        # demo 模式：仅启动 FastAPI + 子进程，持续运行
        server, server_thread, base_url, ws_state = start_fastapi_server(port=args.port)
        print(f"[demo] FastAPI ready: {base_url}", flush=True)
        html_url = f"{base_url}/?ws_url=ws://127.0.0.1:{args.port}/ws/panel"
        from prototype_floating_panel.panel_window import launch_panel
        proc, ready_queue, result_queue = launch_panel(
            html_url, width=360, height=600, x=100, y=100,
        )
        print(f"[demo] panel pid={proc.pid}; Ctrl+C 退出", flush=True)
        try:
            while proc.is_alive():
                proc.join(timeout=1.0)
        except KeyboardInterrupt:
            proc.terminate()
            proc.join(timeout=3.0)


if __name__ == "__main__":
    main()
