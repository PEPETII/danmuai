import base64
import json

import httpx
import pytest
from app.tts import (
    TtsAudioDecodeError,
    TtsAuthError,
    TtsConfigurationError,
    TtsProviderResponseError,
    TtsRateLimitError,
    TtsRequest,
    TtsUnsupportedCapabilityError,
)
from app.tts.providers.mimo import (
    MIMO_CHAT_COMPLETIONS_PATH,
    MIMO_MODEL_ID,
    MIMO_PROVIDER_ID,
    MIMO_TTS_VOICES,
    MimoProvider,
)

API_KEY = "mimo-test-key"
TEXT = "今天直播间气氛很好。"


def _request(*, style_prompt=None, voice_id=None, streaming=False, output_format="wav"):
    return TtsRequest(
        text=TEXT,
        provider_id=MIMO_PROVIDER_ID,
        model_id=MIMO_MODEL_ID,
        voice_id=voice_id,
        style_prompt=style_prompt,
        streaming=streaming,
        output_format=output_format,
    )


def _transport(handler):
    return httpx.MockTransport(handler)


def _audio_response(data=b"fake-wav", *, request_id="mimo-req-1"):
    return httpx.Response(
        200,
        headers={"x-request-id": request_id},
        json={
            "id": request_id,
            "choices": [{"message": {"audio": {"data": base64.b64encode(data).decode()}}}],
        },
    )


def test_descriptor_and_existing_voices_are_available():
    provider = MimoProvider(transport=_transport(lambda request: _audio_response()))

    assert provider.descriptor.id == MIMO_PROVIDER_ID
    assert provider.descriptor.models[0].id == MIMO_MODEL_ID
    assert [voice.id for voice in provider.list_voices({}, model_id=MIMO_MODEL_ID)] == list(
        MIMO_TTS_VOICES
    )
    assert provider.descriptor.models[0].capabilities.streaming is True


def test_non_streaming_payload_uses_assistant_text_optional_user_style_and_bearer():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["authorization"] = request.headers["authorization"]
        seen["payload"] = json.loads(request.content)
        return _audio_response()

    provider = MimoProvider(transport=_transport(handler))
    result = provider.synthesize(
        {"api_key": API_KEY},
        _request(style_prompt="温柔、轻快", voice_id="Mia"),
    )

    assert seen["url"].endswith(MIMO_CHAT_COMPLETIONS_PATH)
    assert seen["authorization"] == f"Bearer {API_KEY}"
    assert seen["payload"] == {
        "model": MIMO_MODEL_ID,
        "messages": [
            {"role": "user", "content": "温柔、轻快"},
            {"role": "assistant", "content": TEXT},
        ],
        "audio": {"format": "wav", "voice": "Mia"},
    }
    assert result.audio_bytes == b"fake-wav"
    assert result.audio_format == "wav"
    assert result.provider_request_id == "mimo-req-1"


def test_empty_text_and_missing_credentials_are_normalized():
    provider = MimoProvider(transport=_transport(lambda request: _audio_response()))

    with pytest.raises(TtsConfigurationError, match="must not be empty"):
        provider.synthesize(
            {"api_key": API_KEY},
            TtsRequest(
                text="   ",
                provider_id=MIMO_PROVIDER_ID,
                model_id=MIMO_MODEL_ID,
            ),
        )
    with pytest.raises(TtsAuthError):
        provider.synthesize({}, _request())


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(401, TtsAuthError), (403, TtsAuthError), (429, TtsRateLimitError)],
)
def test_http_auth_and_rate_errors_are_normalized_without_secret(status_code, error_type):
    provider = MimoProvider(
        transport=_transport(lambda request: httpx.Response(status_code, json={"error": API_KEY}))
    )

    with pytest.raises(error_type) as exc_info:
        provider.synthesize({"api_key": API_KEY}, _request())
    assert API_KEY not in str(exc_info.value)


def test_missing_audio_and_bad_base64_are_normalized():
    missing_audio = MimoProvider(
        transport=_transport(
            lambda request: httpx.Response(200, json={"choices": [{"message": {}}]})
        )
    )
    with pytest.raises(TtsProviderResponseError):
        missing_audio.synthesize({"api_key": API_KEY}, _request())

    bad_base64 = MimoProvider(
        transport=_transport(
            lambda request: httpx.Response(
                200,
                json={"choices": [{"message": {"audio": {"data": "not base64"}}}]},
            )
        )
    )
    with pytest.raises(TtsAudioDecodeError):
        bad_base64.synthesize({"api_key": API_KEY}, _request())


def test_streaming_is_a_separate_pcm16_method_and_does_not_claim_playback():
    events = [
        "data: "
        + json.dumps(
            {
                "id": "stream-1",
                "choices": [
                    {"delta": {"audio": {"data": base64.b64encode(bytes((0, 0))).decode()}}}
                ],
            }
        ),
        "data: [DONE]",
    ]

    def handler(request):
        assert json.loads(request.content)["audio"]["format"] == "pcm16"
        assert json.loads(request.content)["stream"] is True
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=("\n".join(events) + "\n").encode(),
        )

    provider = MimoProvider(transport=_transport(handler))
    chunks = list(
        provider.synthesize_stream(
            {"api_key": API_KEY},
            _request(streaming=True, output_format="pcm16"),
        )
    )

    assert len(chunks) == 1
    assert chunks[0].audio_bytes == bytes((0, 0))
    assert chunks[0].audio_format == "pcm16"
    assert chunks[0].sample_rate == 24000


def test_normal_synthesis_rejects_streaming_request_instead_of_hiding_it():
    provider = MimoProvider(transport=_transport(lambda request: _audio_response()))
    with pytest.raises(TtsUnsupportedCapabilityError, match="synthesize_stream"):
        provider.synthesize(
            {"api_key": API_KEY},
            _request(streaming=True, output_format="pcm16"),
        )
