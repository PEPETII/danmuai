"""Provider registry, capabilities, and OpenAI-compat adapters."""

from app.providers import (
    HOST_ENTRIES,
    get_capabilities,
    get_capabilities_for_endpoint,
    get_openai_adapter,
    guess_provider_from_endpoint,
    match_host_entry,
    provider_extra_body,
    provider_extra_headers,
    resolve_api_transport,
)
from app.providers.adapters.mimo import MimoOpenAIAdapter
from app.providers.constants import THINKING_DISABLED


def test_host_entries_derived_from_providers_single_source():
    fragments = {e.fragment for e in HOST_ENTRIES}
    assert "ark.cn-beijing.volces.com" in fragments
    assert "api.xiaomimimo.com" in fragments
    assert "dashscope.aliyuncs.com" in fragments
    assert len(fragments) == len(HOST_ENTRIES)


def test_guess_and_transport_use_same_registry():
    mimo_ep = "https://api.xiaomimimo.com/v1"
    assert guess_provider_from_endpoint(mimo_ep) == "mimo"
    assert resolve_api_transport(mimo_ep, "doubao") == "openai"

    ark_ep = "https://ark.cn-beijing.volces.com/api/v3"
    assert guess_provider_from_endpoint(ark_ep) == "doubao"
    assert resolve_api_transport(ark_ep, "openai-compatible") == "doubao"


def test_match_host_entry_longest_fragment_wins():
    entry = match_host_entry("https://ark.cn-beijing.volces.com/api/v3")
    assert entry is not None
    assert entry.provider_id == "doubao"
    assert entry.transport == "doubao"


def test_get_capabilities_mimo():
    caps = get_capabilities("mimo")
    assert caps.thinking_param is True
    assert caps.image_before_text is True
    assert caps.max_tokens_field == "max_completion_tokens"
    assert caps.stream_usage_in_final_chunk is False


def test_get_capabilities_for_endpoint_unknown_openai_defaults():
    caps = get_capabilities_for_endpoint("https://unknown.example.com/v1", "openai-compatible")
    assert caps.thinking_param is False
    assert caps.stream_usage_in_final_chunk is True


def test_default_adapter_openai_chat_body_unchanged():
    from app.providers.adapters.default_openai import DefaultOpenAIAdapter

    caps = get_capabilities("siliconflow")
    adapter = DefaultOpenAIAdapter()
    data: dict = {"stream": True}
    adapter.patch_openai_chat_body(data, max_tokens=512, caps=caps)
    assert data["max_tokens"] == 512
    assert data["stream_options"] == {"include_usage": True}
    assert "thinking" not in data


def test_default_adapter_probe_body_omits_stream_options_when_not_streaming():
    from app.providers.adapters.default_openai import DefaultOpenAIAdapter

    caps = get_capabilities("dashscope")
    adapter = DefaultOpenAIAdapter()
    data: dict = {
        "model": "qwen3-vl-flash",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "stream": False,
    }
    adapter.patch_probe_body(data, caps=caps)
    assert data["max_tokens"] == 1
    assert "stream_options" not in data


def test_default_adapter_openai_chat_body_omits_stream_options_when_not_streaming():
    from app.providers.adapters.default_openai import DefaultOpenAIAdapter

    caps = get_capabilities("dashscope")
    adapter = DefaultOpenAIAdapter()
    data: dict = {"stream": False}
    adapter.patch_openai_chat_body(data, max_tokens=512, caps=caps)
    assert data["max_tokens"] == 512
    assert "stream_options" not in data


def test_mimo_adapter_image_before_text_and_extensions():
    caps = get_capabilities("mimo")
    adapter = MimoOpenAIAdapter()
    parts = adapter.build_vision_user_content("hi", "data:image/jpeg;base64,x")
    assert parts[0]["type"] == "image_url"
    assert parts[1]["type"] == "text"

    audio = "data:audio/wav;base64,abc"
    with_audio = adapter.build_vision_user_content("hi", "data:image/jpeg;base64,x", audio_data_uri=audio)
    assert with_audio[2]["type"] == "input_audio"
    assert with_audio[2]["input_audio"]["data"] == audio

    data: dict = {"stream": True}
    adapter.patch_openai_chat_body(data, max_tokens=512, caps=caps)
    assert data["thinking"] == THINKING_DISABLED
    assert data["max_completion_tokens"] == 512
    assert "max_tokens" not in data
    assert "stream_options" not in data


def test_get_openai_adapter_selects_mimo():
    assert isinstance(
        get_openai_adapter("https://api.xiaomimimo.com/v1", "openai-compatible"),
        MimoOpenAIAdapter,
    )


def test_provider_extra_headers_openrouter():
    headers = provider_extra_headers("https://openrouter.ai/api/v1")
    assert "HTTP-Referer" in headers
    assert headers["X-Title"] == "DanmuAI"
    assert provider_extra_headers("https://api.deepseek.com/v1") == {}


def test_provider_extra_body_minimax_reasoning_split():
    assert provider_extra_body("https://api.minimax.io/v1") == {"reasoning_split": True}
    assert provider_extra_body("https://api.minimaxi.com/v1") == {"reasoning_split": True}
    assert provider_extra_body("https://api.deepseek.com/v1") == {}


def test_openai_extensions_shim_siliconflow_empty():
    from app.ai_client import openai_compatible_request_extensions

    assert openai_compatible_request_extensions("https://api.siliconflow.cn/v1") == {}


def test_openai_extensions_shim_minimax_reasoning_split():
    from app.ai_client import openai_compatible_request_extensions

    assert openai_compatible_request_extensions("https://api.minimax.io/v1") == {"reasoning_split": True}


def test_host_registry_no_duplicate_openai_doubao_tables():
    """Transport for known hosts must match HOST_ENTRIES only (no parallel marker tuples)."""
    for entry in HOST_ENTRIES:
        ep = f"https://{entry.fragment}/v1"
        assert guess_provider_from_endpoint(ep) == entry.provider_id
        assert resolve_api_transport(ep, "openai-compatible" if entry.transport == "openai" else "doubao") == entry.transport
