from __future__ import annotations

import base64
import json
from contextlib import contextmanager

import pytest
from app.tts.providers.doubao import (
    DOUBAO_LIST_SPEAKERS_ENDPOINT,
    DOUBAO_MODEL_ID,
    DOUBAO_PROVIDER_ID,
    DOUBAO_TTS_ENDPOINT,
    DoubaoProvider,
    parse_doubao_v3_chunks,
)
from app.tts.types import (
    TtsAuthError,
    TtsConfigurationError,
    TtsProviderResponseError,
    TtsRateLimitError,
    TtsRequest,
)


class _FakeResponse:
    def __init__(self, *, chunks=(), status_code=200, body=None, headers=None):
        self.status_code = status_code
        self._chunks = tuple(chunks)
        self._body = body
        self.headers = headers or {}
        self.text = json.dumps(body, ensure_ascii=False) if body is not None else ""

    def iter_bytes(self):
        yield from self._chunks

    def json(self):
        if self._body is None:
            raise ValueError("no JSON body")
        return self._body


class _FakeTransport:
    def __init__(self, response):
        self.response = response
        self.stream_calls = []
        self.request_calls = []

    @contextmanager
    def stream(self, method, url, **kwargs):
        self.stream_calls.append((method, url, kwargs))
        yield self.response

    def request(self, method, url, **kwargs):
        self.request_calls.append((method, url, kwargs))
        return self.response


def _request(*, voice="zh_female_test", output_format="mp3", **kwargs):
    return TtsRequest(
        text="你好，豆包",
        provider_id=DOUBAO_PROVIDER_ID,
        model_id=DOUBAO_MODEL_ID,
        voice_id=voice,
        output_format=output_format,
        streaming=True,
        **kwargs,
    )


def _audio_frame(audio: bytes, *, audio_format="mp3", sample_rate=None):
    frame = {
        "data": base64.b64encode(audio).decode("ascii"),
        "format": audio_format,
    }
    if sample_rate is not None:
        frame["sample_rate"] = sample_rate
    return json.dumps(frame).encode("utf-8")


def test_descriptor_and_auth_schema_are_v3_only():
    provider = DoubaoProvider()

    assert provider.descriptor.id == DOUBAO_PROVIDER_ID
    assert [model.id for model in provider.descriptor.models] == [DOUBAO_MODEL_ID]
    assert provider.descriptor.models[0].recommended is True
    assert provider.descriptor.models[0].transport == "http_chunked_unidirectional"
    assert len(provider.descriptor.models[0].voices) == 10
    assert provider.descriptor.models[0].pricing.amount == 5.0
    assert {field.id for field in provider.descriptor.auth_schema} == {
        "api_key",
        "access_key_id",
        "secret_access_key",
    }

    provider.validate_credentials({"api_key": "tts-key"})
    provider.validate_credentials({"access_key_id": "ak", "secret_access_key": "sk"})
    with pytest.raises(TtsAuthError, match="legacy AppID/AccessToken"):
        provider.validate_credentials({"app_id": "old-app", "access_token": "old-token"})
    with pytest.raises(TtsAuthError, match="cannot be mixed"):
        provider.validate_credentials({"api_key": "tts-key", "access_key_id": "ak"})


def test_synthesize_uses_v3_http_chunked_transport_and_normalizes_stream():
    response = _FakeResponse(
        chunks=(
            _audio_frame(b"ID3-part-1"),
            _audio_frame(b"part-2"),
        ),
        headers={"X-Api-Request-Id": "server-request-id"},
    )
    transport = _FakeTransport(response)
    provider = DoubaoProvider(transport=transport, request_id_factory=lambda: "client-request-id")

    result = provider.synthesize({"api_key": "tts-key"}, _request())

    assert result.audio_bytes == b"ID3-part-1part-2"
    assert result.audio_format == "mp3"
    assert result.provider_request_id == "server-request-id"
    method, url, kwargs = transport.stream_calls[0]
    assert method == "POST"
    assert url == DOUBAO_TTS_ENDPOINT
    assert kwargs["headers"]["X-Api-Key"] == "tts-key"
    assert kwargs["headers"]["X-Api-Resource-Id"] == DOUBAO_MODEL_ID
    assert kwargs["headers"]["X-Api-Request-Id"] == "client-request-id"
    assert kwargs["json"]["req_params"]["text"] == "你好，豆包"
    assert kwargs["json"]["req_params"]["speaker"] == "zh_female_test"


def test_synthesize_maps_official_speed_volume_and_emotion_parameters():
    response = _FakeResponse(chunks=(_audio_frame(b"audio"),))
    transport = _FakeTransport(response)
    provider = DoubaoProvider(transport=transport)

    provider.synthesize(
        {"api_key": "tts-key"},
        _request(speed=1.5, volume=1.2, emotion="happy"),
    )

    request_params = transport.stream_calls[0][2]["json"]["req_params"]
    assert request_params["speed_ratio"] == 1.5
    assert request_params["loudness_ratio"] == 1.2
    assert request_params["emotion"] == "happy"
    assert request_params["enable_emotion"] is True


