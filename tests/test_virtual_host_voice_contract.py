from __future__ import annotations

from app.virtual_host.audio import (
    AsrResult,
    TtsBinding,
    TtsSynthesizer,
    VirtualHostAudioOrchestrator,
)
from app.virtual_host.contracts import HostTurnResult
from app.virtual_host.playback import PlaybackItem, PlaybackPriority, PlaybackQueue
from app.virtual_host.session import VirtualHostSession


class FakeAsr:
    def transcribe(self, pcm: bytes, *, turn_id: int):
        return AsrResult("ok", text=f"turn-{turn_id}", safe_summary=f"summary-{turn_id}")


class FakeChat:
    def generate(self, prompt, *, turn_id: int):
        return f"回复{turn_id}"


class FakePlayer:
    def __init__(self) -> None:
        self.started: list[bytes] = []
        self._callback = None

    def play(self, audio_bytes: bytes, on_complete):
        self.started.append(audio_bytes)
        self._callback = on_complete
        return object()

    def stop(self):
        pass

    def pause(self):
        return False

    def complete(self) -> None:
        if self._callback is not None:
            self._callback()


def _binding() -> TtsBinding:
    return TtsBinding(
        provider_id="tts-provider",
        model_id="tts-model",
        voice_id="voice-1",
        credentials={"api_key": "secret"},
    )


def _orchestrator(**kwargs) -> VirtualHostAudioOrchestrator:
    session = VirtualHostSession(session_id="contract-session")
    defaults = {
        "session": session,
        "asr": FakeAsr(),
        "chat": FakeChat(),
        "tts": TtsSynthesizer(synthesize_fn=lambda text, binding: text.encode()),
        "tts_binding": _binding(),
        "playback": PlaybackQueue(FakePlayer()),
    }
    defaults.update(kwargs)
    return VirtualHostAudioOrchestrator(**defaults)


def test_duplicate_end_input_and_cancel_are_idempotent():
    orch = _orchestrator()
    turn = orch.begin_mic_turn(runtime_generation=1, scene_generation=2)
    orch.end_input(turn.turn_id)
    first_ended = turn.input_ended_at
    orch.end_input(turn.turn_id)
    assert turn.input_ended_at == first_ended
    assert turn.status == "transcribing"

    orch.cancel_turn(turn.turn_id, reason="user_cancelled")
    orch.cancel_turn(turn.turn_id, reason="duplicate_cancel")
    assert turn.status == "cancelled"
    assert turn.cancel_reason == "user_cancelled"


def test_stale_runtime_generation_rejects_late_asr_and_chat():
    orch = _orchestrator()
    turn = orch.begin_mic_turn(runtime_generation=1, scene_generation=0)
    orch.end_input(turn.turn_id)
    orch.transcribe(turn.turn_id, b"pcm", current_runtime_generation=2)
    assert turn.status == "cancelled"
    assert turn.cancel_reason == "runtime_generation_stale"

    turn2 = orch.begin_mic_turn(runtime_generation=3, scene_generation=0)
    orch.accept_transcript(turn2.turn_id, "用户说话", current_runtime_generation=4)
    assert turn2.status == "cancelled"

    turn3 = orch.begin_mic_turn(runtime_generation=5, scene_generation=0)
    orch.accept_transcript(turn3.turn_id, "用户说话")
    orch.submit_chat_result(
        turn3.turn_id,
        "主播回复",
        current_runtime_generation=6,
    )
    assert turn3.status == "cancelled"


def test_stale_generation_tts_callback_does_not_enqueue_playback():
    player = FakePlayer()
    orch = _orchestrator(playback=PlaybackQueue(player))
    turn = orch.begin_mic_turn(runtime_generation=10, scene_generation=0)
    orch.accept_transcript(turn.turn_id, "你好")
    orch.submit_chat_result(turn.turn_id, HostTurnResult(turn.session_id, turn.turn_id, "播报内容"))
    orch.synthesize_turn(turn.turn_id, current_runtime_generation=11)
    assert turn.status == "cancelled"
    assert player.started == []
    assert orch.playback.queued_items == ()


def test_cancelled_turn_ignores_late_synthesize_and_playback_events():
    player = FakePlayer()
    orch = _orchestrator(playback=PlaybackQueue(player))
    turn = orch.begin_mic_turn(runtime_generation=1)
    orch.accept_transcript(turn.turn_id, "用户")
    orch.submit_chat_result(turn.turn_id, "回复")
    orch.cancel_turn(turn.turn_id, reason="superseded")
    orch.synthesize_turn(turn.turn_id)
    assert turn.status == "cancelled"
    assert player.started == []

    orch.playback.enqueue(
        PlaybackItem(
            session_id=turn.session_id,
            turn_id=turn.turn_id,
            segment_index=0,
            audio_bytes=b"late",
            priority=PlaybackPriority.USER_MIC,
        )
    )
    assert player.started == []


def test_two_fake_adapter_turns_keep_independent_ids_and_snapshots():
    orch = _orchestrator()
    first = orch.begin_mic_turn(runtime_generation=1, scene_generation=1, input_started_at=1.0)
    orch.end_input(first.turn_id, input_ended_at=2.0)
    orch.transcribe(first.turn_id, b"pcm")
    orch.run_chat(first.turn_id)
    snap1 = first.to_snapshot()
    assert snap1.turn_id == 1
    assert snap1.runtime_generation == 1
    assert snap1.transcript_summary == "summary-1"
    assert snap1.source == "user_mic"

    second = orch.begin_mic_turn(runtime_generation=2, scene_generation=1, input_started_at=3.0)
    orch.end_input(second.turn_id, input_ended_at=4.0)
    orch.transcribe(second.turn_id, b"pcm")
    assert second.turn_id == 2
    assert second.to_snapshot().transcript_summary == "summary-2"
