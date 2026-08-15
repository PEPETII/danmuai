import base64
import io
import json
import wave

import pytest
from app.tts import (
    TtsAudioDecodeError,
    TtsAuthError,
    TtsProviderResponseError,
    TtsRateLimitError,
    TtsRequest,
    TtsResult,
    TtsUnsupportedCapabilityError,
)
from app.tts.providers.dashscope import (
    COSYVOICE_V35_FLASH,
    DASHSCOPE_COSYVOICE_ENDPOINT,
    DASHSCOPE_MODELS,
    DASHSCOPE_PROVIDER_ID,
    DASHSCOPE_QWEN_HTTP_ENDPOINT,
    QWEN3_TTS_FLASH,
    QWEN3_TTS_FLASH_REALTIME,
    QWEN3_TTS_INSTRUCT_FLASH,
    DashScopeProvider,
    parse_realtime_events,
)


def _wav() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(24000)
        wav_file.writeframes(b"\x00\x00" * 4)
    return output.getvalue()


def _request(model_id: str, **kwargs) -> TtsRequest:
    return TtsRequest("你好，世界", DASHSCOPE_PROVIDER_ID, model_id, **kwargs)


def test_descriptor_contains_only_the_five_verified_stable_models_and_separate_transports():
    provider = DashScopeProvider()
    assert [model.id for model in provider.descriptor.models] == [model.id for model in DASHSCOPE_MODELS]
    assert {model.id for model in DASHSCOPE_MODELS} == {
        QWEN3_TTS_FLASH,
        QWEN3_TTS_INSTRUCT_FLASH,
        QWEN3_TTS_FLASH_REALTIME,
        "cosyvoice-v3.5-flash",
        "cosyvoice-v3.5-plus",
    }
    assert provider.descriptor.models[0].transport == "qwen_http"
    assert provider.descriptor.models[2].transport == "qwen_realtime"
    assert provider.descriptor.models[3].transport == "cosyvoice_http"
    assert provider.descriptor.models[3].voices == ()


def test_qwen_http_generation_uses_bearer_input_and_downloads_audio(monkeypatch):
    wav = _wav()
    calls: list[tuple[str, dict]] = []

    class Response:
        status_code = 200
        headers = {"x-request-id": "req-qwen"}

        def json(self):
            return {
                "request_id": "req-qwen",
                "output": {"audio": {"url": "https://audio.invalid/qwen.wav"}},
            }

    class AudioResponse:
        status_code = 200
        content = wav

    class Client:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            del args

        def post(self, url, *, json, headers):
            calls.append((url, {"json": json, "headers": headers}))
            return Response()

        def get(self, url):
            assert url == "https://audio.invalid/qwen.wav"
            return AudioResponse()

    monkeypatch.setattr("app.tts.providers.dashscope.httpx.Client", Client)
    result = DashScopeProvider().synthesize(
        {"api_key": "test-key"}, _request(QWEN3_TTS_FLASH)
    )
    assert isinstance(result, TtsResult)
    assert result.audio_bytes == wav
    assert result.audio_format == "wav"
    assert calls[0][0] == DASHSCOPE_QWEN_HTTP_ENDPOINT
    assert calls[0][1]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0][1]["json"]["input"] == {
        "text": "你好，世界",
        "voice": "Cherry",
        "language_type": "Chinese",
    }


def test_qwen_instruct_only_sends_instructions_when_capability_allows(monkeypatch):
    captured: dict = {}
    encoded = base64.b64encode(_wav()).decode("ascii")

    class Response:
        status_code = 200
        headers = {}

        def json(self):
            return {"output": {"audio": {"data": encoded, "format": "wav"}}}

    class Client:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            del args

        def post(self, url, *, json, headers):
            del url, headers
            captured.update(json)
            return Response()

    monkeypatch.setattr("app.tts.providers.dashscope.httpx.Client", Client)
    DashScopeProvider().synthesize(
        {"api_key": "test-key"},
        _request(QWEN3_TTS_INSTRUCT_FLASH, style_prompt="温柔、慢一点"),
    )
    assert captured["input"]["instructions"] == "温柔、慢一点"
    assert captured["input"]["optimize_instructions"] is True
    with pytest.raises(TtsUnsupportedCapabilityError):
        DashScopeProvider().synthesize(
            {"api_key": "test-key"},
            _request(QWEN3_TTS_FLASH, style_prompt="不能发送"),
        )


def test_realtime_event_parser_collects_deltas_and_rejects_malformed_base64():
    first = base64.b64encode(b"pcm-1").decode("ascii")
    second = base64.b64encode(b"pcm-2").decode("ascii")
    audio, request_id = parse_realtime_events(
        [
            {"type": "response.audio.delta", "delta": first},
            {"type": "response.audio.delta", "delta": second},
            {"type": "response.audio.done", "request_id": "req-rt"},
        ]
    )
    assert audio == b"pcm-1pcm-2"
    assert request_id == "req-rt"
    with pytest.raises(TtsAudioDecodeError):
        parse_realtime_events([{"type": "response.audio.delta", "delta": "!!!"}])


