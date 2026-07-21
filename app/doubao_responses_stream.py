"""Parse Volcengine / Doubao Responses API SSE streams and JSON bodies.

协议背景：
- 豆包 Responses 走 ``/responses`` endpoint，返回 SSE 流（每行 ``data: {...}``，``[DONE]`` 结束）。
- 增量文本事件 ``response.output_text.delta`` / ``response.output_text.done``；思考事件
  ``response.reasoning_*`` 仅在 ``summary_parts`` 兜底收集，不混入最终弹幕。
- 终结事件 ``response.completed`` / ``response.incomplete`` / ``response.failed`` 携带 ``usage`` 字段。
- 本模块被 ``ai_client.py`` 调用；调用方在主线程或 HTTP 线程均可
  （纯函数，不持有 Qt 状态）。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Iterable

import httpx

logger = logging.getLogger(__name__)


@dataclass
class DoubaoResponsesResult:
    text: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    error: str = ""
    reasoning_only: bool = False
    stream_events: list[str] = field(default_factory=list)


def extract_text_from_response(response: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in response.get("output", []) or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "message":
            for content in item.get("content", []) or []:
                if not isinstance(content, dict):
                    continue
                if content.get("type") == "output_text":
                    text = content.get("text", "")
                    if text:
                        parts.append(str(text))
        elif item.get("type") == "output_text":
            text = item.get("text", "")
            if text:
                parts.append(str(text))
    return "".join(parts)


def _extract_error_message(chunk: dict[str, Any]) -> str:
    err = chunk.get("error")
    if isinstance(err, dict):
        message = err.get("message") or err.get("code")
        if message:
            return str(message)
    response = chunk.get("response")
    if isinstance(response, dict):
        nested = response.get("error")
        if isinstance(nested, dict):
            message = nested.get("message") or nested.get("code")
            if message:
                return str(message)
        incomplete = response.get("incomplete_details")
        if isinstance(incomplete, dict):
            reason = incomplete.get("reason")
            if reason:
                return f"response incomplete: {reason}"
    message = chunk.get("message")
    if message:
        return str(message)
    return ""


def _apply_usage(result: DoubaoResponsesResult, usage: dict[str, Any]) -> None:
    if not usage:
        return
    result.input_tokens = int(usage.get("input_tokens", result.input_tokens) or 0)
    result.output_tokens = int(usage.get("output_tokens", result.output_tokens) or 0)


def _normalize_sse_line(raw: Any) -> str:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    return str(raw).strip()


def consume_doubao_sse_lines(
    lines: Iterable[Any],
    *,
    deadline_at: float | None = None,
    first_content_timeout: float | None = None,
    started_at: float | None = None,
    stopping: Callable[[], bool] | None = None,
) -> DoubaoResponsesResult:
    collected: list[str] = []
    summary_parts: list[str] = []
    result = DoubaoResponsesResult()
    got_first_content = False

    for raw in lines:
        # BUG-AUD-002: 与 consume_openai_sse_lines 对齐，支持 stop() 中断
        if stopping is not None and stopping():
            break
        if deadline_at is not None and time.monotonic() > float(deadline_at):
            raise httpx.TimeoutException("request wall clock exceeded")
        # W-PERF-STREAM-001：首内容超时检查
        if first_content_timeout is not None and not got_first_content and started_at is not None:
            if time.monotonic() - started_at > first_content_timeout:
                logger.warning(
                    "doubao stream first content timeout: %.1fs elapsed, no content delta received",
                    first_content_timeout,
                )
                break
        line = _normalize_sse_line(raw)
        if not line or not line.startswith("data: "):
            continue
        payload = line[6:]
        if payload.strip() == "[DONE]":
            # SSE 终止符；response.completed 应在 [DONE] 之前到达（见模块头注释）
            break
        try:
            chunk = json.loads(payload)
        except json.JSONDecodeError:
            continue

        chunk_type = chunk.get("type", "")
        if chunk_type and chunk_type not in result.stream_events:
            result.stream_events.append(chunk_type)

        if chunk_type == "response.output_text.delta":
            delta = chunk.get("delta", "")
            if delta:
                got_first_content = True
                collected.append(str(delta))
        elif chunk_type == "response.output_text.done":
            if not collected:  # 仅在无 delta 时取 done 文本（done.text 为完整文本，非增量）
                text = chunk.get("text", "") or chunk.get("delta", "")
                if text:
                    got_first_content = True
                    collected.append(str(text))
        elif chunk_type in (
            "response.reasoning_summary_text.delta",
            "response.reasoning_text.delta",
        ):
            delta = chunk.get("delta", "")
            if delta:
                summary_parts.append(str(delta))
        elif chunk_type in (
            "response.reasoning_summary_text.done",
            "response.reasoning_text.done",
        ):
            if not summary_parts:  # 仅在无 delta 时取 done 文本（done.text 为完整文本，非增量）
                text = chunk.get("text", "") or chunk.get("delta", "")
                if text:
                    summary_parts.append(str(text))
        elif chunk_type in ("response.completed", "response.incomplete", "response.failed"):
            response = chunk.get("response", {})
            if isinstance(response, dict):
                _apply_usage(result, response.get("usage", {}) or {})
                if not collected:
                    collected.append(extract_text_from_response(response))
            if chunk_type in ("response.failed", "response.incomplete"):
                message = _extract_error_message(chunk)
                if message:
                    result.error = message
        elif chunk_type == "error":
            message = _extract_error_message(chunk)
            if message:
                result.error = message

    result.text = "".join(collected)
    result.reasoning_only = not result.text and bool(summary_parts)
    return result


def parse_doubao_json_body(body: dict[str, Any]) -> DoubaoResponsesResult:
    result = DoubaoResponsesResult()
    if isinstance(body.get("error"), dict):
        result.error = _extract_error_message(body)
        return result
    if body.get("message") and (body.get("code") or body.get("error_code")):
        result.error = str(body["message"])
        return result

    response = body.get("response")
    if isinstance(response, dict):
        _apply_usage(result, response.get("usage", {}) or {})
        result.text = extract_text_from_response(response)
        if response.get("status") in ("failed", "incomplete"):
            result.error = _extract_error_message({"response": response}) or str(response.get("status", ""))
        return result

    _apply_usage(result, body.get("usage", {}) or {})
    result.text = extract_text_from_response(body)
    if body.get("status") in ("failed", "incomplete"):
        result.error = _extract_error_message({"response": body}) or str(body.get("status", ""))
    return result


def stream_doubao_responses(
    http_client,
    url: str,
    headers: dict[str, Any],
    data: dict[str, Any],
    *,
    deadline_at: float | None = None,
    first_content_timeout: float | None = None,
    started_at: float | None = None,
    stopping: Callable[[], bool] | None = None,
) -> DoubaoResponsesResult:
    with http_client.stream("POST", url, headers=headers, json=data) as resp:
        resp.raise_for_status()
        content_type = (resp.headers.get("content-type") or "").lower()
        if "application/json" in content_type:
            body = resp.read()
            if isinstance(body, bytes):
                body = body.decode("utf-8", errors="replace")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                return DoubaoResponsesResult(error=str(body)[:500])
            if isinstance(parsed, dict):
                return parse_doubao_json_body(parsed)
            return DoubaoResponsesResult(error="invalid_json_response")
        return consume_doubao_sse_lines(
            resp.iter_lines(),
            deadline_at=deadline_at,
            first_content_timeout=first_content_timeout,
            started_at=started_at,
            stopping=stopping,
        )
