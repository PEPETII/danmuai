"""P2-05 TTS session-epoch and playback-adapter regressions."""

from __future__ import annotations

from app.danmu_read_service import _DanmuTtsRunnable
from app.danmu_tts_playback import DanmuTtsPlayback
from app.tts_providers import ResolvedTtsConfig
from app.virtual_host.playback import PlaybackItem, PlaybackQueue
from app.virtual_host_playback_adapter import DanmuTtsPlaybackAdapter

from tests.test_tts_playback_lifecycle import _make_read_service


def _resolved_tts_config() -> ResolvedTtsConfig:
    return ResolvedTtsConfig(
        provider="mimo",
        endpoint="https://api.xiaomimo.com/v1",
        model="mimo-v2.5",
        is_custom=False,
        stored_provider="",
        stored_endpoint="",
        stored_model_id="",
    )


def _tts_runnable(service, *, session_epoch: int) -> _DanmuTtsRunnable:
    return _DanmuTtsRunnable(
        service,
        text="旧 worker",
        api_key="test-key",
        voice="voice1",
        style_prompt="",
        resolved=_resolved_tts_config(),
        credentials={"api_key": "test-key"},
        session_epoch=session_epoch,
    )


def _playback_item(turn_id: int) -> PlaybackItem:
    return PlaybackItem(
        session_id="session-1",
        turn_id=turn_id,
        segment_index=0,
        audio_bytes=f"audio-{turn_id}".encode(),
    )


def test_read_service_drops_old_worker_after_stop_start(qapp, monkeypatch):
    service = _make_read_service(qapp)
    service._app.engine.running = True
    service._tts_in_flight = True
    monkeypatch.setattr(service._playback, "stop", lambda: None)
    play_calls: list[bytes] = []
    monkeypatch.setattr(
        service._playback,
        "play_wav_bytes",
        lambda wav: play_calls.append(wav) or True,
    )
    monkeypatch.setattr(
        "app.danmu_read_service.synthesize_tts",
        lambda *_args, **_kwargs: b"old-audio",
    )

    old_epoch = service._tts_session_epoch
    old_worker = _tts_runnable(service, session_epoch=old_epoch)

    service._app.engine.running = False
    service.on_engine_stopped()
    service._app.engine.running = True
    service.on_engine_started()
    service._tts_in_flight = True

    old_worker.run()
    qapp.processEvents()

    assert service._tts_session_epoch != old_epoch
    assert play_calls == []
    assert service._tts_in_flight is True


def test_playback_adapter_releases_queue_on_failed_or_stopped(qapp, monkeypatch):
    playback = DanmuTtsPlayback()
    adapter = DanmuTtsPlaybackAdapter(playback)
    next_playback_id = 0

    def fake_play_wav_bytes(_wav: bytes) -> int:
        nonlocal next_playback_id
        next_playback_id += 1
        return next_playback_id

    monkeypatch.setattr(playback, "play_wav_bytes", fake_play_wav_bytes)
    queue = PlaybackQueue(adapter)

    queue.enqueue(_playback_item(1))
    assert queue.active_item is not None
    playback.playback_failed.emit(adapter._active_playback_id)
    qapp.processEvents()
    assert queue.active_item is None

    queue.enqueue(_playback_item(2))
    assert queue.active_item is not None
    playback.playback_stopped.emit(adapter._active_playback_id)
    qapp.processEvents()
    assert queue.active_item is None
