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
    assert result.stream_completed is True
    assert result.terminated_by == "done"


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
    assert result.terminated_by == "eof"


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
    assert result.stream_completed is True
    assert result.outcome == "finished"


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
    assert result.outcome == "error"


def test_consume_openai_sse_lines_finish_reason_length_marks_incomplete():
    chunk1 = {"choices": [{"delta": {"content": '[{"anchor"'}}]}
    chunk2 = {"choices": [{"delta": {}, "finish_reason": "length"}]}
    lines = [f"data: {json.dumps(chunk1)}", f"data: {json.dumps(chunk2)}", "data: [DONE]"]
    result = consume_openai_sse_lines(
        lines,
        adapter=_FakeAdapter(),
        caps=None,
    )
    assert result.text == '[{"anchor"'
    assert result.finish_reason == "length"
    assert "stream incomplete: finish_reason=length" in result.error
    assert result.outcome == "error"


def test_consume_openai_sse_lines_eof_without_done_marks_incomplete():
    lines = [
        'data: {"choices":[{"delta":{"content":"partial json ["}}]}',
    ]
    result = consume_openai_sse_lines(
        lines,
        adapter=_FakeAdapter(),
        caps=None,
    )
    assert result.text == "partial json ["
    assert result.stream_completed is False
    assert result.terminated_by == "eof"
    assert result.error == "stream incomplete: eof_without_done"


def test_consume_openai_sse_lines_stop_with_done_is_success():
    chunk1 = {"choices": [{"delta": {"content": '["danmu-one"]'}}]}
    chunk2 = {"choices": [{"delta": {}, "finish_reason": "stop"}]}
    lines = [f"data: {json.dumps(chunk1)}", f"data: {json.dumps(chunk2)}", "data: [DONE]"]
    result = consume_openai_sse_lines(
        lines,
        adapter=_FakeAdapter(),
        caps=None,
    )
    assert result.text == '["danmu-one"]'
    assert result.finish_reason == "stop"
    assert result.error == ""
    assert result.outcome == "finished"


def test_consume_openai_sse_lines_stopping_does_not_finish_partial_text():
    lines = [
        'data: {"choices":[{"delta":{"content":"partial"}}]}',
        'data: {"choices":[{"delta":{"content":" ignored"}}]}',
    ]
    seen = {"count": 0}

    def stopping():
        seen["count"] += 1
        return seen["count"] >= 2

    result = consume_openai_sse_lines(
        lines,
        adapter=_FakeAdapter(),
        caps=None,
        stopping=stopping,
    )
    assert result.text == "partial"
    assert result.terminated_by == "stopping"
    assert result.error == "stream terminated: stopping"


class _FakeAdapter:
    def normalize_usage(self, usage, *, caps=None):
        return int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0))
