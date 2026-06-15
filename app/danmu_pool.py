"""公式化弹幕库：SQLite 自定义句；供 on-screen 补足与 normalize_reply_batch 填充。

开关与 min_on_screen 经 /api/danmu-pool/* 写入（见 web_api/danmu_pool.py），不在 PUT /api/config 全量表单内。
自定义库开启且 min_on_screen>0 时，main._maybe_pool_topup 从自定义池抽样补足同屏密度。
"""

from __future__ import annotations

import random
from typing import Any

# 按 config 实例缓存公式化句集合；池/烂梗库写入后须 invalidate_formula_text_cache。
_formula_custom_sets: dict[int, set[str]] = {}
_formula_meme_sets: dict[int, set[str]] = {}
_custom_pool_lists: dict[int, list[str]] = {}


def danmu_pool_use_custom_from_config(config) -> bool:
    """True when custom formula pool is enabled (default off if unset)."""
    raw = config.get("danmu_pool_use_custom", "")
    if raw in ("", None):
        return False
    return str(raw).strip() != "0"


def any_danmu_pool_source_enabled(config) -> bool:
    """True when custom formula pool is enabled."""
    if config is None:
        return False
    return danmu_pool_use_custom_from_config(config)


def pool_enabled(config) -> bool:
    if config is None:
        return False
    return any_danmu_pool_source_enabled(config)


def effective_min_on_screen(config) -> int:
    """Formula top-up target; 0 when custom pool is disabled."""
    if not any_danmu_pool_source_enabled(config):
        return 0
    return max(0, config.get_int("min_on_screen", 5))


def load_custom_danmu_pool(config) -> list[str]:
    if config is None or not danmu_pool_use_custom_from_config(config):
        return []
    key = id(config)
    cached = _custom_pool_lists.get(key)
    if cached is not None:
        return cached
    getter = getattr(config, "get_custom_danmu_pool", None)
    if callable(getter):
        items = getter()
    else:
        raw = config.get_json("custom_danmu_pool", []) if hasattr(config, "get_json") else []
        items = raw if isinstance(raw, list) else []
    result = _dedupe_lines(str(item) for item in items)
    _custom_pool_lists[key] = result
    return result


def load_danmu_pool_for_config(config) -> list[str]:
    if not pool_enabled(config):
        return []
    return load_custom_danmu_pool(config)


def sample_danmu_for_config(
    config,
    count: int,
    *,
    rng: random.Random | None = None,
) -> list[str]:
    if not pool_enabled(config) or count <= 0:
        return []
    pool = load_danmu_pool_for_config(config)
    if not pool:
        return []
    rng = rng or random
    if count >= len(pool):
        return rng.sample(pool, len(pool))
    return rng.sample(pool, count)


def _dedupe_lines(lines) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        text = str(raw).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def custom_pool_size(config) -> int:
    return len(load_custom_danmu_pool(config))


def invalidate_formula_text_cache(config: Any | None = None) -> None:
    """Drop cached formula-text sets after custom pool or meme library writes."""
    if config is None:
        _formula_custom_sets.clear()
        _formula_meme_sets.clear()
        _custom_pool_lists.clear()
        return
    key = id(config)
    _formula_custom_sets.pop(key, None)
    _formula_meme_sets.pop(key, None)
    _custom_pool_lists.pop(key, None)


def _custom_pool_text_set(config) -> set[str]:
    key = id(config)
    cached = _formula_custom_sets.get(key)
    if cached is not None:
        return cached
    getter = getattr(config, "get_custom_danmu_pool", None)
    if not callable(getter):
        cached = set()
    else:
        cached = {str(item).strip() for item in getter() if str(item).strip()}
    _formula_custom_sets[key] = cached
    return cached


def _meme_barrage_text_set(config) -> set[str]:
    key = id(config)
    cached = _formula_meme_sets.get(key)
    if cached is not None:
        return cached
    bulk = getattr(config, "meme_barrage_library_all_texts", None)
    if callable(bulk):
        cached = {str(t).strip() for t in bulk() if str(t).strip()}
    else:
        cached = set()
    _formula_meme_sets[key] = cached
    return cached


def is_stored_custom_pool_text(config, content: str) -> bool:
    """True when content exactly matches a saved custom pool line (full display, no truncation)."""
    if config is None:
        return False
    text = str(content).strip()
    if not text:
        return False
    getter = getattr(config, "get_custom_danmu_pool", None)
    if not callable(getter):
        return False
    return text in _custom_pool_text_set(config)


def is_stored_meme_barrage_text(config, content: str) -> bool:
    """True when content exactly matches a saved meme barrage library line."""
    if config is None:
        return False
    text = str(content).strip()
    if not text:
        return False
    if not callable(getattr(config, "meme_barrage_library_contains_text", None)) and not callable(
        getattr(config, "meme_barrage_library_all_texts", None)
    ):
        return False
    return text in _meme_barrage_text_set(config)


def is_formula_danmu_text(config, content: str) -> bool:
    """True when content is from formula sources (custom pool or meme barrage)."""
    return is_stored_custom_pool_text(config, content) or is_stored_meme_barrage_text(
        config, content
    )


def maybe_pool_topup(engine, config, scene_generation: int) -> int:
    """从自定义池抽样补足同屏密度。

    Returns the number of items actually added.
    """
    if not engine.running:
        return 0
    if not any_danmu_pool_source_enabled(config):
        return 0
    # W-DANMU-POOL-003: 用户配了 danmu_pending_entry_cap 时，避免入口区被池句占满
    entry_checker = getattr(engine, "entry_zone_overloaded", None)
    if callable(entry_checker) and entry_checker():
        return 0
    deficit = engine.deficit_below_min()
    if deficit <= 0:
        return 0
    limit = min(deficit, 8)
    texts = sample_danmu_for_config(config, limit)
    if not texts:
        return 0
    added = 0
    for text in texts:
        if added >= limit:
            break
        item = engine.add_text(
            text,
            persona="",
            batch_id=0,
            scene_generation=scene_generation,
            skip_dedup=True,
        )
        if item:
            added += 1
    return added
