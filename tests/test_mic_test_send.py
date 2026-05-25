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
    app._mic_audio_supported.return_value = False
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


def test_send_mic_probe_non_doubao_mode():
    config = MagicMock()
    worker = MagicMock()
    worker._resolve_request_credentials.return_value = (
        "https://example.com/v1",
        "sk-test",
        "model",
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
    assert result.error == "unsupported_api_mode"


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
            "已收到音频",
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
    assert result.reply_preview == "已收到音频"


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
        "app.mic_test_send.capture_mic_sample",
        lambda *args, **kwargs: (pcm, capture_result),
    )
    monkeypatch.setattr(
        "app.mic_test_send.pcm_to_wav_data_uri",
        lambda _: "data:audio/wav;base64,abc",
    )
    monkeypatch.setattr(
        "app.mic_test_send.send_mic_probe",
        lambda *args, **kwargs: MicSendProbeResult(
            ok=True,
            message="发送成功（input=900 · output=12）",
            input_tokens=900,
            output_tokens=12,
            reply_preview="已收到音频",
        ),
    )

    app = MagicMock()
    app._mic_audio_supported.return_value = True
    app.config = MagicMock()
    app.engine.running = False

    result = run_mic_test_send(app)
    assert result.ok is True
    assert result.audio_attached is True
    assert result.input_tokens == 900
    assert "已收到音频" in result.message
