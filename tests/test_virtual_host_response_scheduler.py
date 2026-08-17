"""VirtualHostResponseScheduler 门控与评分测试。"""

from __future__ import annotations

import time

from app.virtual_host.contracts import DanmuBatchCreated, SceneContext
from app.virtual_host.response_scheduler import (
    ResponseCandidateEvent,
    VirtualHostResponseScheduler,
    build_autonomous_input,
)
from app.virtual_host.session import VirtualHostSession


def _session_with_danmu(*, scene_generation: int = 0, lines: tuple[str, ...] = ("弹幕A", "弹幕B")) -> VirtualHostSession:
    session = VirtualHostSession()
    session.update_scene_context(
        SceneContext(scene_generation=scene_generation, summary="游戏画面", updated_at=time.time())
    )
    batch = DanmuBatchCreated.from_lines(
        batch_id="batch-1",
        lines=list(lines),
        created_at=time.time(),
        scene_generation=scene_generation,
    )
    session.ingest_danmu_batch(batch, current_scene_generation=scene_generation)
    return session


def _event(kind: str = "danmu_batch", **kwargs) -> ResponseCandidateEvent:
    return ResponseCandidateEvent(
        kind=kind,
        at=kwargs.get("at", time.time()),
        batch_id=kwargs.get("batch_id", "batch-1"),
        scene_generation=kwargs.get("scene_generation", 0),
    )


def test_scheduler_runtime_stopped_is_no_op():
    scheduler = VirtualHostResponseScheduler(rng=lambda: 1.0)
    session = _session_with_danmu()
    decision = scheduler.evaluate(
        _event(),
        running=False,
        model_enabled=True,
        chat_in_flight=False,
        last_spoke_at=None,
        session=session,
    )
    assert decision.should_respond is False
    assert decision.reason == "runtime_stopped"


def test_scheduler_model_disabled_is_no_op():
    scheduler = VirtualHostResponseScheduler(rng=lambda: 1.0)
    session = _session_with_danmu()
    decision = scheduler.evaluate(
        _event(),
        running=True,
        model_enabled=False,
        chat_in_flight=False,
        last_spoke_at=None,
        session=session,
    )
    assert decision.should_respond is False
    assert decision.reason == "model_disabled"


def test_scheduler_chat_in_flight_is_no_op():
    scheduler = VirtualHostResponseScheduler(rng=lambda: 1.0)
    session = _session_with_danmu()
    decision = scheduler.evaluate(
        _event(),
        running=True,
        model_enabled=True,
        chat_in_flight=True,
        last_spoke_at=None,
        session=session,
    )
    assert decision.should_respond is False
    assert decision.reason == "chat_in_flight"


def test_scheduler_cooldown_blocks_response():
    now = 1000.0
    scheduler = VirtualHostResponseScheduler(min_cooldown_seconds=30.0, rng=lambda: 1.0, clock=lambda: now)
    session = _session_with_danmu()
    decision = scheduler.evaluate(
        _event(at=now),
        running=True,
        model_enabled=True,
        chat_in_flight=False,
        last_spoke_at=now - 5.0,
        session=session,
        now=now,
    )
    assert decision.should_respond is False
    assert decision.reason == "cooldown"


def test_scheduler_probability_miss_with_high_roll():
    scheduler = VirtualHostResponseScheduler(rng=lambda: 0.99)
    session = _session_with_danmu(lines=("单条",))
    decision = scheduler.evaluate(
        _event(),
        running=True,
        model_enabled=True,
        chat_in_flight=False,
        last_spoke_at=None,
        session=session,
    )
    assert decision.should_respond is False
    assert decision.reason == "probability_miss"


def test_scheduler_probability_hit_with_low_roll():
    scheduler = VirtualHostResponseScheduler(rng=lambda: 0.0)
    session = _session_with_danmu(lines=("弹幕一", "弹幕二", "弹幕三"))
    decision = scheduler.evaluate(
        _event(),
        running=True,
        model_enabled=True,
        chat_in_flight=False,
        last_spoke_at=None,
        session=session,
    )
    assert decision.should_respond is True
    assert decision.reason == "probability_hit"
    assert decision.score > 0.0


def test_scheduler_scene_change_candidate_can_score():
    scheduler = VirtualHostResponseScheduler(rng=lambda: 0.0)
    session = VirtualHostSession()
    session.update_scene_context(
        SceneContext(scene_generation=1, summary="Boss 战", keywords=("Boss",), updated_at=time.time())
    )
    decision = scheduler.evaluate(
        _event(kind="scene_change", scene_generation=1),
        running=True,
        model_enabled=True,
        chat_in_flight=False,
        last_spoke_at=None,
        session=session,
    )
    assert decision.should_respond is True


def test_scheduler_ordinary_batches_not_trigger_every_cooldown_cycle():
    """连续 100 个普通 batch 不应每个 cooldown 周期都触发。"""
    now = 1000.0
    rolls = [0.0 if index % 2 == 0 else 0.99 for index in range(100)]
    roll_iter = iter(rolls)
    scheduler = VirtualHostResponseScheduler(
        min_cooldown_seconds=0.0,
        rng=lambda: next(roll_iter),
        clock=lambda: now,
    )
    session = VirtualHostSession()
    session.update_scene_context(
        SceneContext(scene_generation=0, summary="普通画面", updated_at=now)
    )
    triggered = 0
    for index in range(100):
        batch_id = f"batch-{index}"
        batch = DanmuBatchCreated.from_lines(
            batch_id=batch_id,
            lines=["普通弹幕"],
            created_at=now,
            scene_generation=0,
        )
        session.ingest_danmu_batch(batch, current_scene_generation=0, now=now)
        decision = scheduler.evaluate(
            ResponseCandidateEvent(
                kind="danmu_batch",
                at=now + index,
                batch_id=batch_id,
                scene_generation=0,
            ),
            running=True,
            model_enabled=True,
            chat_in_flight=False,
            last_spoke_at=None,
            session=session,
            now=now + index,
        )
        if decision.should_respond:
            triggered += 1
    assert triggered < 100
    assert triggered > 0


def test_build_autonomous_input_uses_semantic_instruction_for_danmu():
    session = _session_with_danmu(lines=("观众提问", "再来一条"))
    text = build_autonomous_input(session)
    assert "观众提问" not in text
    assert "再来一条" not in text
    assert "弹幕" in text


def test_build_autonomous_input_falls_back_to_scene_instruction():
    session = VirtualHostSession()
    session.update_scene_context(
        SceneContext(scene_generation=0, summary="桌面浏览器", updated_at=time.time())
    )
    text = build_autonomous_input(session)
    assert "桌面浏览器" not in text
    assert "画面" in text
