"""烂梗弹幕 Web API 路由注册。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from fastapi import Header
from pydantic import BaseModel

from app.web_api import meme_barrage as meme_api
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge


class MemeBarrageSettingsPayload(BaseModel):
    enabled: bool | None = None
    category: str | None = None
    tag: list[str] | None = None
    display_mode: str | None = None
    collect_interval_sec: int | None = None
    collect_batch_size: int | None = None
    display_interval_sec: int | None = None
    display_batch_size: int | None = None


def register_meme_barrage_routes(
    app,
    bridge: "WebConsoleBridge",
    check_token: Callable,
    invoke_main: Callable,
) -> None:
    @app.get("/api/meme-barrage/meta")
    def get_meme_barrage_meta():
        return meme_api.get_meta(bridge.danmu_app)

    @app.put("/api/meme-barrage/settings")
    @require_auth(check_token)
    def put_meme_barrage_settings(
        body: MemeBarrageSettingsPayload,
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(
            meme_api.save_settings,
            bridge.danmu_app,
            body.model_dump(exclude_none=True),
        )

    @app.get("/api/meme-barrage/tags")
    def get_meme_barrage_tags():
        return meme_api.get_tags()

    @app.post("/api/meme-barrage/clear")
    @require_auth(check_token)
    def post_meme_barrage_clear(
        authorization: str | None = Header(default=None),
    ):
        return invoke_main(meme_api.clear_library, bridge.danmu_app)
