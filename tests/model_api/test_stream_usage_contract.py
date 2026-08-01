from app.providers.adapters.default_openai import DefaultOpenAIAdapter
from app.providers.capabilities import ProviderCapabilities
from app.providers.endpoint_resolver import API_FAMILY_OPENAI_CHAT, API_FAMILY_OPENAI_RESPONSES
from app.providers.stream_parser import consume_stream, parser_id_for_api_family
from app.providers.usage_normalizer import normalize_usage_by_style, normalize_usage_details


def test_stream_parser_contract_keeps_api_family_selection_explicit():
    assert parser_id_for_api_family(API_FAMILY_OPENAI_CHAT) == "openai_chat_sse"
    assert parser_id_for_api_family(API_FAMILY_OPENAI_RESPONSES) == "doubao_responses_sse"
    assert parser_id_for_api_family("unregistered-family") == "unknown_sse"


def test_chat_stream_contract_preserves_text_reasoning_and_usage():
    result = consume_stream(
        [
            'data: {"choices":[{"delta":{"content":"hello"}}]}',
            'data: {"choices":[{"delta":{"reasoning_content":"private reasoning"}}]}',
            'data: {"choices":[],"usage":{"prompt_tokens":4,"completion_tokens":2,"total_tokens":6}}',
            "data: [DONE]",
        ],
        api_family=API_FAMILY_OPENAI_CHAT,
        adapter=DefaultOpenAIAdapter(),
        caps=ProviderCapabilities(),
    )

    assert result.text == "hello"
    assert result.reasoning_only is False
    assert (result.input_tokens, result.output_tokens) == (4, 2)


def test_responses_stream_contract_reads_terminal_usage_without_network():
    result = consume_stream(
        [
            'data: {"type":"response.output_text.delta","delta":"hello","id":"resp-contract"}',
            'data: {"type":"response.completed","id":"resp-contract","response":{"usage":{"input_tokens":3,"output_tokens":2}}}',
            "data: [DONE]",
        ],
        api_family=API_FAMILY_OPENAI_RESPONSES,
    )

    assert result.text == "hello"
    assert (result.input_tokens, result.output_tokens) == (3, 2)
    assert result.request_id == "resp-contract"


def test_usage_normalization_supports_openai_dashscope_and_details():
    openai = normalize_usage_details(
        {
            "prompt_tokens": 5,
            "completion_tokens": 7,
            "total_tokens": 12,
            "prompt_tokens_details": {"cached_tokens": 2},
            "completion_tokens_details": {"reasoning_tokens": 3},
        }
    )
    dashscope = normalize_usage_by_style({"input_tokens": 8, "output_tokens": 9}, usage_token_style="dashscope")

    assert (openai.input_tokens, openai.output_tokens, openai.total_tokens) == (5, 7, 12)
    assert openai.cached_tokens == 2
    assert openai.reasoning_tokens == 3
    assert dashscope == (8, 9)


def test_malformed_or_empty_usage_is_safe_and_does_not_invent_tokens():
    assert normalize_usage_details(None).input_tokens is None
    assert normalize_usage_details({"prompt_tokens": "not-a-number"}).input_tokens is None
    assert normalize_usage_details({"prompt_tokens": True}).input_tokens is None
