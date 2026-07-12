"""诊断 Web API 路由注册（GET /api/diagnostics 与 SSE）。"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Callable

from fastapi import Header
from fastapi.responses import StreamingResponse

from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge

# W-MEDLOW-002：诊断 SSE 推送间隔（秒）；与 GET /api/diagnostics 解耦，仅控制流式刷新节奏。
DIAGNOSTICS_SSE_INTERVAL_SEC = 2.5


def register_diagnostics_routes(app, bridge: "WebConsoleBridge", check_token: Callable) -> None:
    @app.get("/api/diagnostics")
    @require_auth(check_token)
    def get_diagnostics(authorization: str | None = Header(default=None)):
        # 只读诊断；调度/timing 数据经 DanmuApp 公开入口，不读 _last_api_trigger_at 等私有字段
        return {
            "ok": True,
            "diagnostics": bridge.danmu_app.build_diagnostic_snapshot(),
        }


def register_diagnostics_sse_route(app, diagnostics_hub, bridge, check_token) -> None:
    """注册 /api/diagnostics/events SSE 端点。

    推送初始 hello 事件、初始诊断快照，随后每 2.5 秒推送更新快照。
    与 /api/diagnostics GET 一致，需要 Bearer 鉴权（Authorization header）。
    """

    @app.get("/api/diagnostics/events")
    @require_auth(check_token)
    async def diagnostics_events(authorization: str | None = Header(default=None)):
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        diagnostics_hub.register(queue)

        async def event_stream():
            try:
                hello = json.dumps(
                    {"event": "hello", "ts": time.time()},
                    ensure_ascii=False,
                )
                yield f"event: hello\ndata: {hello}\n\n"

                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None,
                    lambda: bridge.invoke_on_main(bridge.publish_diagnostic_snapshot),
                )

                while True:
                    try:
                        item = await asyncio.wait_for(
                            queue.get(), timeout=DIAGNOSTICS_SSE_INTERVAL_SEC
                        )
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
                        continue
                    snapshot = item.get("data") if isinstance(item, dict) else None
                    if snapshot is None:
                        continue
                    snapshot_data = json.dumps(snapshot, ensure_ascii=False)
                    yield f"event: diagnostic_snapshot\ndata: {snapshot_data}\n\n"
            finally:
                diagnostics_hub.unregister(queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
