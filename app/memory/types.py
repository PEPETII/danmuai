"""Types and config helpers for scene memory."""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_BULLET_SNIPPET_LEN = 15
DEFAULT_MEMORY_WINDOW = 10
MEMORY_WINDOW_MIN = 1
MEMORY_WINDOW_MAX = 20

MEMORY_MODES = frozenset({"off", "dedup_only", "scene_card", "strong"})
MEMORY_MODE_OFF = "off"
MEMORY_MODE_DEDUP_ONLY = "dedup_only"
MEMORY_MODE_SCENE_CARD = "scene_card"
MEMORY_MODE_STRONG = "strong"

STABLE_FACTS_MAX = 5
VOLATILE_FACTS_MAX = 8
OPEN_THREADS_MAX = 4
SCENE_SUMMARY_MAX_LEN = 40
STABLE_CONFIDENCE_THRESHOLD = 0.6
INFERRED_CONFIDENCE = 0.4


def clamp_memory_window(raw: int | str | None, *, default: int = DEFAULT_MEMORY_WINDOW) -> int:
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return max(MEMORY_WINDOW_MIN, min(value, MEMORY_WINDOW_MAX))


def memory_window_from_config(config) -> int:
    return clamp_memory_window(config.get("memory_window", ""), default=DEFAULT_MEMORY_WINDOW)


def bullet_angle_from_index(content_index: int, scene_count: int) -> str:
    if content_index < scene_count:
        return f"scene_{content_index}"
    return f"filler_{content_index - scene_count}"


@dataclass
class VisualMemoryUpdate:
    scene_generation: int
    scene_type: str = ""
    scene_summary: str = ""
    stable_facts: list[str] = field(default_factory=list)
    volatile_facts: list[str] = field(default_factory=list)
    open_threads: list[str] = field(default_factory=list)
    last_focus: str = ""
    confidence: float = INFERRED_CONFIDENCE


@dataclass
class DisplayedBullet:
    text: str
    angle: str = ""
    recorded_at: float = 0.0
