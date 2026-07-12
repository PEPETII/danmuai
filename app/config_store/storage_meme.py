"""ConfigStore 子包：烂梗库 ``meme_barrage_library`` 表 CRUD 实现。

``ConfigStore`` 通过 ``storage.py`` 内薄委托方法调用本模块 ``*_for_store`` 函数；
锁语义不变：写路径持 ``store._write_lock``，读路径不持锁。
"""
from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config_store.storage import ConfigStore


def meme_barrage_library_count_for_store(store: ConfigStore) -> int:
    if not store._conn_usable():
        return 0
    try:
        row = store.conn.execute("SELECT COUNT(*) FROM meme_barrage_library").fetchone()
    except sqlite3.ProgrammingError:
        return 0
    if not row or row[0] is None:
        return 0
    return int(row[0])


def meme_barrage_library_clear_for_store(store: ConfigStore) -> None:
    with store._write_lock:
        store.conn.execute("DELETE FROM meme_barrage_library")
        store.conn.commit()
    store._invalidate_formula_text_cache()


def meme_barrage_library_insert_many_for_store(
    store: ConfigStore,
    items: list[tuple[str, str | None, int | None]],
    *,
    collected_at: float,
    max_rows: int,
) -> int:
    params = []
    for text, source_tag, remote_id in items:
        stripped = str(text).strip()
        if stripped:
            params.append((stripped, source_tag, remote_id, collected_at))
    if not params:
        return 0
    with store._write_lock:
        before = store.conn.total_changes
        store.conn.executemany(
            "INSERT OR IGNORE INTO meme_barrage_library "
            "(text, source_tag, remote_id, collected_at) VALUES (?, ?, ?, ?)",
            params,
        )
        added = store.conn.total_changes - before
        _trim_meme_barrage_library_locked(store, max_rows)
        store.conn.commit()
    store._invalidate_formula_text_cache()
    return added


def meme_barrage_library_all_texts_for_store(store: ConfigStore) -> list[str]:
    """All meme library lines for formula-text cache warm-up (max LIBRARY_MAX_ROWS)."""
    if not store._conn_usable():
        return []
    try:
        from app.meme_barrage.store import LIBRARY_MAX_ROWS

        rows = store.conn.execute(
            "SELECT text FROM meme_barrage_library ORDER BY id ASC LIMIT ?",
            (LIBRARY_MAX_ROWS,),
        ).fetchall()
    except sqlite3.ProgrammingError:
        return []
    return [str(row[0]).strip() for row in rows if row and row[0] and str(row[0]).strip()]


def meme_barrage_library_contains_text_for_store(store: ConfigStore, text: str) -> bool:
    """True when text exactly matches a row in meme_barrage_library."""
    value = str(text).strip()
    if not value:
        return False
    if not store._conn_usable():
        return False
    try:
        row = store.conn.execute(
            "SELECT 1 FROM meme_barrage_library WHERE text = ? LIMIT 1",
            (value,),
        ).fetchone()
    except sqlite3.ProgrammingError:
        return False
    return row is not None


def meme_barrage_library_fetch_batch_for_store(
    store: ConfigStore, offset: int, limit: int
) -> tuple[list[str], int]:
    if limit <= 0:
        return [], offset
    total = meme_barrage_library_count_for_store(store)
    if total <= 0:
        return [], 0
    offset = int(offset) % total
    if not store._conn_usable():
        return [], offset
    try:
        rows = store.conn.execute(
            "SELECT text FROM meme_barrage_library ORDER BY id ASC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    except sqlite3.ProgrammingError:
        return [], offset
    texts = [str(row[0]) for row in rows if row and row[0]]
    next_offset = (offset + len(texts)) % total if total else 0
    return texts, next_offset


def _trim_meme_barrage_library_locked(store: ConfigStore, max_rows: int) -> None:
    count = store.conn.execute("SELECT COUNT(*) FROM meme_barrage_library").fetchone()
    total = 0 if not count or count[0] is None else int(count[0])
    if total <= max_rows:
        return
    excess = total - max_rows
    store.conn.execute(
        "DELETE FROM meme_barrage_library WHERE id IN ("
        "SELECT id FROM meme_barrage_library ORDER BY id ASC LIMIT ?"
        ")",
        (excess,),
    )
    store._invalidate_formula_text_cache()
