"""虚拟主播 TTS 播放生命周期：runtime 切换、token 竞态与优先级。"""

from __future__ import annotations

import time

import pytest
from app.danmu_tts_playback import DanmuTtsPlayback
from app.virtual_host.chat import HostChatHttpResult
from app.virtual_host.contracts import HostTurnResult
from app.virtual_host.playback import PlaybackItem, PlaybackPriority, PlaybackQueue
from app.virtual_host_playback_adapter import DanmuTtsPlaybackAdapter

from tests.test_virtual_host_autonomous_response import (
    _service_with_player,
    _tts_vision_config,
    _wait_pool,
)
from tests.test_virtual_host_playback import FakePlayer


class _RuntimePlayer(FakePlayer):
    def __init__(self) -> None:
        super().__init__()
        self.active_ids: list[str] = []

    def play(self, audio_bytes: bytes, on_complete):
        self.active_ids.append(audio_bytes.decode())
        return super().play(audio_bytes, on_complete)


def _auto_item(
    *,
    turn_id: int = 1,
    segment_index: int = 0,
    runtime_generation: int = 1,
    audio: bytes | None = None,
) -> PlaybackItem:
    return PlaybackItem(
        session_id="session-1",
        turn_id=turn_id,
        segment_index=segment_index,
        audio_bytes=audio or f"auto-{turn_id}-{segment_index}".encode(),
        priority=PlaybackPriority.AUTO_SCENE,
        source="auto_reply",
        runtime_generation=runtime_generation,
    )


def _mic_item(
    *,
    turn_id: int = 9,
    segment_index: int = 0,
    runtime_generation: int = 0,
) -> PlaybackItem:
    return PlaybackItem(
        session_id="session-1",
        turn_id=turn_id,
        segment_index=segment_index,
        audio_bytes=f"mic-{turn_id}-{segment_index}".encode(),
        priority=PlaybackPriority.USER_MIC,
        source="mic_reply",
        runtime_generation=runtime_generation,
    )


def test_purge_stale_auto_runtime_stops_active_and_clears_pending():
    player = _RuntimePlayer()
    events: list[str] = []
    queue = PlaybackQueue(
        player,
        on_event=lambda event: events.append(f"{event.kind}:{event.reason}"),
    )

    current = queue.enqueue(_auto_item(turn_id=1, runtime_generation=1))
    assert current.status == "queued"
    pending = _auto_item(turn_id=1, segment_index=1, runtime_generation=1)
    queue.enqueue(pending)

    assert queue.active_item is not None
    assert len(queue.queued_items) == 1

    queue.purge_stale_auto_runtime(2, reason="runtime_reset")

    assert queue.active_item is None
    assert queue.queued_items == ()
    assert player.stop_count == 1
    assert any("interrupted:runtime_reset" in event for event in events)


def test_purge_stale_auto_runtime_preserves_user_mic():
    player = _RuntimePlayer()
    queue = PlaybackQueue(player)

    queue.enqueue(_auto_item(runtime_generation=1))
    queue.enqueue(_mic_item(runtime_generation=0))

    queue.purge_stale_auto_runtime(2, reason="runtime_reset")

    assert queue.active_item is not None
    assert queue.active_item.priority == PlaybackPriority.USER_MIC
    assert player.started[-1] == b"mic-9-0"


def test_stale_playback_finished_does_not_complete_new_item(qapp, monkeypatch):
    playback = DanmuTtsPlayback()
    adapter = DanmuTtsPlaybackAdapter(playback)
    completed: list[str] = []
    next_id = 0

    def _fake_play(_wav_bytes: bytes) -> int:
        nonlocal next_id
        next_id += 1
        return next_id

    monkeypatch.setattr(playback, "play_wav_bytes", _fake_play)
    monkeypatch.setattr(playback, "stop", lambda: None)

    adapter.play(b"bytes-a", lambda: completed.append("a"))
    stale_id = adapter._active_playback_id
    assert stale_id > 0

    adapter.stop()
    adapter.play(b"bytes-b", lambda: completed.append("b"))
    current_id = adapter._active_playback_id
    assert current_id != stale_id

    playback.playback_finished.emit(stale_id)
    qapp.processEvents()
    assert completed == []

    playback.playback_finished.emit(current_id)
    qapp.processEvents()
    assert completed == ["b"]


