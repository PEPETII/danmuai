"""W-AIBUTLER-CHAT-ONLY-001 — AI管家对话路由。

注册 ``POST /api/ai-butler/chat``：
- 鉴权：需 Bearer token（与 settings 写路由一致）
- 线程模型：async 路由 + 专用 ThreadPoolExecutor 跑同步 LLM（不触 Qt / 主链路；config 只读快照）
- 入参：``{"messages": [...], "model_id": str?}``
- 出参：``{"ok": True, "reply": str, "tool_calls": []}`` 或 ``{"ok": False, "error": str}``

仅返回自然语言对话；**不执行**任何配置变更。``tool_calls`` 恒为空数组（兼容旧前端字段）。
"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Callable

from fastapi import Body, Header, HTTPException
from pydantic import BaseModel, Field

from app.application.ai_butler_service import chat as butler_chat
from app.errors import AppError
from app.translations import tr
from app.web_api.auth import require_auth

if TYPE_CHECKING:
    from app.web_console import WebConsoleBridge

logger = logging.getLogger(__name__)

_BUTLER_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-butler")


class AiButlerMessage(BaseModel):
    role: str = "user"
    content: str = ""


class AiButlerChatRequest(BaseModel):
    messages: list[AiButlerMessage] = Field(default_factory=list)
    model_id: str | None = None  # 保留字段；服务层暂忽略覆盖


def register_ai_butler_route(app, bridge: "WebConsoleBridge", check_token: Callable) -> None:
    """注册 AI管家对话路由。"""

    @app.post("/api/ai-butler/chat")
    @require_auth(check_token)
    async def ai_butler_chat(
        body: AiButlerChatRequest = Body(...),
        authorization: str | None = Header(default=None),
    ):
        if not body.messages:
            raise HTTPException(status_code=400, detail=tr("aiButler.messagesRequired"))
        config = bridge.danmu_app.config
        messages = [m.model_dump() for m in body.messages]
        loop = asyncio.get_running_loop()
        try:
            return await loop.run_in_executor(
                _BUTLER_EXECUTOR,
                lambda: butler_chat(config, messages, body.model_id),
            )
        except AppError as exc:
            logger.warning("ai_butler: app_error %r", exc)
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            logger.exception("ai_butler: internal_error %r", exc)
            return {"ok": False, "error": f"internal_error:{type(exc).__name__}"}
