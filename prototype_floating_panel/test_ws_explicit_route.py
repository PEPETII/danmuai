"""用生产代码的 WebSocketRoute 注册方式 + 调试 starlette 路由匹配。"""
from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def start_server_with_explicit_route(port: int):
    """显式 WebSocketRoute 注册（生产代码风格）。"""
    from fastapi import FastAPI, WebSocket
    from starlette.routing import WebSocketRoute
    from starlette.websockets import WebSocketDisconnect
    import uvicorn

    app = FastAPI()
    state = {"ws_clients": 0, "ws_msgs_sent": 0, "ws_msgs_recv": 0}

    @app.get("/api/health")
    def health():
        return {"ok": True, "state": state, "routes": [r.path for r in app.router.routes if hasattr(r, 'path')]}

    async def ws_panel(websocket: WebSocket):
        print(f"[explicit-route] ws_panel called", flush=True)
        try:
            await websocket.accept()
            print("[explicit-route] accepted", flush=True)
        except Exception as exc:
            print(f"[explicit-route] accept failed: {exc!r}", flush=True)
            return
        state["ws_clients"] += 1
        try:
            await websocket.send_json({"type": "welcome"})
            state["ws_msgs_sent"] += 1
            while True:
                msg = await websocket.receive_json()
                state["ws_msgs_recv"] += 1
                print(f"[explicit-route] recv: {msg}", flush=True)
                await websocket.send_json({"type": "echo", "data": msg})
                state["ws_msgs_sent"] += 1
        except WebSocketDisconnect:
            print("[explicit-route] disconnected", flush=True)
        except Exception as exc:
            print(f"[explicit-route] error: {exc!r}", flush=True)
        finally:
            state["ws_clients"] -= 1

    # 生产代码风格：显式 insert
    app.router.routes.insert(0, WebSocketRoute("/ws/panel", endpoint=ws_panel))
    print(f"[setup] routes after insert: {[r.path for r in app.router.routes if hasattr(r, 'path')]}", flush=True)

    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="info",
        access_log=True,
        ws="websockets",
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
            print(f"[server] failed: {exc!r}", flush=True)
            ready.set()

    t = threading.Thread(target=_run, daemon=True, name="ExplicitRoute")
    t.start()
    ready.wait(timeout=5.0)
    return server, t, state


def test_http(base_url: str):
    import urllib.request
    try:
        with urllib.request.urlopen(f"{base_url}/api/health", timeout=2.0) as resp:
            data = json.loads(resp.read())
        print(f"[http] /api/health: {data}", flush=True)
        return True
    except Exception as exc:
        print(f"[http] failed: {exc!r}", flush=True)
        return False


async def test_ws(url: str):
    print(f"\n[ws-client] connecting to {url}", flush=True)
    try:
        import websockets
        async with websockets.connect(url, open_timeout=5.0) as ws:
            print("[ws-client] connected", flush=True)
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f"[ws-client] received: {msg}", flush=True)
            await ws.send(json.dumps({"type": "ping", "t": time.time()}))
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f"[ws-client] received: {msg}", flush=True)
            return True
    except Exception as exc:
        print(f"[ws-client] failed: {exc!r}", flush=True)
        return False


def main():
    port = 18802
    print(f"[main] starting server on port {port}", flush=True)
    server, t, state = start_server_with_explicit_route(port=port)
    base_url = f"http://127.0.0.1:{port}"
    print(f"[main] server ready: {base_url}", flush=True)

    time.sleep(0.5)
    test_http(base_url)
    ws_url = f"ws://127.0.0.1:{port}/ws/panel"
    ok = asyncio.run(test_ws(ws_url))

    print(f"\n[main] WS test: {'PASS' if ok else 'FAIL'}", flush=True)
    print(f"[main] final state: {state}", flush=True)

    server.should_exit = True
    t.join(timeout=3.0)


if __name__ == "__main__":
    main()
