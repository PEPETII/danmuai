"""虚拟主播自主回应运行时集成测试。"""

from __future__ import annotations

import threading
import time

import pytest
from app.virtual_host.audio import TtsSynthesisOutcome, TtsSynthesizer
from app.virtual_host.chat import HostChatHttpResult
from app.virtual_host.contracts import DanmuBatchCreated, HostTurnResult, SceneContext
from app.virtual_host.model_config import (
    VISION_MODEL_KEY,
    apply_virtual_host_model_config,
    encode_tts_option_id,
)
from app.virtual_host.playback import PlaybackQueue
from app.virtual_host.runtime_service import (
    ChatResponseCoordinator,
    TtsSynthesisCoordinator,
    VirtualHostRuntimeService,
    _TtsSynthesisRunnable,
)
from PyQt6.QtCore import QObject, QThreadPool, pyqtSlot

from tests.test_virtual_host_runtime import (
    _fake_app,
    _FakeConfig,
    _FakePlayer,
    _tts_manager,
    _vision_profile,
)


def _vision_config(vision_model: str = "qwen3-vl-flash") -> _FakeConfig:
    config = _FakeConfig({VISION_MODEL_KEY: vision_model}, custom_models=[_vision_profile(vision_model)])
    apply_virtual_host_model_config(config, {"vision_model_id": vision_model})
    return config


def _tts_vision_config(monkeypatch, vision_model: str = "qwen3-vl-flash") -> tuple[_FakeConfig, list[str]]:
    tts_calls: list[str] = []
    manager = _tts_manager(calls=tts_calls)
    option_id = encode_tts_option_id("vh-tts-provider", "vh-tts-model")
    config = _FakeConfig(
        {
            VISION_MODEL_KEY: vision_model,
            "virtual_host_tts_provider": "vh-tts-provider",
            "virtual_host_tts_model_id": "vh-tts-model",
        },
        custom_models=[_vision_profile(vision_model)],
    )
    config._tts_secrets["vh-tts-provider"] = {"api_key": "tts-secret"}
    apply_virtual_host_model_config(config, {"vision_model_id": vision_model})
    monkeypatch.setattr(
        "app.virtual_host.model_config.list_tts_model_options",
        lambda _config: [
            {
                "id": option_id,
                "label": "VH",
                "provider_id": "vh-tts-provider",
                "model_id": "vh-tts-model",
            }
        ],
    )
    monkeypatch.setattr("app.virtual_host.runtime_service.get_tts_manager", lambda: manager)
    return config, tts_calls


def _service(monkeypatch, config: _FakeConfig, *, rng=lambda: 0.0) -> VirtualHostRuntimeService:
    pool = QThreadPool()
    monkeypatch.setattr("app.virtual_host.runtime_service.ai_worker_pool", lambda: pool)
    service = VirtualHostRuntimeService(_fake_app(config))
    service._response_scheduler = type(service._response_scheduler)(
        rng=rng,
        min_cooldown_seconds=0.0,
    )
    service.start()
    service._test_pool = pool
    return service


def _service_with_player(monkeypatch, config: _FakeConfig, *, rng=lambda: 0.0) -> tuple[VirtualHostRuntimeService, _FakePlayer]:
    service = _service(monkeypatch, config, rng=rng)
    player = _FakePlayer()
    service._audio.playback = PlaybackQueue(player)
    return service, player


def _wait_pool(service: VirtualHostRuntimeService, qapp, timeout: float = 2.0) -> None:
    pool = getattr(service, "_test_pool", None)
    if pool is not None:
        pool.waitForDone(int(timeout * 1000))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)


def test_autonomous_batch_probability_miss_makes_zero_http(monkeypatch):
    config = _vision_config()
    service = _service(monkeypatch, config, rng=lambda: 0.99)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda *_args, **_kwargs: pytest.fail("chat HTTP must not run"),
    )
    service.session.update_scene_context(
        SceneContext(scene_generation=0, summary="画面", updated_at=time.time())
    )
    batch = DanmuBatchCreated.from_lines(
        batch_id="b1",
        lines=["单条"],
        created_at=time.time(),
        scene_generation=0,
    )
    service.on_danmu_batch_created(batch)
    assert service.chat_request_count == 0


