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


class _FakeAdapter:
    def normalize_usage(self, usage, *, caps=None):
        return int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