@pytest.mark.parametrize(
    ("field", "value"),
    [("speed", 0.05), ("volume", 2.1)],
)
def test_synthesize_enforces_official_numeric_ranges(field, value):
    provider = DoubaoProvider()
    with pytest.raises(TtsConfigurationError, match="out of range"):
        provider.synthesize(
            {"api_key": "tts-key"},
            _request(**{field: value}),
        )


@pytest.mark.parametrize(
    ("audio_format", "sample_rate", "payload"),
    [("pcm", 24000, b"\x00\x00\x01\x00"), ("mp3", None, b"ID3fake")],
)
def test_parser_handles_split_json_and_audio_formats(audio_format, sample_rate, payload):
    encoded = _audio_frame(payload, audio_format=audio_format, sample_rate=sample_rate)
    midpoint = len(encoded) // 2

    audio, fmt, rate = parse_doubao_v3_chunks((encoded[:midpoint], encoded[midpoint:]))

    assert audio == payload
    assert fmt == audio_format
    assert rate == sample_rate


def test_malformed_response_requires_protocol_fields_and_valid_base64():
    missing_format = json.dumps({"data": base64.b64encode(b"audio").decode("ascii")}).encode()
    with pytest.raises(TtsProviderResponseError, match="missing required format"):
        parse_doubao_v3_chunks((missing_format,))

    malformed_base64 = b'{"data":"not-base64!","format":"mp3"}'
    with pytest.raises(TtsProviderResponseError, match="valid base64"):
        parse_doubao_v3_chunks((malformed_base64,))

    with pytest.raises(TtsProviderResponseError, match="no audio data"):
        parse_doubao_v3_chunks((b'{"code":0,"is_last_package":true}',))


def test_auth_error_redacts_tts_secret_and_never_uses_legacy_headers():
    secret = "tts-secret-value"
    response = _FakeResponse(
        status_code=401,
        body={"message": f"invalid api_key={secret}"},
    )
    transport = _FakeTransport(response)
    provider = DoubaoProvider(transport=transport)

    with pytest.raises(TtsAuthError) as exc_info:
        provider.synthesize({"api_key": secret}, _request())

    error_text = str(exc_info.value)
    assert secret not in error_text
    assert "<redacted>" in error_text
    headers = transport.stream_calls[0][2]["headers"]
    assert headers["X-Api-Key"] == secret
    assert "X-Api-App-Key" not in headers
    assert "X-Api-Access-Key" not in headers


def test_rate_limit_is_normalized_without_exposing_credentials():
    response = _FakeResponse(status_code=429, body={"message": "slow down"})
    provider = DoubaoProvider(transport=_FakeTransport(response))

    with pytest.raises(TtsRateLimitError, match="status=429"):
        provider.synthesize({"api_key": "tts-key"}, _request())


def test_list_speakers_uses_injected_ak_sk_hmac_transport_only():
    response = _FakeResponse(
        body={
            "code": 0,
            "data": {
                "speakers": [
                    {
                        "voice_type": "voice-1",
                        "name": "测试音色",
                        "gender": "female",
                        "language": ["zh-CN"],
                        "trial_url": "https://example.invalid/preview.mp3",
                    }
                ]
            },
        }
    )
    transport = _FakeTransport(response)
    provider = DoubaoProvider(speaker_transport=transport)

    voices = provider.list_voices(
        {"access_key_id": "ak-test", "secret_access_key": "sk-test"},
        model_id=DOUBAO_MODEL_ID,
    )

    assert voices[0].id == "voice-1"
    assert voices[0].source == "remote_catalog"
    method, url, kwargs = transport.request_calls[0]
    assert method == "POST"
    assert url == DOUBAO_LIST_SPEAKERS_ENDPOINT
    assert kwargs["headers"]["Authorization"].startswith("HMAC-SHA256 Credential=ak-test/")
    assert "X-Api-Key" not in kwargs["headers"]
    assert kwargs["json"] == {
        "ResourceIDs": [DOUBAO_MODEL_ID],
        "Page": 1,
        "Limit": 30,
    }
    with pytest.raises(TtsAuthError, match="AK/SK"):
        provider.list_voices({"api_key": "tts-key"}, model_id=DOUBAO_MODEL_ID)


def test_list_speakers_maps_official_uppercase_result_fields():
    response = _FakeResponse(
        body={
            "Code": 0,
            "Result": {
                "Speakers": [
                    {
                        "VoiceType": "zh_female_official",
                        "Name": "官方女声",
                        "Gender": "female",
                        "Languages": ["zh-CN"],
                        "Emotions": ["happy"],
                        "Categories": ["通用"],
                        "Description": "官方描述",
                        "TrialURL": "https://example.invalid/official.mp3",
                    }
                ]
            },
        }
    )
    provider = DoubaoProvider(speaker_transport=_FakeTransport(response))

    voices = provider.list_voices(
        {"access_key_id": "ak-test", "secret_access_key": "sk-test"},
        model_id=DOUBAO_MODEL_ID,
    )

    assert voices[0].id == "zh_female_official"
    assert voices[0].name == "官方女声"
    assert voices[0].description == "官方描述"
    assert voices[0].languages == ("zh-CN",)
    assert voices[0].emotions == ("happy",)
    assert voices[0].preview_url.endswith("official.mp3")
