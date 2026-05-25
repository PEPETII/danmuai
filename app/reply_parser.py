from __future__ import annotations

import json
import random
from typing import TYPE_CHECKING

from app.danmu_pool import load_danmu_pool_for_config, sample_danmu_for_config
from app.translations import tr

if TYPE_CHECKING:
    from app.memory.types import VisualMemoryUpdate

_LEGACY_SCENE_FILLERS = (
    "reply.scene_filler_1",
    "reply.scene_filler_2",
)
_LEGACY_GENERIC_FILLERS = (
    "reply.generic_filler_1",
    "reply.generic_filler_2",
    "reply.generic_filler_3",
)


def _legacy_scene_fillers() -> list[str]:
    return [tr(key) for key in _LEGACY_SCENE_FILLERS]


def _legacy_generic_fillers() -> list[str]:
    return [tr(key) for key in _LEGACY_GENERIC_FILLERS]


def _scene_fillers(config=None) -> list[str]:
    pool = load_danmu_pool_for_config(config)
    if pool:
        return sample_danmu_for_config(config, min(32, len(pool)), rng=random)
    return _legacy_scene_fillers()


def _generic_fillers(config=None) -> list[str]:
    pool = load_danmu_pool_for_config(config)
    if pool:
        return sample_danmu_for_config(config, min(48, len(pool)), rng=random)
    return _legacy_generic_fillers()


def _try_parse_json_array(raw: str):
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return parsed
    if "][" in raw:
        head = raw.split("][", 1)[0] + "]"
        try:
            parsed = json.loads(head)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list):
            return parsed
    return None


def parse_ai_reply_with_memory(
    text: str,
    scene_generation: int = 0,
) -> tuple[list[str], VisualMemoryUpdate | None]:
    from app.memory.visual_update import (
        extract_comments_from_envelope,
        parse_scene_memory_envelope,
        visual_update_from_dict,
    )

    raw = str(text or "").strip()
    if not raw:
        return [], None

    parsed = None
    memory_update: VisualMemoryUpdate | None = None

    if raw.startswith("[") or raw.startswith("{"):
        if raw.startswith("["):
            parsed = _try_parse_json_array(raw)
        else:
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = None

    if isinstance(parsed, dict):
        envelope_comments = extract_comments_from_envelope(parsed)
        if envelope_comments is not None:
            candidates = envelope_comments
        else:
            for key in ("comments", "replies", "items", "data"):
                value = parsed.get(key)
                if isinstance(value, list):
                    candidates = value
                    break
            else:
                candidates = []
        memory_update = parse_scene_memory_envelope(parsed)
        if memory_update is None and isinstance(parsed.get("scene_memory"), dict):
            memory_update = visual_update_from_dict(parsed["scene_memory"], scene_generation)
        if memory_update is not None and memory_update.scene_generation <= 0:
            memory_update.scene_generation = scene_generation
    elif isinstance(parsed, list):
        candidates = parsed
    else:
        candidates = [
            part.strip(" -\t\r\n")
            for part in raw.replace("\r", "\n").split("\n")
            if part.strip()
        ]

    normalized: list[str] = []
    for item in candidates:
        value = str(item).strip().strip('"').strip("'")
        if value:
            normalized.append(value)
    return normalized, memory_update


def parse_ai_reply_payload(text: str) -> list[str]:
    items, _ = parse_ai_reply_with_memory(text)
    return items


def _append_next_unique_from_pool(
    result: list[str],
    seen: set[str],
    pool: list[str],
    cursor: list[int],
) -> bool:
    """Rotate pool once; append one unseen phrase. False if pool has no new phrase."""
    if not pool:
        return False
    n = len(pool)
    for _ in range(n):
        text = pool[cursor[0] % n]
        cursor[0] += 1
        if text in seen:
            continue
        seen.add(text)
        result.append(text)
        return True
    return False


def normalize_reply_batch(
    items: list[str],
    scene_count: int = 2,
    filler_count: int = 3,
    *,
    allow_shortfall: bool = False,
    config=None,
) -> list[str]:
    scene_count = max(1, int(scene_count))
    filler_count = max(1, int(filler_count))
    desired_count = scene_count + filler_count

    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)

    result = cleaned[:desired_count]
    scene_fillers = _scene_fillers(config)
    generic_fillers = _generic_fillers(config)

    if allow_shortfall:
        seen = set(result)
        scene_cursor = [0]
        while len(result) < min(scene_count, desired_count):
            if not _append_next_unique_from_pool(result, seen, scene_fillers, scene_cursor):
                break
        generic_cursor = [0]
        while len(result) < desired_count:
            if not _append_next_unique_from_pool(result, seen, generic_fillers, generic_cursor):
                break
        return result

    while len(result) < min(scene_count, desired_count):
        pool_index = min(len(result), len(scene_fillers) - 1)
        result.append(scene_fillers[pool_index])
    while len(result) < desired_count:
        filler_index = len(result) - scene_count
        pool_index = min(filler_index, len(generic_fillers) - 1)
        result.append(generic_fillers[pool_index])
    return result[:desired_count]
