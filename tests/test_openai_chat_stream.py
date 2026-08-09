"""Unit tests for OpenAI Chat Completions SSE stream parsing."""

from __future__ import annotations

import json
import logging

from app.openai_chat_stream import consume_openai_sse_lines


def test_consume_openai_sse_lines_ignores_reasoning_content():
    chunk = {"choices": [{"delta": {"reasoning_content": "内部推理不应作为弹幕"}}]}
    lines = [f"data: {json.dumps(chunk)}", "data: [DONE]"]
    result = consume_openai_sse_lines(
        lines,
        adapter=_FakeAdapter(),
        caps=None,
    )
    assert result.text == ""
    assert result.input_tokens == 0
    assert result.output_tokens == 0
    assert result.reasoning_only is True


def test_consume_openai_sse_lines_logs_mimo_reasoning_only(caplog):
    chunk = {"choices": [{"delta": {"reasoning_content": "only reasoning"}}]}
    lines = [f"data: {json.dumps(chunk)}", "data: [DONE]"]
    with caplog.at_level(logging.WARNING):
        consume_openai_sse_lines(
            lines,
            adapter=_FakeAdapter(),
            caps=None,
            endpoint="https://api.xiaomimimo.com/v1",
        )
    assert any(
        "只有 reasoning_content 没有 content" in r.message for r in caplog.records
    )


def test_consume_openai_sse_lines_skips_malformed_json():
    lines = ["not-json-at-all"]
    result = consume_openai_sse_lines(
        lines,
        adapter=_FakeAdapter(),
        caps=None,
    )
    assert result.text == ""
    assert result.input_tokens == 0
    assert result.output_tokens == 0


def test_consume_openai_sse_lines_preserves_delta_usage_and_done():
    lines = [
        'data:{"choices":[{"delta":{"content":"hello"}}]}',
        'data: {"usage":{"prompt_tokens":4,"completion_tokens":2},"choices":[]}',
        "data:[DONE]",
        'data: {"choices":[{"delta":{"content":"ignored"}}]}',
    ]
    result = consume_openai_sse_lines(
        lines,
        adapter=_FakeAdapter(),
        caps=None,
    )
    assert result.text == "hello"
    assert (result.input_tokens, result.output_tokens) == (4, 2)
    assert result.error == ""


def test_consume_openai_sse_lines_top_level_error_after_partial_is_not_empty_success():
    secret = "sk-openai-stream-secret"
    lines = [
        'data: {"choices":[{"delta":{"content":"partial"}}]}',
        f'data:{{"error":{{"message":"Authorization: Bearer {secret}"}}}}',
        "data: [DONE]",
    ]
    result = consume_openai_sse_lines(
        lines,
        adapter=_FakeAdapter(),
        caps=None,
    )
    assert result.text == "partial"
    assert result.error
    assert secret not in result.error
    assert "Authorization" in result.error


class _FakeAdapter:
    def normalize_usage(self, usage, *, caps=None):
        return int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
