"""Parse OpenAI-compatible Chat Completions SSE streams.

协议背景：
- OpenAI / MiMo / DashScope 等走 ``/chat/completions`` endpoint，返回 SSE 流（每行 ``data: {...}``，``[DONE]`` 结束）。
- 增量文本在 ``choices[0].delta.content``；``reasoning_content`` 仅用于诊断日志，不混入最终弹幕。
- 本模块被 ``ai_client_requests.stream_openai`` 调用；纯函数，不持有 Qt 状态。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import httpx

from app.model_providers import normalize_endpoint
from app.providers import get_capabilities_for_endpoint, get_openai_adapter

logger = logging.getLogger(__name__)


@dataclass
class OpenAIChatStreamResult:
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_only: bool = False


def _request_wall_clock_exceeded(*, deadline_at: float | None) -> bool:
    if deadline_at is None:
        return False
    return time.monotonic() > float(deadline_at)


def _raise_if_wall_clock_exceeded(*, deadline_at: float | None) -> None:
    if _request_wall_clock_exceeded(deadline_at=deadline_at):
        raise httpx.TimeoutException("request wall clock exceeded")


def consume_openai_sse_lines(
    lines: Iterable[Any],
    *,
    adapter,
    caps,
    deadline_at: float | None = None,
    first_content_timeout: float | None = None,
    started_at: float | None = None,
    stopping: Callable[[], bool] | None = None,
    endpoint: str = "",
    url: str = "",
) -> OpenAIChatStreamResult:
    collected: list[str] = []
    reasoning_parts: list[str] = []
    input_tokens = 0
    output_tokens = 0
    got_first_content = False
    endpoint_label = normalize_endpoint(endpoint) if endpoint else url

    for line in lines:
        if stopping is not None and stopping():
            break
        _raise_if_wall_clock_exceeded(deadline_at=deadline_at)
        # W-PERF-STREAM-001：首内容超时检查
        if first_content_timeout is not None and not got_first_content:
            if started_at is not None and time.monotonic() - started_at > first_content_timeout:
                logger.warning(
                    "openai stream first content timeout: %.1fs elapsed, no content delta received, endpoint=%s",
                    first_content_timeout,
                    endpoint_label,
                )
                break
        if not line or not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload.strip() == "[DONE]":
            break
        try:
            chunk = json.loads(payload)
            usage = chunk.get("usage")
            if usage:
                input_tokens, output_tokens = adapter.normalize_usage(usage, caps=caps)
            choice = chunk.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            content = delta.get("content", "")
            if content:
                got_first_content = True
                collected.append(content)
            reasoning = delta.get("reasoning_content", "")  # 忽略：豆包/OpenAI 思考内容不应作为弹幕
            if reasoning:
                reasoning_parts.append(reasoning)  # 仅用于诊断日志
            if not content and not reasoning:
                message = choice.get("message", {})
                message_content = message.get("content", "")
                if message_content:
                    got_first_content = True
                    collected.append(message_content)
                message_reasoning = message.get("reasoning_content", "")
                if message_reasoning:
                    reasoning_parts.append(message_reasoning)
        except (json.JSONDecodeError, IndexError, KeyError) as exc:
            logger.debug("stream chunk parse skipped: %r payload=%.80s", exc, payload)
            continue

    text = "".join(collected)
    reasoning_only = not text and bool(reasoning_parts)
    if reasoning_only:
        reasoning_len = sum(len(part) for part in reasoning_parts)
        logger.warning(
            "openai stream 只有 reasoning_content 没有 content "
            "(thinking:disabled 未生效，已通过增大 max_completion_tokens 缓解): "
            "input_tokens=%s output_tokens=%s reasoning_chars=%s endpoint=%s",
            input_tokens,
            output_tokens,
            reasoning_len,
            endpoint_label,
        )
    return OpenAIChatStreamResult(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_only=reasoning_only,
    )


def stream_openai_chat(
    http_client,
    url: str,
    headers: dict[str, Any],
    data: dict[str, Any],
    *,
    endpoint: str = "",
    api_mode: str = "",
    deadline_at: float | None = None,
    first_content_timeout: float | None = None,
    started_at: float | None = None,
    stopping: Callable[[], bool] | None = None,
) -> OpenAIChatStreamResult:
    caps = get_capabilities_for_endpoint(endpoint, api_mode)
    adapter = get_openai_adapter(endpoint, api_mode)
    with http_client.stream("POST", url, headers=headers, json=data) as resp:
        resp.raise_for_status()
        return consume_openai_sse_lines(
            resp.iter_lines(),
            adapter=adapter,
            caps=caps,
            deadline_at=deadline_at,
            first_content_timeout=first_content_timeout,
            started_at=started_at,
            stopping=stopping,
            endpoint=endpoint,
            url=url,
        )
