from app.providers.capabilities import ProviderCapabilities
from app.providers.usage_normalizer import normalize_usage_by_style, normalize_usage_details


def test_openai_usage_details_and_legacy_tuple():
    usage = {"prompt_tokens": 10, "completion_tokens": 7, "total_tokens": 17,
             "prompt_tokens_details": {"cached_tokens": 3},
             "completion_tokens_details": {"reasoning_tokens": 2}}
    details = normalize_usage_details(usage, caps=ProviderCapabilities())
    assert (details.input_tokens, details.output_tokens, details.total_tokens) == (10, 7, 17)
    assert (details.cached_tokens, details.reasoning_tokens) == (3, 2)
    assert normalize_usage_by_style(usage) == (10, 7)
    assert details.raw_usage == usage and details.raw_usage is not usage


def test_dashscope_and_responses_shapes():
    dash = normalize_usage_details({"input_tokens": 4, "output_tokens": 5, "total_tokens": 9}, usage_token_style="dashscope")
    responses = normalize_usage_details({"input_tokens": 2, "output_tokens": 3, "total_tokens": 5}, caps=ProviderCapabilities())
    assert (dash.input_tokens, dash.output_tokens) == (4, 5)
    assert (responses.input_tokens, responses.output_tokens) == (2, 3)


def test_empty_and_unknown_usage_do_not_invent_numbers():
    assert normalize_usage_details(None).input_tokens is None
    details = normalize_usage_details({"prompt_tokens": "not-a-number", "vendor_metric": 99})
    assert details.input_tokens is None and details.output_tokens is None
    assert details.raw_usage["vendor_metric"] == 99
