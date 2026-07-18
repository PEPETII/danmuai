"""公式化弹幕库：SQLite 自定义句；供 on-screen 补足与 normalize_reply_batch 填充。

开关与 min_on_screen 经 /api/danmu-pool/* 写入（见 web_api/danmu_pool.py），不在 PUT /api/config 全量表单内。
自定义库开启且 min_on_screen>0 时，main._maybe_pool_topup 从自定义池抽样补足同屏密度。
plan_pool_topup 对引擎 duck-type：running + deficit_below_min()（DanmuEngine 与
FloatingPanelEngine 均提供）；可选 entry_zone_overloaded() 仅横向有。
实际上屏由 DanmuApp 按 danmu_render_mode 路由到 scrolling 或 floating_panel。
"""

from __future__ import annotations

import logging
import random
import sqlite3
import time
import weakref
from typing import Any

logger = logging.getLogger(__name__)

CUSTOM_DANMU_POOL_MAX = 20000
_TEXTS_BY_IDS_CHUNK = 500
_CUSTOM_POOL_PAGE_SIZE = 500

# 按 config 实例缓存烂梗库句集合；池/烂梗库写入后须 invalidate_formula_text_cache。
_formula_meme_sets: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
# 按 config 实例缓存自定义弹幕库句列表（兼容层）；池写入后须 invalidate_formula_text_cache。
_formula_custom_lists: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
# 按 config 实例缓存自定义弹幕库句集合（兼容层）；与 _formula_custom_lists 同步填充。
_formula_custom_sets: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
# 按 config 实例缓存 enabled 行 id 列表（F-P002/G-005 热路径抽样）。
_formula_custom_ids: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


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
    """Load all custom pool texts (compat / export only).

    Production hot paths should prefer ``custom_danmu_count``, paginated
    ``custom_danmu_list``, or id-based sampling instead of this full load.
    """
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
    return _sample_custom_pool_texts(config, 200)


def sample_danmu_for_config(
    config,
    count: int,
    *,
    rng: random.Random | None = None,
) -> list[str]:
    return _sample_custom_pool_texts(config, count, rng=rng)


def _custom_pool_text_list(config) -> list[str]:
    """Cached ordered list of all custom pool texts (compat / export only).

    Main-thread hot paths must not call this; use id cache + ``texts_by_ids`` or
    ``custom_danmu_random_sample`` for sampling instead.
    """
    cached = _formula_custom_lists.get(config)
    if cached is not None:
        return cached
    getter = getattr(config, "get_custom_danmu_pool", None)
    if callable(getter):
        cached = [str(t).strip() for t in getter() if str(t).strip()]
    else:
        raw = config.get_json("custom_danmu_pool", []) if hasattr(config, "get_json") else []
        items = raw if isinstance(raw, list) else []
        cached = _dedupe_lines(str(item) for item in items)
    _formula_custom_lists[config] = cached
    _formula_custom_sets[config] = set(cached)
    return cached


def _custom_pool_id_list(config) -> list[int]:
    """Cached enabled row ids for *config* (lightweight hot-path snapshot)."""
    cached = _formula_custom_ids.get(config)
    if cached is not None:
        return cached
    ids_getter = getattr(config, "custom_danmu_enabled_ids", None)
    if callable(ids_getter):
        cached = [int(i) for i in ids_getter() if int(i) > 0]
    else:
        cached = []
    _formula_custom_ids[config] = cached
    return cached


def _sample_custom_pool_texts(
    config,
    count: int,
    *,
    rng: random.Random | None = None,
) -> list[str]:
    """Sample up to *count* texts via id cache + batch text fetch (no full-table text load)."""
    if not pool_enabled(config) or count <= 0:
        return []
    count_fn = getattr(config, "custom_danmu_count", None)
    if callable(count_fn) and count_fn() <= 0:
        return []
    rng = rng or random

    ids = _custom_pool_id_list(config)
    if ids:
        n = min(count, len(ids))
        picked_ids = list(rng.sample(ids, n))
        fetcher = getattr(config, "custom_danmu_texts_by_ids", None)
        if callable(fetcher):
            return fetcher(picked_ids)
        return []

    # Fallback for configs without SQL id facades (FakeConfig / tests).
    sampler = getattr(config, "custom_danmu_random_sample", None)
    if callable(sampler):
        return sampler(count)

    pool = _custom_pool_text_list(config)
    if not pool:
        return []
    if count >= len(pool):
        return list(rng.sample(pool, len(pool)))
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
        _formula_custom_lists.clear()
        _formula_custom_sets.clear()
        _formula_custom_ids.clear()
        return
    _formula_meme_sets.pop(config, None)
    _formula_custom_lists.pop(config, None)
    _formula_custom_sets.pop(config, None)
    _formula_custom_ids.pop(config, None)


