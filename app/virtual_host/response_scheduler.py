"""虚拟主播自主回应调度：候选事件评分 + 门控，不保证每批弹幕都触发发言。"""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from app.virtual_host.contracts import normalize_text
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
    """纯逻辑调度器；HTTP / Session 写入由运行时在外部门控后执行。"""

    def __init__(
        self,
        *,
        min_cooldown_seconds: float = 20.0,
        score_threshold: float = 0.55,
        rng: Callable[[], float] = random.random,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._min_cooldown_seconds = max(0.0, float(min_cooldown_seconds))
        self._score_threshold = max(0.0, min(1.0, float(score_threshold)))
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

        context_score = self._context_score(session, now=current)
        if context_score <= 0.0:
            return ScheduleDecision(False, 0.0, "no_context")

        event_score = self._event_score(event, session=session, now=current)
        perturbation = float(self._rng()) * 0.35
        total = min(1.0, context_score + event_score + perturbation)
        if total < self._score_threshold:
            return ScheduleDecision(False, total, "below_threshold")
        return ScheduleDecision(True, total, "threshold_met")

    def _context_score(self, session: VirtualHostSession, *, now: float) -> float:
        batches = session.recent_batches(now=now)
        line_count = sum(len(batch.lines) for batch in batches)
        scene = session.current_scene_context(now=now)
        score = 0.0
        if line_count > 0:
            score += min(0.45, 0.08 * line_count)
        if scene is not None and scene.has_semantic_context:
            score += 0.2
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
                    return min(0.35, 0.07 * len(matched.lines))
            return min(0.25, 0.05 * sum(len(batch.lines) for batch in batches))
        if event.kind == "scene_change":
            scene = session.current_scene_context(now=now)
            if scene is None:
                return 0.0
            keyword_bonus = min(0.1, 0.02 * len(scene.keywords))
            summary_bonus = 0.2 if scene.summary else 0.0
            return summary_bonus + keyword_bonus
        return 0.0


def build_autonomous_input(session: VirtualHostSession, *, now: float | None = None) -> str:
    """为自主轮次构造 HOST_INPUT：优先近期弹幕，其次画面摘要。"""

    current = time.time() if now is None else float(now)
    lines: list[str] = []
    for batch in session.recent_batches(now=current):
        for line in batch.lines:
            text = normalize_text(line)
            if text and text not in lines:
                lines.append(text)
    if lines:
        return "\n".join(lines[:8])
    scene = session.current_scene_context(now=current)
    if scene is not None and scene.summary:
        return f"画面更新：{scene.summary}"
    return "自主回应"


__all__ = [
    "ResponseCandidateEvent",
    "ScheduleDecision",
    "VirtualHostResponseScheduler",
    "build_autonomous_input",
]
