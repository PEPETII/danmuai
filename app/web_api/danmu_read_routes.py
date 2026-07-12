"""读弹幕 Web API 路由注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header
from pydantic import BaseModel

from app.web_api import danmu_read as read_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


class DanmuReadConfigPayload(BaseModel):
    enabled: bool | None = None
    interval_sec: int | None = None
    voice: str | None = None
    style_prompt: str | None = None
    api_key: str | None = None
    provider: str | None = None
    endpoint: str | None = None
    model_id: str | None = None
    custom_endpoint: str | None = None
    custom_model_id: str | None = None


class DanmuReadProbePayload(BaseModel):
    api_key: str | None = None
    provider: str | None = None
    endpoint: str | None = None
    model_id: str | None = None
    custom_endpoint: str | None = None
    custom_model_id: str | None = None


def register_danmu_read_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.get("/api/danmu-read/config")
    def get_danmu_read_config():
        return read_api.get_config(bridge.danmu_app)

    @app.get("/api/danmu-read/catalog")
    def get_danmu_read_catalog():
        return read_api.get_catalog()

    @app.put("/api/danmu-read/config")
    @require_auth(check_token)
    def put_danmu_read_config(
        body: DanmuReadConfigPayload,
        authorization: str | None = Header(default=None),
    ):
        payload = read_api.normalize_put_payload(body.model_dump(exclude_none=True))
        return invoke_main(read_api.save_config, bridge.danmu_app, payload)

    @app.post("/api/danmu-read/probe")
    @require_auth(check_token)
    def post_danmu_read_probe(
        body: DanmuReadProbePayload | None = None,
        authorization: str | None = Header(default=None),
    ):
        payload = body.model_dump(exclude_none=True) if body else {}
        return invoke_main(read_api.run_probe, bridge.danmu_app, payload)
