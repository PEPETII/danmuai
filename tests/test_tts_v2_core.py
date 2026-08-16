import io
import wave

import pytest
from app.tts import (
    AuthDescriptor,
    AuthFieldDescriptor,
    BaseTtsProvider,
    InMemoryCredentialStore,
    ModelDescriptor,
    PricingDescriptor,
    ProviderDescriptor,
    ProviderRegistry,
    TtsAudioDecodeError,
    TtsAuthError,
    TtsCapabilities,
    TtsCatalog,
    TtsInvalidVoiceError,
    TtsManager,
    TtsRequest,
    TtsResult,
    TtsUnsupportedCapabilityError,
    VoiceDescriptor,
    VoiceSource,
    pcm_to_wav,
)


def _wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(b"\x00\x00" * 4)
    return buffer.getvalue()


class FakeProvider(BaseTtsProvider):
    def __init__(self, descriptor: ProviderDescriptor) -> None:
        super().__init__(descriptor)
        self.calls = 0

    def synthesize(self, credentials, request, *, timeout_sec=60.0):
        del timeout_sec
        self.calls += 1
        assert credentials["api_key"] == "secret"
        return TtsResult(_wav(), "wav", provider_request_id="req-1")


def _provider(*, capabilities=None, voices=()):
    model = ModelDescriptor(
        id="model-1",
        label="Test model",
        capabilities=capabilities or TtsCapabilities(),
        pricing=PricingDescriptor(),
        voices=voices,
    )
    return ProviderDescriptor(
        id="provider-1",
        label="Test provider",
        auth=AuthDescriptor((AuthFieldDescriptor("api_key", "API key"),)),
        models=(model,),
    )


def _manager(descriptor=None):
    provider = FakeProvider(descriptor or _provider())
    registry = ProviderRegistry([provider])
    store = InMemoryCredentialStore()
    store.set("provider-1", {"api_key": "secret"})
    manager = TtsManager(registry, TtsCatalog([provider.descriptor]))
    manager.credentials = manager.credentials.__class__(store)
    return manager, provider


def test_registry_is_explicit_and_does_not_fallback():
    manager, _provider_instance = _manager()
    with pytest.raises(ValueError, match="Unknown TTS provider"):
        manager.synthesize(TtsRequest("hi", "missing", "model-1"))


def test_manager_validates_model_voice_and_capability():
    voice = VoiceDescriptor("voice-1", "Voice 1")
    descriptor = _provider(
        capabilities=TtsCapabilities(style_prompt=False),
        voices=(voice,),
    )
    manager, provider = _manager(descriptor)
    with pytest.raises(TtsUnsupportedCapabilityError):
        manager.synthesize(
            TtsRequest("hi", "provider-1", "model-1", style_prompt="bright")
        )
    with pytest.raises(TtsInvalidVoiceError):
        manager.synthesize(TtsRequest("hi", "provider-1", "model-1", voice_id="bad"))
    assert provider.calls == 0


def test_manager_rejects_historical_model_with_replacement_hint():
    model = ModelDescriptor(
        id="old-model",
        label="Old model",
        status="historical",
        replacement_model_id="model-1",
    )
    descriptor = ProviderDescriptor(
        id="provider-1",
        label="Test provider",
        auth=AuthDescriptor((AuthFieldDescriptor("api_key", "API key"),)),
        models=(model, _provider().models[0]),
    )
    manager, provider = _manager(descriptor)

    with pytest.raises(ValueError, match="historical.*model-1"):
        manager.synthesize(TtsRequest("hi", "provider-1", "old-model"))
    assert provider.calls == 0


def test_zero_numeric_options_still_require_capability():
    manager, provider = _manager()
    with pytest.raises(TtsUnsupportedCapabilityError):
        manager.synthesize(TtsRequest("hi", "provider-1", "model-1", speed=0))
    assert provider.calls == 0


def test_manager_returns_normalized_result_and_preserves_request_id():
    manager, provider = _manager()
    result = manager.synthesize(TtsRequest("hi", "provider-1", "model-1"))
    assert result.audio_format == "wav"
    assert result.provider_request_id == "req-1"
    assert provider.calls == 1


def test_provider_required_credentials_are_scoped_and_maskable():
    manager, _provider_instance = _manager()
    manager.credentials = manager.credentials.__class__(InMemoryCredentialStore())
    with pytest.raises(TtsAuthError):
        manager.synthesize(TtsRequest("hi", "provider-1", "model-1"))


def test_pcm_normalization_rejects_partial_frame_and_wraps_valid_audio():
    with pytest.raises(TtsAudioDecodeError):
        pcm_to_wav(b"\x00", sample_rate=24000, channels=1, sample_width=2)
    output = pcm_to_wav(b"\x00\x00" * 4)
    with wave.open(io.BytesIO(output), "rb") as wav_file:
        assert wav_file.getframerate() == 24000
        assert wav_file.getnframes() == 4


def test_catalog_pricing_is_unknown_until_official_data_is_supplied():
    descriptor = _provider()
    assert descriptor.models[0].pricing.kind == "unknown"
    assert descriptor.models[0].pricing.verified_at is None


def test_voice_cache_source_shape_and_dynamic_voice_fallback():
    voice = VoiceDescriptor("remote-1", "Remote voice", source=VoiceSource.REMOTE_CATALOG)
    capabilities = TtsCapabilities(voice_list=True, custom_voice_id=False)
    descriptor = _provider(capabilities=capabilities)
    manager, provider = _manager(descriptor)
    provider.list_voices = lambda credentials, *, model_id, force_refresh: [voice]
    voices = manager.list_voices("provider-1", "model-1")
    assert voices[0].source == VoiceSource.REMOTE_CATALOG
    assert manager.voice_cache.get("provider-1", "model-1").voices == (voice,)
    result = manager.synthesize(
        TtsRequest("hi", "provider-1", "model-1", voice_id="remote-1")
    )
    assert result.audio_format == "wav"
