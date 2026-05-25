"""Parse optional AI scene_memory envelope and infer updates from reply batches."""

from __future__ import annotations

from app.memory.types import (
    INFERRED_CONFIDENCE,
    MAX_BULLET_SNIPPET_LEN,
    SCENE_SUMMARY_MAX_LEN,
    VisualMemoryUpdate,
)


def _truncate(text: str, max_len: int) -> str:
    text = (text or "").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len]


def _coerce_str_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        text = str(item).strip()
        if text:
            out.append(_truncate(text, SCENE_SUMMARY_MAX_LEN))
    return out


def visual_update_from_dict(data: dict, scene_generation: int) -> VisualMemoryUpdate | None:
    if not isinstance(data, dict):
        return None
    return VisualMemoryUpdate(
        scene_generation=scene_generation,
        scene_type=str(data.get("scene_type", "") or "").strip(),
        scene_summary=_truncate(str(data.get("scene_summary", "") or ""), SCENE_SUMMARY_MAX_LEN),
        stable_facts=_coerce_str_list(data.get("stable_facts")),
        volatile_facts=_coerce_str_list(data.get("volatile_facts")),
        open_threads=_coerce_str_list(data.get("open_threads")),
        last_focus=_truncate(str(data.get("last_focus", "") or ""), SCENE_SUMMARY_MAX_LEN),
        confidence=float(data.get("confidence", 0.7) or 0.7),
    )


def parse_scene_memory_envelope(parsed: dict) -> VisualMemoryUpdate | None:
    """Extract scene_memory from a parsed top-level JSON object."""
    if not isinstance(parsed, dict):
        return None
    raw = parsed.get("scene_memory")
    if not isinstance(raw, dict):
        return None
    gen = int(raw.get("scene_generation", 0) or 0)
    return visual_update_from_dict(raw, gen)


def infer_visual_update_from_batch(
    items: list[str],
    scene_count: int,
    scene_generation: int,
) -> VisualMemoryUpdate | None:
    """Derive a low-confidence scene update from normalized reply slots (no regex topics)."""
    if not items or scene_count < 1:
        return None
    scene_slots = items[:scene_count]
    if not any(s.strip() for s in scene_slots):
        return None
    first = _truncate(scene_slots[0], SCENE_SUMMARY_MAX_LEN)
    volatile = [
        _truncate(s, MAX_BULLET_SNIPPET_LEN) for s in scene_slots if (s or "").strip()
    ]
    last_focus = _truncate(scene_slots[-1], SCENE_SUMMARY_MAX_LEN) if scene_slots else ""
    return VisualMemoryUpdate(
        scene_generation=scene_generation,
        scene_summary=first,
        volatile_facts=volatile,
        last_focus=last_focus,
        confidence=INFERRED_CONFIDENCE,
    )


def extract_comments_from_envelope(parsed: dict) -> list[str] | None:
    """Return comment list from envelope dict, or None if not an envelope."""
    if not isinstance(parsed, dict):
        return None
    for key in ("comments", "replies", "items", "data"):
        value = parsed.get(key)
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()]
    return None
