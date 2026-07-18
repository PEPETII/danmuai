"""知识包 CRUD（packages / sources / chunks / items / jobs）。

风格仿 ``app/config_store/storage_meme.py`` 的 ``*_for_store`` 纯函数；
本模块提供 ``*_for_db(db, ...)`` 形式，``KnowledgeDatabase`` 实例作为第一参数。

锁语义（与 ``storage_meme`` 一致）：
- 写路径持 ``db._write_lock``（经 ``db.with_write_lock()`` 上下文）；
- 读路径不持锁，依赖 WAL 不阻塞写。

级联删除：``delete_package_for_db`` 在单事务内显式 DELETE
FTS → items → chunks → sources → jobs → packages（项目未启用
``PRAGMA foreign_keys``，不依赖 DB 层 FK 级联）。

FTS 索引同步：``insert_item_for_db`` 插入主表后同步插入 FTS 行；
``delete_item_for_db`` / ``delete_package_for_db`` 删除主表前同步删除 FTS 行
（external-content 表不自动级联）。
"""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.knowledge.database import KnowledgeDatabase


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    """当前 UTC ISO8601 时间戳（秒精度，与 SQLite TEXT 兼容）。"""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_public_id() -> str:
    """生成 public_id（``secrets.token_urlsafe(12)``，spec §ADDED Web API 场景）。"""
    return secrets.token_urlsafe(12)


