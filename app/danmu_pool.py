"""公式化弹幕库：SQLite 自定义句；供 on-screen 补足与 normalize_reply_batch 填充。

开关与 min_on_screen 经 /api/danmu-pool/* 写入（见 web_api/danmu_pool.py），不在 PUT /api/config 全量表单内。
自定义库开启且 min_on_screen>0 时，main._maybe_pool_topup 从自定义池抽样补足同屏密度。
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time
from typing import Any

logger = logging.getLogger(__name__)

CUSTOM_DANMU_POOL_MAX = 20000

# 按 config 实例缓存烂梗库句集合；池/烂梗库写入后须 invalidate_formula_text_cache。
_formula_meme_sets: dict[int, set[str]] = {}


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
    """Load all custom pool texts (compat / empty-pool checks); prefer SQL facades in hot paths."""
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
    count_fn = getattr(config, "custom_danmu_count", None)
    if callable(count_fn) and count_fn() <= 0:
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
    sampler = getattr(config, "custom_danmu_random_sample", None)
    if callable(sampler):
        return sampler(count)
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
    counter = getattr(config, "custom_danmu_count", None)
    if callable(counter):
        return int(counter())
    return len(load_custom_danmu_pool(config))


def invalidate_formula_text_cache(config: Any | None = None) -> None:
    """Drop cached formula-text sets after custom pool or meme library writes."""
    if config is None:
        _formula_meme_sets.clear()
        return
    key = id(config)
    _formula_meme_sets.pop(key, None)


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
    contains = getattr(config, "custom_danmu_contains_text", None)
    if callable(contains):
        return bool(contains(text))
    getter = getattr(config, "get_custom_danmu_pool", None)
    if not callable(getter):
        return False
    return text in {str(item).strip() for item in getter() if str(item).strip()}


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


def _custom_danmu_count_locked(store, source: str | None = None) -> int:
    if source:
        row = store.conn.execute(
            "SELECT COUNT(*) FROM custom_danmu_pool_entries WHERE source = ?",
            (source,),
        ).fetchone()
    else:
        row = store.conn.execute("SELECT COUNT(*) FROM custom_danmu_pool_entries").fetchone()
    return 0 if not row or row[0] is None else int(row[0])


def migrate_custom_danmu_pool_json(store) -> None:
    if store.get("custom_danmu_pool_migrated") == "1":
        return
    with store._write_lock:
        if _custom_danmu_count_locked(store) > 0:
            pass
        else:
            raw = store.get_json("custom_danmu_pool", [])
            texts: list[str] = []
            if isinstance(raw, list):
                seen: set[str] = set()
                for item in raw:
                    text = str(item).strip()
                    if text and text not in seen:
                        seen.add(text)
                        texts.append(text)
            if texts:
                now = time.time()
                try:
                    store.conn.executemany(
                        "INSERT OR IGNORE INTO custom_danmu_pool_entries "
                        "(text, source, enabled, created_at, updated_at) "
                        "VALUES (?, 'manual', 1, ?, ?)",
                        [(text, now, now) for text in texts],
                    )
                    store.conn.commit()
                except sqlite3.Error:
                    store.conn.rollback()
                    logger.exception("custom_danmu_pool JSON migration failed")
                    return
    store.set("custom_danmu_pool_migrated", "1")


def custom_danmu_count_for_store(store, source: str | None = None) -> int:
    if not store._conn_usable():
        return 0
    try:
        with store._write_lock:
            return _custom_danmu_count_locked(store, source)
    except sqlite3.ProgrammingError:
        return 0


def custom_danmu_list_for_store(
    store,
    page: int = 1,
    page_size: int = 100,
    search: str = "",
    source: str | None = "manual",
) -> dict:
    page = max(1, int(page))
    page_size = max(1, min(200, int(page_size)))
    offset = (page - 1) * page_size
    clauses = ["enabled = 1"]
    params: list = []
    if source:
        clauses.append("source = ?")
        params.append(source)
    query = str(search or "").strip()
    if query:
        clauses.append("text LIKE ?")
        params.append(f"%{query}%")
    where = " AND ".join(clauses)
    total_row = store.conn.execute(
        f"SELECT COUNT(*) FROM custom_danmu_pool_entries WHERE {where}",
        params,
    ).fetchone()
    total = 0 if not total_row or total_row[0] is None else int(total_row[0])
    rows = store.conn.execute(
        f"SELECT id, text FROM custom_danmu_pool_entries WHERE {where} "
        "ORDER BY id ASC LIMIT ? OFFSET ?",
        [*params, page_size, offset],
    ).fetchall()
    items = [{"id": int(row[0]), "text": str(row[1])} for row in rows if row]
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "source": source or "",
    }


def custom_danmu_insert_many_for_store(
    store, texts: list[str], source: str = "manual"
) -> dict[str, int]:
    src = "import" if source == "import" else "manual"
    stats = {"added": 0, "skipped_duplicate": 0, "skipped_empty": 0, "skipped_limit": 0}
    now = time.time()
    batch: list[tuple[str, str, float, float]] = []
    seen: set[str] = set()
    with store._write_lock:
        room = max(0, CUSTOM_DANMU_POOL_MAX - _custom_danmu_count_locked(store))
        for raw in texts:
            text = str(raw).strip()
            if not text:
                stats["skipped_empty"] += 1
                continue
            if text in seen:
                stats["skipped_duplicate"] += 1
                continue
            seen.add(text)
            if len(batch) >= room:
                stats["skipped_limit"] += 1
                continue
            batch.append((text, src, now, now))
        if batch:
            before = store.conn.total_changes
            store.conn.executemany(
                "INSERT OR IGNORE INTO custom_danmu_pool_entries "
                "(text, source, enabled, created_at, updated_at) VALUES (?, ?, 1, ?, ?)",
                batch,
            )
            inserted = store.conn.total_changes - before
            stats["added"] = inserted
            stats["skipped_duplicate"] += len(batch) - inserted
            store.conn.commit()
    store._invalidate_formula_text_cache()
    return stats


def custom_danmu_delete_ids_for_store(store, ids: list[int]) -> int:
    clean = [int(i) for i in ids if int(i) > 0]
    if not clean:
        return 0
    placeholders = ",".join("?" for _ in clean)
    with store._write_lock:
        before = store.conn.total_changes
        store.conn.execute(
            f"DELETE FROM custom_danmu_pool_entries WHERE id IN ({placeholders})",
            clean,
        )
        removed = store.conn.total_changes - before
        store.conn.commit()
    if removed:
        store._invalidate_formula_text_cache()
    return removed


def custom_danmu_delete_texts_for_store(store, texts: list[str]) -> int:
    clean = [str(text).strip() for text in texts if str(text).strip()]
    if not clean:
        return 0
    placeholders = ",".join("?" for _ in clean)
    with store._write_lock:
        before = store.conn.total_changes
        store.conn.execute(
            f"DELETE FROM custom_danmu_pool_entries WHERE text IN ({placeholders})",
            clean,
        )
        removed = store.conn.total_changes - before
        store.conn.commit()
    if removed:
        store._invalidate_formula_text_cache()
    return removed


def custom_danmu_random_sample_for_store(store, count: int) -> list[str]:
    if count <= 0 or not store._conn_usable():
        return []
    try:
        rows = store.conn.execute(
            "SELECT text FROM custom_danmu_pool_entries "
            "WHERE enabled = 1 ORDER BY RANDOM() LIMIT ?",
            (int(count),),
        ).fetchall()
    except sqlite3.ProgrammingError:
        return []
    return [str(row[0]) for row in rows if row and row[0]]


def custom_danmu_contains_text_for_store(store, text: str) -> bool:
    value = str(text).strip()
    if not value:
        return False
    row = store.conn.execute(
        "SELECT 1 FROM custom_danmu_pool_entries WHERE text = ? LIMIT 1",
        (value,),
    ).fetchone()
    return row is not None


def get_custom_danmu_pool_for_store(store) -> list[str]:
    if not store._conn_usable():
        return []
    try:
        rows = store.conn.execute(
            "SELECT text FROM custom_danmu_pool_entries ORDER BY id ASC"
        ).fetchall()
    except sqlite3.ProgrammingError:
        return []
    return [str(row[0]).strip() for row in rows if row and row[0] and str(row[0]).strip()]


def set_custom_danmu_pool_for_store(store, items: list[str]) -> None:
    now = time.time()
    params: list[tuple[str, float, float]] = []
    seen: set[str] = set()
    for raw in items:
        text = str(raw).strip()
        if text and text not in seen:
            seen.add(text)
            params.append((text, now, now))
    with store._write_lock:
        store.conn.execute("DELETE FROM custom_danmu_pool_entries")
        if params:
            store.conn.executemany(
                "INSERT INTO custom_danmu_pool_entries "
                "(text, source, enabled, created_at, updated_at) VALUES (?, 'manual', 1, ?, ?)",
                params,
            )
        store.conn.commit()
    store._invalidate_formula_text_cache()
