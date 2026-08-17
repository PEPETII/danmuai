"""虚拟主播：主链路 DanmuBatchCreated → VirtualHostSession 接入测试。"""

from __future__ import annotations

import time
from unittest.mock import Mock

from app.application.generation_pipeline import GenerationPipeline
from app.main_request_context_mixin import format_reply_request_id
from app.virtual_host.contracts import DanmuBatchCreated, SceneContext
from app.virtual_host.runtime_service import VirtualHostRuntimeService

from tests.conftest import make_minimal_danmu_app
from tests.test_virtual_host_runtime import _fake_app, _FakeConfig


def _make_runtime_service(*, vision_model: str | None = None) -> VirtualHostRuntimeService:
    data: dict[str, str] = {}
    if vision_model is not None:
        data["virtual_host_vision_model_id"] = vision_model
    config = _FakeConfig(data)
    return VirtualHostRuntimeService(_fake_app(config))


def _batch(
    batch_id: str,
    *,
    created_at: float | None = None,
    scene_generation: int,
    lines: tuple[str, ...] = ("弹幕一", "弹幕二"),
    ttl_seconds: float = 120.0,
) -> DanmuBatchCreated:
    current = time.time() if created_at is None else created_at
    return DanmuBatchCreated.from_lines(
        batch_id=batch_id,
        lines=list(lines),
        created_at=current,
        source="ai",
        screenshot_id=10,
        scene_generation=scene_generation,
        ttl_seconds=ttl_seconds,
    )


def _attach_runtime(app, service: VirtualHostRuntimeService) -> None:
    object.__setattr__(app, "virtual_host_runtime", service)
    object.__setattr__(app, "_generation_pipeline", GenerationPipeline(app))


def _handle_visual_reply(app, *, scene_generation: int = 0) -> bool:
    app._register_request_meta(10, 10, scene_generation, "visual")
    return app._generation_pipeline.handle_reply_parsed(
        text='["场景弹幕", "填充弹幕一", "填充弹幕二"]',
        persona_id="persona-1",
        request_round=10,
        screenshot_id=10,
        captured_at=1.0,
        scene_generation=scene_generation,
        request_started_at=2.0,
        reply_received_at=3.0,
    )


def test_runtime_accepts_batch_when_running():
    service = _make_runtime_service()
    service.start()
    service.session.update_scene_context(
        SceneContext(scene_generation=0, summary="画面", updated_at=time.time())
    )
    batch = _batch("10:10:0", scene_generation=0)
    decision = service.on_danmu_batch_created(batch)
    assert decision.accepted is True
    assert decision.reason == "accepted"
    assert service.session.recent_batches()[0].lines == batch.lines


def test_runtime_rejects_batch_when_stopped():
    service = _make_runtime_service()
    batch = _batch("10:10:0", scene_generation=0)
    decision = service.on_danmu_batch_created(batch)
    assert decision.accepted is False
    assert decision.reason == "invalid"
    assert service.session.recent_batches() == ()


def test_runtime_rejects_duplicate_batch_id():
    service = _make_runtime_service()
    service.start()
    batch = _batch("dup-id", scene_generation=0)
    assert service.on_danmu_batch_created(batch).accepted is True
    duplicate = service.on_danmu_batch_created(batch)
    assert duplicate.accepted is False
    assert duplicate.reason == "duplicate"


def test_runtime_rejects_scene_generation_mismatch():
    service = _make_runtime_service()
    service.start()
    service.session.update_scene_context(
        SceneContext(scene_generation=2, summary="画面", updated_at=time.time())
    )
    stale = _batch("stale-gen", scene_generation=1)
    decision = service.on_danmu_batch_created(stale)
    assert decision.accepted is False
    assert decision.reason == "scene_generation"


def test_runtime_rejects_expired_batch():
    service = _make_runtime_service()
    service.start()
    expired = _batch("expired", created_at=time.time() - 200.0, scene_generation=0, ttl_seconds=1.0)
    decision = service.on_danmu_batch_created(expired)
    assert decision.accepted is False
    assert decision.reason == "expired"


def test_vision_disabled_still_accepts_danmu_batch():
    service = _make_runtime_service(vision_model="")
    service.start()
    assert service.update_scene_from_image_data_uri(
        "data:image/jpeg;base64,ZmFrZQ==",
        screenshot_id=1,
        scene_generation=0,
    ) is None
    batch = _batch("no-vision", scene_generation=0)
    decision = service.on_danmu_batch_created(batch)
    assert decision.accepted is True
    assert service.session.recent_batches()[0].batch_id == "no-vision"


def test_handle_reply_parsed_feeds_virtual_host_without_affecting_reply_buffer():
    app = make_minimal_danmu_app()
    service = _make_runtime_service()
    service.start()
    _attach_runtime(app, service)
    assert _handle_visual_reply(app) is True
    assert app.reply_buffer.size() > 0
    batches = service.session.recent_batches()
    assert len(batches) == 1
    assert batches[0].batch_id == format_reply_request_id(10, 10, 0)
    assert batches[0].source == "ai"
    assert "场景弹幕" in batches[0].lines


def test_handle_reply_parsed_does_not_trigger_chat_or_tts(monkeypatch):
    app = make_minimal_danmu_app()
    service = _make_runtime_service()
    service.start()
    _attach_runtime(app, service)
    start_turn = Mock(side_effect=service.session.start_turn)
    monkeypatch.setattr(service.session, "start_turn", start_turn)
    synthesize_turn = Mock(side_effect=service.audio.synthesize_turn)
    monkeypatch.setattr(service.audio, "synthesize_turn", synthesize_turn)
    assert _handle_visual_reply(app) is True
    start_turn.assert_not_called()
    synthesize_turn.assert_not_called()
    assert service.tts_synthesize_count == 0


def test_handle_reply_parsed_skips_virtual_host_when_stopped():
    app = make_minimal_danmu_app()
    service = _make_runtime_service()
    _attach_runtime(app, service)
    assert _handle_visual_reply(app) is True
    assert service.session.recent_batches() == ()


def test_handle_reply_parsed_empty_normalized_items_skips_virtual_host():
    app = make_minimal_danmu_app()
    service = _make_runtime_service()
    service.start()
    _attach_runtime(app, service)
    app._register_request_meta(10, 10, 0, "visual")
    accepted = app._generation_pipeline.handle_reply_parsed(
        text="[]",
        persona_id="persona-1",
        request_round=10,
        screenshot_id=10,
        captured_at=1.0,
        scene_generation=0,
        request_started_at=2.0,
        reply_received_at=3.0,
    )
    assert accepted is False
    assert service.session.recent_batches() == ()
