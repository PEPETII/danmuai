"""W-BILILIVE-DM-PLUGIN-BRIDGE-003 — bililive_dm 评论旁路真实 AI 生成。"""

from __future__ import annotations

import logging
import re
import threading
import time

import httpx
from pydantic import BaseModel, Field

from app.ai_client_requests import format_credential_error, resolve_request_credentials
from app.ai_client_requests import stream_doubao, stream_openai
from app.model_providers import resolve_api_transport
from app.providers import get_capabilities_for_endpoint, get_openai_adapter, provider_extra_headers
from app.providers.constants import THINKING_DISABLED
from app.providers.thinking import apply_thinking_disabled
from app.errors import AppError


class BililiveDmBridgeRequest(BaseModel):
    room_id: int | None = None
    user_name: str | None = None
    user_id: str | None = None
    text: str | None = None


class BililiveDmBridgeResponse(BaseModel):
    ok: bool
    error: str | None = None
    items: list[str] = Field(default_factory=list)


logger = logging.getLogger(__name__)

_BRIDGE_SYSTEM_PROMPT = (
    "你是直播间 AI 助手。请基于用户评论生成 1-2 条简短、口语化、长度不超过 30 个字的弹幕回复。"
    "只输出弹幕文本本身，每条单独一行；不要解释、不要 Markdown、不要 JSON。"
)

_MAX_ITEMS = 3
_MAX_ITEM_CHARS = 60
_MAX_USER_TEXT_CHARS = 200
_DEFAULT_TIMEOUT_SEC = 10.0
_BULLET_PREFIX_RE = re.compile(r"^[\-\*•\d]+[\.\)、\s]+")


class _BridgeStreamWorker:
    """duck-typed worker for stream_openai / stream_doubao（非 QObject）。"""

    def __init__(self, config) -> None:
        self.config = config
        self._stopping = threading.Event()
        self._thread_local = threading.local()
        self._client_lock = threading.Lock()
        self._clients: set[httpx.Client] = set()
        self._request_started_at = time.monotonic()
        self._request_deadline_at = self._request_started_at + _DEFAULT_TIMEOUT_SEC

    def _resolve_request_credentials(self):
        return resolve_request_credentials(self.config)

    def _get_http_client(self) -> httpx.Client:
        client = getattr(self._thread_local, "client", None)
        if client is None:
            client = httpx.Client(
                timeout=httpx.Timeout(_DEFAULT_TIMEOUT_SEC, connect=5.0),
            )
            with self._client_lock:
                self._clients.add(client)
            self._thread_local.client = client
        return client


def _make_user_prompt(request: BililiveDmBridgeRequest) -> str:
    user_name = (request.user_name or "观众").strip() or "观众"
    text = (request.text or "").strip()
    if len(text) > _MAX_USER_TEXT_CHARS:
        text = text[:_MAX_USER_TEXT_CHARS]
    return f"观众 {user_name} 说：{text}"


def _parse_bridge_text(raw: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for line in raw.replace("\r", "").split("\n"):
        text = _BULLET_PREFIX_RE.sub("", line.strip())
        if not text:
            continue
        if len(text) > _MAX_ITEM_CHARS:
            text = text[: _MAX_ITEM_CHARS - 1] + "…"
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= _MAX_ITEMS:
            break
    return out


def _stream_ai_reply(worker: _BridgeStreamWorker, system_pt: str, user_pt: str) -> str:
    resolved = worker._resolve_request_credentials()
    if resolved is None:
        raise ValueError("model_not_configured")
    endpoint, api_key, model, api_mode = resolved
    http_client = worker._get_http_client()
    transport = resolve_api_transport(endpoint, api_mode)

    if transport == "doubao":
        data = {
            "model": model,
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_pt}],
                }
            ],
            "stream": True,
            "thinking": dict(THINKING_DISABLED),
            "max_output_tokens": 512,
        }
        if system_pt:
            data["instructions"] = system_pt
        url = f"{endpoint}/responses"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        text, _, _, _ = stream_doubao(worker, http_client, url, headers, data)
        return text

    caps = get_capabilities_for_endpoint(endpoint, api_mode)
    adapter = get_openai_adapter(endpoint, api_mode)
    data = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_pt},
            {"role": "user", "content": user_pt},
        ],
        "stream": True,
    }
    adapter.patch_openai_chat_body(data, max_tokens=512, caps=caps)
    apply_thinking_disabled(data, caps=caps)
    url = f"{endpoint}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    headers.update(provider_extra_headers(endpoint))
    text, _, _ = stream_openai(
        worker,
        http_client,
        url,
        headers,
        data,
        endpoint=endpoint,
        api_mode=api_mode,
    )
    return text


def generate_ai_replies(
    config,
    request: BililiveDmBridgeRequest,
) -> BililiveDmBridgeResponse:
    text = (request.text or "").strip()
    if not text:
        return BililiveDmBridgeResponse(ok=False, error="empty_text", items=[])

    if config is None:
        return BililiveDmBridgeResponse(ok=False, error="model_not_configured", items=[])

    resolved = resolve_request_credentials(config)
    if resolved is None:
        return BililiveDmBridgeResponse(
            ok=False,
            error=format_credential_error(config),
            items=[],
        )

    worker = _BridgeStreamWorker(config)
    user_pt = _make_user_prompt(request)
    try:
        raw = _stream_ai_reply(worker, _BRIDGE_SYSTEM_PROMPT, user_pt)
    except ValueError as exc:
        if str(exc) == "model_not_configured":
            return BililiveDmBridgeResponse(ok=False, error="model_not_configured", items=[])
        return BililiveDmBridgeResponse(
            ok=False,
            error=f"internal_error:{type(exc).__name__}",
            items=[],
        )
    except httpx.TimeoutException:
        return BililiveDmBridgeResponse(ok=False, error="timeout", items=[])
    except httpx.HTTPStatusError as exc:
        return BililiveDmBridgeResponse(
            ok=False,
            error=f"http_{exc.response.status_code}",
            items=[],
        )
    except AppError as exc:
        logger.warning("bililive_dm_bridge_service: app_error %r", exc)
        return BililiveDmBridgeResponse(ok=False, error=str(exc), items=[])
    except Exception as exc:  # boundary: unexpected stream failure
        logger.warning("bililive_dm_bridge_service: stream failed %r", exc)
        return BililiveDmBridgeResponse(
            ok=False,
            error=f"internal_error:{type(exc).__name__}",
            items=[],
        )

    items = _parse_bridge_text(raw or "")
    if not items:
        if not (raw or "").strip():
            return BililiveDmBridgeResponse(ok=False, error="empty_response", items=[])
        return BililiveDmBridgeResponse(ok=False, error="empty_after_parse", items=[])
    return BililiveDmBridgeResponse(ok=True, error=None, items=items)
