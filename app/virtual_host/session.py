"""虚拟主播独立会话与上下文编排。"""

from __future__ import annotations

import time
import uuid
from collections import OrderedDict
from typing import Any, Callable

from app.virtual_host.contracts import (
    BatchAcceptance,
    ConversationTurn,
    DanmuBatchCreated,
    HostPrompt,
    HostTurn,
    HostTurnResult,
    KnowledgeContextResult,
    SceneContext,
)


class VirtualHostSession:
    """不拥有模型、线程、窗口或播放器的虚拟主播会话。

    人格在构造时选择一次；批次和画面上下文只在当前 scene generation 且未过期
    时进入新轮次。该类不执行 ``HostTurnResult.actions``，动作消费由后续运行时
    工单负责。
    """

    def __init__(
        self,
        persona_manager: Any | None = None,
        *,
        persona_name: str | None = None,
        session_id: str | None = None,
        clock: Callable[[], float] = time.time,
        max_batches: int = 3,
        batch_char_budget: int = 600,
        max_history_turns: int = 8,
    ) -> None:
        self.session_id = str(session_id or uuid.uuid4().hex)
        if not self.session_id.strip():
            raise ValueError("session_id must not be empty")
        self._clock = clock
        self._persona_manager = persona_manager
        self._persona_id = self._select_persona(persona_name)
        self._persona_system, self._persona_user = self._load_persona_prompt()
        self._next_turn_id = 1
        self._max_batches = max(1, min(int(max_batches), 3))
        self._batch_char_budget = max(1, int(batch_char_budget))
        self._max_history_turns = max(1, int(max_history_turns))
        self._batches: OrderedDict[str, DanmuBatchCreated] = OrderedDict()
        self._seen_batch_ids: set[str] = set()
        self._scene_context: SceneContext | None = None
        self._scene_generation: int | None = None
        self._history: list[ConversationTurn] = []
        self._last_batch_acceptance = BatchAcceptance(False, "empty")

    @property
    def persona_id(self) -> str:
        return self._persona_id

    @property
    def turn_id(self) -> int:
        return self._next_turn_id

    @property
    def last_batch_acceptance(self) -> BatchAcceptance:
        return self._last_batch_acceptance

    @property
    def history(self) -> tuple[ConversationTurn, ...]:
        return tuple(self._history)

    def _select_persona(self, requested: str | None) -> str:
        if requested and str(requested).strip():
            return str(requested).strip()
        manager = self._persona_manager
        if manager is not None:
            pick = getattr(manager, "pick_random", None)
            if callable(pick):
                selected = str(pick() or "").strip()
                if selected:
                    return selected
            get_active = getattr(manager, "get_active", None)
            if callable(get_active):
                active = list(get_active() or [])
                if active and str(active[0]).strip():
                    return str(active[0]).strip()
        return "default"

    def _load_persona_prompt(self) -> tuple[str, str]:
        getter = getattr(self._persona_manager, "get_prompt", None)
        if not callable(getter):
            return "", ""
        system_prompt, user_prompt = getter(self._persona_id)
        return str(system_prompt or "").strip(), str(user_prompt or "").strip()

    def update_scene_context(self, context: SceneContext) -> bool:
        """更新画面上下文；较旧 generation 不得覆盖当前上下文。"""

        if not isinstance(context, SceneContext):
            raise TypeError("context must be SceneContext")
        if self._scene_generation is not None and context.scene_generation < self._scene_generation:
            return False
        self._scene_context = context
        self._scene_generation = context.scene_generation
        self._prune_batches(now=self._clock())
        return True

    def current_scene_context(self, *, now: float | None = None) -> SceneContext | None:
        context = self._scene_context
        if context is None:
            return None
        current = self._clock() if now is None else now
        if not context.is_fresh(scene_generation=self._scene_generation, now=current):
            return None
        return context

    def ingest_danmu_batch(
        self,
        batch: DanmuBatchCreated,
        *,
        current_scene_generation: int | None = None,
        now: float | None = None,
    ) -> BatchAcceptance:
        current = self._clock() if now is None else float(now)
        if not isinstance(batch, DanmuBatchCreated):
            decision = BatchAcceptance(False, "invalid")
        elif not batch.lines:
            decision = BatchAcceptance(False, "empty", batch.batch_id)
        elif batch.batch_id in self._seen_batch_ids:
            decision = BatchAcceptance(False, "duplicate", batch.batch_id)
        elif batch.is_expired(now=current):
            decision = BatchAcceptance(False, "expired", batch.batch_id)
        else:
            expected_generation = (
                self._scene_generation
                if current_scene_generation is None
                else int(current_scene_generation)
            )
            if expected_generation is not None and batch.scene_generation != expected_generation:
                decision = BatchAcceptance(False, "scene_generation", batch.batch_id)
            else:
                if batch.char_count > self._batch_char_budget:
                    batch = DanmuBatchCreated.from_lines(
                        batch_id=batch.batch_id,
                        lines=batch.lines,
                        created_at=batch.created_at,
                        source=batch.source,
                        screenshot_id=batch.screenshot_id,
                        scene_generation=batch.scene_generation,
                        ttl_seconds=batch.ttl_seconds,
                        char_budget=self._batch_char_budget,
                    )
                if not batch.lines:
                    decision = BatchAcceptance(False, "empty", batch.batch_id)
                    self._last_batch_acceptance = decision
                    return decision
                self._batches[batch.batch_id] = batch
                self._seen_batch_ids.add(batch.batch_id)
                self._prune_batches(now=current)
                decision = BatchAcceptance(True, "accepted", batch.batch_id)
        self._last_batch_acceptance = decision
        return decision

    def accept_danmu_batch(
        self,
        batch: DanmuBatchCreated,
        *,
        current_scene_generation: int | None = None,
        now: float | None = None,
    ) -> bool:
        return self.ingest_danmu_batch(
            batch,
            current_scene_generation=current_scene_generation,
            now=now,
        ).accepted

    def recent_batches(self, *, now: float | None = None) -> tuple[DanmuBatchCreated, ...]:
        self._prune_batches(now=self._clock() if now is None else float(now))
        return tuple(self._batches.values())

    def _prune_batches(self, *, now: float) -> None:
        for batch_id, batch in list(self._batches.items()):
            if batch.is_expired(now=now) or (
                self._scene_generation is not None
                and batch.scene_generation != self._scene_generation
            ):
                self._batches.pop(batch_id, None)
        while len(self._batches) > self._max_batches:
            self._batches.popitem(last=False)
        while sum(batch.char_count for batch in self._batches.values()) > self._batch_char_budget:
            if not self._batches:
                break
            self._batches.popitem(last=False)

    def start_turn(
        self,
        input_text: str,
        *,
        mic_text: str = "",
        live_topic: str = "",
        scene_context: SceneContext | None = None,
        include_recent_batches: bool = True,
        now: float | None = None,
    ) -> HostTurn:
        current = self._clock() if now is None else float(now)
        if scene_context is not None:
            self.update_scene_context(scene_context)
        turn = HostTurn(
            session_id=self.session_id,
            turn_id=self._next_turn_id,
            created_at=current,
            input_text=" ".join(str(input_text or "").split()),
            mic_text=" ".join(str(mic_text or "").split()),
            live_topic=" ".join(str(live_topic or "").split()),
            scene_context=self.current_scene_context(now=current),
            recent_batches=(self.recent_batches(now=current) if include_recent_batches else ()),
            history=tuple(self._history),
        )
        self._next_turn_id += 1
        return turn

    def compose_prompt(
        self,
        turn: HostTurn,
        *,
        knowledge: KnowledgeContextResult | None = None,
        now: float | None = None,
    ) -> HostPrompt:
        if turn.session_id != self.session_id:
            raise ValueError("turn belongs to another session")
        active_knowledge = knowledge or KnowledgeContextResult(
            status="unavailable",
            diagnostic="knowledge_not_requested",
        )
        active_scene = turn.scene_context
        if active_scene is not None and not active_scene.is_fresh(
            scene_generation=self._scene_generation,
            now=self._clock() if now is None else now,
        ):
            active_scene = None
        history_text = "\n".join(
            f"turn {item.turn_id}: user={item.user_text} assistant={item.assistant_text}"
            for item in turn.history
        )
        return HostPrompt(
            persona_system=self._persona_system,
            persona_user=self._persona_user,
            session_context=history_text,
            scene_context=(active_scene.summary if active_scene else ""),
            danmu_context=tuple(
                line for batch in turn.recent_batches if batch.is_current(
                    scene_generation=self._scene_generation,
                    now=self._clock() if now is None else now,
                ) for line in batch.lines
            ),
            knowledge=active_knowledge,
            current_input=turn.input_text,
        )

    def complete_turn(self, turn: HostTurn, result: HostTurnResult) -> HostTurnResult:
        """记录文本连续性；动作/记忆效果只作为结构化数据保留，不执行。"""

        if turn.session_id != self.session_id or result.session_id != self.session_id:
            raise ValueError("turn/result belongs to another session")
        if result.turn_id != turn.turn_id:
            raise ValueError("result turn_id does not match turn")
        self._history.append(
            ConversationTurn(
                turn_id=turn.turn_id,
                user_text=turn.input_text,
                assistant_text=result.text,
            )
        )
        del self._history[: max(0, len(self._history) - self._max_history_turns)]
        return result
