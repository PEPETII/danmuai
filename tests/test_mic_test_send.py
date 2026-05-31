import struct
from unittest.mock import MagicMock

from app.mic_test_send import (
    MicSendProbeResult,
    placeholder_image_data_uri,
    run_mic_test_send,
    send_mic_probe,
)


def test_placeholder_image_data_uri():
    uri = placeholder_image_data_uri()
    assert uri.startswith("data:image/jpeg;base64,")


def test_run_mic_test_send_unsupported_api():
    app = MagicMock()
    app.mic_audio_supported.return_value = False

    result = run_mic_test_send(app)

    assert result.ok is False
    assert result.error == "unsupported_api_mode"


def test_send_mic_probe_incomplete_credentials():
    config = MagicMock()
    worker = MagicMock()
    worker._resolve_request_credentials.return_value = None

    result = send_mic_probe(
        config,
        worker,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert result.ok is False
    assert result.error == "incomplete_credentials"


def test_send_mic_probe_unsupported_model():
    config = MagicMock()
    worker = MagicMock()
    worker._resolve_request_credentials.return_value = (
        "https://ark.cn-beijing.volces.com/api/v3",
        "sk-test",
        "doubao-seed-1-6-flash-250828",
        "doubao",
    )

    result = send_mic_probe(
        config,
        worker,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert result.ok is False
    assert result.error == "unsupported_model"


def test_send_mic_probe_unsupported_generic_openai():
    config = MagicMock()
    worker = MagicMock()
    worker._resolve_request_credentials.return_value = (
        "https://example.com/v1",
        "sk-test",
        "gpt-4o",
        "openai",
    )

    result = send_mic_probe(
        config,
        worker,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert result.ok is False
    assert result.error == "unsupported_model"


def test_send_mic_probe_success_mimo_via_request():
    worker = MagicMock()
    worker._resolve_request_credentials.return_value = (
        "https://api.xiaomimimo.com/v1",
        "sk-test",
        "mimo-v2.5",
        "openai-compatible",
    )

    def fake_request(*args, **kwargs):
        worker._emit_result(
            "finished",
            "heard",
            "mic_probe",
            0,
            0,
            0.0,
            0,
            50,
            8,
        )

    worker._request.side_effect = fake_request

    result = send_mic_probe(
        MagicMock(),
        worker,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert result.ok is True
    worker._request.assert_called_once()
    worker._request_doubao.assert_not_called()


def test_send_mic_probe_success_via_worker():
    worker = MagicMock()
    worker._resolve_request_credentials.return_value = (
        "https://ark.cn-beijing.volces.com/api/v3",
        "sk-test",
        "doubao-seed-2-0-mini-260428",
        "doubao",
    )

    def fake_request_doubao(*args, **kwargs):
        worker._emit_result(
            "finished",
            "received",
            "mic_probe",
            0,
            0,
            0.0,
            0,
            900,
            12,
        )

    worker._request_doubao.side_effect = fake_request_doubao

    result = send_mic_probe(
        MagicMock(),
        worker,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert result.ok is True
    assert result.input_tokens == 900
    assert result.reply_preview == "received"


def test_run_mic_test_send_success(monkeypatch):
    pcm = struct.pack("<8000h", *([1000] * 8000))
    capture_result = MagicMock(
        wav_ok=True,
        pcm_bytes=len(pcm),
        rms=1000,
        level="good",
        message="ok",
        error="",
    )
    monkeypatch.setattr(
        "app.mic_test_send.pcm_to_wav_data_uri",
        lambda _pcm: "data:audio/wav;base64,abc",
    )

    app = MagicMock()
    app.mic_audio_supported.return_value = True
    app.config = MagicMock()
    app.engine.running = False
    app.capture_mic_test_sample.return_value = (pcm, capture_result)
    app.send_mic_test_probe.return_value = MicSendProbeResult(
        ok=True,
        message="sent",
        input_tokens=900,
        output_tokens=12,
        reply_preview="reply",
    )

    result = run_mic_test_send(app)

    assert result.ok is True
    assert result.audio_attached is True
    assert result.input_tokens == 900
    assert "reply" in result.message