def _meme_barrage_text_set(config) -> set[str]:
    cached = _formula_meme_sets.get(config)
    if cached is not None:
        return cached
    bulk = getattr(config, "meme_barrage_library_all_texts", None)
    if callable(bulk):
        cached = {str(t).strip() for t in bulk() if str(t).strip()}
    else:
        cached = set()
    _formula_meme_sets[config] = cached
    return cached


def _custom_pool_text_set(config) -> set[str]:
    """Cached set of all enabled custom pool texts for *config*."""
    cached = _formula_custom_sets.get(config)
    if cached is not None:
        return cached
    return set(_custom_pool_text_list(config))


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
    conn_usable = getattr(config, "_conn_usable", None)
    if callable(conn_usable) and conn_usable():
        return custom_danmu_contains_text_for_store(config, text)
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


def _pool_entry_zone_overloaded(engine) -> bool:
    entry_checker = getattr(engine, "entry_zone_overloaded", None)
    return callable(entry_checker) and entry_checker()


def plan_pool_topup(engine, config) -> tuple[int, list[str]]:
    """规划同屏密度补池：返回 (limit, texts)，无补池时 limit=0。"""
    if not engine.running:
        return 0, []
    if not any_danmu_pool_source_enabled(config):
        return 0, []
    # W-DANMU-POOL-003: 用户配了 danmu_pending_entry_cap 时，避免入口区被池句占满
    if _pool_entry_zone_overloaded(engine):
        return 0, []
    deficit = engine.deficit_below_min()
    if deficit <= 0:
        return 0, []
    limit = min(deficit, 8)
    texts = sample_danmu_for_config(config, limit)
    if not texts:
        return 0, []
    return limit, texts


def plan_duplicate_loss_topup(
    engine,
    config,
    *,
    duplicate_loss_total: int,
    threshold: int = 2,
    limit: int = 3,
) -> list[str]:
    """规划 duplicate loss 补偿补池文本；无补偿时返回空列表。"""
    if duplicate_loss_total < max(1, int(threshold)):
        return []
    if not engine.running:
        return []
    if not any_danmu_pool_source_enabled(config):
        return []
    if _pool_entry_zone_overloaded(engine):
        return []
    return sample_danmu_for_config(config, max(1, int(limit)))


def maybe_pool_topup(engine, config, scene_generation: int) -> int:
    """从自定义池抽样补足同屏密度。

    Returns the number of items actually added.
    """
    limit, texts = plan_pool_topup(engine, config)
    if limit <= 0 or not texts:
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


def maybe_duplicate_loss_topup(
    engine,
    config,
    scene_generation: int,
    *,
    duplicate_loss_total: int,
    threshold: int = 2,
    limit: int = 3,
) -> int:
    """当单批 duplicate 损耗达到阈值时，额外做一次小剂量补偿。"""
    texts = plan_duplicate_loss_topup(
        engine,
        config,
        duplicate_loss_total=duplicate_loss_total,
        threshold=threshold,
        limit=limit,
    )
    if not texts:
        return 0
    added = 0
    for text in texts:
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
    # 持写锁迁移；store.set 必须在锁外（_write_lock 不可重入，W-AUDIT-V2-BUG-005）。
    with store._pool_write_lock:
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
    if not store._conn_usable():
        return {"items": [], "total": 0, "page": 1, "page_size": 100, "source": source or ""}
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
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        clauses.append("text LIKE ? ESCAPE '\\'")
        params.append(f"%{escaped}%")
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


def _existing_custom_texts_locked(store, texts: list[str]) -> set[str]:
    """在持锁上下文内，分块 IN 查询候选文本是否已存在于库。"""
    if not texts or not store._conn_usable():
        return set()
    existing: set[str] = set()
    for offset in range(0, len(texts), _TEXTS_BY_IDS_CHUNK):
        chunk = texts[offset : offset + _TEXTS_BY_IDS_CHUNK]
        placeholders = ",".join("?" for _ in chunk)
        rows = store.conn.execute(
            f"SELECT text FROM custom_danmu_pool_entries WHERE text IN ({placeholders})",
            chunk,
        ).fetchall()
        existing.update(
            str(row[0]).strip() for row in rows if row and row[0] and str(row[0]).strip()
        )
    return existing


