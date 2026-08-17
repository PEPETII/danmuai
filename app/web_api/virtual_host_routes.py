"""虚拟主播模型选择 Web API 路由。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Body, Header, HTTPException

from app.web_api import virtual_host as virtual_host_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


def register_virtual_host_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.get("/api/virtual-host/models")
    def get_virtual_host_models():
        return invoke_main(virtual_host_api.get_model_config, bridge.danmu_app)

    @app.put("/api/virtual-host/models")
    @require_auth(check_token)
    def put_virtual_host_models(
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        del authorization
        try:
            return invoke_main(virtual_host_api.save_model_config, bridge.danmu_app, payload)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
