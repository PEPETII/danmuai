"""W-017：虚拟主播语音输出、播放优先级、回声抑制与 Live2D 反馈。"""

from __future__ import annotations

import time

from app.mic_transcription import MicTranscriptionResult
from app.virtual_host.audio import TtsSynthesisOutcome
from app.virtual_host.chat import HostChatHttpResult
from app.virtual_host.contracts import ActionDraft, EmotionDraft, HostTurnResult
from app.virtual_host.playback import PlaybackItem, PlaybackPriority

from tests.test_virtual_host_autonomous_response import (
    _service_with_player,
    _tts_vision_config,
    _wait_pool,
)
from tests.test_virtual_host_live2d_feedback import FakeRuntime
from tests.test_virtual_host_runtime import _register_runtime_test


def _dialogue_service_with_tts(monkeypatch, qapp):
    config, tts_calls = _tts_vision_config(monkeypatch)
    apply = __import__(
        "app.virtual_host.mode_config",
        fromlist=["apply_virtual_host_mode_settings"],
    ).apply_virtual_host_mode_settings
    apply(config, {"dialogue_enabled": True, "danmu_adapter_enabled": False})
    service, player = _service_with_player(monkeypatch, config)
    service.start_voice_session()
    runtime = FakeRuntime()
    service.attach_live2d_runtime(runtime)
    _register_runtime_test(service, service._test_pool)
    return service, player, tts_calls, runtime


def test_voice_chat_enqueues_user_mic_tts_and_live2d_feedback(monkeypatch, qapp):
    service, player, tts_calls, runtime = _dialogue_service_with_tts(monkeypatch, qapp)
    feedback_calls: list[object] = []
    original_apply = service.live2d_feedback.apply_turn_result

    def _track_apply(result, *, runtime_generation):
        feedback_calls.append(result)
        return original_apply(result, runtime_generation=runtime_generation)

    monkeypatch.setattr(service.live2d_feedback, "apply_turn_result", _track_apply)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda prompt, resolved, *, session_id, turn_id: HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=session_id,
                turn_id=turn_id,
                text="这是主播回复。",
                speak=True,
                emotion=EmotionDraft("happy"),
                actions=(ActionDraft("gesture", name="nod"),),
            ),
        ),
    )
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(True, text="你好"),
    )

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm")
    _wait_pool(service, qapp)

    assert tts_calls == ["vh-tts-model"]
    assert len(player.started) == 1
    assert feedback_calls
    assert feedback_calls[0].text == "这是主播回复。"
    assert any(kind == "expression" for kind, _args in runtime.calls)
    active = service.audio.playback.active_item
    assert active is not None
    assert active.priority == PlaybackPriority.USER_MIC
    assert active.source == "mic_reply"


def test_user_mic_playback_interrupts_auto_scene(monkeypatch, qapp):
    service, player, _tts_calls, _runtime = _dialogue_service_with_tts(monkeypatch, qapp)
    events: list[str] = []
    service.audio.playback.add_listener(
        lambda event: events.append(f"{event.kind}:{event.reason}")
    )

    service.audio.playback.enqueue(
        PlaybackItem(
            session_id=service.session.session_id,
            turn_id=1,
            segment_index=0,
            audio_bytes=b"auto-scene",
            priority=PlaybackPriority.AUTO_SCENE,
            source="auto_reply",
            runtime_generation=service.runtime_generation,
        )
    )
    assert player.started == [b"auto-scene"]

    service.audio.playback.enqueue(
        PlaybackItem(
            session_id=service.session.session_id,
            turn_id=2,
            segment_index=0,
            audio_bytes=b"user-reply",
            priority=PlaybackPriority.USER_MIC,
            source="mic_reply",
            runtime_generation=service.runtime_generation,
        )
    )
    assert player.started[-1] == b"user-reply"
    assert "interrupted:higher_priority" in events
    assert service.audio.playback.active_item is not None
    assert service.audio.playback.active_item.source == "mic_reply"