def _commit_pool_write(conn, *, op: str) -> None:
    """Commit a custom-pool write; on failure rollback then re-raise.

    Mirrors the diff-setter contract: commit failure must not leave an active
    transaction that a later successful commit would flush. Rollback failure
    is logged and re-raised; the connection must not be treated as reusable.
    """
    try:
        conn.commit()
    except sqlite3.Error:
        try:
            conn.rollback()
        except sqlite3.Error:
            logger.exception(
                "custom_danmu_pool %s rollback failed after commit failure", op
            )
            raise
        raise


def custom_danmu_insert_many_for_store(
    store, texts: list[str], source: str = "manual"
) -> dict[str, int]:
    src = "import" if source == "import" else "manual"
    stats = {"added": 0, "skipped_duplicate": 0, "skipped_empty": 0, "skipped_limit": 0}
    now = time.time()
    batch: list[tuple[str, str, float, float]] = []
    seen: set[str] = set()
    candidates: list[str] = []
    for raw in texts:
        text = str(raw).strip()
        if not text:
            stats["skipped_empty"] += 1
            continue
        if text in seen:
            stats["skipped_duplicate"] += 1
            continue
        seen.add(text)
        candidates.append(text)
    with store._pool_write_lock:
        existing = _existing_custom_texts_locked(store, candidates)
        room = max(0, CUSTOM_DANMU_POOL_MAX - _custom_danmu_count_locked(store))
        for text in candidates:
            if text in existing:
                stats["skipped_duplicate"] += 1
                continue
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
            _commit_pool_write(store.conn, op="insert_many")
    store._invalidate_formula_text_cache()
    return stats


def custom_danmu_delete_ids_for_store(store, ids: list[int]) -> int:
    clean = [int(i) for i in ids if int(i) > 0]
    if not clean:
        return 0
    placeholders = ",".join("?" for _ in clean)
    with store._pool_write_lock:
        before = store.conn.total_changes
        store.conn.execute(
            f"DELETE FROM custom_danmu_pool_entries WHERE id IN ({placeholders})",
            clean,
        )
        removed = store.conn.total_changes - before
        _commit_pool_write(store.conn, op="delete_ids")
    if removed:
        store._invalidate_formula_text_cache()
    return removed


def custom_danmu_delete_texts_for_store(store, texts: list[str]) -> int:
    clean = [str(text).strip() for text in texts if str(text).strip()]
    if not clean:
        return 0
    placeholders = ",".join("?" for _ in clean)
    with store._pool_write_lock:
        before = store.conn.total_changes
        store.conn.execute(
            f"DELETE FROM custom_danmu_pool_entries WHERE text IN ({placeholders})",
            clean,
        )
        removed = store.conn.total_changes - before
        _commit_pool_write(store.conn, op="delete_texts")
    if removed:
        store._invalidate_formula_text_cache()
    return removed


def custom_danmu_enabled_ids_for_store(store) -> list[int]:
    if not store._conn_usable():
        return []
    try:
        rows = store.conn.execute(
            "SELECT id FROM custom_danmu_pool_entries WHERE enabled = 1 "
            f"ORDER BY id ASC LIMIT {CUSTOM_DANMU_POOL_MAX}"
        ).fetchall()
    except sqlite3.ProgrammingError:
        return []
    return [int(row[0]) for row in rows if row and row[0] is not None]


