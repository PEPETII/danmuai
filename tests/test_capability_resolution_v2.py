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
