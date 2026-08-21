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

from app.ai_client_support import sanitize_provider_error_snippet
from app.model_providers import normalize_endpoint
from app.providers import get_capabilities_for_endpoint, get_openai_adapter

logger = logging.getLogger(__name__)

_INCOMPLETE_FINISH_REASONS = frozenset(
    {"length", "content_filter", "max_tokens", "model_length", "incomplete"}
)


@dataclass
class OpenAIChatStreamResult:
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_only: bool = False
    error: str = ""
    finish_reason: str = ""
    stream_completed: bool = False
    terminated_by: str = ""
    request_id: str = ""

    @property
    def outcome(self) -> str:
        if self.error:
            return "error"
        if self.text:
            return "finished"
        if self.reasoning_only:
            return "reasoning_only"
        return "empty"


def _request_wall_clock_exceeded(*, deadline_at: float | None) -> bool:
    if deadline_at is None:
        return False
    return time.monotonic() > float(deadline_at)


def _raise_if_wall_clock_exceeded(*, deadline_at: float | None) -> None:
    if _request_wall_clock_exceeded(deadline_at=deadline_at):
        raise httpx.TimeoutException("request wall clock exceeded")


def _normalize_sse_line(raw: Any) -> str:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return str(raw).strip()


def _sse_payload(raw: Any) -> str | None:
    line = _normalize_sse_line(raw)
    if not line.startswith("data:"):
        return None
    return line[5:].lstrip()


def _extract_error_message(chunk: dict[str, Any]) -> str:
    error = chunk.get("error")
    if isinstance(error, dict):
        message = error.get("message") or error.get("code") or error.get("type")
        if message:
            return sanitize_provider_error_snippet(str(message))
    elif isinstance(error, str) and error.strip():
        return sanitize_provider_error_snippet(error)
    message = chunk.get("message")
    if message:
        return sanitize_provider_error_snippet(str(message))
    return ""


def _finish_reason_is_incomplete(finish_reason: str) -> bool:
    return (finish_reason or "").strip().lower() in _INCOMPLETE_FINISH_REASONS


def _apply_stream_completion_state(result: OpenAIChatStreamResult) -> None:
    """Fill ``error`` for incomplete streams; provider errors take precedence."""
    if result.error:
        return
    if result.terminated_by == "stopping":
        if result.text:
            result.error = "stream terminated: stopping"
        return
    finish_reason = (result.finish_reason or "").strip()
    if _finish_reason_is_incomplete(finish_reason):
        result.error = f"stream incomplete: finish_reason={finish_reason}"
        return
    if result.text and not result.stream_completed:
        result.error = "stream incomplete: eof_without_done"
        return
    if result.terminated_by == "first_content_timeout":
        result.error = "stream incomplete: first_content_timeout"


def _log_openai_stream_outcome(result: OpenAIChatStreamResult, *, endpoint_label: str) -> None:
    logger.info(
        "openai stream outcome endpoint=%s request_id=%s text_len=%s "
        "input_tokens=%s output_tokens=%s finish_reason=%s terminated_by=%s "
        "stream_completed=%s outcome=%s",
        endpoint_label,
        result.request_id or "-",
        len(result.text),
        result.input_tokens,
        result.output_tokens,
        result.finish_reason or "-",
        result.terminated_by or "-",
        result.stream_completed,
        result.outcome,
    )


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
    stream_error = ""
    got_first_content = False
    finish_reason = ""
    request_id = ""
    saw_done = False
    terminated_by = "eof"
    endpoint_label = normalize_endpoint(endpoint) if endpoint else url

    for raw in lines:
        if stopping is not None and stopping():
            terminated_by = "stopping"
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
                terminated_by = "first_content_timeout"
                break
        payload = _sse_payload(raw)
        if payload is None:
            continue
        if payload.strip() == "[DONE]":
            saw_done = True
            terminated_by = "done"
            break
        try:
            chunk = json.loads(payload)
            chunk_id = chunk.get("id")
            if chunk_id:
                request_id = str(chunk_id)
            usage = chunk.get("usage")
            if usage:
                input_tokens, output_tokens = adapter.normalize_usage(usage, caps=caps)
            if "error" in chunk:
                stream_error = stream_error or _extract_error_message(chunk) or "provider stream error"
                continue
            choice = chunk.get("choices", [{}])[0]
            choice_finish = choice.get("finish_reason")
            if choice_finish:
                finish_reason = str(choice_finish)
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
        except (json.JSONDecodeError, IndexError, KeyError, TypeError, AttributeError) as exc:
            safe_payload = sanitize_provider_error_snippet(payload, max_len=80)
            logger.debug("stream chunk parse skipped: %r payload=%s", exc, safe_payload)
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
    result = OpenAIChatStreamResult(
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        reasoning_only=reasoning_only,
        error=stream_error,
        finish_reason=finish_reason,
        stream_completed=saw_done,
        terminated_by=terminated_by,
        request_id=request_id,
    )
    _apply_stream_completion_state(result)
    _log_openai_stream_outcome(result, endpoint_label=endpoint_label)
    return result


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
