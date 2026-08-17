"""External Live2D model Web API routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header

from app.web_api import live2d as live2d_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


def register_live2d_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.get("/api/live2d/model")
    def get_live2d_model():
        return live2d_api.get_model_snapshot(bridge.danmu_app)

    @app.post("/api/live2d/import-model")
    @require_auth(check_token)
    def post_live2d_import_model(authorization: str | None = Header(default=None)):
        return invoke_main(live2d_api.import_model_via_dialog, bridge.danmu_app)

    @app.post("/api/live2d/clear-model")
    @require_auth(check_token)
    def post_live2d_clear_model(authorization: str | None = Header(default=None)):
        return invoke_main(live2d_api.clear_model, bridge.danmu_app)
