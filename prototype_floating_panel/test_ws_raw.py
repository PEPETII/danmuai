"""用原始 websockets 库做服务端，绕过 uvicorn/starlette，隔离 Python 3.14 兼容性问题。"""
from __future__ import annotations

import asyncio
import json
import threading
import time


async def raw_ws_handler(websocket):
    """原始 websockets 库的 handler。"""
    print(f"[raw-server] connection from {websocket.remote_address}", flush=True)
    try:
        await websocket.send(json.dumps({"type": "welcome"}))
        async for msg in websocket:
            data = json.loads(msg)
            print(f"[raw-server] recv: {data}", flush=True)
            await websocket.send(json.dumps({"type": "echo", "data": data}))
    except Exception as exc:
        print(f"[raw-server] error: {exc!r}", flush=True)


def start_raw_server(port: int):
    """启动原始 websockets 服务器（线程中）。"""
    import websockets
    print(f"[raw-server] starting on port {port}", flush=True)
    
    ready = threading.Event()
    server_holder = {}
    
    async def _serve():
        async with websockets.serve(raw_ws_handler, "127.0.0.1", port):
            print(f"[raw-server] listening", flush=True)
            ready.set()
            await asyncio.Future()  # 永远阻塞
    
    def _run():
        try:
            asyncio.run(_serve())
        except Exception as exc:
            print(f"[raw-server] failed: {exc!r}", flush=True)
            ready.set()
    
    t = threading.Thread(target=_run, daemon=True, name="RawWsServer")
    t.start()
    ready.wait(timeout=5.0)
    return t


async def test_ws_client(url: str):
    """测试客户端。"""
    print(f"\n[client] connecting to {url}", flush=True)
    try:
        import websockets
        async with websockets.connect(url, open_timeout=5.0) as ws:
            print("[client] connected", flush=True)
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f"[client] received: {msg}", flush=True)
            await ws.send(json.dumps({"type": "ping", "t": time.time()}))
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f"[client] received: {msg}", flush=True)
            return True
    except Exception as exc:
        print(f"[client] failed: {exc!r}", flush=True)
        return False


def main():
    port = 18801
    t = start_raw_server(port=port)
    time.sleep(0.3)
    url = f"ws://127.0.0.1:{port}"
    ok = asyncio.run(test_ws_client(url))
    print(f"\n[main] raw websockets server test: {'PASS' if ok else 'FAIL'}", flush=True)


if __name__ == "__main__":
    main()
