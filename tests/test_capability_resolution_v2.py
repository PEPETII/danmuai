from app.providers.capabilities import capabilities_for_api_family
from app.providers.capability_resolver import resolve_capabilities


def test_curated_models_use_explicit_model_capabilities():
    qwen = resolve_capabilities("qwen3-vl-flash", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    mimo = resolve_capabilities("mimo-v2.5", "https://api.xiaomimimo.com/v1")
    assert qwen.vision is True
    assert mimo.mic_audio is True


def test_known_provider_unknown_model_is_conservative():
    caps = resolve_capabilities("future-model", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    assert caps.vision is False
    assert caps.mic_audio is False
    assert caps.supports_thinking is False
    assert caps.stream_usage_in_final_chunk is False


def test_custom_doubao_unknown_does_not_infer_thinking():
    caps = resolve_capabilities("my-model", "https://example.com/v1", provider_id="custom_doubao")
    assert caps.supports_thinking is False
    assert caps.thinking_param is False
    assert caps.transport == "doubao"


def test_all_model_overrides_win():
    caps = resolve_capabilities(
        "future-model", "https://dashscope.aliyuncs.com/compatible-mode/v1",
        supports_vision_override=True, supports_mic_override=True,
        supports_audio_override=True, supports_video_override=True,
        supports_file_override=True, supports_structured_output_override=True,
    )
    assert (caps.vision, caps.mic_audio, caps.audio_input, caps.video_input,
            caps.file_input, caps.structured_output) == (True, True, True, True, True, True)


def test_price_audio_does_not_imply_audio_capability():
    caps = resolve_capabilities("doubao-seed-1-8-251228", "https://ark.cn-beijing.volces.com/api/v3")
    assert caps.audio_input is False


def test_gpt56_capabilities_are_model_and_api_family_specific():
    caps = resolve_capabilities(
        "gpt-5.6-sol",
        "https://api.openai.com/v1",
        api_mode="openai-compatible",
        provider_id="openai",
    )
    assert caps.vision is True
    assert caps.temperature_support == "never"
    assert caps.reasoning_effort_values == ("none", "low", "medium", "high", "xhigh", "max")
    assert caps.thinking_param_style == "reasoning_effort_flat"
    assert caps.max_tokens_field == "max_completion_tokens"
    assert caps.max_output_tokens == 128_000
    responses_caps = capabilities_for_api_family(caps, "openai_responses")
    assert responses_caps.thinking_param_style == "reasoning_object"
