"""External Live2D model Web API routes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header, HTTPException
from fastapi.responses import Response

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

    @app.post("/api/live2d/import-model-file")
    @require_auth(check_token)
    def post_live2d_import_model_file(authorization: str | None = Header(default=None)):
        return invoke_main(live2d_api.import_model_file_via_dialog, bridge.danmu_app)

    @app.post("/api/live2d/clear-model")
    @require_auth(check_token)
    def post_live2d_clear_model(authorization: str | None = Header(default=None)):
        return invoke_main(live2d_api.clear_model, bridge.danmu_app)

    @app.post("/api/live2d/start")
    @require_auth(check_token)
    def post_live2d_start(authorization: str | None = Header(default=None)):
        try:
            return invoke_main(live2d_api.start_model, bridge.danmu_app)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/live2d/stop")
    @require_auth(check_token)
    def post_live2d_stop(authorization: str | None = Header(default=None)):
        return invoke_main(live2d_api.stop_model, bridge.danmu_app)

    @app.get("/api/live2d/resource/{resource_path:path}")
    def get_live2d_resource(resource_path: str):
        try:
            content, media_type = live2d_api.get_model_resource(
                bridge.danmu_app,
                resource_path,
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return Response(content=content, media_type=media_type)
