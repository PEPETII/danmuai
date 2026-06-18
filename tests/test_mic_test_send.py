import struct
import time
from unittest.mock import MagicMock

import pytest
from app.ai_client import AiProbeResult
from app.mic_test_send import (
    MicSendProbeResult,
    placeholder_image_data_uri,
    run_mic_test_send,
    send_mic_probe,
)
from PyQt6.QtCore import QCoreApplication, QTimer
from PyQt6.QtWidgets import QApplication

from tests.fakes import FakeConfig, FakeLogger


@pytest.fixture(scope="module")
def qapp():
    app = QCoreApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_placeholder_image_data_uri():
    uri = placeholder_image_data_uri()
    assert uri.startswith("data:image/jpeg;base64,")


def test_run_mic_test_send_unsupported_api():
    app = MagicMock()
    app.mic_audio_supported.return_value = False
    app.ai_worker.resolve_mic_request_credentials.return_value = None

    result = run_mic_test_send(app)

    assert result.ok is False
    assert result.error == "unsupported_api_mode"


def test_send_mic_probe_incomplete_credentials():
    app = MagicMock()
    app.ai_worker = MagicMock()
    app.config = FakeConfig()
    app.ai_worker.resolve_mic_request_credentials.return_value = None

    result = send_mic_probe(
        app,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert result.ok is False
    assert result.error == "incomplete_credentials"


def test_send_mic_probe_unsupported_model():
    app = MagicMock()
    app.ai_worker = MagicMock()
    app.config = FakeConfig()
    app.ai_worker.resolve_mic_request_credentials.return_value = (
        "https://ark.cn-beijing.volces.com/api/v3",
        "sk-test",
        "doubao-seed-1-6-flash-250828",
        "doubao",
    )

    result = send_mic_probe(
        app,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert result.ok is False
    assert result.error == "unsupported_model"
    assert "未声明 mic_audio 支持" in result.message


def test_send_mic_probe_unsupported_generic_openai():
    app = MagicMock()
    app.ai_worker = MagicMock()
    app.config = FakeConfig()
    app.ai_worker.resolve_mic_request_credentials.return_value = (
        "https://example.com/v1",
        "sk-test",
        "gpt-4o",
        "openai",
    )

    result = send_mic_probe(
        app,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert result.ok is False
    assert result.error == "unsupported_model"
    assert "未声明 mic_audio 支持" in result.message


def test_send_mic_probe_allows_declared_custom_openai():
    app = MagicMock()
    app.ai_worker = MagicMock()
    app.config = FakeConfig(
        {
            "default_model_id": "or-audio",
            "custom_models": [{"modelId": "or-audio", "supportsMic": True}],
        }
    )
    app.ai_worker.resolve_mic_request_credentials.return_value = (
        "https://openrouter.ai/api/v1",
        "sk-test",
        "or-audio",
        "openai-compatible",
    )
    app.run_mic_probe_in_pool = MagicMock(
        return_value=AiProbeResult(
            signal="finished",
            message="ok",
            input_tokens=1,
            output_tokens=1,
        ),
    )

    result = send_mic_probe(
        app,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert result.ok is True
    app.run_mic_probe_in_pool.assert_called_once()


def test_send_mic_probe_success_mimo(monkeypatch):
    app = MagicMock()
    app.ai_worker = MagicMock()
    app.config = FakeConfig()
    app.ai_worker.resolve_mic_request_credentials.return_value = (
        "https://api.xiaomimimo.com/v1",
        "sk-test",
        "mimo-v2.5",
        "openai-compatible",
    )

    app.run_mic_probe_in_pool = MagicMock(
        return_value=AiProbeResult(
            signal="finished",
            message="heard",
            input_tokens=50,
            output_tokens=8,
        ),
    )

    result = send_mic_probe(
        app,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert result.ok is True
    assert result.reply_preview == "heard"


def test_send_mic_probe_supports_mimo_v2_5_on_custom_endpoint():
    app = MagicMock()
    app.ai_worker = MagicMock()
    app.config = FakeConfig()
    app.ai_worker.resolve_mic_request_credentials.return_value = (
        "https://my-mimo-proxy.com/v1",
        "sk-test",
        "mimo-v2.5",
        "openai-compatible",
    )
    app.run_mic_probe_in_pool = MagicMock(
        return_value=AiProbeResult(
            signal="finished",
            message="heard",
            input_tokens=50,
            output_tokens=8,
        ),
    )

    result = send_mic_probe(
        app,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert result.error != "unsupported_model"
    assert result.ok is True
    assert result.reply_preview == "heard"
    app.run_mic_probe_in_pool.assert_called_once()


def test_send_mic_probe_success_doubao(monkeypatch):
    app = MagicMock()
    app.ai_worker = MagicMock()
    app.config = FakeConfig()
    app.ai_worker.resolve_mic_request_credentials.return_value = (
        "https://ark.cn-beijing.volces.com/api/v3",
        "sk-test",
        "doubao-seed-2-0-mini-260428",
        "doubao",
    )

    app.run_mic_probe_in_pool = MagicMock(
        return_value=AiProbeResult(
            signal="finished",
            message="received",
            input_tokens=900,
            output_tokens=12,
        ),
    )

    result = send_mic_probe(
        app,
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
    app.config = FakeConfig()
    app.engine.running = False
    app.capture_mic_test_sample.return_value = (pcm, capture_result)
    monkeypatch.setattr(
        "app.mic_test_send.send_mic_probe",
        lambda *_args, **_kwargs: MicSendProbeResult(
            ok=True,
            message="sent",
            input_tokens=900,
            output_tokens=12,
            reply_preview="reply",
        ),
    )

    result = run_mic_test_send(app)

    assert result.ok is True
    assert result.audio_attached is True
    assert result.input_tokens == 900
    assert "reply" in result.message


def test_run_mic_test_send_does_not_block_main_thread(qapp):
    from main import DanmuApp

    timer_fired = {"value": False}

    def on_timeout():
        timer_fired["value"] = True

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(on_timeout)
    timer.start(100)

    def slow_probe(*_args, **_kwargs):
        time.sleep(0.35)
        return AiProbeResult(signal="finished", message="ok", input_tokens=1, output_tokens=1)

    app = DanmuApp.__new__(DanmuApp)
    app.config = FakeConfig()
    app.ai_worker = MagicMock()
    app.ai_worker.run_mic_audio_probe.side_effect = slow_probe
    app.run_mic_probe_in_pool = DanmuApp.run_mic_probe_in_pool.__get__(app, DanmuApp)
    app.ai_worker.resolve_mic_request_credentials = MagicMock(
        return_value=(
            "https://ark.cn-beijing.volces.com/api/v3",
            "sk-test",
            "doubao-seed-2-0-mini-260428",
            "doubao",
        )
    )

    send_mic_probe(
        app,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )

    assert timer_fired["value"] is True
    timer.stop()


def test_run_mic_test_send_does_not_emit_pop_before_reply_warning(monkeypatch):
    from main import DanmuApp

    app = DanmuApp.__new__(DanmuApp)
    app.config = FakeConfig()
    app.logger = FakeLogger()
    app._pending_request_meta = {}
    app.ai_worker = MagicMock()
    app.ai_worker.resolve_mic_request_credentials = MagicMock(
        return_value=(
            "https://ark.cn-beijing.volces.com/api/v3",
            "sk-test",
            "doubao-seed-2-0-mini-260428",
            "doubao",
        )
    )

    app.run_mic_probe_in_pool = MagicMock(
        return_value=AiProbeResult(
            signal="error",
            message="probe failed",
        ),
    )

    before = dict(app._pending_request_meta)
    send_mic_probe(
        app,
        placeholder_image_data_uri(),
        "test",
        "data:audio/wav;base64,abc",
    )
    assert app._pending_request_meta == before
    assert not any("pop_before_reply" in line for line in app.logger.warning_messages)
