"""麦克风 Web API 路由注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header
from pydantic import BaseModel

from app.web_api import mic_test as mic_test_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


class MicTestPayload(BaseModel):
    duration_sec: float = 3.0
    send_to_ai: bool = False


def register_mic_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.post("/api/mic/test")
    @require_auth(check_token)
    def mic_test(
        body: MicTestPayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(
            mic_test_api.run_mic_test,
            bridge.danmu_app,
            body.duration_sec,
            body.send_to_ai,
        )

    @app.get("/api/mic/devices")
    def get_mic_devices():
        return mic_test_api.list_mic_devices(bridge.danmu_app)

    @app.post("/api/mic/test-send")
    @require_auth(check_token)
    def mic_test_send(
        body: MicTestPayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(
            mic_test_api.run_mic_test,
            bridge.danmu_app,
            body.duration_sec,
            True,
        )
