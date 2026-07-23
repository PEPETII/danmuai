"""最小 FastAPI WebSocket 测试：隔离 WS 服务端是否真的工作。

逐步排查：
1. 启动 FastAPI + uvicorn 显式 ws="websockets"
2. HTTP GET /api/health 确认服务可达
3. 用 websockets 库客户端连 /ws/panel
4. 用 aiohttp 客户端连 /ws/panel 作为对照
"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def start_server(port: int):
    """启动最小 FastAPI 服务（uvicorn ws=websockets 显式）。"""
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    import uvicorn

    app = FastAPI()
    state = {"ws_clients": 0, "ws_msgs_sent": 0, "ws_msgs_recv": 0}

    @app.get("/api/health")
    def health():
        return {"ok": True, "state": state}

    @app.websocket("/ws/panel")
    async def ws_panel(websocket: WebSocket):
        print(f"[server] ws_panel called, client={websocket.client}", flush=True)
        try:
            await websocket.accept()
            print("[server] ws_panel accepted", flush=True)
        except Exception as exc:
            print(f"[server] ws_panel accept failed: {exc!r}", flush=True)
            return
        state["ws_clients"] += 1
        try:
            await websocket.send_json({"type": "welcome"})
            state["ws_msgs_sent"] += 1
            while True:
                msg = await websocket.receive_json()
                state["ws_msgs_recv"] += 1
                print(f"[server] recv: {msg}", flush=True)
                await websocket.send_json({"type": "echo", "data": msg})
                state["ws_msgs_sent"] += 1
        except WebSocketDisconnect:
            print("[server] ws_panel client disconnected", flush=True)
        except Exception as exc:
            print(f"[server] ws_panel error: {exc!r}", flush=True)
        finally:
            state["ws_clients"] -= 1

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",  # 提高日志级别看清楚 WS 握手过程
        access_log=True,
        ws="websockets",  # 显式指定 ws 实现
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    ready = threading.Event()

    original_startup = server.startup
    async def patched_startup(*args, **kwargs):
        res = await original_startup(*args, **kwargs)
        if server.started:
            ready.set()
        return res
    server.startup = patched_startup

    def _run():
        try:
            server.run()
        except Exception as exc:
            print(f"[server] uvicorn failed: {exc!r}", flush=True)
            ready.set()

    t = threading.Thread(target=_run, name="TestServer", daemon=True)
    t.start()
    ready.wait(timeout=5.0)
    return server, t, state


def test_http(base_url: str):
    """1. HTTP 健康检查。"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=2.0) as resp:
            data = json.loads(resp.read())
        print(f"[http] /api/health: {data}", flush=True)
        return True
    except Exception as exc:
        print(f"[http] /api/health failed: {exc!r}", flush=True)
        return False


async def test_ws_websockets_lib(url: str):
    """2. 用 websockets 库客户端测试。"""
    print(f"\n[ws-websockets] connecting to {url}", flush=True)
    try:
        import websockets
        async with websockets.connect(url, open_timeout=5.0) as ws:
            print("[ws-websockets] connected", flush=True)
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f"[ws-websockets] received: {msg}", flush=True)
            await ws.send(json.dumps({"type": "ping", "t": time.time()}))
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f"[ws-websockets] received: {msg}", flush=True)
            return True
    except Exception as exc:
        print(f"[ws-websockets] failed: {exc!r}", flush=True)
        return False


async def test_ws_aiohttp(url: str):
    """3. 用 aiohttp 客户端测试（对照）。"""
    print(f"\n[ws-aiohttp] connecting to {url}", flush=True)
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url, timeout=5.0) as ws:
                print("[ws-aiohttp] connected", flush=True)
                msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                print(f"[ws-aiohttp] received: {msg}", flush=True)
                await ws.send_json({"type": "ping", "t": time.time()})
                msg = await asyncio.wait_for(ws.receive_json(), timeout=2.0)
                print(f"[ws-aiohttp] received: {msg}", flush=True)
                return True
    except ImportError:
        print("[ws-aiohttp] aiohttp not installed, skipping", flush=True)
        return None
    except Exception as exc:
        print(f"[ws-aiohttp] failed: {exc!r}", flush=True)
        return False


def main():
    port = 18800
    print(f"[main] starting server on port {port}", flush=True)
    server, t, state = start_server(port=port)
    base_url = f"http://127.0.0.1:{port}"
    print(f"[main] server ready: {base_url}", flush=True)
    print(f"[main] initial state: {state}", flush=True)

    # 让服务稳定一下
    time.sleep(0.5)

    # 1. HTTP 测试
    http_ok = test_http(base_url)

    # 2. WS 测试 - websockets 库
    ws_url = f"ws://127.0.0.1:{port}/ws/panel"
    ws_ok = asyncio.run(test_ws_websockets_lib(ws_url))

    # 3. WS 测试 - aiohttp
    aiohttp_ok = asyncio.run(test_ws_aiohttp(ws_url))

    print(f"\n[main] HTTP /api/health: {'PASS' if http_ok else 'FAIL'}", flush=True)
    print(f"[main] WS websockets: {'PASS' if ws_ok else 'FAIL'}", flush=True)
    print(f"[main] WS aiohttp: {aiohttp_ok}", flush=True)
    print(f"[main] final state: {state}", flush=True)

    server.should_exit = True
    t.join(timeout=3.0)


if __name__ == "__main__":
    main()