def test_autonomous_response_completes_session_and_skips_tts_when_speak_false(monkeypatch, qapp):
    config = _vision_config()
    service = _service(monkeypatch, config)
    service.session.update_scene_context(
        SceneContext(scene_generation=0, summary="游戏", updated_at=time.time())
    )
    chat_calls = 0

    def _fake_chat(prompt, resolved, *, session_id, turn_id, http_client=None):
        del prompt, http_client
        nonlocal chat_calls
        chat_calls += 1
        return HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="静默回应", speak=False),
            model_id=resolved[2],
        )

    monkeypatch.setattr("app.virtual_host.runtime_service.request_host_chat", _fake_chat)

    coordinator = ChatResponseCoordinator()
    receiver_done = threading.Event()

    class _Receiver(QObject):
        @pyqtSlot(object, object, int, str)
        def on_done(self, result, host_turn, runtime_generation, model_id):
            del result, host_turn, runtime_generation, model_id
            receiver_done.set()

    receiver = _Receiver()
    coordinator.completed.connect(receiver.on_done)

    from app.virtual_host.runtime_service import _ChatResponseRunnable

    host_turn = service.session.start_turn("弹幕一", now=time.time())
    prompt = service.session.compose_prompt(host_turn)
    resolved = ("https://example.com/v1", "key", "qwen3-vl-flash", "openai-compatible")
    runnable = _ChatResponseRunnable(
        coordinator,
        prompt=prompt,
        resolved=resolved,
        host_turn=host_turn,
        runtime_generation=service.runtime_generation,
        chat_model_id="qwen3-vl-flash",
    )
    worker = threading.Thread(target=runnable.run)
    worker.start()
    worker.join(timeout=2.0)

    deadline = time.monotonic() + 1.0
    while not receiver_done.is_set() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text="静默回应",
                speak=False,
            ),
            model_id="qwen3-vl-flash",
        ),
        host_turn,
        service.runtime_generation,
        "qwen3-vl-flash",
    )
    assert chat_calls == 1
    assert len(service.session.history) == 1
    assert service.session.history[0].assistant_text == "静默回应"
    assert service.tts_synthesize_count == 0


def test_stale_runtime_generation_chat_result_does_not_write_session(monkeypatch):
    config = _vision_config()
    service = _service(monkeypatch, config)
    host_turn = service.session.start_turn("弹幕", now=time.time())
    stale_generation = service.runtime_generation
    service.stop()
    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text="过期",
                speak=True,
            ),
            model_id="qwen3-vl-flash",
        ),
        host_turn,
        stale_generation,
        "qwen3-vl-flash",
    )
    assert service.session.history == ()


def test_on_danmu_batch_triggers_chat_when_scheduler_passes(monkeypatch, qapp):
    config = _vision_config()
    service = _service(monkeypatch, config)
    service.session.update_scene_context(
        SceneContext(scene_generation=0, summary="画面", updated_at=time.time())
    )

    def _fake_chat(prompt, resolved, *, session_id, turn_id, http_client=None):
        del prompt, http_client
        return HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text="回应", speak=True),
            model_id=resolved[2],
        )

    monkeypatch.setattr("app.virtual_host.runtime_service.request_host_chat", _fake_chat)

    batch = DanmuBatchCreated.from_lines(
        batch_id="trigger-batch",
        lines=["弹幕一", "弹幕二", "弹幕三"],
        created_at=time.time(),
        scene_generation=0,
    )
    service.on_danmu_batch_created(batch)

    deadline = time.monotonic() + 2.0
    while (service.chat_in_flight or not service.session.history) and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert service.chat_request_count == 1
    assert len(service.session.history) == 1


def test_model_none_makes_zero_chat_http(monkeypatch):
    config = _FakeConfig(custom_models=[_vision_profile()])
    service = _service(monkeypatch, config)
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda *_args, **_kwargs: pytest.fail("chat HTTP must not run"),
    )
    batch = DanmuBatchCreated.from_lines(
        batch_id="no-model",
        lines=["弹幕"],
        created_at=time.time(),
        scene_generation=0,
    )
    service.on_danmu_batch_created(batch)
    assert service.chat_request_count == 0


def test_no_tts_binding_makes_zero_tts_synthesis(monkeypatch, qapp):
    config = _vision_config()
    service, player = _service_with_player(monkeypatch, config)
    host_turn = service.session.start_turn("指令", now=time.time())
    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text="需要播报",
                speak=True,
            ),
            model_id="qwen3-vl-flash",
        ),
        host_turn,
        service.runtime_generation,
        "qwen3-vl-flash",
    )
    _wait_pool(service, qapp)
    assert service.tts_synthesize_count == 0
    assert player.started == []


