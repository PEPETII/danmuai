"""W-AIBUTLER-001 — AI管家对话路由。

注册 ``POST /api/ai-butler/chat``：
- 鉴权：需 Bearer token（与 settings 写路由一致）
- 线程模型：HTTP 线程直接跑（LLM 调用是 IO，不触 Qt / 主链路；config 只读快照）
- 入参：``{"messages": [...], "model_id": str?}``
- 出参：``{"ok": True, "reply": str, "tool_calls": list}`` 或 ``{"ok": False, "error": str}``

不执行任何配置变更：变更执行由前端调既有 ``PUT /api/config`` /
``POST /api/custom-models/{index}/default`` 完成（W-003）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from fastapi import Body, Header, HTTPException
from pydantic import BaseModel, Field

from app.application.ai_butler_service import chat as butler_chat

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge

logger = logging.getLogger(__name__)


class AiButlerMessage(BaseModel):
    role: str = "user"
    content: str = ""


class AiButlerChatRequest(BaseModel):
    messages: list[AiButlerMessage] = Field(default_factory=list)
    model_id: str | None = None  # W-001 暂不支持覆盖，保留字段


def register_ai_butler_route(app, bridge: "WebConsoleBridge", check_token: Callable) -> None:
    """注册 AI管家对话路由。"""

    @app.post("/api/ai-butler/chat")
    def ai_butler_chat(
        body: AiButlerChatRequest = Body(...),
        authorization: str | None = Header(default=None),
    ):
        check_token(authorization)
        if not body.messages:
            raise HTTPException(status_code=400, detail="messages 不能为空")
        config = bridge.danmu_app.config
        messages = [m.model_dump() for m in body.messages]
        try:
            return butler_chat(config, messages, body.model_id)
        except Exception as exc:
            logger.warning("ai_butler: internal_error %r", exc)
            return {"ok": False, "error": f"internal_error:{type(exc).__name__}"}