def custom_danmu_texts_by_ids_for_store(store, ids: list[int]) -> list[str]:
    if not ids or not store._conn_usable():
        return []
    clean_ids = [int(i) for i in ids if int(i) > 0]
    if not clean_ids:
        return []
    texts: list[str] = []
    try:
        for offset in range(0, len(clean_ids), _TEXTS_BY_IDS_CHUNK):
            chunk = clean_ids[offset : offset + _TEXTS_BY_IDS_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            rows = store.conn.execute(
                f"SELECT text FROM custom_danmu_pool_entries "
                f"WHERE enabled = 1 AND id IN ({placeholders})",
                chunk,
            ).fetchall()
            texts.extend(
                str(row[0]).strip()
                for row in rows
                if row and row[0] and str(row[0]).strip()
            )
    except sqlite3.ProgrammingError:
        return []
    return texts


def custom_danmu_random_sample_for_store(store, count: int) -> list[str]:
    if count <= 0 or not store._conn_usable():
        return []
    ids = custom_danmu_enabled_ids_for_store(store)
    if not ids:
        return []
    picked = random.sample(ids, min(int(count), len(ids)))
    return custom_danmu_texts_by_ids_for_store(store, picked)


def custom_danmu_contains_text_for_store(store, text: str) -> bool:
    value = str(text).strip()
    if not value or not store._conn_usable():
        return False
    row = store.conn.execute(
        "SELECT 1 FROM custom_danmu_pool_entries WHERE text = ? LIMIT 1",
        (value,),
    ).fetchone()
    return row is not None


def _iter_custom_danmu_pool_texts_for_store(store):
    """Yield custom pool texts in id order, paged to avoid single huge fetchall."""
    if not store._conn_usable():
        return
    offset = 0
    fetched = 0
    try:
        while fetched < CUSTOM_DANMU_POOL_MAX:
            limit = min(_CUSTOM_POOL_PAGE_SIZE, CUSTOM_DANMU_POOL_MAX - fetched)
            rows = store.conn.execute(
                "SELECT text FROM custom_danmu_pool_entries ORDER BY id ASC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            if not rows:
                break
            for row in rows:
                if row and row[0]:
                    text = str(row[0]).strip()
                    if text:
                        yield text
            batch_len = len(rows)
            fetched += batch_len
            offset += batch_len
            if batch_len < limit:
                break
    except sqlite3.ProgrammingError:
        return


def get_custom_danmu_pool_for_store(store) -> list[str]:
    return list(_iter_custom_danmu_pool_texts_for_store(store))


def _diff_custom_danmu_pool(
    existing: set[str], new_items: list[str], max_count: int
) -> tuple[list[str], list[str]]:
    """计算增量差异：返回 (to_add, to_remove)。

    to_add: 新列表中有、旧库中没有的文本（按顺序，去重，截断到 max_count - len(existing ∩ new)）
    to_remove: 旧库中有、新列表中没有的文本
    """
    seen: set[str] = set()
    new_ordered: list[str] = []
    for raw in new_items:
        text = str(raw).strip()
        if text and text not in seen:
            seen.add(text)
            new_ordered.append(text)

    new_set = set(new_ordered)
    to_remove = existing - new_set
    to_add_ordered = [t for t in new_ordered if t not in existing]

    # 上限截断：保留的 + 新增的 ≤ max_count
    keep_count = len(existing) - len(to_remove)
    add_budget = max(0, max_count - keep_count)
    to_add = to_add_ordered[:add_budget]

    return to_add, list(to_remove)


def set_custom_danmu_pool_for_store(store, items: list[str]) -> None:
    """增量 diff 更新自定义弹幕库，避免全量 DELETE+INSERT 导致的 WAL 膨胀。"""
    now = time.time()

    # 读取当前库中所有 text
    existing: set[str] = set()
    if store._conn_usable():
        try:
            rows = store.conn.execute(
                f"SELECT text FROM custom_danmu_pool_entries ORDER BY id ASC LIMIT {CUSTOM_DANMU_POOL_MAX}"
            ).fetchall()
            existing = {str(row[0]).strip() for row in rows if row and row[0]}
        except sqlite3.ProgrammingError:
            pass

    to_add, to_remove = _diff_custom_danmu_pool(existing, items, CUSTOM_DANMU_POOL_MAX)

    if not to_add and not to_remove:
        return

    try:
        with store._pool_write_lock:
            if to_remove:
                placeholders = ",".join("?" for _ in to_remove)
                store.conn.execute(
                    f"DELETE FROM custom_danmu_pool_entries WHERE text IN ({placeholders})",
                    to_remove,
                )
            if to_add:
                params = [(text, now, now) for text in to_add]
                store.conn.executemany(
                    "INSERT OR IGNORE INTO custom_danmu_pool_entries "
                    "(text, source, enabled, created_at, updated_at) VALUES (?, 'manual', 1, ?, ?)",
                    params,
                )
            store.conn.commit()
    except sqlite3.DatabaseError:
        try:
            store.conn.rollback()
        except sqlite3.Error:
            pass
        logger.exception("custom_danmu_pool diff write failed")
        return
    store._invalidate_formula_text_cache()