def _content_hash(text: str) -> str:
    """SHA-256 十六进制（用于去重与内容指纹）。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_search_text(
    title: str,
    content: str,
    examples: list[str],
    triggers: list[str],
    tones: list[str],
    scopes: list[str],
    entities: list[str],
) -> str:
    """拼接 search_text（spec §5.2：title + content + examples + triggers + tones + scopes + entities）。"""
    parts = [title, content]
    parts.extend(examples)
    parts.extend(triggers)
    parts.extend(tones)
    parts.extend(scopes)
    parts.extend(entities)
    return " ".join(p for p in parts if p)


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """sqlite3.Row → dict；None → None。"""
    if row is None:
        return None
    return dict(row)


def _json_loads(value: str | None, default: Any = None) -> Any:
    """安全 JSON 解析；空值或解析失败返回 default。"""
    if not value:
        return default if default is not None else []
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default if default is not None else []


# ---------------------------------------------------------------------------
# packages CRUD
# ---------------------------------------------------------------------------


def list_packages_for_db(
    db: "KnowledgeDatabase", *, enabled_only: bool = False
) -> list[dict[str, Any]]:
    """列出全部知识包（按 priority DESC, id ASC）。"""
    sql = "SELECT * FROM knowledge_packages"
    if enabled_only:
        sql += " WHERE enabled=1"
    sql += " ORDER BY priority DESC, id ASC"
    rows = db.conn.execute(sql).fetchall()
    return [_deserialize_package_row(r) for r in rows]


def get_package_for_db(
    db: "KnowledgeDatabase", public_id: str
) -> dict[str, Any] | None:
    """按 public_id 取单个知识包；不存在返回 None。"""
    row = db.conn.execute(
        "SELECT * FROM knowledge_packages WHERE public_id=?",
        (public_id,),
    ).fetchone()
    return _deserialize_package_row(row) if row else None


def _get_package_id_by_public_id(
    db: "KnowledgeDatabase", public_id: str
) -> int | None:
    """public_id → 内部 id；不存在返回 None。读路径不持锁。"""
    row = db.conn.execute(
        "SELECT id FROM knowledge_packages WHERE public_id=?",
        (public_id,),
    ).fetchone()
    return int(row[0]) if row else None


def create_package_for_db(
    db: "KnowledgeDatabase",
    *,
    name: str,
    description: str = "",
    content_kind: str = "auto",
    scope_mode: str = "global",
    scope_tags: list[str] | None = None,
    enabled: bool = True,
    priority: int = 0,
) -> dict[str, Any]:
    """创建知识包；返回新行字典（含 public_id）。"""
    public_id = _new_public_id()
    now = _now_iso()
    scope_tags = scope_tags or []
    scope_tags_json = json.dumps(scope_tags, ensure_ascii=False)
    with db.with_write_lock():
        db.conn.execute(
            "INSERT INTO knowledge_packages "
            "(public_id, name, description, content_kind, scope_mode, scope_tags_json, "
            "enabled, priority, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                public_id,
                name,
                description,
                content_kind,
                scope_mode,
                scope_tags_json,
                1 if enabled else 0,
                int(priority),
                now,
                now,
            ),
        )
        db.conn.commit()
    return {
        "public_id": public_id,
        "name": name,
        "description": description,
        "content_kind": content_kind,
        "scope_mode": scope_mode,
        "scope_tags": list(scope_tags),
        "enabled": bool(enabled),
        "priority": int(priority),
        "created_at": now,
        "updated_at": now,
    }


def update_package_for_db(
    db: "KnowledgeDatabase",
    public_id: str,
    *,
    name: str | None = None,
    description: str | None = None,
    content_kind: str | None = None,
    scope_mode: str | None = None,
    scope_tags: list[str] | None = None,
    enabled: bool | None = None,
    priority: int | None = None,
) -> dict[str, Any] | None:
    """部分更新知识包；返回更新后的行字典，包不存在返回 None。"""
    sets: list[str] = []
    params: list[Any] = []
    if name is not None:
        sets.append("name=?")
        params.append(name)
    if description is not None:
        sets.append("description=?")
        params.append(description)
    if content_kind is not None:
        sets.append("content_kind=?")
        params.append(content_kind)
    if scope_mode is not None:
        sets.append("scope_mode=?")
        params.append(scope_mode)
    if scope_tags is not None:
        sets.append("scope_tags_json=?")
        params.append(json.dumps(scope_tags, ensure_ascii=False))
    if enabled is not None:
        sets.append("enabled=?")
        params.append(1 if enabled else 0)
    if priority is not None:
        sets.append("priority=?")
        params.append(int(priority))
    if not sets:
        return get_package_for_db(db, public_id)
    sets.append("updated_at=?")
    params.append(_now_iso())
    params.append(public_id)
    with db.with_write_lock():
        cursor = db.conn.execute(
            f"UPDATE knowledge_packages SET {', '.join(sets)} WHERE public_id=?",
            params,
        )
        if cursor.rowcount == 0:
            db.conn.rollback()
            return None
        db.conn.commit()
    return get_package_for_db(db, public_id)


def delete_package_for_db(db: "KnowledgeDatabase", public_id: str) -> bool:
    """删包级联：单事务内 DELETE FTS → items → chunks → sources → jobs → packages。

    项目未启用 ``PRAGMA foreign_keys``，不依赖 DB 层 FK 级联。
    FTS 行单独 DELETE（external-content 表不自动级联）。

    Returns:
        True 表示包存在且已删除；False 表示包不存在。
    """
    with db.with_write_lock():
        row = db.conn.execute(
            "SELECT id FROM knowledge_packages WHERE public_id=?", (public_id,)
        ).fetchone()
        if not row:
            return False
        package_id = int(row[0])
        # FTS 行先删（external-content 表不自动级联；spec §6.2 + 风险表）
        _delete_fts_rows_for_package_locked(db, package_id)
        db.conn.execute(
            "DELETE FROM knowledge_items WHERE package_id=?", (package_id,)
        )
        db.conn.execute(
            "DELETE FROM knowledge_chunks WHERE source_id IN ("
            "SELECT id FROM knowledge_sources WHERE package_id=?"
            ")",
            (package_id,),
        )
        db.conn.execute(
            "DELETE FROM knowledge_sources WHERE package_id=?", (package_id,)
        )
        db.conn.execute(
            "DELETE FROM knowledge_jobs WHERE package_id=?", (package_id,)
        )
        db.conn.execute(
            "DELETE FROM knowledge_packages WHERE id=?", (package_id,)
        )
        db.conn.commit()
    return True


def _delete_fts_rows_for_package_locked(
    db: "KnowledgeDatabase", package_id: int
) -> None:
    """删除 package 下所有 items 的 FTS 索引行（须持写锁）。"""
    if db.fts_backend == "fallback":
        return
    try:
        db.conn.execute(
            "DELETE FROM knowledge_items_fts WHERE rowid IN ("
            "SELECT id FROM knowledge_items WHERE package_id=?"
            ")",
            (package_id,),
        )
    except sqlite3.OperationalError:
        # FTS 表可能不存在（fallback 或迁移失败）；静默跳过。
        pass


def _deserialize_package_row(row: sqlite3.Row) -> dict[str, Any]:
    """sqlite3.Row → dict，scope_tags_json 反序列化为 scope_tags 列表。"""
    d = dict(row)
    d["scope_tags"] = _json_loads(d.pop("scope_tags_json", "[]"), default=[])
    d["enabled"] = bool(d.get("enabled", 0))
    return d


# ---------------------------------------------------------------------------
# sources CRUD
# ---------------------------------------------------------------------------


def create_source_for_db(
    db: "KnowledgeDatabase",
    *,
    package_id: int,
    source_type: str,
    display_name: str,
    source_url: str | None = None,
    raw_text: str = "",
    normalized_text: str = "",
    status: str = "pending",
    error_message: str = "",
) -> dict[str, Any]:
    """创建 source 行；返回新行字典（含 public_id、内部 id 由 DB 自增）。"""
    public_id = _new_public_id()
    now = _now_iso()
    content_hash = _content_hash(normalized_text or raw_text)
    with db.with_write_lock():
        cursor = db.conn.execute(
            "INSERT INTO knowledge_sources "
            "(public_id, package_id, source_type, display_name, source_url, "
            "raw_text, normalized_text, content_hash, status, error_message, "
            "created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                public_id,
                package_id,
                source_type,
                display_name,
                source_url,
                raw_text,
                normalized_text,
                content_hash,
                status,
                error_message,
                now,
                now,
            ),
        )
        source_id = int(cursor.lastrowid)
        db.conn.commit()
    return {
        "id": source_id,
        "public_id": public_id,
        "package_id": package_id,
        "source_type": source_type,
        "display_name": display_name,
        "source_url": source_url,
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "content_hash": content_hash,
        "status": status,
        "error_message": error_message,
        "created_at": now,
        "updated_at": now,
    }


def get_source_for_db(
    db: "KnowledgeDatabase", public_id: str
) -> dict[str, Any] | None:
    """按 public_id 取单个 source。"""
    row = db.conn.execute(
        "SELECT * FROM knowledge_sources WHERE public_id=?",
        (public_id,),
    ).fetchone()
    return _row_to_dict(row)


def list_sources_for_db(
    db: "KnowledgeDatabase", package_id: int
) -> list[dict[str, Any]]:
    """列出一包下全部 sources（按 id ASC）。"""
    rows = db.conn.execute(
        "SELECT * FROM knowledge_sources WHERE package_id=? ORDER BY id ASC",
        (package_id,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[list-item]


def update_source_status_for_db(
    db: "KnowledgeDatabase",
    source_public_id: str,
    *,
    status: str,
    error_message: str | None = None,
    normalized_text: str | None = None,
) -> dict[str, Any] | None:
    """更新 source 状态（导入流程用）。"""
    sets = ["status=?", "updated_at=?"]
    params: list[Any] = [status, _now_iso()]
    if error_message is not None:
        sets.append("error_message=?")
        params.append(error_message)
    if normalized_text is not None:
        sets.append("normalized_text=?")
        params.append(normalized_text)
        sets.append("content_hash=?")
        params.append(_content_hash(normalized_text))
    params.append(source_public_id)
    with db.with_write_lock():
        cursor = db.conn.execute(
            f"UPDATE knowledge_sources SET {', '.join(sets)} WHERE public_id=?",
            params,
        )
        if cursor.rowcount == 0:
            db.conn.rollback()
            return None
        db.conn.commit()
    return get_source_for_db(db, source_public_id)


# ---------------------------------------------------------------------------
# chunks CRUD
# ---------------------------------------------------------------------------


def insert_chunks_for_db(
    db: "KnowledgeDatabase",
    *,
    source_id: int,
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """批量插入 chunks；每个 chunk 须含 sequence_no / heading / content。

    Returns:
        插入后的 chunk 字典列表（含 id、content_hash）。
    """
    if not chunks:
        return []
    now = _now_iso()
    result: list[dict[str, Any]] = []
    with db.with_write_lock():
        for chunk in chunks:
            content = str(chunk.get("content", ""))
            heading = str(chunk.get("heading", ""))
            sequence_no = int(chunk.get("sequence_no", 0))
            content_hash = _content_hash(content)
            cursor = db.conn.execute(
                "INSERT INTO knowledge_chunks "
                "(source_id, sequence_no, heading, content, content_hash, status, error_message) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    source_id,
                    sequence_no,
                    heading,
                    content,
                    content_hash,
                    chunk.get("status", "pending"),
                    chunk.get("error_message", ""),
                ),
            )
            chunk_id = int(cursor.lastrowid)
            result.append(
                {
                    "id": chunk_id,
                    "source_id": source_id,
                    "sequence_no": sequence_no,
                    "heading": heading,
                    "content": content,
                    "content_hash": content_hash,
                    "status": chunk.get("status", "pending"),
                    "error_message": chunk.get("error_message", ""),
                }
            )
        db.conn.commit()
    return result


def list_chunks_for_db(
    db: "KnowledgeDatabase", source_id: int
) -> list[dict[str, Any]]:
    """列出 source 下全部 chunks（按 sequence_no ASC）。"""
    rows = db.conn.execute(
        "SELECT * FROM knowledge_chunks WHERE source_id=? ORDER BY sequence_no ASC",
        (source_id,),
    ).fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[list-item]


def update_chunk_status_for_db(
    db: "KnowledgeDatabase",
    chunk_id: int,
    *,
    status: str,
    error_message: str | None = None,
) -> None:
    """更新 chunk 状态（导入流程逐 chunk 调用）。"""
    sets = ["status=?"]
    params: list[Any] = [status]
    if error_message is not None:
        sets.append("error_message=?")
        params.append(error_message)
    params.append(chunk_id)
    with db.with_write_lock():
        db.conn.execute(
            f"UPDATE knowledge_chunks SET {', '.join(sets)} WHERE id=?",
            params,
        )
        db.conn.commit()


# ---------------------------------------------------------------------------
# items CRUD
# ---------------------------------------------------------------------------


def insert_item_for_db(
    db: "KnowledgeDatabase",
    *,
    package_id: int,
    source_id: int,
    chunk_id: int | None,
    kind: str,
    title: str,
    content: str,
    examples: list[str] | None = None,
    triggers: list[str] | None = None,
    tones: list[str] | None = None,
    scopes: list[str] | None = None,
    entities: list[str] | None = None,
    confidence: float = 1.0,
    evidence: str = "",
    enabled: bool = True,
    priority: int = 0,
) -> dict[str, Any]:
    """插入单条知识 item；同步插入 FTS 行。

    Returns:
        新 item 字典（含 id、public_id、search_text、content_hash）。
    """
    examples = examples or []
    triggers = triggers or []
    tones = tones or []
    scopes = scopes or []
    entities = entities or []
    public_id = _new_public_id()
    now = _now_iso()
    search_text = _build_search_text(
        title, content, examples, triggers, tones, scopes, entities
    )
    content_hash = _content_hash(content)
    examples_json = json.dumps(examples, ensure_ascii=False)
    triggers_json = json.dumps(triggers, ensure_ascii=False)
    tones_json = json.dumps(tones, ensure_ascii=False)
    scopes_json = json.dumps(scopes, ensure_ascii=False)
    entities_json = json.dumps(entities, ensure_ascii=False)
    with db.with_write_lock():
        cursor = db.conn.execute(
            "INSERT INTO knowledge_items "
            "(public_id, package_id, source_id, chunk_id, kind, title, content, "
            "examples_json, triggers_json, tones_json, scopes_json, entities_json, "
            "search_text, confidence, evidence, content_hash, enabled, priority, "
            "use_count, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
            (
                public_id,
                package_id,
                source_id,
                chunk_id,
                kind,
                title,
                content,
                examples_json,
                triggers_json,
                tones_json,
                scopes_json,
                entities_json,
                search_text,
                float(confidence),
                evidence,
                content_hash,
                1 if enabled else 0,
                int(priority),
                now,
                now,
            ),
        )
        item_id = int(cursor.lastrowid)
        _insert_fts_row_locked(
            db,
            rowid=item_id,
            title=title,
            content=content,
            search_text=search_text,
        )
        db.conn.commit()
    return {
        "id": item_id,
        "public_id": public_id,
        "package_id": package_id,
        "source_id": source_id,
        "chunk_id": chunk_id,
        "kind": kind,
        "title": title,
        "content": content,
        "examples": list(examples),
        "triggers": list(triggers),
        "tones": list(tones),
        "scopes": list(scopes),
        "entities": list(entities),
        "search_text": search_text,
        "confidence": float(confidence),
        "evidence": evidence,
        "content_hash": content_hash,
        "enabled": bool(enabled),
        "priority": int(priority),
        "last_used_at": None,
        "use_count": 0,
        "created_at": now,
        "updated_at": now,
    }


def _insert_fts_row_locked(
    db: "KnowledgeDatabase",
    *,
    rowid: int,
    title: str,
    content: str,
    search_text: str,
) -> None:
    """同步插入 FTS 索引行（须持写锁）。fallback 模式 no-op。"""
    if db.fts_backend == "fallback":
        return
    try:
        db.conn.execute(
            "INSERT INTO knowledge_items_fts (rowid, title, content, search_text) "
            "VALUES (?, ?, ?, ?)",
            (rowid, title, content, search_text),
        )
    except sqlite3.OperationalError:
        # FTS 表可能不存在；静默跳过（retriever 会回退到 LIKE）。
        pass


def _delete_fts_row_locked(db: "KnowledgeDatabase", rowid: int) -> None:
    """同步删除 FTS 索引行（须持写锁）。fallback 模式 no-op。"""
    if db.fts_backend == "fallback":
        return
    try:
        db.conn.execute(
            "DELETE FROM knowledge_items_fts WHERE rowid=?", (rowid,)
        )
    except sqlite3.OperationalError:
        pass


def get_item_for_db(
    db: "KnowledgeDatabase", public_id: str
) -> dict[str, Any] | None:
    """按 public_id 取单个 item（含反序列化的 JSON 字段）。"""
    row = db.conn.execute(
        "SELECT * FROM knowledge_items WHERE public_id=?",
        (public_id,),
    ).fetchone()
    return _deserialize_item_row(row) if row else None


def get_item_by_id_for_db(
    db: "KnowledgeDatabase", item_id: int
) -> dict[str, Any] | None:
    """按内部 id 取单个 item。"""
    row = db.conn.execute(
        "SELECT * FROM knowledge_items WHERE id=?",
        (item_id,),
    ).fetchone()
    return _deserialize_item_row(row) if row else None


def list_items_for_db(
    db: "KnowledgeDatabase",
    *,
    package_id: int | None = None,
    kind: str | None = None,
    enabled: bool | None = None,
    query: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """分页列出 items。

    Args:
        package_id: 限定包；None 表示全部。
        kind: 限定 kind；None 表示全部。
        enabled: 限定启用状态；None 表示全部。
        query: 关键词检索（命中 search_text LIKE）；None 表示不检索。
        page: 1-based 页码。
        page_size: 每页条数（1-200）。

    Returns:
        ``{"items": [...], "page": int, "page_size": int, "total": int}``。
    """
    page = max(1, int(page))
    page_size = max(1, min(200, int(page_size)))
    where: list[str] = []
    params: list[Any] = []
    if package_id is not None:
        where.append("package_id=?")
        params.append(int(package_id))
    if kind is not None:
        where.append("kind=?")
        params.append(kind)
    if enabled is not None:
        where.append("enabled=?")
        params.append(1 if enabled else 0)
    if query:
        where.append("search_text LIKE ?")
        params.append(f"%{query}%")
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    total_row = db.conn.execute(
        f"SELECT COUNT(*) FROM knowledge_items{where_sql}", params
    ).fetchone()
    total = int(total_row[0]) if total_row else 0
    offset = (page - 1) * page_size
    rows = db.conn.execute(
        f"SELECT * FROM knowledge_items{where_sql} "
        "ORDER BY priority DESC, id ASC LIMIT ? OFFSET ?",
        [*params, page_size, offset],
    ).fetchall()
    return {
        "items": [_deserialize_item_row(r) for r in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


def update_item_for_db(
    db: "KnowledgeDatabase",
    public_id: str,
    *,
    title: str | None = None,
    content: str | None = None,
    examples: list[str] | None = None,
    triggers: list[str] | None = None,
    tones: list[str] | None = None,
    scopes: list[str] | None = None,
    entities: list[str] | None = None,
    enabled: bool | None = None,
    priority: int | None = None,
) -> dict[str, Any] | None:
    """部分更新 item；若 title/content/examples/triggers/tones/scopes/entities
    任一变更，则同步重建 search_text 与 FTS 索引行。"""
    sets: list[str] = []
    params: list[Any] = []
    need_reindex = False
    new_title: str | None = None
    new_content: str | None = None
    new_examples: list[str] | None = None
    new_triggers: list[str] | None = None
    new_tones: list[str] | None = None
    new_scopes: list[str] | None = None
    new_entities: list[str] | None = None
    if title is not None:
        sets.append("title=?")
        params.append(title)
        new_title = title
        need_reindex = True
    if content is not None:
        sets.append("content=?")
        params.append(content)
        new_content = content
        need_reindex = True
    if examples is not None:
        sets.append("examples_json=?")
        params.append(json.dumps(examples, ensure_ascii=False))
        new_examples = examples
        need_reindex = True
    if triggers is not None:
        sets.append("triggers_json=?")
        params.append(json.dumps(triggers, ensure_ascii=False))
        new_triggers = triggers
        need_reindex = True
    if tones is not None:
        sets.append("tones_json=?")
        params.append(json.dumps(tones, ensure_ascii=False))
        new_tones = tones
        need_reindex = True
    if scopes is not None:
        sets.append("scopes_json=?")
        params.append(json.dumps(scopes, ensure_ascii=False))
        new_scopes = scopes
        need_reindex = True
    if entities is not None:
        sets.append("entities_json=?")
        params.append(json.dumps(entities, ensure_ascii=False))
        new_entities = entities
        need_reindex = True
    if enabled is not None:
        sets.append("enabled=?")
        params.append(1 if enabled else 0)
    if priority is not None:
        sets.append("priority=?")
        params.append(int(priority))
    if not sets:
        return get_item_for_db(db, public_id)
    with db.with_write_lock():
        row = db.conn.execute(
            "SELECT id, title, content, examples_json, triggers_json, tones_json, "
            "scopes_json, entities_json FROM knowledge_items WHERE public_id=?",
            (public_id,),
        ).fetchone()
        if row is None:
            db.conn.rollback()
            return None
        item_id = int(row[0])
        if need_reindex:
            cur_title = new_title if new_title is not None else str(row[1])
            cur_content = new_content if new_content is not None else str(row[2])
            cur_examples = (
                new_examples
                if new_examples is not None
                else _json_loads(row[3], default=[])
            )
            cur_triggers = (
                new_triggers
                if new_triggers is not None
                else _json_loads(row[4], default=[])
            )
            cur_tones = (
                new_tones
                if new_tones is not None
                else _json_loads(row[5], default=[])
            )
            cur_scopes = (
                new_scopes
                if new_scopes is not None
                else _json_loads(row[6], default=[])
            )
            cur_entities = (
                new_entities
                if new_entities is not None
                else _json_loads(row[7], default=[])
            )
            search_text = _build_search_text(
                cur_title,
                cur_content,
                cur_examples,
                cur_triggers,
                cur_tones,
                cur_scopes,
                cur_entities,
            )
            sets.append("search_text=?")
            params.append(search_text)
            # FTS 索引同步：先删后插（external-content 表不自动跟随主表 UPDATE）
            _delete_fts_row_locked(db, item_id)
            _insert_fts_row_locked(
                db,
                rowid=item_id,
                title=cur_title,
                content=cur_content,
                search_text=search_text,
            )
        sets.append("updated_at=?")
        params.append(_now_iso())
        params.append(public_id)
        db.conn.execute(
            f"UPDATE knowledge_items SET {', '.join(sets)} WHERE public_id=?",
            params,
        )
        db.conn.commit()
    return get_item_for_db(db, public_id)


def delete_item_for_db(db: "KnowledgeDatabase", public_id: str) -> bool:
    """删除单条 item；同步删除 FTS 行。"""
    with db.with_write_lock():
        row = db.conn.execute(
            "SELECT id FROM knowledge_items WHERE public_id=?", (public_id,)
        ).fetchone()
        if row is None:
            return False
        item_id = int(row[0])
        _delete_fts_row_locked(db, item_id)
        db.conn.execute("DELETE FROM knowledge_items WHERE id=?", (item_id,))
        db.conn.commit()
    return True


def mark_items_used_for_db(
    db: "KnowledgeDatabase",
    item_ids: list[int],
    *,
    used_at: float | None = None,
) -> None:
    """更新 use_count + last_used_at（runtime_service 注入后调用）。

    spec §13.4：注入时调 ``mark_items_used(snapshot.item_ids, now)``。
    """
    if not item_ids:
        return
    timestamp = _now_iso() if used_at is None else (
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(used_at))
    )
    ids = [int(i) for i in item_ids if i is not None]
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    with db.with_write_lock():
        db.conn.execute(
            f"UPDATE knowledge_items SET use_count=use_count+1, "
            f"last_used_at=?, updated_at=? WHERE id IN ({placeholders})",
            [timestamp, _now_iso(), *ids],
        )
        db.conn.commit()


def _deserialize_item_row(row: sqlite3.Row) -> dict[str, Any]:
    """sqlite3.Row → dict；JSON 字段反序列化为列表。"""
    d = dict(row)
    d["examples"] = _json_loads(d.pop("examples_json", "[]"), default=[])
    d["triggers"] = _json_loads(d.pop("triggers_json", "[]"), default=[])
    d["tones"] = _json_loads(d.pop("tones_json", "[]"), default=[])
    d["scopes"] = _json_loads(d.pop("scopes_json", "[]"), default=[])
    d["entities"] = _json_loads(d.pop("entities_json", "[]"), default=[])
    d["enabled"] = bool(d.get("enabled", 0))
    return d


# ---------------------------------------------------------------------------
# jobs CRUD
# ---------------------------------------------------------------------------


def create_job_for_db(
    db: "KnowledgeDatabase",
    *,
    package_id: int,
    source_id: int,
    status: str = "pending",
    stage: str = "queued",
    total_chunks: int = 0,
) -> dict[str, Any]:
    """创建导入任务行；返回新行字典（含 public_id）。"""
    public_id = _new_public_id()
    now = _now_iso()
    with db.with_write_lock():
        cursor = db.conn.execute(
            "INSERT INTO knowledge_jobs "
            "(public_id, package_id, source_id, status, stage, total_chunks, "
            "processed_chunks, failed_chunks, generated_items, deduplicated_items, "
            "input_tokens, output_tokens, error_message, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 0, 0, 0, 0, 0, '', ?, ?)",
            (
                public_id,
                package_id,
                source_id,
                status,
                stage,
                int(total_chunks),
                now,
                now,
            ),
        )
        job_id = int(cursor.lastrowid)
        db.conn.commit()
    return {
        "id": job_id,
        "public_id": public_id,
        "package_id": package_id,
        "source_id": source_id,
        "status": status,
        "stage": stage,
        "total_chunks": int(total_chunks),
        "processed_chunks": 0,
        "failed_chunks": 0,
        "generated_items": 0,
        "deduplicated_items": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "error_message": "",
        "created_at": now,
        "updated_at": now,
        "finished_at": None,
    }


def get_job_for_db(
    db: "KnowledgeDatabase", public_id: str
) -> dict[str, Any] | None:
    """按 public_id 取单个 job。"""
    row = db.conn.execute(
        "SELECT * FROM knowledge_jobs WHERE public_id=?",
        (public_id,),
    ).fetchone()
    return _row_to_dict(row)


def list_jobs_for_db(
    db: "KnowledgeDatabase",
    *,
    package_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """列出 jobs（按 id DESC，最近优先）。"""
    where: list[str] = []
    params: list[Any] = []
    if package_id is not None:
        where.append("package_id=?")
        params.append(int(package_id))
    if status is not None:
        where.append("status=?")
        params.append(status)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    limit = max(1, min(200, int(limit)))
    rows = db.conn.execute(
        f"SELECT * FROM knowledge_jobs{where_sql} ORDER BY id DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    return [_row_to_dict(r) for r in rows]  # type: ignore[list-item]


def update_job_progress_for_db(
    db: "KnowledgeDatabase",
    job_public_id: str,
    *,
    status: str | None = None,
    stage: str | None = None,
    total_chunks: int | None = None,
    processed_chunks: int | None = None,
    failed_chunks: int | None = None,
    generated_items: int | None = None,
    deduplicated_items: int | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    error_message: str | None = None,
    finished_at: str | None = None,
) -> dict[str, Any] | None:
    """部分更新 job 进度；任意字段 None 表示不更新。"""
    sets: list[str] = []
    params: list[Any] = []
    if status is not None:
        sets.append("status=?")
        params.append(status)
    if stage is not None:
        sets.append("stage=?")
        params.append(stage)
    if total_chunks is not None:
        sets.append("total_chunks=?")
        params.append(int(total_chunks))
    if processed_chunks is not None:
        sets.append("processed_chunks=?")
        params.append(int(processed_chunks))
    if failed_chunks is not None:
        sets.append("failed_chunks=?")
        params.append(int(failed_chunks))
    if generated_items is not None:
        sets.append("generated_items=?")
        params.append(int(generated_items))
    if deduplicated_items is not None:
        sets.append("deduplicated_items=?")
        params.append(int(deduplicated_items))
    if input_tokens is not None:
        sets.append("input_tokens=?")
        params.append(int(input_tokens))
    if output_tokens is not None:
        sets.append("output_tokens=?")
        params.append(int(output_tokens))
    if error_message is not None:
        sets.append("error_message=?")
        params.append(error_message)
    if finished_at is not None:
        sets.append("finished_at=?")
        params.append(finished_at)
    if not sets:
        return get_job_for_db(db, job_public_id)
    sets.append("updated_at=?")
    params.append(_now_iso())
    params.append(job_public_id)
    with db.with_write_lock():
        cursor = db.conn.execute(
            f"UPDATE knowledge_jobs SET {', '.join(sets)} WHERE public_id=?",
            params,
        )
        if cursor.rowcount == 0:
            db.conn.rollback()
            return None
        db.conn.commit()
    return get_job_for_db(db, job_public_id)


def mark_job_interrupted_at_startup(db: "KnowledgeDatabase") -> int:
    """启动时把所有 status IN ('pending','running') 的 job 标记为 'interrupted'。

    spec §5.2：应用启动时，之前仍为 running 的任务应标记为 interrupted，
    不得永远显示处理中。

    Returns:
        受影响行数。
    """
    with db.with_write_lock():
        cursor = db.conn.execute(
            "UPDATE knowledge_jobs SET status='interrupted', "
            "updated_at=?, finished_at=? "
            "WHERE status IN ('pending', 'running')",
            (_now_iso(), _now_iso()),
        )
        affected = int(cursor.rowcount)
        db.conn.commit()
    return affected


# ---------------------------------------------------------------------------
# KnowledgeRepository 类（持有 db 引用 + 委托纯函数，便于后续注入）
# ---------------------------------------------------------------------------


class KnowledgeRepository:
    """知识包仓储门面；持有 ``KnowledgeDatabase`` 引用，委托模块级纯函数。

    用法：
        repo = KnowledgeRepository(db)
        pkg = repo.create_package(name="我的知识包")
        repo.delete_package(pkg["public_id"])

    纯函数式 API（``*_for_db``）也直接可用，便于测试与多 db 场景。
    """

    def __init__(self, db: "KnowledgeDatabase"):
        self.db = db

    # packages
    def list_packages(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        return list_packages_for_db(self.db, enabled_only=enabled_only)

    def get_package(self, public_id: str) -> dict[str, Any] | None:
        return get_package_for_db(self.db, public_id)

    def create_package(self, **kwargs: Any) -> dict[str, Any]:
        return create_package_for_db(self.db, **kwargs)

    def update_package(self, public_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return update_package_for_db(self.db, public_id, **kwargs)

    def delete_package(self, public_id: str) -> bool:
        return delete_package_for_db(self.db, public_id)

    # sources
    def create_source(self, **kwargs: Any) -> dict[str, Any]:
        return create_source_for_db(self.db, **kwargs)

    def get_source(self, public_id: str) -> dict[str, Any] | None:
        return get_source_for_db(self.db, public_id)

    def list_sources(self, package_id: int) -> list[dict[str, Any]]:
        return list_sources_for_db(self.db, package_id)

    def update_source_status(self, public_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return update_source_status_for_db(self.db, public_id, **kwargs)

    # chunks
    def insert_chunks(self, **kwargs: Any) -> list[dict[str, Any]]:
        return insert_chunks_for_db(self.db, **kwargs)

    def list_chunks(self, source_id: int) -> list[dict[str, Any]]:
        return list_chunks_for_db(self.db, source_id)

    def update_chunk_status(self, chunk_id: int, **kwargs: Any) -> None:
        return update_chunk_status_for_db(self.db, chunk_id, **kwargs)

    # items
    def insert_item(self, **kwargs: Any) -> dict[str, Any]:
        return insert_item_for_db(self.db, **kwargs)

    def get_item(self, public_id: str) -> dict[str, Any] | None:
        return get_item_for_db(self.db, public_id)

    def get_item_by_id(self, item_id: int) -> dict[str, Any] | None:
        return get_item_by_id_for_db(self.db, item_id)

    def list_items(self, **kwargs: Any) -> dict[str, Any]:
        return list_items_for_db(self.db, **kwargs)

    def update_item(self, public_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return update_item_for_db(self.db, public_id, **kwargs)

    def delete_item(self, public_id: str) -> bool:
        return delete_item_for_db(self.db, public_id)

    def mark_items_used(self, item_ids: list[int], **kwargs: Any) -> None:
        return mark_items_used_for_db(self.db, item_ids, **kwargs)

    # jobs
    def create_job(self, **kwargs: Any) -> dict[str, Any]:
        return create_job_for_db(self.db, **kwargs)

    def get_job(self, public_id: str) -> dict[str, Any] | None:
        return get_job_for_db(self.db, public_id)

    def list_jobs(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list_jobs_for_db(self.db, **kwargs)

    def update_job_progress(self, public_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return update_job_progress_for_db(self.db, public_id, **kwargs)

    def mark_job_interrupted_at_startup(self) -> int:
        return mark_job_interrupted_at_startup(self.db)


__all__ = [
    # 纯函数 API
    "list_packages_for_db",
    "get_package_for_db",
    "create_package_for_db",
    "update_package_for_db",
    "delete_package_for_db",
    "create_source_for_db",
    "get_source_for_db",
    "list_sources_for_db",
    "update_source_status_for_db",
    "insert_chunks_for_db",
    "list_chunks_for_db",
    "update_chunk_status_for_db",
    "insert_item_for_db",
    "get_item_for_db",
    "get_item_by_id_for_db",
    "list_items_for_db",
    "update_item_for_db",
    "delete_item_for_db",
    "mark_items_used_for_db",
    "create_job_for_db",
    "get_job_for_db",
    "list_jobs_for_db",
    "update_job_progress_for_db",
    "mark_job_interrupted_at_startup",
    # 类
    "KnowledgeRepository",
]
