"""W-BILILIVE-DM-PLUGIN-BRIDGE-002/003 — bililive_dm 评论事件桥接路由。"""

from __future__ import annotations

import logging
from typing import Annotated, Callable

from fastapi import Body, Header

from app.application.bililive_dm_bridge_service import (
    BililiveDmBridgeRequest,
    BililiveDmBridgeResponse,
    generate_ai_replies,
)
from app.bililive_dm_plugin_auth import PLUGIN_SECRET_HEADER, validate_plugin_secret
from app.errors import AppError

logger = logging.getLogger(__name__)

BRIDGE_PATH = "/api/plugin/bililive-dm/reply"

__all__ = [
    "BRIDGE_PATH",
    "BililiveDmBridgeRequest",
    "BililiveDmBridgeResponse",
    "register_bililive_dm_bridge_route",
]


def _generate_ai_reply(config, payload: BililiveDmBridgeRequest) -> BililiveDmBridgeResponse:
    return generate_ai_replies(config, payload)


def register_bililive_dm_bridge_route(app, config, check_token: Callable) -> None:
    """注册插件评论桥接路由（本机 127.0.0.1 + 插件共享密钥，无 Web Bearer）。"""

    @app.post(BRIDGE_PATH, response_model=BililiveDmBridgeResponse)
    def bililive_dm_reply(
        body: BililiveDmBridgeRequest = Body(...),
        plugin_secret: Annotated[str | None, Header(alias=PLUGIN_SECRET_HEADER)] = None,
    ):
        # 插件侧无 Bearer token；check_token 仅用于注册签名一致性。
        _ = check_token
        validate_plugin_secret(plugin_secret)
        try:
            return _generate_ai_reply(config, body)
        except (AppError, ValueError) as exc:
            logger.warning("bililive_dm_bridge: internal_error %r", exc)
            return BililiveDmBridgeResponse(
                ok=False,
                error=f"internal_error:{type(exc).__name__}",
                items=[],
            )
