"""虚拟主播自主回应运行时集成测试。"""

from __future__ import annotations

import threading
import time

import pytest
from app.virtual_host.chat import HostChatHttpResult
from app.virtual_host.contracts import DanmuBatchCreated, HostTurnResult, SceneContext
from app.virtual_host.model_config import VISION_MODEL_KEY, apply_virtual_host_model_config
from app.virtual_host.runtime_service import ChatResponseCoordinator, VirtualHostRuntimeService
from PyQt6.QtCore import QObject, QThreadPool, pyqtSlot

from tests.test_virtual_host_runtime import _fake_app, _FakeConfig, _vision_profile


def _vision_config(vision_model: str = "qwen3-vl-flash") -> _FakeConfig:
    config = _FakeConfig({VISION_MODEL_KEY: vision_model}, custom_models=[_vision_profile(vision_model)])
    apply_virtual_host_model_config(config, {"vision_model_id": vision_model})
    return config


def _service(monkeypatch, config: _FakeConfig, *, rng=lambda: 1.0) -> VirtualHostRuntimeService:
    pool = QThreadPool()
    monkeypatch.setattr("app.virtual_host.runtime_service.ai_worker_pool", lambda: pool)
    service = VirtualHostRuntimeService(_fake_app(config))
    service._response_scheduler = type(service._response_scheduler)(
        score_threshold=0.4,
        rng=rng,
        min_cooldown_seconds=0.0,
    )
    service.start()
    return service


def test_autonomous_batch_below_threshold_makes_zero_http(monkeypatch):
    config = _vision_config()
    service = _service(monkeypatch, config, rng=lambda: 0.0)
    service._response_scheduler = type(service._response_scheduler)(
        score_threshold=0.99,
        rng=lambda: 0.0,
        min_cooldown_seconds=0.0,
    )
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
