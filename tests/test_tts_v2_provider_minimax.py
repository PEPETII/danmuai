import pytest
from app.tts import (
    TtsAudioDecodeError,
    TtsAuthError,
    TtsConfigurationError,
    TtsProviderResponseError,
    TtsRateLimitError,
    TtsRequest,
    TtsUnsupportedCapabilityError,
    VoiceSource,
)
from app.tts.providers.minimax import (
    MINIMAX_CURRENT_MODELS,
    MINIMAX_DEFAULT_VOICE,
    MINIMAX_GET_VOICE_ENDPOINT,
    MINIMAX_HISTORICAL_MODELS,
    MINIMAX_PROVIDER_ID,
    MINIMAX_RECOMMENDED_VOICES,
    MINIMAX_T2A_ENDPOINT,
    MiniMaxProvider,
)


class FakeResponse:
    def __init__(self, body, *, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, **_kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def post(self, url, *, json, headers):
        self.calls.append((url, json, headers))
        return self.response


def _request(**kwargs):
    values = {
        "text": "你好，MiniMax",
        "provider_id": MINIMAX_PROVIDER_ID,
        "model_id": "speech-2.8-turbo",
        "output_format": "mp3",
    }
    values.update(kwargs)
    return TtsRequest(**values)


def _success_body(audio_hex="494433", trace_id="trace-minimax"):
    return {
        "data": {"audio": audio_hex, "status": 2},
        "extra_info": {"audio_sample_rate": 32000, "audio_format": "mp3"},
        "trace_id": trace_id,
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }


def test_descriptor_has_current_and_historical_models_with_official_prices():
    descriptor = MiniMaxProvider().descriptor
    models = {model.id: model for model in descriptor.models}
    assert tuple(model.id for model in descriptor.models[:2]) == MINIMAX_CURRENT_MODELS
    assert set(MINIMAX_HISTORICAL_MODELS) <= set(models)
    assert models["speech-2.8-turbo"].recommended is True
    assert models["speech-2.8-turbo"].status == "active"
    assert models["speech-2.6-turbo"].status == "historical"
    assert models["speech-2.8-turbo"].pricing.amount == 2.0
    assert models["speech-2.8-hd"].pricing.amount == 3.5
    assert models["speech-02-hd"].replacement_model_id == "speech-2.8-hd"
    assert all(model.pricing.source_url for model in models.values())


def test_missing_api_key_is_normalized_without_network_call():
    provider = MiniMaxProvider()
    with pytest.raises(TtsAuthError):
        provider.synthesize({}, _request())


def test_success_maps_payload_and_hex_audio():
    client = FakeClient(FakeResponse(_success_body()))
    provider = MiniMaxProvider(client_factory=client)
    result = provider.synthesize(
        {"api_key": "secret-key"},
        _request(speed=1.25, volume=0.8, pitch=-1, emotion="happy", voice_id="voice-1"),
    )
    assert result.audio_bytes == bytes.fromhex("494433")
    assert result.audio_format == "mp3"
    assert result.sample_rate == 32000
    assert result.provider_request_id == "trace-minimax"
    url, payload, headers = client.calls[0]
    assert url == MINIMAX_T2A_ENDPOINT
    assert headers == {"Authorization": "Bearer secret-key", "Content-Type": "application/json"}
    assert payload["model"] == "speech-2.8-turbo"
    assert payload["stream"] is False
    assert payload["voice_setting"] == {
        "voice_id": "voice-1",
        "speed": 1.25,
        "vol": 0.8,
        "pitch": -1,
        "emotion": "happy",
    }
    assert payload["audio_setting"] == {"format": "mp3"}
    assert payload["output_format"] == "hex"


@pytest.mark.parametrize("status_code, error_type", [(401, TtsAuthError), (429, TtsRateLimitError)])
def test_http_auth_and_rate_limit_are_normalized(status_code, error_type):
    client = FakeClient(FakeResponse({}, status_code=status_code))
    provider = MiniMaxProvider(client_factory=client)
    with pytest.raises(error_type) as exc_info:
        provider.synthesize({"api_key": "secret-key"}, _request())
    assert "secret-key" not in str(exc_info.value)


def test_provider_error_and_malformed_audio_are_normalized():
    provider_error = MiniMaxProvider(
        client_factory=FakeClient(
            FakeResponse(
                {
                    "trace_id": "trace-error",
                    "base_resp": {"status_code": 1002, "status_msg": "rate limit"},
                }
            )
        )
    )
    with pytest.raises(TtsRateLimitError) as rate_error:
        provider_error.synthesize({"api_key": "secret-key"}, _request())
    assert rate_error.value.provider_request_id == "trace-error"

    malformed = MiniMaxProvider(client_factory=FakeClient(FakeResponse(_success_body("not-hex"))))
    with pytest.raises(TtsAudioDecodeError):
        malformed.synthesize({"api_key": "secret-key"}, _request())

    missing_audio = MiniMaxProvider(
        client_factory=FakeClient(
            FakeResponse({"base_resp": {"status_code": 0, "status_msg": "success"}})
        )
    )
    with pytest.raises(TtsProviderResponseError):
        missing_audio.synthesize({"api_key": "secret-key"}, _request())


def test_unknown_model_empty_text_and_unsupported_options_are_rejected():
    provider = MiniMaxProvider()
    with pytest.raises(TtsConfigurationError):
        provider.synthesize(
            {"api_key": "secret-key"},
            _request(model_id="speech-9.9"),
        )
    with pytest.raises(TtsConfigurationError):
        provider.synthesize(
            {"api_key": "secret-key"},
            _request(text=""),
        )
    with pytest.raises(TtsUnsupportedCapabilityError):
        provider.synthesize(
            {"api_key": "secret-key"},
            _request(style_prompt="warm"),
        )


def test_dynamic_voice_list_maps_categories_and_falls_back_on_failure():
    voice_body = {
        "system_voice": [{"voice_id": "system-1", "voice_name": "System One"}],
        "voice_cloning": [{"voice_id": "clone-1", "description": []}],
        "voice_generation": [{"voice_id": "design-1", "description": []}],
        "base_resp": {"status_code": 0, "status_msg": "success"},
    }
    client = FakeClient(FakeResponse(voice_body))
    provider = MiniMaxProvider(client_factory=client)
    voices = provider.list_voices({"api_key": "secret-key"}, model_id="speech-2.8-hd")
    assert [voice.id for voice in voices] == ["system-1", "clone-1", "design-1"]
    assert [voice.source for voice in voices] == [
        VoiceSource.REMOTE_CATALOG,
        VoiceSource.CLONED_VOICE,
        VoiceSource.DESIGNED_VOICE,
    ]
    assert client.calls[0][0] == MINIMAX_GET_VOICE_ENDPOINT
    assert client.calls[0][1] == {"voice_type": "all"}

    fallback = MiniMaxProvider(client_factory=FakeClient(FakeResponse({}, status_code=503)))
    voices = fallback.list_voices({"api_key": "secret-key"}, model_id="speech-2.8-hd")
    assert [voice.id for voice in voices] == list(MINIMAX_RECOMMENDED_VOICES)
    assert voices[0].id == MINIMAX_DEFAULT_VOICE