def test_tts_synthesis_runs_off_main_thread(monkeypatch, qapp):
    config, _ = _tts_vision_config(monkeypatch)
    service, _ = _service_with_player(monkeypatch, config)
    main_thread_id = threading.get_ident()
    worker_thread_ids: list[int] = []

    def _fake_build():
        def _synth(text, binding):
            del text, binding
            worker_thread_ids.append(threading.get_ident())
            return TtsSynthesisOutcome("ok", b"audio-chunk")

        return TtsSynthesizer(synthesize_fn=_synth)

    monkeypatch.setattr(service, "_build_worker_tts_synthesizer", _fake_build)
    host_turn = service.session.start_turn("指令", now=time.time())
    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text="自主回应文本。",
                speak=True,
            ),
            model_id="qwen3-vl-flash",
        ),
        host_turn,
        service.runtime_generation,
        "qwen3-vl-flash",
    )
    _wait_pool(service, qapp)
    assert worker_thread_ids
    assert all(thread_id != main_thread_id for thread_id in worker_thread_ids)


def test_stale_tts_result_does_not_enqueue_playback(monkeypatch, qapp):
    config, _ = _tts_vision_config(monkeypatch)
    service, player = _service_with_player(monkeypatch, config)
    coordinator = TtsSynthesisCoordinator()
    host_turn = service.session.start_turn("指令", now=time.time())
    runtime_generation = service.runtime_generation
    service.stop()

    def _slow_build():
        def _synth(text, binding):
            del text, binding
            time.sleep(0.05)
            return TtsSynthesisOutcome("ok", b"stale-audio")

        return TtsSynthesizer(synthesize_fn=_synth)

    monkeypatch.setattr(service, "_build_worker_tts_synthesizer", _slow_build)
    binding = service._tts_binding
    assert binding is not None

    from app.virtual_host.runtime_service import TtsSynthesisJob

    job = TtsSynthesisJob(
        session_id=service.session.session_id,
        turn_id=host_turn.turn_id,
        segment_index=0,
        text="过期音频。",
        runtime_generation=runtime_generation,
        binding=binding,
    )
    runnable = _TtsSynthesisRunnable(
        coordinator,
        job=job,
        synthesizer=_slow_build(),
    )
    worker = threading.Thread(target=runnable.run)
    worker.start()
    worker.join(timeout=2.0)

    receiver_done = threading.Event()

    class _Receiver(QObject):
        @pyqtSlot(object, object)
        def on_done(self, _job, _outcome):
            receiver_done.set()

    receiver = _Receiver()
    coordinator.completed.connect(receiver.on_done)
    deadline = time.monotonic() + 1.0
    while not receiver_done.is_set() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    service._on_tts_synthesis_completed(
        job,
        TtsSynthesisOutcome("ok", b"stale-audio"),
    )
    assert player.started == []


def test_autonomous_speak_true_reaches_fake_audio_player(monkeypatch, qapp):
    config, tts_calls = _tts_vision_config(monkeypatch)
    service, player = _service_with_player(monkeypatch, config)
    host_turn = service.session.start_turn("指令", now=time.time())
    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text="大家好。",
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
    assert tts_calls == ["vh-tts-model"]
    assert len(player.started) == 1


def test_tts_failure_does_not_block_subsequent_chat(monkeypatch, qapp):
    config = _vision_config()
    service = _service(monkeypatch, config)
    service.session.update_scene_context(
        SceneContext(scene_generation=0, summary="画面", updated_at=time.time())
    )
    chat_calls = 0

    def _fake_chat(prompt, resolved, *, session_id, turn_id, http_client=None):
        del prompt, http_client
        nonlocal chat_calls
        chat_calls += 1
        text = "失败回应" if chat_calls == 1 else "第二次回应"
        return HostChatHttpResult(
            ok=True,
            result=HostTurnResult(session_id=session_id, turn_id=turn_id, text=text, speak=True),
            model_id=resolved[2],
        )

    monkeypatch.setattr("app.virtual_host.runtime_service.request_host_chat", _fake_chat)

    def _fail_build():
        def _synth(text, binding):
            del text, binding
            return TtsSynthesisOutcome("failed", reason="network_error")

        return TtsSynthesizer(synthesize_fn=_synth)

    monkeypatch.setattr(service, "_build_worker_tts_synthesizer", _fail_build)

    batch1 = DanmuBatchCreated.from_lines(
        batch_id="batch-a",
        lines=["弹幕一"],
        created_at=time.time(),
        scene_generation=0,
    )
    service.on_danmu_batch_created(batch1)
    _wait_pool(service, qapp)
    assert chat_calls == 1

    batch2 = DanmuBatchCreated.from_lines(
        batch_id="batch-b",
        lines=["弹幕二"],
        created_at=time.time(),
        scene_generation=0,
    )
    service.on_danmu_batch_created(batch2)
    _wait_pool(service, qapp)
    assert chat_calls == 2
