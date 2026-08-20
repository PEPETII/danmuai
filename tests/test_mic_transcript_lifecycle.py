"""MIC-TRANSCRIPT-LIFECYCLE: partial utterance and transcript worker terminal states."""

from __future__ import annotations

import struct
from unittest.mock import MagicMock, Mock, patch

import pytest
from app.main_helpers import MAX_MIC_IN_FLIGHT
from app.main_mic_mixin import DanmuAppMicMixin
from app.mic_log_store import MicLogStore
from app.mic_orchestrator import MicOrchestrator
from app.mic_transcript_worker import MicTranscriptCoordinator, MicTranscriptRunnable
from app.mic_transcription import MicTranscriptionResult
from app.mic_utterance import MicUtteranceConfig, MicUtteranceDetector, UtteranceState
from PyQt6.QtCore import QObject


def _sample_pcm(num_frames: int = 1600) -> bytes:
    return struct.pack(f"<{num_frames}h", *([100] * num_frames))


class _MicLifecycleApp(DanmuAppMicMixin):
    def __init__(self, *, connect_transcript: bool = False) -> None:
        from types import SimpleNamespace

        self.config = MagicMock()
        self.engine = SimpleNamespace(running=True)
        self.logger = MagicMock()
        self._active_mic_utterance_id = ""
        self._mic_log_store = MicLogStore()
        self._qt_parent = QObject()
        self._mic_transcript_coordinator = MicTranscriptCoordinator(self._qt_parent)
        if connect_transcript:
            self._mic_transcript_coordinator.finished.connect(self._on_mic_transcript_finished)
        self._mic_orchestrator = MagicMock(
            snapshot_pcm_for_utterance=MagicMock(return_value=_sample_pcm()),
            pcm_metrics=MagicMock(return_value=(120, 0)),
        )
        self.mic_in_flight = 0
        self._latest_screenshot = object()
        self._mic_request_seq = 0
        self._capture_session_epoch = 0

    def _mic_audio_supported(self) -> bool:
        return True

    def _has_mic_request_in_flight(self) -> bool:
        return self.mic_in_flight >= MAX_MIC_IN_FLIGHT


def test_reset_discards_active_partial():
    discards: list[str] = []
    detector = MicUtteranceDetector(
        on_utterance_end=lambda: pytest.fail("end must not fire on reset"),
        on_speech_start=lambda: None,
        on_utterance_discarded=lambda: discards.append("discard"),
        config=MicUtteranceConfig(speech_rms=10, silence_ms=50, min_speech_ms=1000),
    )
    detector.set_noise_floor(0)
    loud = struct.pack(f"<{800}h", *([5000] * 800))
    detector.poll(loud, now=1000.0)
    assert detector.state == UtteranceState.SPEAKING

    detector.reset()

    assert discards == ["discard"]
    assert detector.state == UtteranceState.IDLE


def test_stop_detector_discards_active_partial():
    discards: list[str] = []
    mic = MagicMock()
    mic.is_running.return_value = True
    orch = MicOrchestrator(
        mic_service=mic,
        on_utterance_end=Mock(),
        on_utterance_discarded=lambda: discards.append("discard"),
        log_fn=Mock(),
    )
    orch.start_detector(
        MagicMock(
            get_int=Mock(side_effect=lambda key, default: default),
            get_float=Mock(side_effect=lambda key, default: default),
        )
    )
    detector = orch.detector
    assert detector is not None
    detector.set_noise_floor(0)
    loud = struct.pack(f"<{800}h", *([5000] * 800))
    detector.poll(loud, now=1000.0)
    assert detector.state == UtteranceState.SPEAKING

    orch.stop_detector()

    assert discards == ["discard"]
    assert orch.detector is None


def test_busy_utterance_end_schedules_transcript_without_api(monkeypatch):
    monkeypatch.setattr("app.main_mic_mixin.mic_mode_enabled", lambda _cfg: True)
    app = _MicLifecycleApp()
    app.mic_in_flight = MAX_MIC_IN_FLIGHT
    app._on_mic_speech_start()
    utterance_id = app._active_mic_utterance_id
    assert utterance_id
    assert app._mic_log_store.list_recent()[0]["status"] == "partial"

    scheduled: list[tuple[str, bytes]] = []
    app._schedule_mic_transcription_log = lambda uid, pcm: scheduled.append((uid, pcm))
    trigger = MagicMock()
    app._trigger_mic_api_call = trigger

    app._on_mic_utterance_end()

    assert scheduled == [(utterance_id, _sample_pcm())]
    trigger.assert_not_called()
    assert any(
        "mic insert skipped: request already in flight" in str(call)
        for call in app.logger.info.call_args_list
    )


def test_transcript_finished_clears_active_partial(monkeypatch):
    monkeypatch.setattr("app.main_mic_mixin.mic_mode_enabled", lambda _cfg: True)
    app = _MicLifecycleApp(connect_transcript=True)
    app._on_mic_speech_start()
    utterance_id = app._active_mic_utterance_id

    app._on_mic_transcript_finished(
        utterance_id,
        MicTranscriptionResult(ok=True, text="你好"),
    )

    items = app._mic_log_store.list_recent()
    assert len(items) == 1
    assert items[0]["status"] == "success"
    assert items[0]["text"] == "你好"
    assert app._active_mic_utterance_id == ""


def test_transcript_finished_failure_clears_active_partial(monkeypatch):
    monkeypatch.setattr("app.main_mic_mixin.mic_mode_enabled", lambda _cfg: True)
    app = _MicLifecycleApp(connect_transcript=True)
    app._on_mic_speech_start()
    utterance_id = app._active_mic_utterance_id

    app._on_mic_transcript_finished(
        utterance_id,
        MicTranscriptionResult(ok=False, error="empty_transcript"),
    )

    items = app._mic_log_store.list_recent()
    assert len(items) == 1
    assert items[0]["status"] == "failed"
    assert items[0]["error"] == "empty_transcript"
    assert app._active_mic_utterance_id == ""


def test_transcript_worker_emits_finished_on_unexpected_exception():
    config = MagicMock()
    pcm = _sample_pcm()
    coordinator = MagicMock()
    runnable = MicTranscriptRunnable(
        config=config,
        pcm=pcm,
        utterance_id="u-worker",
        coordinator=coordinator,
    )

    with patch(
        "app.mic_transcript_worker.transcribe_pcm",
        side_effect=RuntimeError("boom"),
    ):
        runnable.run()

    coordinator.finished.emit.assert_called_once()
    utterance_id, result = coordinator.finished.emit.call_args.args
    assert utterance_id == "u-worker"
    assert result.ok is False
    assert result.error == "RuntimeError"


def test_speech_discard_removes_partial_log(monkeypatch):
    monkeypatch.setattr("app.main_mic_mixin.mic_mode_enabled", lambda _cfg: True)
    app = _MicLifecycleApp()
    app._on_mic_speech_start()
    utterance_id = app._active_mic_utterance_id
    assert app._mic_log_store.list_recent()

    app._on_mic_utterance_discarded()

    assert app._mic_log_store.list_recent() == []
    assert app._active_mic_utterance_id == ""
