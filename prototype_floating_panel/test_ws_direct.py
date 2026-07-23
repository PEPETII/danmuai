"""直接测试 FastAPI WebSocket 端点，确认服务端是否正常。"""
import asyncio
import json
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from prototype_floating_panel.run_prototype import start_fastapi_server


async def ws_client_test(url: str):
    import websockets
    try:
        async with websockets.connect(url) as ws:
            print(f"[ws-client] connected to {url}", flush=True)
            # 接收欢迎消息
            msg = await asyncio.wait_for(ws.recv(), timeout=2.0)
            print(f"[ws-client] received: {msg}", flush=True)
            # 等待 ping 并回 pong
            for _ in range(3):
                msg = await asyncio.wait_for(ws.recv(), timeout=3.0)
                data = json.loads(msg)
                print(f"[ws-client] received: {data}", flush=True)
                if data.get("type") == "ping":
                    await ws.send(json.dumps({"type": "pong", "t": time.time()}))
                    print(f"[ws-client] sent pong", flush=True)
            return True
    except Exception as exc:
        print(f"[ws-client] failed: {exc!r}", flush=True)
        return False


def main():
    server, t, base_url, state = start_fastapi_server(port=18799)
    print(f"[main] server ready: {base_url}", flush=True)
    print(f"[main] initial state: {state}", flush=True)

    # 直接 WS 客户端测试
    url = "ws://127.0.0.1:18799/ws/panel"
    ok = asyncio.run(ws_client_test(url))
    print(f"[main] ws test result: {ok}", flush=True)
    print(f"[main] final state: {state}", flush=True)

    server.should_exit = True
    t.join(timeout=3.0)


if __name__ == "__main__":
    main()