def test_echo_guard_blocks_mic_during_user_reply_playback(monkeypatch, qapp):
    service, player, _tts_calls, _runtime = _dialogue_service_with_tts(monkeypatch, qapp)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda prompt, resolved, *, session_id, turn_id: HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="播报中"),
        ),
    )
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(True, text="第一轮"),
    )

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm-1")
    _wait_pool(service, qapp)
    assert player.started
    assert service.audio.playback.active_item is not None

    assert not service.on_mic_speech_start()
    assert service.audio.get_turn(1).status == "chat_completed"


def test_echo_guard_releases_after_playback_and_cooldown(monkeypatch, qapp):
    service, player, _tts_calls, _runtime = _dialogue_service_with_tts(monkeypatch, qapp)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service._USER_MIC_PLAYBACK_ECHO_COOLDOWN_SEC",
        0.05,
    )
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda prompt, resolved, *, session_id, turn_id: HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="短回复"),
        ),
    )
    transcripts = iter(["第一轮", "第二轮"])
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(True, text=next(transcripts)),
    )

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm-1")
    _wait_pool(service, qapp)
    player.complete()
    assert service.audio.playback.active_item is None

    deadline = time.monotonic() + 1.0
    while service._user_mic_echo_guard_active() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert not service._user_mic_echo_guard_active()

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm-2")
    _wait_pool(service, qapp)
    assert service.audio.get_turn(2).transcript == "第二轮"


def test_stale_voice_tts_generation_is_cancelled(monkeypatch, qapp):
    import threading

    service, player, _tts_calls, _runtime = _dialogue_service_with_tts(monkeypatch, qapp)
    release = threading.Event()
    started = threading.Event()

    def _fake_request(prompt, resolved, *, session_id, turn_id):
        started.set()
        assert release.wait(timeout=2.0)
        return HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="迟到音频"),
        )

    monkeypatch.setattr("app.virtual_host.runtime_service.request_host_chat", _fake_request)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(True, text="用户"),
    )

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm")
    _wait_pool(service, qapp, timeout=0.2)
    deadline = time.monotonic() + 2.0
    while not started.is_set() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert started.is_set()

    service._bump_runtime_generation()
    release.set()
    _wait_pool(service, qapp)
    assert player.started == []


def test_voice_tts_failure_does_not_enqueue_playback(monkeypatch, qapp):
    service, player, _tts_calls, _runtime = _dialogue_service_with_tts(monkeypatch, qapp)

    def _fail_synthesize(_text, _binding):
        return TtsSynthesisOutcome("failed", reason="provider_unavailable")

    monkeypatch.setattr(
        service,
        "_build_worker_tts_synthesizer",
        lambda: __import__(
            "app.virtual_host.audio",
            fromlist=["TtsSynthesizer"],
        ).TtsSynthesizer(synthesize_fn=_fail_synthesize),
    )
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda prompt, resolved, *, session_id, turn_id: HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="会失败"),
        ),
    )
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(True, text="用户"),
    )

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm")
    _wait_pool(service, qapp)

    assert player.started == []
    assert service.audio.playback.queued_items == ()


def test_auto_scene_playback_does_not_block_user_interrupt(monkeypatch, qapp):
    service, player, _tts_calls, _runtime = _dialogue_service_with_tts(monkeypatch, qapp)
    service.audio.playback.enqueue(
        PlaybackItem(
            session_id=service.session.session_id,
            turn_id=50,
            segment_index=0,
            audio_bytes=b"auto",
            priority=PlaybackPriority.AUTO_SCENE,
            source="auto_reply",
            runtime_generation=service.runtime_generation,
        )
    )
    assert player.started == [b"auto"]
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(True, text="打断"),
    )
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda prompt, resolved, *, session_id, turn_id: HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="收到"),
        ),
    )

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm")
    _wait_pool(service, qapp)
    assert service.audio.get_turn(1).transcript == "打断"
