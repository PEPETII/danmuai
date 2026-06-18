from app.doubao_responses_stream import (
    consume_doubao_sse_lines,
    extract_text_from_response,
    parse_doubao_json_body,
)


def test_extract_text_from_response_message_output():
    response = {
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "已收到音频"}],
            }
        ]
    }
    assert extract_text_from_response(response) == "已收到音频"


def test_consume_doubao_sse_lines_collects_done_event():
    lines = [
        'data: {"type":"response.output_text.done","text":"hello"}',
        'data: {"type":"response.completed","response":{"usage":{"input_tokens":900,"output_tokens":12},"output":[{"type":"message","content":[{"type":"output_text","text":"hello"}]}]}}',
    ]
    result = consume_doubao_sse_lines(lines)
    assert result.text == "hello"
    assert result.input_tokens == 900
    assert result.output_tokens == 12
    assert result.reasoning_only is False


def test_consume_doubao_sse_lines_collects_delta_and_done_text():
    lines = [
        'data: {"type":"response.output_text.delta","delta":"hel"}',
        'data: {"type":"response.output_text.done","text":"lo"}',
        'data: {"type":"response.completed","response":{"usage":{"input_tokens":256,"output_tokens":8}}}',
    ]
    result = consume_doubao_sse_lines(lines)
    assert result.text == "hello"
    assert result.input_tokens == 256
    assert result.output_tokens == 8
    assert result.reasoning_only is False


def test_consume_doubao_sse_lines_reasoning_only_does_not_fallback_to_text():
    lines = [
        'data: {"type":"response.reasoning_summary_text.delta","delta":"先想一下"}',
        'data: {"type":"response.reasoning_summary_text.done","text":"最终也只有思考"}',
        'data: {"type":"response.completed","response":{"usage":{"input_tokens":111,"output_tokens":22}}}',
    ]
    result = consume_doubao_sse_lines(lines)
    assert result.text == ""
    assert result.input_tokens == 111
    assert result.output_tokens == 22
    assert result.reasoning_only is True


def test_consume_doubao_sse_lines_completed_response_extracts_text_without_stream_deltas():
    lines = [
        'data: {"type":"response.completed","response":{"usage":{"input_tokens":300,"output_tokens":16},"output":[{"type":"message","content":[{"type":"output_text","text":"从 completed 提取正文"}]}]}}',
    ]
    result = consume_doubao_sse_lines(lines)
    assert result.text == "从 completed 提取正文"
    assert result.input_tokens == 300
    assert result.output_tokens == 16
    assert result.reasoning_only is False


def test_consume_doubao_sse_lines_failed_event():
    lines = [
        'data: {"type":"response.failed","response":{"error":{"message":"model does not support audio"}}}',
    ]
    result = consume_doubao_sse_lines(lines)
    assert result.error == "model does not support audio"
    assert result.text == ""


def test_parse_doubao_json_body_top_level_error():
    body = {"error": {"message": "Invalid input_audio"}}
    result = parse_doubao_json_body(body)
    assert result.error == "Invalid input_audio"


def test_parse_doubao_json_body_volcengine_code_message():
    body = {"code": "InvalidParameter", "message": "model does not support input_audio"}
    result = parse_doubao_json_body(body)
    assert result.error == "model does not support input_audio"


def test_parse_doubao_json_body_completed_response():
    body = {
        "usage": {"input_tokens": 1200, "output_tokens": 20},
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "ok"}],
            }
        ],
    }
    result = parse_doubao_json_body(body)
    assert result.text == "ok"
    assert result.input_tokens == 1200
    assert result.output_tokens == 20
