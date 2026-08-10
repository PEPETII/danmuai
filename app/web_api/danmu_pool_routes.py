"""公式化弹幕池 Web API 路由注册。

路由（由 ``app.web_api.routes`` 调用 ``register_danmu_pool_routes``）：
- ``GET /api/danmu-pool/meta`` / ``PUT /api/danmu-pool/settings``：元信息与开关
- ``POST /api/danmu-pool/custom/refresh``：重新扫描 TXT 句库
- ``POST /api/danmu-pool/custom/open-folder``：在资源管理器中打开 TXT 目录
- ``POST /api/test/danmu``：测试弹幕注入

写操作经 ``invoke_main``（``WebConsoleBridge.invoke_on_main`` 包装）回到主线程。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header
from pydantic import BaseModel

from app.web_api import danmu_pool as pool_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


class DanmuPoolSettingsPayload(BaseModel):
    custom_enabled: bool | None = None
    min_on_screen: int | None = None


class TestDanmuPayload(BaseModel):
    items: list[str]
    persona: str = "测试"


def register_danmu_pool_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.get("/api/danmu-pool/meta")
    def get_danmu_pool_meta():
        return pool_api.get_meta(bridge.danmu_app)

    @app.put("/api/danmu-pool/settings")
    @require_auth(check_token)
    def put_danmu_pool_settings(
        body: DanmuPoolSettingsPayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(pool_api.save_settings, bridge.danmu_app, body.model_dump(exclude_none=True))

    @app.post("/api/danmu-pool/custom/refresh")
    @require_auth(check_token)
    def post_danmu_pool_custom_refresh(authorization: str | None = Header(default=None)):
        return invoke_main(pool_api.refresh_custom_txt_pool, bridge.danmu_app)

    @app.post("/api/danmu-pool/custom/open-folder")
    @require_auth(check_token)
    def post_danmu_pool_custom_open_folder(authorization: str | None = Header(default=None)):
        return invoke_main(pool_api.open_custom_txt_folder, bridge.danmu_app)

    @app.post("/api/test/danmu")
    @require_auth(check_token)
    def post_test_danmu(
        body: TestDanmuPayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(bridge.danmu_app.inject_test_danmu_batch, body.items, persona_id=body.persona)
