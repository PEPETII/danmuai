"""应用更新 Web API 路由注册。"""

from __future__ import annotations

from typing import Callable

from fastapi import Header

from app.web_api import update as update_api
from app.web_api.auth import require_auth


def register_update_routes(app, check_token: Callable) -> None:
    @app.get("/api/update/channels")
    def get_update_channels_route():
        return update_api.get_release_channels()

    @app.get("/api/update/status")
    @require_auth(check_token)
    def get_update_status_route(authorization: str | None = Header(default=None)):
        return update_api.get_update_status()

    @app.post("/api/update/check")
    @require_auth(check_token)
    def post_update_check_route(authorization: str | None = Header(default=None)):
        return update_api.post_update_check()

    @app.post("/api/update/download")
    @require_auth(check_token)
    def post_update_download_route(authorization: str | None = Header(default=None)):
        return update_api.post_update_download()

    @app.post("/api/update/restart")
    @require_auth(check_token)
    def post_update_restart_route(authorization: str | None = Header(default=None)):
        return update_api.post_update_restart()
