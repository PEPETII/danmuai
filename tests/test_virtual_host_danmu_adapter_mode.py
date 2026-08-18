"""W-010：虚拟主播 AI 读弹幕适配模式门控测试。"""

from __future__ import annotations

import time

import pytest
from app.virtual_host.chat import HostChatHttpResult
from app.virtual_host.contracts import HostTurnResult, SceneContext
from app.virtual_host.mode_config import apply_virtual_host_mode_settings
from app.virtual_host.model_config import VISION_MODEL_KEY, apply_virtual_host_model_config
from app.virtual_host.runtime_service import VirtualHostRuntimeService
from app.virtual_host.vision import SceneSummaryResult

from tests.test_virtual_host_autonomous_response import (
    _service,
    _service_with_player,
    _tts_vision_config,
    _vision_config,
    _wait_pool,
)
from tests.test_virtual_host_danmu_batch_pipeline import _batch
from tests.test_virtual_host_runtime import (
    _FakeConfig,
    _vision_profile,
)


def _adapter_config(
    *,
    danmu_adapter: bool = True,
    dialogue: bool = False,
    vision_model: str = "qwen3-vl-flash",
) -> _FakeConfig:
    config = _FakeConfig(
        {
            "virtual_host_danmu_adapter_enabled": "1" if danmu_adapter else "0",
            "virtual_host_dialogue_enabled": "1" if dialogue else "0",
            VISION_MODEL_KEY: vision_model,
        },
        custom_models=[_vision_profile(vision_model)],
    )
    apply_virtual_host_model_config(config, {"vision_model_id": vision_model})
    return config


def _make_service(
    monkeypatch,
    config: _FakeConfig,
    *,
    rng=lambda: 0.0,
) -> VirtualHostRuntimeService:
    return _service(monkeypatch, config, rng=rng)


def test_danmu_batch_rejected_with_mode_disabled_when_adapter_off(monkeypatch):
    config = _adapter_config(danmu_adapter=False)
    service = _make_service(monkeypatch, config)
    service.start()
    service.session.update_scene_context(
        SceneContext(scene_generation=0, summary="画面", updated_at=time.time())
    )

    decision = service.on_danmu_batch_created(_batch("off-batch", scene_generation=0))

    assert decision.accepted is False
    assert decision.reason == "mode_disabled"
    assert service.session.recent_batches() == ()


def test_danmu_batch_rejected_with_mode_disabled_when_dialogue_on(monkeypatch):
    config = _adapter_config(danmu_adapter=False, dialogue=True)
    service = _make_service(monkeypatch, config)
    service.start()
    service.session.update_scene_context(
        SceneContext(scene_generation=0, summary="画面", updated_at=time.time())
    )

    decision = service.on_danmu_batch_created(_batch("dialogue-batch", scene_generation=0))

    assert decision.accepted is False
    assert decision.reason == "mode_disabled"
    assert service.session.recent_batches() == ()


def test_scene_change_does_not_trigger_chat_when_adapter_off(monkeypatch):
    config = _vision_config()
    service = _make_service(monkeypatch, config)
    service.start()
    service._danmu_adapter_enabled = False
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda *_args, **_kwargs: pytest.fail("chat HTTP must not run"),
    )

    service._apply_scene_summary(
        SceneSummaryResult(ok=True, text="新画面", model_id="qwen3-vl-flash"),
        screenshot_id=1,
        scene_generation=0,
        captured_at=time.monotonic(),
    )

    assert service.chat_request_count == 0


def test_scene_change_does_not_trigger_chat_when_dialogue_on(monkeypatch):
    config = _adapter_config(danmu_adapter=False, dialogue=True)
    service = _make_service(monkeypatch, config)
    service.start()
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda *_args, **_kwargs: pytest.fail("chat HTTP must not run"),
    )

    service._apply_scene_summary(
        SceneSummaryResult(ok=True, text="新画面", model_id="qwen3-vl-flash"),
        screenshot_id=1,
        scene_generation=0,
        captured_at=time.monotonic(),
    )

    assert service.chat_request_count == 0


def test_adapter_enabled_preserves_existing_batch_acceptance(monkeypatch):
    config = _adapter_config(danmu_adapter=True)
    service = _make_service(monkeypatch, config)
    service.start()
    service.session.update_scene_context(
        SceneContext(scene_generation=0, summary="画面", updated_at=time.time())
    )

    decision = service.on_danmu_batch_created(_batch("enabled-batch", scene_generation=0))

    assert decision.accepted is True
    assert decision.reason == "accepted"
    assert service.session.recent_batches()[0].batch_id == "enabled-batch"


def test_batches_during_disabled_period_are_not_replayed_on_re_enable(monkeypatch):
    config = _adapter_config(danmu_adapter=False)
    service = _make_service(monkeypatch, config)
    service.start()
    service.session.update_scene_context(
        SceneContext(scene_generation=0, summary="画面", updated_at=time.time())
    )
    monkeypatch.setattr(
        "app.virtual_host.runtime_service.request_host_chat",
        lambda *_args, **_kwargs: pytest.fail("chat HTTP must not run"),
    )

    assert service.on_danmu_batch_created(_batch("missed", scene_generation=0)).reason == "mode_disabled"

    apply_virtual_host_mode_settings(config, {"danmu_adapter_enabled": True})
    service.refresh_mode_settings()

    assert service.session.recent_batches() == ()
    assert service.on_danmu_batch_created(_batch("fresh", scene_generation=0)).accepted is True
    assert [batch.batch_id for batch in service.session.recent_batches()] == ["fresh"]


def test_switch_auto_to_dialogue_rejects_stale_auto_chat(monkeypatch, qapp):
    config = _adapter_config(danmu_adapter=True)
    service = _make_service(monkeypatch, config)
    service.start()
    host_turn = service.session.start_turn("自动", now=time.time())
    stale_generation = service.runtime_generation

    apply_virtual_host_mode_settings(config, {"dialogue_enabled": True})
    service.refresh_mode_settings()

    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text="迟到自动回复",
                speak=True,
            ),
            model_id="qwen3-vl-flash",
        ),
        host_turn,
        stale_generation,
        "qwen3-vl-flash",
    )
    _wait_pool(service, qapp)

    assert service.session.history == ()


def test_switch_auto_to_dialogue_cancels_auto_playback(monkeypatch, qapp):
    config, _ = _tts_vision_config(monkeypatch)
    service, player = _service_with_player(monkeypatch, config)
    host_turn = service.session.start_turn("自动", now=time.time())
    service._on_chat_response_completed(
        HostChatHttpResult(
            ok=True,
            result=HostTurnResult(
                session_id=service.session.session_id,
                turn_id=host_turn.turn_id,
                text="自动播报。",
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

    apply_virtual_host_mode_settings(config, {"dialogue_enabled": True})
    service.refresh_mode_settings()

    assert service.audio.playback.active_item is None
    assert service.audio.playback.queued_items == ()


def test_danmu_read_config_unaffected_by_virtual_host_mode_switch():
    from app.danmu_read_service import danmu_read_enabled

    config = _FakeConfig(
        {
            "danmu_read_enabled": "1",
            "virtual_host_danmu_adapter_enabled": "1",
            "virtual_host_dialogue_enabled": "0",
        }
    )
    assert danmu_read_enabled(config) is True

    apply_virtual_host_mode_settings(config, {"dialogue_enabled": True})

    assert danmu_read_enabled(config) is True
    assert config.get("danmu_read_enabled") == "1"
    assert config.get("virtual_host_dialogue_enabled") == "1"
    assert config.get("virtual_host_danmu_adapter_enabled") == "0"
