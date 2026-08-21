from app.providers.adapters.default_openai import DefaultOpenAIAdapter
from app.providers.capabilities import ProviderCapabilities
from app.providers.endpoint_resolver import (
    API_FAMILY_ANTHROPIC_MESSAGES,
    API_FAMILY_OPENAI_CHAT,
    API_FAMILY_OPENAI_RESPONSES,
)
from app.providers.stream_parser import consume_stream, parser_id_for_api_family


def test_parser_ids_are_explicit_and_unknown_is_safe():
    assert parser_id_for_api_family(API_FAMILY_OPENAI_CHAT) == "openai_chat_sse"
    assert parser_id_for_api_family(API_FAMILY_OPENAI_RESPONSES) == "doubao_responses_sse"
    assert parser_id_for_api_family(API_FAMILY_ANTHROPIC_MESSAGES) == "anthropic_messages_sse"
    assert parser_id_for_api_family("future") == "unknown_sse"


def test_doubao_facade_handles_delta_reasoning_usage_and_metadata():
    lines = [
        'data: {"type":"response.output_text.delta","delta":"hi","id":"resp_1"}',
        'data: {"type":"response.reasoning_text.delta","delta":"think"}',
        'data: {"type":"response.completed","id":"resp_1","response":{"usage":{"input_tokens":2,"output_tokens":1}}}',
        "data: [DONE]",
    ]
    result = consume_stream(lines, api_family=API_FAMILY_OPENAI_RESPONSES)
    assert result.text == "hi" and result.reasoning_only is False
    assert (result.input_tokens, result.output_tokens, result.request_id) == (2, 1, "resp_1")
    assert result.raw_usage == {"input_tokens": 2, "output_tokens": 1}


def test_chat_facade_preserves_empty_and_malformed_chunks():
    lines = ["data: {bad", 'data: {"choices":[{"delta":{"content":"ok"}}]}', "data: [DONE]"]
    result = consume_stream(lines, api_family=API_FAMILY_OPENAI_CHAT,
                            adapter=DefaultOpenAIAdapter(), caps=ProviderCapabilities())
    assert result.text == "ok"


def test_chat_facade_propagates_top_level_error_without_space_after_data():
    lines = [
        'data:{"error":{"message":"rate limited"}}',
        "data: [DONE]",
    ]
    result = consume_stream(
        lines,
        api_family=API_FAMILY_OPENAI_CHAT,
        adapter=DefaultOpenAIAdapter(),
        caps=ProviderCapabilities(),
    )
    assert result.text == ""
    assert result.error == "rate limited"


def test_chat_facade_eof_without_done_marks_incomplete():
    lines = ['data: {"choices":[{"delta":{"content":"partial"}}]}']
    result = consume_stream(
        lines,
        api_family=API_FAMILY_OPENAI_CHAT,
        adapter=DefaultOpenAIAdapter(),
        caps=ProviderCapabilities(),
    )
    assert result.text == "partial"
    assert result.error == "stream incomplete: eof_without_done"
