"""MicOrchestrator 状态机与生命周期（W-MEDLOW-005 / MMIC-001）。"""

from __future__ import annotations

from unittest.mock import MagicMock, Mock

from app.mic_orchestrator import MicOrchestrator


def _orch(mic_service: MagicMock | None = None) -> MicOrchestrator:
    return MicOrchestrator(
        mic_service=mic_service or MagicMock(),
        on_utterance_end=Mock(),
        log_fn=Mock(),
    )


def test_sync_stops_capture_when_engine_stops(monkeypatch):
    mic = MagicMock()
    mic.is_running.return_value = True
    orch = _orch(mic)
    monkeypatch.setattr("app.mic_orchestrator.mic_mode_enabled", lambda _cfg: True)

    orch.sync(
        engine_running=False,
        config=MagicMock(),
        mic_audio_supported_fn=lambda: True,
        resolve_active_model_id_fn=lambda: "mimo",
    )

    mic.sync.assert_called_once_with(enabled=False)


def test_sync_disables_mic_when_mode_off(monkeypatch):
    mic = MagicMock()
    orch = _orch(mic)
    monkeypatch.setattr("app.mic_orchestrator.mic_mode_enabled", lambda _cfg: False)

    orch.sync(
        engine_running=True,
        config=MagicMock(),
        mic_audio_supported_fn=lambda: True,
        resolve_active_model_id_fn=lambda: "mimo",
    )

    mic.sync.assert_called_once_with(enabled=False)
    assert orch._mic_utterance_detector is None


def test_stop_detector_resets_utterance_state():
    mic = MagicMock()
    mic.is_running.return_value = True
    orch = _orch(mic)
    detector = MagicMock()
    orch._mic_utterance_detector = detector

    orch.stop_detector()

    detector.reset.assert_called_once()


def test_poll_returns_false_when_engine_stopped(monkeypatch):
    mic = MagicMock()
    mic.is_running.return_value = True
    orch = _orch(mic)
    orch._mic_utterance_detector = MagicMock()
    monkeypatch.setattr("app.mic_orchestrator.mic_mode_enabled", lambda _cfg: True)

    assert (
        orch.poll(
            engine_running=False,
            config=MagicMock(),
        )
        is False
    )


def test_should_schedule_next_poll_requires_detector(monkeypatch):
    mic = MagicMock()
    mic.is_running.return_value = True
    orch = _orch(mic)
    monkeypatch.setattr("app.mic_orchestrator.mic_mode_enabled", lambda _cfg: True)

    assert (
        orch.should_schedule_next_poll(engine_running=True, config=MagicMock()) is False
    )

    orch._mic_utterance_detector = MagicMock()
    assert (
        orch.should_schedule_next_poll(engine_running=True, config=MagicMock()) is True
    )
