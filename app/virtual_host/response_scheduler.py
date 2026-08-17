"""虚拟主播自主回应调度：候选事件评分 + 门控，不保证每批弹幕都触发发言。"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.virtual_host.session import VirtualHostSession

CandidateKind = Literal["danmu_batch", "scene_change"]


@dataclass(frozen=True)
class ResponseCandidateEvent:
    kind: CandidateKind
    at: float
    batch_id: str = ""
    scene_generation: int = 0


@dataclass(frozen=True)
class ScheduleDecision:
    should_respond: bool
    score: float
    reason: str


class VirtualHostResponseScheduler:
    """纯逻辑调度器；HTTP / Session 写入由运行时在外部门控后执行。

    硬门控通过后，由 relevance score 直接映射为触发概率，而不是 score+随机扰动
    与固定阈值比较，避免 cooldown 后近似必触发。
    """

    def __init__(
        self,
        *,
        min_cooldown_seconds: float = 20.0,
        rng: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._min_cooldown_seconds = max(0.0, float(min_cooldown_seconds))
        self._rng = rng
        self._clock = clock

    def evaluate(
        self,
        event: ResponseCandidateEvent,
        *,
        running: bool,
        model_enabled: bool,
        chat_in_flight: bool,
        last_spoke_at: float | None,
        session: VirtualHostSession,
        now: float | None = None,
    ) -> ScheduleDecision:
        current = self._clock() if now is None else float(now)
        if not running:
            return ScheduleDecision(False, 0.0, "runtime_stopped")
        if not model_enabled:
            return ScheduleDecision(False, 0.0, "model_disabled")
        if chat_in_flight:
            return ScheduleDecision(False, 0.0, "chat_in_flight")
        if last_spoke_at is not None and current - float(last_spoke_at) < self._min_cooldown_seconds:
            return ScheduleDecision(False, 0.0, "cooldown")

        relevance = self._relevance_score(event, session=session, now=current)
        if relevance <= 0.0:
            return ScheduleDecision(False, 0.0, "no_context")

        probability = min(1.0, max(0.0, relevance))
        roll = float(self._rng())
        if roll >= probability:
            return ScheduleDecision(False, relevance, "probability_miss")
        return ScheduleDecision(True, relevance, "probability_hit")

    def _relevance_score(
        self,
        event: ResponseCandidateEvent,
        *,
        session: VirtualHostSession,
        now: float,
    ) -> float:
        context = self._context_score(session, now=now)
        if context <= 0.0:
            return 0.0
        event_score = self._event_score(event, session=session, now=now)
        return min(1.0, context + event_score)

    def _context_score(self, session: VirtualHostSession, *, now: float) -> float:
        batches = session.recent_batches(now=now)
        line_count = sum(len(batch.lines) for batch in batches)
        scene = session.current_scene_context(now=now)
        score = 0.0
        if line_count > 0:
            score += min(0.15, 0.03 * line_count)
        if scene is not None and scene.has_semantic_context:
            score += 0.1
        return score

    def _event_score(
        self,
        event: ResponseCandidateEvent,
        *,
        session: VirtualHostSession,
        now: float,
    ) -> float:
        if event.kind == "danmu_batch":
            batches = session.recent_batches(now=now)
            if event.batch_id:
                matched = next((batch for batch in batches if batch.batch_id == event.batch_id), None)
                if matched is not None:
                    return min(0.2, 0.04 * len(matched.lines))
            return min(0.15, 0.03 * sum(len(batch.lines) for batch in batches))
        if event.kind == "scene_change":
            scene = session.current_scene_context(now=now)
            if scene is None:
                return 0.0
            keyword_bonus = min(0.1, 0.02 * len(scene.keywords))
            summary_bonus = 0.35 if scene.summary else 0.0
            return summary_bonus + keyword_bonus
        return 0.0


def build_autonomous_input(session: VirtualHostSession, *, now: float | None = None) -> str:
    """为自主轮次构造 HOST_INPUT：简短语义指令，不重复复制弹幕正文。"""

    current = time.time() if now is None else float(now)
    line_count = sum(len(batch.lines) for batch in session.recent_batches(now=current))
    if line_count > 0:
        return "观众发来新弹幕，请根据当前弹幕与画面自然接话。"
    scene = session.current_scene_context(now=current)
    if scene is not None and scene.summary:
        return "画面有更新，请根据当前画面自然接话。"
    return "请根据当前直播情境自然接话。"


__all__ = [
    "ResponseCandidateEvent",
    "ScheduleDecision",
    "VirtualHostResponseScheduler",
    "build_autonomous_input",
]
