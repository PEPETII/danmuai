"""识图区域 Web API 路由注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header

from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


def register_capture_region_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
) -> None:
    @app.get("/api/capture-region")
    def get_capture_region():
        return bridge.danmu_app.get_capture_region_status()

    @app.post("/api/capture-region/select")
    @require_auth(check_token)
    def post_capture_region_select(
        authorization: str | None = Header(default=None),
    ):
        current = bridge.danmu_app.get_capture_region_status()
        if current.get("selection_state") == "selecting":
            return {"ok": True, "selection_state": "selecting"}
        bridge.region_select_requested.emit()
        return {"ok": True, "selection_state": "selecting"}

    @app.post("/api/capture-region/reset")
    @require_auth(check_token)
    def post_capture_region_reset(
        authorization: str | None = Header(default=None),
    ):
        bridge.region_reset_requested.emit()
        return {"ok": True}
