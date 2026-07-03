"""直播网页弹幕层路由：透明页、SSE 推送、测试弹幕。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /live-overlay.html``：返回透明背景的 HTML（OBS/直播伴侣作为网页源叠加）。
- ``GET /api/live-overlay/events``：SSE 流（``text/event-stream``），由
  ``app.live_overlay_hub.LiveOverlayHub`` 推送实时弹幕。
- ``POST /api/live-overlay/test``：发送测试弹幕（仅调试用）。

注册方式：``app.web_api.routes`` 调用 ``register_live_overlay_routes(app, bridge, check_token)``。
本模块仅做 HTTP 路由 + SSE 响应包装，业务逻辑在 ``LiveOverlayHub``。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Callable

from fastapi import Body, Header, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from app.bundle_paths import resource_path
from app.live_overlay_hub import LiveOverlayHub
from app.web_api.auth import require_auth

STATIC_DIR = resource_path("web", "static")
LIVE_OVERLAY_HTML = STATIC_DIR / "live-overlay.html"


class LiveOverlayTestPayload(BaseModel):
    items: list[str] | None = None


def register_live_overlay_routes(
    app,
    hub: LiveOverlayHub,
    base_url: str,
    check_token: Callable,
) -> None:
    @app.get("/live-overlay")
    def live_overlay_page():
        if not LIVE_OVERLAY_HTML.is_file():
            raise HTTPException(status_code=404, detail="live-overlay.html missing")
        return FileResponse(
            LIVE_OVERLAY_HTML,
            headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
        )

    @app.get("/api/live-overlay/status")
    def live_overlay_status():
        out = hub.snapshot()
        out["overlay_url"] = f"{base_url.rstrip('/')}/live-overlay"
        return out

    @app.post("/api/live-overlay/test")
    @require_auth(check_token)
    def live_overlay_test(
        body: LiveOverlayTestPayload | None = Body(default=None),
        authorization: str | None = Header(default=None),
    ):
        items = body.items if body and body.items else None
        hub.broadcast_test(items)
        return {"ok": True, "count": len(items) if items else 2}

    @app.get("/api/live-overlay/events")
    async def live_overlay_events():
        queue: asyncio.Queue = asyncio.Queue(maxsize=64)
        hub.register(queue)

        async def event_stream():
            try:
                hello = json.dumps(
                    {"event": "hello", "ts": time.time()},
                    ensure_ascii=False,
                )
                yield f"event: hello\ndata: {hello}\n\n"
                for replay in hub.recent_items():
                    replay_data = json.dumps(replay, ensure_ascii=False)
                    yield f"data: {replay_data}\n\n"
                while True:
                    payload = await queue.get()
                    data = json.dumps(payload, ensure_ascii=False)
                    yield f"data: {data}\n\n"
            finally:
                hub.unregister(queue)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
