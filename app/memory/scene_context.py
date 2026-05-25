"""Scene-bound context memory (not conversation history)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.memory.types import (
    OPEN_THREADS_MAX,
    SCENE_SUMMARY_MAX_LEN,
    STABLE_CONFIDENCE_THRESHOLD,
    STABLE_FACTS_MAX,
    VOLATILE_FACTS_MAX,
    VisualMemoryUpdate,
)


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _append_unique_capped(items: list[str], incoming: list[str], *, limit: int) -> list[str]:
    out = list(items)
    seen = {x for x in out}
    for raw in incoming:
        value = (raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
        if len(out) > limit:
            out = out[-limit:]
    return out


@dataclass
class SceneContextMemory:
    scene_generation: int = 0
    scene_type: str = ""
    scene_summary: str = ""
    stable_facts: list[str] = field(default_factory=list)
    volatile_facts: list[str] = field(default_factory=list)
    open_threads: list[str] = field(default_factory=list)
    last_focus: str = ""
    confidence: float = 0.0
    tone_hint: str = ""
    updated_at: float = 0.0

    def is_empty(self) -> bool:
        return not (
            self.scene_type
            or self.scene_summary
            or self.stable_facts
            or self.volatile_facts
            or self.open_threads
            or self.last_focus
        )

    def merge_visual_update(self, update: VisualMemoryUpdate) -> None:
        if update.scene_type:
            self.scene_type = update.scene_type.strip()
        if update.scene_summary:
            self.scene_summary = _truncate(update.scene_summary, SCENE_SUMMARY_MAX_LEN)
        if update.stable_facts:
            self.stable_facts = _append_unique_capped(
                self.stable_facts, update.stable_facts, limit=STABLE_FACTS_MAX
            )
        if update.volatile_facts:
            self.volatile_facts = _append_unique_capped(
                self.volatile_facts, update.volatile_facts, limit=VOLATILE_FACTS_MAX
            )
        if update.open_threads:
            self.open_threads = _append_unique_capped(
                self.open_threads, update.open_threads, limit=OPEN_THREADS_MAX
            )
        if update.last_focus:
            self.last_focus = _truncate(update.last_focus, SCENE_SUMMARY_MAX_LEN)
        if update.confidence > 0:
            self.confidence = max(self.confidence, min(1.0, update.confidence))
        self.updated_at = time.monotonic()

    def carryover_summary_line(self) -> str:
        if self.scene_summary:
            return self.scene_summary
        if self.last_focus:
            return self.last_focus
        if self.stable_facts:
            return self.stable_facts[-1]
        return ""

    def filter_stable_for_medium(self) -> list[str]:
        if self.confidence >= STABLE_CONFIDENCE_THRESHOLD:
            return list(self.stable_facts)
        return [f for f in self.stable_facts if len(f) <= SCENE_SUMMARY_MAX_LEN]

    def reset_for_generation(
        self,
        scene_generation: int,
        *,
        tone_hint: str = "",
        scene_type: str = "",
        scene_summary: str = "",
        stable_facts: list[str] | None = None,
        volatile_facts: list[str] | None = None,
        open_threads: list[str] | None = None,
        last_focus: str = "",
        confidence: float = 0.0,
    ) -> None:
        self.scene_generation = scene_generation
        self.scene_type = scene_type
        self.scene_summary = scene_summary
        self.stable_facts = list(stable_facts or [])
        self.volatile_facts = list(volatile_facts or [])
        self.open_threads = list(open_threads or [])
        self.last_focus = last_focus
        self.confidence = confidence
        self.tone_hint = tone_hint
        self.updated_at = time.monotonic() if not self.is_empty() else 0.0

    def empty_clone(self, scene_generation: int, *, tone_hint: str = "") -> SceneContextMemory:
        return SceneContextMemory(scene_generation=scene_generation, tone_hint=tone_hint)
