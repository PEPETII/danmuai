"""AiRunnable pre-request preprocessing exception boundary (W-REVIEW-20260820-AI-RUNNABLE-BOUNDARY-001)."""

from __future__ import annotations

import threading
from unittest.mock import Mock

import pytest
from app.ai_client import AiWorker
from app.runnable import AiRunnable
from main import DanmuApp
from PyQt6.QtWidgets import QApplication

from tests.conftest import make_minimal_danmu_app


def _mock_pixmap() -> Mock:
    mock_pixmap = Mock()
    mock_pixmap.width.return_value = 100
    mock_pixmap.height.return_value = 80
    return mock_pixmap


def _mock_worker() -> Mock:
    mock_worker = Mock()
    mock_worker._stopping = threading.Event()
    return mock_worker


def _base_runnable_kwargs(**overrides):
    defaults = {
        "worker": _mock_worker(),
        "pixmap": _mock_pixmap(),
        "system_pt": "system",
        "user_pt": "user",
        "persona_id": "test-persona",
        "request_round": 2,
        "screenshot_id": 3,
        "captured_at": 2.0,
        "scene_generation": 1,
        "compress_fn": lambda _p: "data:image/jpeg;base64,abc",
        "image_quality": 85,
    }
    defaults.update(overrides)
    return defaults


@pytest.mark.parametrize(
    ("field", "value", "expect_request"),
    [
        ("image_quality", "not-a-number", False),
        ("image_quality", object(), False),
    ],
)
def test_preprocess_invalid_image_quality_emits_error(field, value, expect_request):
    worker = _mock_worker()
    runnable = AiRunnable(**_base_runnable_kwargs(worker=worker, **{field: value}))
    runnable.run()

    worker._emit_safe.assert_called_once()
    assert worker._emit_safe.call_args[0][0] == "error"
    if expect_request:
        worker._request.assert_called_once()
    else:
        worker._request.assert_not_called()


def test_preprocess_metrics_failure_emits_error(monkeypatch):
    worker = _mock_worker()

    def _raise_metrics(*_args, **_kwargs):
        raise RuntimeError("metrics boom")

    monkeypatch.setattr("app.runnable.log_compress_metrics", _raise_metrics)

    runnable = AiRunnable(**_base_runnable_kwargs(worker=worker))
    runnable.run()

    worker._emit_safe.assert_called_once()
    assert worker._emit_safe.call_args[0][0] == "error"
    worker._request.assert_not_called()


def test_preprocess_pcm_encode_failure_emits_error(monkeypatch):
    worker = _mock_worker()

    def _raise_pcm(*_args, **_kwargs):
        raise ValueError("pcm boom")

    monkeypatch.setattr("app.runnable.pcm_to_wav_data_uri", _raise_pcm)

    pcm = b"\x00\x01" * 1600
    runnable = AiRunnable(
        **_base_runnable_kwargs(
            worker=worker,
            mic_pcm=pcm,
            mic_attach_audio=True,
        )
    )
    runnable.run()

    worker._emit_safe.assert_called_once()
    assert worker._emit_safe.call_args[0][0] == "error"
    worker._request.assert_not_called()


def test_preprocess_failure_releases_ai_in_flight():
    _ = QApplication.instance() or QApplication([])

    app = make_minimal_danmu_app()
    worker = AiWorker(app.config)
    app.ai_worker = worker
    app._on_ai_error = DanmuApp._on_ai_error.__get__(app, DanmuApp)
    worker.error.connect(lambda *args: app._on_ai_error(*args))

    app.ai_in_flight = 1
    app._is_generating = True
    app._register_request_meta(2, 3, 1, "visual")

    runnable = AiRunnable(
        **_base_runnable_kwargs(
            worker=worker,
            image_quality="invalid",
        )
    )
    runnable.run()
    QApplication.processEvents()

    assert app.ai_in_flight == 0
    assert app._is_generating is False
    worker.close()


def test_preprocess_success_still_reaches_request():
    worker = _mock_worker()
    runnable = AiRunnable(**_base_runnable_kwargs(worker=worker))
    runnable.run()

    worker._emit_safe.assert_not_called()
    worker._request.assert_called_once()
