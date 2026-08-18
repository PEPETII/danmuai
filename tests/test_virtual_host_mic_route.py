"""W-015：虚拟主播对话模式麦克风分流测试。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.mic_transcription import MicTranscriptionResult
from app.virtual_host.chat import HostChatHttpResult
from app.virtual_host.contracts import HostTurnResult
from app.virtual_host.mic_route import mic_route_enabled
from app.virtual_host.mode_config import apply_virtual_host_mode_settings
from app.virtual_host.model_config import VISION_MODEL_KEY, apply_virtual_host_model_config
from app.virtual_host.playback import PlaybackItem, PlaybackPriority, PlaybackQueue
from app.virtual_host.runtime_service import VirtualHostRuntimeService
from PyQt6.QtCore import QThreadPool

from tests.test_virtual_host_autonomous_response import _wait_pool
from tests.test_virtual_host_runtime import (
    _fake_app,
    _FakeConfig,
    _register_runtime_test,
    _vision_profile,
)


def _runtime_service(
    monkeypatch,
    config: _FakeConfig,
    *,
    arm_voice: bool = False,
) -> VirtualHostRuntimeService:
    pool = QThreadPool()
    monkeypatch.setattr("app.virtual_host.runtime_service.ai_worker_pool", lambda: pool)
    service = VirtualHostRuntimeService(_fake_app(config))
    service.start()
    if arm_voice:
        service.start_voice_session()
    service._test_pool = pool
    _register_runtime_test(service, pool)
    return service


def _dialogue_service(monkeypatch, config: _FakeConfig) -> VirtualHostRuntimeService:
    return _runtime_service(monkeypatch, config, arm_voice=True)


def _dialogue_config() -> _FakeConfig:
    config = _FakeConfig(
        {
            "virtual_host_dialogue_enabled": "1",
            "virtual_host_danmu_adapter_enabled": "0",
            VISION_MODEL_KEY: "qwen3-vl-flash",
        },
        custom_models=[_vision_profile()],
    )
    apply_virtual_host_model_config(config, {"vision_model_id": "qwen3-vl-flash"})
    return config


def _adapter_config() -> _FakeConfig:
    config = _FakeConfig(
        {
            "virtual_host_dialogue_enabled": "0",
            "virtual_host_danmu_adapter_enabled": "1",
            VISION_MODEL_KEY: "qwen3-vl-flash",
        },
        custom_models=[_vision_profile()],
    )
    apply_virtual_host_model_config(config, {"vision_model_id": "qwen3-vl-flash"})
    return config


class _BlockingPlayer:
    def __init__(self) -> None:
        self.started: list[bytes] = []
        self._callback = None

    def play(self, audio_bytes: bytes, on_complete):
        self.started.append(audio_bytes)
        self._callback = on_complete
        return object()

    def stop(self):
        self._callback = None

    def pause(self):
        return False


def test_mic_route_enabled_requires_dialogue_without_adapter():
    assert mic_route_enabled(running=True, dialogue_enabled=True, danmu_adapter_enabled=False)
    assert not mic_route_enabled(running=True, dialogue_enabled=False, danmu_adapter_enabled=True)
    assert not mic_route_enabled(running=False, dialogue_enabled=True, danmu_adapter_enabled=False)


def test_dialogue_mode_requires_armed_voice_session(monkeypatch, qapp):
    config = _dialogue_config()
    service = _dialogue_service(monkeypatch, config)
    service.stop_voice_session()
    assert not service.on_mic_speech_start()
    assert not service.on_mic_utterance_end(b"pcm")


def test_dialogue_mode_routes_two_independent_turns(monkeypatch, qapp):
    config = _dialogue_config()
    service = _dialogue_service(monkeypatch, config)
    app = service._app
    app._scene_generation = 3

    transcripts = iter(["第一轮", "第二轮"])
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(
            True,
            text=next(transcripts),
        ),
    )
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda prompt, resolved, *, session_id, turn_id: HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="测试回复"),
        ),
    )

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm-bytes-1")
    _wait_pool(service, qapp)

    turn1 = service.audio.get_turn(1)
    assert turn1.transcript == "第一轮"
    assert turn1.asr_status == "completed"
    assert turn1.status == "chat_completed"

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm-bytes-2")
    _wait_pool(service, qapp)

    turn2 = service.audio.get_turn(2)
    assert turn2.transcript == "第二轮"
    assert turn2.turn_id == 2
    assert turn2.status == "chat_completed"


def test_adapter_mode_does_not_route_mic(monkeypatch, qapp):
    config = _adapter_config()
    service = _runtime_service(monkeypatch, config)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda *_args, **_kwargs: pytest.fail("ASR must not run in adapter mode"),
    )

    assert not service.mic_route_active()
    assert not service.on_mic_speech_start()
    assert not service.on_mic_utterance_end(b"pcm")


def test_late_asr_after_mode_switch_does_not_create_transcript(monkeypatch, qapp):
    config = _dialogue_config()
    service = _dialogue_service(monkeypatch, config)
    service.on_mic_speech_start()
    stale_generation = service.runtime_generation
    apply_virtual_host_mode_settings(config, {"danmu_adapter_enabled": True})
    service.refresh_mode_settings()

    service._mic_route.on_asr_completed(
        1,
        MicTranscriptionResult(True, text="迟到转写"),
        stale_generation,
    )
    qapp.processEvents()

    turn = service.audio.get_turn(1)
    assert turn.status == "cancelled"
    assert turn.transcript == ""


def test_empty_pcm_marks_failed_without_blocking_next_turn(monkeypatch, qapp):
    config = _dialogue_config()
    service = _dialogue_service(monkeypatch, config)

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"")
    turn1 = service.audio.get_turn(1)
    assert turn1.status == "failed"
    assert turn1.failure_reason == "empty_pcm"

    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(True, text="恢复轮次"),
    )
    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm")
    _wait_pool(service, qapp)
    assert service.audio.get_turn(2).transcript == "恢复轮次"


def test_playback_suppressed_during_mic_capture(monkeypatch, qapp):
    config = _dialogue_config()
    service = _dialogue_service(monkeypatch, config)
    player = _BlockingPlayer()
    service.audio.playback = PlaybackQueue(player)

    service.audio.playback.enqueue(
        PlaybackItem(
            session_id=service.session.session_id,
            turn_id=99,
            segment_index=0,
            audio_bytes=b"queued",
            priority=PlaybackPriority.AUTO_SCENE,
        )
    )
    assert player.started == [b"queued"]

    service.on_mic_speech_start()
    assert service.audio.playback.playback_suppressed
    assert service.audio.playback.active_item is None

    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(True, text="ok"),
    )
    assert service.on_mic_utterance_end(b"pcm")
    _wait_pool(service, qapp)
    assert not service.audio.playback.playback_suppressed


def test_main_mic_mixin_skips_insert_when_routed(monkeypatch):
    from app.main_mic_mixin import DanmuAppMicMixin

    class _App(DanmuAppMicMixin):
        def __init__(self):
            self.config = _dialogue_config()
            self.engine = SimpleNamespace(running=True)
            self.logger = Mock()
            self._active_mic_utterance_id = ""
            self._mic_log_store = Mock(begin_partial=Mock(), finalize=Mock())
            self._mic_orchestrator = Mock(
                snapshot_pcm_for_utterance=Mock(return_value=b"pcm"),
                pcm_metrics=Mock(return_value=(0.1, 0.2)),
            )
            self.mic_in_flight = 0
            self.__dict__["virtual_host_runtime"] = Mock(
                on_mic_utterance_end=Mock(return_value=True),
            )

        def _has_mic_request_in_flight(self):
            return False

        def _mic_audio_supported(self):
            return True

        def _schedule_mic_transcription_log(self, *_args):
            pass

        def _trigger_mic_api_call(self, pcm):
            pytest.fail("mic insert must not run when virtual host routed")

    monkeypatch.setattr("app.main_mic_mixin.mic_mode_enabled", lambda _cfg: True)
    app = _App()
    app._on_mic_utterance_end()
    app.__dict__["virtual_host_runtime"].on_mic_utterance_end.assert_called_once_with(b"pcm")
