from app.tts_catalog import (
    default_voice_for_provider,
    list_catalog_for_api,
    normalize_catalog_voice,
)
from app.tts_providers import TTS_PROVIDER_DASHSCOPE_QWEN, TTS_PROVIDER_MIMO


def test_list_catalog_for_api_has_providers():
    data = list_catalog_for_api()
    ids = {p["id"] for p in data}
    assert TTS_PROVIDER_MIMO in ids
    assert TTS_PROVIDER_DASHSCOPE_QWEN in ids
    assert "doubao" in ids
    assert "minimax" in ids
    assert "custom_openai" not in ids


def test_normalize_catalog_voice_dashscope():
    voice = normalize_catalog_voice(
        "invalid",
        provider_id=TTS_PROVIDER_DASHSCOPE_QWEN,
        model_id="qwen3-tts-flash-2025-11-27",
    )
    assert voice == "Cherry"


def test_default_voice_mimo():
    assert default_voice_for_provider(TTS_PROVIDER_MIMO) == "mimo_default"
