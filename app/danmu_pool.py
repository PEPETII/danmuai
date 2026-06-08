"""公式化弹幕库：SQLite 自定义句；供 on-screen 补足与 normalize_reply_batch 填充。

开关与 min_on_screen 经 /api/danmu-pool/* 写入（见 web_api/danmu_pool.py），不在 PUT /api/config 全量表单内。
自定义库开启且 min_on_screen>0 时，main._maybe_pool_topup 从自定义池抽样补足同屏密度。
"""

from __future__ import annotations

import random


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
    getter = getattr(config, "get_custom_danmu_pool", None)
    if callable(getter):
        items = getter()
    else:
        raw = config.get_json("custom_danmu_pool", []) if hasattr(config, "get_json") else []
        items = raw if isinstance(raw, list) else []
    return _dedupe_lines(str(item) for item in items)


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
    return text in set(getter())


def is_stored_meme_barrage_text(config, content: str) -> bool:
    """True when content exactly matches a saved meme barrage library line."""
    if config is None:
        return False
    text = str(content).strip()
    if not text:
        return False
    checker = getattr(config, "meme_barrage_library_contains_text", None)
    if not callable(checker):
        return False
    return bool(checker(text))


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
    if getattr(engine, "entry_zone_overloaded", lambda: False)():
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
