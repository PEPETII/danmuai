"""Scene memory store: context + bullet dedup."""

from __future__ import annotations

from app.memory.bullet_dedup import BulletDedupMemory
from app.memory.scene_context import SceneContextMemory
from app.memory.types import (
    INFERRED_CONFIDENCE,
    OPEN_THREADS_MAX,
    STABLE_CONFIDENCE_THRESHOLD,
    VisualMemoryUpdate,
)


class SceneMemoryStore:
    def __init__(self) -> None:
        self._context = SceneContextMemory(scene_generation=0)
        self._dedup = BulletDedupMemory()

    @property
    def context(self) -> SceneContextMemory:
        return self._context

    @property
    def dedup(self) -> BulletDedupMemory:
        return self._dedup

    @property
    def generation(self) -> int:
        return self._context.scene_generation

    def reset(self) -> None:
        self._context = SceneContextMemory(scene_generation=0)
        self._dedup.clear()

    def update_from_visual_result(self, update: VisualMemoryUpdate) -> None:
        if update.scene_generation != self._context.scene_generation:
            return
        self._context.merge_visual_update(update)

    def record_displayed_bullet(
        self,
        content: str,
        scene_generation: int,
        *,
        window: int = 10,
        angle: str = "",
    ) -> None:
        if scene_generation != self._context.scene_generation:
            return
        self._dedup.record(content, angle=angle, window=window)

    def on_scene_change(
        self,
        new_generation: int,
        policy: str,
        *,
        tone_hint: str = "",
        memory_window: int = 10,
        memory_mode: str = "scene_card",
    ) -> None:
        prev = self._context
        preserved_tone = tone_hint or prev.tone_hint
        policy = (policy or "medium").strip().lower()

        if policy == "strict":
            self._context = SceneContextMemory(
                scene_generation=new_generation,
                tone_hint=preserved_tone,
            )
            self._dedup.clear()
            return

        if policy == "medium":
            stable = prev.filter_stable_for_medium()
            if (
                memory_mode == "strong"
                and not stable
                and prev.carryover_summary_line()
            ):
                stable = [prev.carryover_summary_line()]
                conf = INFERRED_CONFIDENCE
            else:
                conf = prev.confidence if stable else 0.0
            self._context.reset_for_generation(
                new_generation,
                tone_hint=preserved_tone,
                stable_facts=stable,
                confidence=conf,
            )
            self._dedup.clear()
            return

        # loose
        carry = prev.carryover_summary_line()
        stable = list(prev.stable_facts) or (
            [carry] if carry and prev.confidence >= STABLE_CONFIDENCE_THRESHOLD else []
        )
        threads = list(prev.open_threads[-OPEN_THREADS_MAX:])
        self._context.reset_for_generation(
            new_generation,
            tone_hint=preserved_tone,
            scene_summary=carry,
            stable_facts=stable,
            open_threads=threads,
            last_focus=prev.last_focus if prev.last_focus else carry,
            confidence=prev.confidence if stable else INFERRED_CONFIDENCE,
        )
        keep_bullets = min(3, memory_window) if memory_window > 0 else 0
        self._dedup.trim_to(keep_bullets)

    def format_prompt_for_generation(
        self,
        scene_generation: int,
        memory_mode: str,
    ) -> str:
        if scene_generation != self._context.scene_generation:
            return ""
        from app.memory_prompt_builder import build_memory_prompt_block

        return build_memory_prompt_block(self._context, self._dedup, memory_mode)
