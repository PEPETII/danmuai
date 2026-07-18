"""诊断 Web API 路由注册（GET /api/diagnostics）。

面板专用 SSE（/api/diagnostics/events）已于 W-DIAGNOSTICS-PANEL-REMOVE-001 移除。
错误上报仍依赖本 GET 端点。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header

from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


def register_diagnostics_routes(app, bridge: "WebConsoleBridge", check_token: Callable) -> None:
    @app.get("/api/diagnostics")
    @require_auth(check_token)
    def get_diagnostics(authorization: str | None = Header(default=None)):
        # 只读诊断；调度/timing 数据经 DanmuApp 公开入口，不读 _last_api_trigger_at 等私有字段
        return {
            "ok": True,
            "diagnostics": bridge.danmu_app.build_diagnostic_snapshot(),
        }