def test_realtime_transport_uses_model_url_and_returns_pcm():
    events = [
        {"type": "response.audio.delta", "delta": base64.b64encode(b"pcm").decode()},
        {"type": "response.audio.done", "request_id": "req-realtime"},
    ]
    captured: dict = {}

    class Client:
        def __init__(self, callback):
            self.callback = callback

        def connect(self):
            self.callback.on_open()
            for event in events:
                self.callback.on_event(event)

        def update_session(self, **kwargs):
            captured["session"] = kwargs

        def append_text(self, text):
            captured["text"] = text

        def finish(self):
            return None

    def factory(model_id, callback, url, api_key):
        captured.update(model=model_id, url=url, api_key=api_key)
        return Client(callback)

    result = DashScopeProvider(realtime_client_factory=factory).synthesize(
        {"api_key": "test-key"}, _request(QWEN3_TTS_FLASH_REALTIME)
    )
    assert result.audio_format == "pcm"
    assert result.audio_bytes == b"pcm"
    assert "model=qwen3-tts-flash-realtime" in captured["url"]
    assert captured["session"]["response_format"] == "pcm"


def test_cosyvoice_has_no_qwen_static_voice_and_uses_its_own_sse_protocol(monkeypatch):
    captured: dict = {}
    encoded = base64.b64encode(b"cosy-pcm").decode("ascii")

    class StreamResponse:
        status_code = 200
        headers = {}

        def iter_lines(self):
            yield "data: " + json.dumps(
                {"output": {"audio": {"data": encoded, "format": "pcm"}}}
            )
            yield ""

    class StreamContext:
        def __enter__(self):
            return StreamResponse()

        def __exit__(self, *args):
            del args

    class Client:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            del args

        def stream(self, method, url, *, json, headers):
            captured.update(method=method, url=url, json=json, headers=headers)
            return StreamContext()

    monkeypatch.setattr("app.tts.providers.dashscope.httpx.Client", Client)
    provider = DashScopeProvider()
    model = provider.descriptor.models[3]
    assert model.id == COSYVOICE_V35_FLASH
    assert model.voices == ()
    result = provider.synthesize(
        {"api_key": "test-key"},
        _request(COSYVOICE_V35_FLASH, voice_id="custom-voice", style_prompt="温柔", streaming=True),
    )
    assert result.audio_bytes == b"cosy-pcm"
    assert result.audio_format == "pcm"
    assert captured["url"] == DASHSCOPE_COSYVOICE_ENDPOINT
    assert captured["headers"]["X-DashScope-SSE"] == "enable"
    assert captured["json"]["input"]["voice"] == "custom-voice"
    assert captured["json"]["input"]["instruction"] == "温柔"
    assert "Cherry" not in json.dumps(captured["json"])


@pytest.mark.parametrize(
    ("status_code", "error_type"),
    [(401, TtsAuthError), (429, TtsRateLimitError)],
)
def test_http_errors_are_normalized_without_leaking_api_key(monkeypatch, status_code, error_type):
    secret = "dashscope-test-secret"

    class Response:
        def __init__(self):
            self.status_code = status_code
            self.headers = {"x-request-id": "req-error"}

        def json(self):
            return {"message": secret}

    class Client:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            del args

        def post(self, url, *, json, headers):
            del url, json, headers
            return Response()

    monkeypatch.setattr("app.tts.providers.dashscope.httpx.Client", Client)
    with pytest.raises(error_type) as exc_info:
        DashScopeProvider().synthesize({"api_key": secret}, _request(QWEN3_TTS_FLASH))
    assert secret not in str(exc_info.value)
    assert exc_info.value.provider_request_id == "req-error"


def test_malformed_http_audio_is_normalized(monkeypatch):
    class Response:
        status_code = 200
        headers = {}

        def json(self):
            return {"output": {"audio": {"data": "not-base64"}}}

    class Client:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            del args

        def post(self, url, *, json, headers):
            del url, json, headers
            return Response()

    monkeypatch.setattr("app.tts.providers.dashscope.httpx.Client", Client)
    with pytest.raises(TtsAudioDecodeError):
        DashScopeProvider().synthesize({"api_key": "test-key"}, _request(QWEN3_TTS_FLASH))


def test_missing_http_audio_is_normalized(monkeypatch):
    class Response:
        status_code = 200
        headers = {}

        def json(self):
            return {"output": {"finish_reason": "stop"}}

    class Client:
        def __init__(self, *args, **kwargs):
            del args, kwargs

        def __enter__(self):
            return self

        def __exit__(self, *args):
            del args

        def post(self, url, *, json, headers):
            del url, json, headers
            return Response()

    monkeypatch.setattr("app.tts.providers.dashscope.httpx.Client", Client)
    with pytest.raises(TtsProviderResponseError):
        DashScopeProvider().synthesize({"api_key": "test-key"}, _request(QWEN3_TTS_FLASH))
