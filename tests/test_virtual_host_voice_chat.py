"""W-016：虚拟主播 ASR 转写接入 Chat 会话测试。"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from app.mic_transcription import MicTranscriptionResult
from app.virtual_host.chat import HostChatHttpResult
from app.virtual_host.contracts import DanmuBatchCreated, HostTurnResult, SceneContext
from app.virtual_host.knowledge import KnowledgeContextAdapter
from app.virtual_host.playback import PlaybackQueue
from app.virtual_host.runtime_service import VirtualHostRuntimeService
from PyQt6.QtCore import QThreadPool

from tests.test_virtual_host_autonomous_response import _wait_pool
from tests.test_virtual_host_mic_route import _dialogue_config, _dialogue_service
from tests.test_virtual_host_runtime import (
    _FakePlayer,
    _register_runtime_test,
)


class _PersonaManager:
    def __init__(self) -> None:
        self.pick_count = 0

    def pick_random(self):
        self.pick_count += 1
        return "稳定主播"

    def get_prompt(self, name):
        return f"系统人格:{name}", f"用户人格:{name}"


def _dialogue_service_with_persona(monkeypatch, config) -> VirtualHostRuntimeService:
    pool = QThreadPool()
    monkeypatch.setattr("app.virtual_host.runtime_service.ai_worker_pool", lambda: pool)
    app = SimpleNamespace(
        config=config,
        personae=_PersonaManager(),
        logger=SimpleNamespace(warning=lambda *args, **kwargs: None),
    )
    service = VirtualHostRuntimeService(app)
    service.start()
    service.start_voice_session()
    service._test_pool = pool
    _register_runtime_test(service, pool)
    return service


def _fake_chat_ok(text: str) -> HostChatHttpResult:
    return HostChatHttpResult(
        ok=True,
        result=HostTurnResult(session_id="ignored", turn_id=0, text=text, speak=True),
    )


def test_voice_chat_two_rounds_keep_stable_persona_and_host_turn_result(monkeypatch, qapp):
    config = _dialogue_config()
    service = _dialogue_service_with_persona(monkeypatch, config)
    service._app._scene_generation = 2
    replies = iter(["第一轮回复", "第二轮回复"])
    captured_turn_ids: list[int] = []

    def _fake_request(prompt, resolved, *, session_id, turn_id):
        captured_turn_ids.append(int(turn_id))
        result = _fake_chat_ok(next(replies))
        return HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text=result.result.text),
        )

    monkeypatch.setattr("app.virtual_host.runtime_service.request_host_chat", _fake_request)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(True, text="第一轮" if b"1" in pcm else "第二轮"),
    )

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm-1")
    _wait_pool(service, qapp)

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm-2")
    _wait_pool(service, qapp)

    assert service._app.personae.pick_count == 1
    assert captured_turn_ids == [1, 2]
    assert len(service.session.history) == 2
    assert service.session.history[0].assistant_text == "第一轮回复"
    assert service.session.history[1].assistant_text == "第二轮回复"

    turn1 = service.audio.get_turn(1)
    turn2 = service.audio.get_turn(2)
    assert turn1.status == "chat_completed"
    assert turn2.status == "chat_completed"
    assert turn1.host_result is not None
    assert turn2.host_result is not None
    assert turn1.host_result.text == "第一轮回复"
    assert turn2.host_result.text == "第二轮回复"


def test_voice_chat_request_carries_session_scene_and_knowledge_context(monkeypatch, qapp):
    config = _dialogue_config()
    service = _dialogue_service_with_persona(monkeypatch, config)
    service._app._scene_generation = 5
    service.session.update_scene_context(
        SceneContext(scene_generation=5, summary="Boss 战", updated_at=time.time())
    )
    captured: dict[str, object] = {}

    class _Retriever:
        def retrieve(self, **kwargs):
            captured["knowledge_kwargs"] = kwargs
            result = SimpleNamespace(
                prompt_text="知识片段",
                hit_count=1,
                items=[{"id": 3, "public_id": "pub-3", "title": "wiki"}],
            )
            return result

    service._knowledge_adapter = KnowledgeContextAdapter(retriever=_Retriever())

    def _fake_request(prompt, resolved, *, session_id, turn_id):
        captured["session_id"] = session_id
        captured["turn_id"] = turn_id
        captured["system_text"], captured["user_text"] = prompt.render()
        captured["scene_generation"] = service.audio.get_turn(1).scene_generation
        return HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="收到"),
        )

    monkeypatch.setattr("app.virtual_host.runtime_service.request_host_chat", _fake_request)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(True, text="这个 Boss 怎么打"),
    )

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm")
    _wait_pool(service, qapp)

    assert captured["session_id"] == service.session.session_id
    assert captured["turn_id"] == 1
    assert captured["scene_generation"] == 5
    assert "系统人格:稳定主播" in str(captured["system_text"])
    assert "Boss 战" in str(captured["user_text"])
    assert "这个 Boss 怎么打" in str(captured["user_text"])
    assert "知识片段" in str(captured["system_text"])
    assert captured["knowledge_kwargs"]["request_round"] == 1


def test_voice_chat_does_not_inject_recent_danmu_batches(monkeypatch, qapp):
    config = _dialogue_config()
    service = _dialogue_service_with_persona(monkeypatch, config)
    service._app._scene_generation = 0
    batch = DanmuBatchCreated.from_lines(
        batch_id="stale-danmu",
        lines=["不应进入语音对话的弹幕"],
        created_at=time.time(),
        scene_generation=0,
    )
    assert service.session.accept_danmu_batch(batch, current_scene_generation=0)
    captured: dict[str, object] = {}

    def _fake_request(prompt, resolved, *, session_id, turn_id):
        del resolved
        captured["prompt"] = prompt
        return HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="语音回复"),
        )

    monkeypatch.setattr("app.virtual_host.runtime_service.request_host_chat", _fake_request)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, _pcm: MicTranscriptionResult(True, text="玩家语音"),
    )

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm")
    _wait_pool(service, qapp)

    prompt = captured["prompt"]
    assert prompt.danmu_context == ()
    assert "[HOST_DANMU]" not in prompt.user_prompt
    assert "不应进入语音对话的弹幕" not in prompt.user_prompt


def test_voice_chat_failures_do_not_enqueue_playable_output(monkeypatch, qapp):
    config = _dialogue_config()
    service = _dialogue_service_with_persona(monkeypatch, config)
    player = _FakePlayer()
    service.audio.playback = PlaybackQueue(player)

    cases = [
        HostChatHttpResult(ok=False, error="empty_parse"),
        HostChatHttpResult(ok=False, error="http_500"),
        HostChatHttpResult(ok=False, error="ReadTimeout"),
    ]

    for index, chat_result in enumerate(cases, start=1):

        def _fake_fail(*_args, _result=chat_result, **_kwargs):
            return _result

        monkeypatch.setattr(
            "app.virtual_host.runtime_service.request_host_chat",
            _fake_fail,
        )
        monkeypatch.setattr(
            "app.virtual_host.runtime_service.transcribe_pcm",
            lambda _cfg, pcm, round_id=index: MicTranscriptionResult(True, text=f"问{round_id}"),
        )
        assert service.on_mic_speech_start()
        assert service.on_mic_utterance_end(f"pcm-{index}".encode())
        _wait_pool(service, qapp)
        turn = service.audio.get_turn(index)
        assert turn.status == "failed"
        assert turn.host_result is None

    assert player.started == []
    assert service.audio.playback.queued_items == ()


def test_stale_voice_chat_generation_is_ignored(monkeypatch, qapp):
    import threading

    config = _dialogue_config()
    service = _dialogue_service_with_persona(monkeypatch, config)
    release = threading.Event()
    started = threading.Event()

    def _fake_request(prompt, resolved, *, session_id, turn_id):
        started.set()
        assert release.wait(timeout=2.0)
        return HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="迟到回复"),
        )

    monkeypatch.setattr("app.virtual_host.runtime_service.request_host_chat", _fake_request)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.transcribe_pcm",
        lambda _cfg, pcm: MicTranscriptionResult(True, text="用户说话"),
    )

    assert service.on_mic_speech_start()
    assert service.on_mic_utterance_end(b"pcm")
    _wait_pool(service, qapp, timeout=0.2)
    deadline = time.monotonic() + 2.0
    while not started.is_set() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    assert started.is_set()

    stale_generation = service.runtime_generation
    service._bump_runtime_generation()
    release.set()
    _wait_pool(service, qapp)

    turn = service.audio.get_turn(1)
    assert turn.host_result is None
    assert service.session.history == ()
    assert stale_generation != service.runtime_generation


def test_dialogue_mode_danmu_batch_does_not_trigger_chat(monkeypatch, qapp):
    config = _dialogue_config()
    service = _dialogue_service(monkeypatch, config)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda *_args, **_kwargs: pytest.fail("danmu batch must not trigger chat in dialogue mode"),
    )
    batch = DanmuBatchCreated.from_lines(
        batch_id="dialogue-batch",
        lines=["弹幕不应触发"],
        created_at=time.time(),
        scene_generation=0,
    )
    decision = service.on_danmu_batch_created(batch)
    assert decision.accepted is False
    assert decision.reason == "mode_disabled"
    assert service.chat_request_count == 0


def test_adapter_mode_danmu_batch_still_accepts_without_voice_chat(monkeypatch, qapp):
    from tests.test_virtual_host_mic_route import _adapter_config

    config = _adapter_config()
    pool = QThreadPool()
    monkeypatch.setattr("app.virtual_host.runtime_service.ai_worker_pool", lambda: pool)
    service = VirtualHostRuntimeService(
        SimpleNamespace(config=config, personae=None, logger=SimpleNamespace(warning=lambda *_a, **_k: None))
    )
    service.start()
    _register_runtime_test(service, pool)

    batch = DanmuBatchCreated.from_lines(
        batch_id="adapter-batch",
        lines=["适配模式弹幕"],
        created_at=time.time(),
        scene_generation=0,
    )
    decision = service.on_danmu_batch_created(batch)
    assert decision.accepted is True
    assert not service.mic_route_active()