def test_runtime_stop_interrupts_active_auto_scene(monkeypatch, qapp):
    config, _ = _tts_vision_config(monkeypatch)
    service, player = _service_with_player(monkeypatch, config)
    host_turn = service.session.start_turn("指令", now=time.time())
    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text="正在播报。",
                speak=True,
            ),
            model_id="qwen3-vl-flash",
        ),
        host_turn,
        service.runtime_generation,
        "qwen3-vl-flash",
    )
    _wait_pool(service, qapp)
    assert player.started

    service.stop()
    assert service.audio.playback.active_item is None
    assert service.audio.playback.queued_items == ()


def test_runtime_stop_clears_queued_auto_scene(monkeypatch, qapp):
    config, _ = _tts_vision_config(monkeypatch)
    service, player = _service_with_player(monkeypatch, config)

    long_text = "第一句很长需要排队。" + "第二句也要排队播放。"
    host_turn = service.session.start_turn("指令", now=time.time())
    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text=long_text,
                speak=True,
            ),
            model_id="qwen3-vl-flash",
        ),
        host_turn,
        service.runtime_generation,
        "qwen3-vl-flash",
    )
    _wait_pool(service, qapp)
    assert len(player.started) >= 1

    queued_before = len(service.audio.playback.queued_items)
    if queued_before == 0:
        pytest.skip("segment_text did not produce multiple playback items in this environment")

    service.stop()
    assert service.audio.playback.queued_items == ()
    assert service.audio.playback.active_item is None


def test_runtime_generation_bump_blocks_stale_auto_playback(monkeypatch, qapp):
    """TTS/vision 模型切换会 bump runtime generation 并走同一清理路径。"""
    config, _ = _tts_vision_config(monkeypatch)
    service, player = _service_with_player(monkeypatch, config)
    host_turn = service.session.start_turn("指令", now=time.time())
    stale_generation = service.runtime_generation
    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text="旧模型音频。",
                speak=True,
            ),
            model_id="qwen3-vl-flash",
        ),
        host_turn,
        stale_generation,
        "qwen3-vl-flash",
    )
    _wait_pool(service, qapp)
    started_before = list(player.started)
    assert stale_generation < service.runtime_generation or started_before

    service._bump_runtime_generation()

    assert service.audio.playback.active_item is None
    assert service.audio.playback.queued_items == ()
    assert player.started == started_before


def test_user_mic_interrupts_auto_scene_and_completes_cleanly():
    player = FakePlayer()
    events: list[str] = []
    queue = PlaybackQueue(
        player,
        on_event=lambda event: events.append(event.kind),
    )

    queue.enqueue(_auto_item(turn_id=1))
    queue.enqueue(_mic_item(turn_id=2))

    assert queue.active_item is not None
    assert queue.active_item.priority == PlaybackPriority.USER_MIC
    assert "interrupted" in events

    player.complete()
    assert queue.active_item is None
    assert not queue.queued_items


def test_multi_segment_auto_scene_plays_in_order(monkeypatch, qapp):
    config, _ = _tts_vision_config(monkeypatch)
    service, player = _service_with_player(monkeypatch, config)
    host_turn = service.session.start_turn("指令", now=time.time())
    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text="第一段。第二段。",
                speak=True,
            ),
            model_id="qwen3-vl-flash",
        ),
        host_turn,
        service.runtime_generation,
        "qwen3-vl-flash",
    )
    _wait_pool(service, qapp)
    assert len(player.started) == 1
    assert len(service.audio.playback.queued_items) >= 1

    player.complete()
    assert len(player.started) == 2
    player.complete()
    assert service.audio.playback.active_item is None


def test_tts_synthesize_count_incremented_on_main_thread(monkeypatch, qapp):
    import threading

    config, _ = _tts_vision_config(monkeypatch)
    service, _ = _service_with_player(monkeypatch, config)
    main_thread_id = threading.get_ident()
    dispatch_threads: list[int] = []

    original_start = service._start_next_tts_segment

    def _tracking_start(key):
        dispatch_threads.append(threading.get_ident())
        return original_start(key)

    monkeypatch.setattr(service, "_start_next_tts_segment", _tracking_start)
    host_turn = service.session.start_turn("指令", now=time.time())
    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text="主线程计数。",
                speak=True,
            ),
            model_id="qwen3-vl-flash",
        ),
        host_turn,
        service.runtime_generation,
        "qwen3-vl-flash",
    )
    _wait_pool(service, qapp)
    assert service.tts_synthesize_count == 1
    assert dispatch_threads == [main_thread_id]
