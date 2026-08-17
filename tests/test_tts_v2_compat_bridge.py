import io
import wave

import pytest
from app import tts_providers
from app.tts.types import TtsResult

from tests.fakes import FakeConfig


def _wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(b"\x00\x00" * 4)
    return output.getvalue()


def test_default_registry_contains_all_v2_providers():
    assert tts_providers.get_tts_registry().ids() == (
        "mimo",
        "dashscope",
        "minimax",
        "doubao",
    )


def test_legacy_dashscope_alias_resolves_to_stable_v2_model():
    resolved = tts_providers.resolve_tts_config(
        FakeConfig(
            {
                "tts_provider": tts_providers.TTS_PROVIDER_DASHSCOPE_QWEN,
                "tts_model_id": "qwen3-tts-flash-2025-11-27",
            }
        )
    )
    assert resolved.provider == tts_providers.TTS_PROVIDER_DASHSCOPE_QWEN
    assert resolved.model == "qwen3-tts-flash-2025-11-27"
    assert (
        tts_providers.canonical_tts_model_id("dashscope", resolved.model)
        == "qwen3-tts-flash"
    )


def test_stored_catalog_only_model_falls_back_to_active_model():
    resolved = tts_providers.resolve_tts_config(
        FakeConfig(
            {
                "tts_provider": "dashscope",
                "tts_model_id": "qwen-audio-3.0-tts-flash",
            }
        )
    )
    assert resolved.model == "qwen3-tts-flash"


@pytest.mark.parametrize(
    ("provider", "model"),
    [
        ("mimo", "mimo-v2.5-tts"),
        ("dashscope_qwen", "qwen3-tts-flash-2025-11-27"),
        ("dashscope", "qwen3-tts-flash"),
        ("minimax", "speech-2.8-turbo"),
        ("doubao", "seed-tts-2.0"),
    ],
)
def test_synthesize_tts_dispatches_explicit_provider(provider, model, monkeypatch):
    calls = []

    class Catalog:
        def require_model(self, provider_id, model_id):
            return object()

    class Manager:
        catalog = Catalog()

        def synthesize(self, request, *, credentials, timeout_sec):
            calls.append((request, credentials, timeout_sec))
            return TtsResult(_wav(), "wav")

    monkeypatch.setattr(tts_providers, "get_tts_manager", lambda: Manager())
    resolved = tts_providers.ResolvedTtsConfig(
        provider=provider,
        endpoint="",
        model=model,
        is_custom=provider != "mimo",
        stored_provider=provider,
        stored_endpoint="",
        stored_model_id=model,
    )
    output = tts_providers.synthesize_tts(
        "secret", "你好", resolved=resolved, credentials={"api_key": "other"}
    )

    assert output.startswith(b"RIFF")
    request, credentials, _timeout = calls[0]
    expected_provider = "dashscope" if provider == "dashscope_qwen" else provider
    assert request.provider_id == expected_provider
    assert request.output_format == ("mp3" if expected_provider == "doubao" else "wav")
    assert credentials == {"api_key": "other"}


def test_unsupported_audio_format_is_explicit(monkeypatch):
    class Catalog:
        def require_model(self, provider_id, model_id):
            return object()

    class Manager:
        catalog = Catalog()

        def synthesize(self, request, *, credentials, timeout_sec):
            return TtsResult(b"not-audio", "mp3")

    monkeypatch.setattr(tts_providers, "get_tts_manager", lambda: Manager())
    resolved = tts_providers.ResolvedTtsConfig(
        provider="minimax",
        endpoint="",
        model="speech-2.8-turbo",
        is_custom=True,
        stored_provider="minimax",
        stored_endpoint="",
        stored_model_id="speech-2.8-turbo",
    )
    with pytest.raises(tts_providers.DanmuTtsError, match="Unsupported TTS audio format"):
        tts_providers.synthesize_tts("secret", "你好", resolved=resolved)


def test_unknown_provider_does_not_fallback():
    with pytest.raises(ValueError, match="不支持的.*平台"):
        tts_providers.resolve_tts_config(FakeConfig({"tts_provider": "unknown"}))
