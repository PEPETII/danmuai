from app.model_catalog import PLATFORM_CATALOGS
from app.providers.capabilities import get_capabilities, list_registered_provider_ids
from app.providers.capability_resolver import resolve_capabilities, unknown_capabilities


def test_all_catalog_platforms_have_registered_capability_profiles():
    provider_ids = {catalog.provider_id for catalog in PLATFORM_CATALOGS}

    assert provider_ids <= set(list_registered_provider_ids())
    for provider_id in provider_ids:
        caps = get_capabilities(provider_id)
        assert caps.transport in {"openai", "doubao"}
        assert caps.max_tokens_field
        assert caps.usage_token_style in {"openai", "dashscope"}
        assert caps.stream_usage_in_final_chunk is not None


def test_known_mimo_and_doubao_capability_contracts_are_explicit():
    mimo = get_capabilities("mimo")
    doubao = get_capabilities("doubao")

    assert mimo.transport == "openai"
    assert mimo.mic_audio is True
    assert mimo.image_before_text is True
    assert mimo.max_tokens_field == "max_completion_tokens"
    assert mimo.stream_usage_in_final_chunk is False
    assert doubao.transport == "doubao"
    assert doubao.max_tokens_field == "max_output_tokens"
    assert doubao.stream_usage_in_final_chunk is False


def test_unknown_custom_model_capabilities_remain_conservative():
    caps = resolve_capabilities(
        "vendor/model-not-in-catalog",
        "https://custom.example.test/v1",
        "openai-compatible",
        provider_id="custom_openai",
    )
    unknown = unknown_capabilities()

    assert caps == unknown
    assert caps.vision is False
    assert caps.mic_audio is False
    assert caps.supports_thinking is False
    assert caps.text_input is None
    assert caps.image_input is None
    assert caps.audio_input is None
    assert caps.structured_output is None
