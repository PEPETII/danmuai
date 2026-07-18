"""知识库 schema 迁移注册表（仿 ``app/config_migrations.py``）。

迁移函数签名 ``(conn, fts_backend) -> None``，需自行保证幂等
（``CREATE TABLE IF NOT EXISTS`` 等）。``fts_backend`` 由
``app.knowledge.database.KnowledgeDatabase`` 在打开连接后探测并传入，
用于决定是否创建 FTS5 虚拟表与使用何种 tokenizer。

FTS5 能力探测（``_detect_fts_backend``）使用独立 ``:memory:`` 连接，
避免污染实际业务连接的事务状态。
"""
from __future__ import annotations

import logging
import sqlite3
from typing import Callable, List, Tuple

logger = logging.getLogger(__name__)

# (version, name, fn(conn, fts_backend)) —— fn 在已开连接内运行，需幂等。
MIGRATIONS: List[Tuple[int, str, Callable[[sqlite3.Connection, str], None]]] = []


def register(version: int, name: str):
    """装饰器：注册一个知识库 schema 迁移函数。

    Args:
        version: 正整数 schema 版本；迁移按 version 升序运行。
        name: 人类可读名称，仅用于日志。

    Returns:
        装饰器，原函数原样返回。
    """

    def deco(fn: Callable[[sqlite3.Connection, str], None]):
        MIGRATIONS.append((version, name, fn))
        return fn

    return deco


def _detect_fts_backend(conn: sqlite3.Connection) -> str:
    """探测 SQLite FTS5 能力（用独立内存连接探测，避免污染实际连接）。

    Returns:
        'trigram' — FTS5 + trigram tokenizer 可用（首选，支持中文子串匹配）
        'fts5'    — FTS5 可用但 trigram 不可用（用默认 porter tokenizer）
        'fallback' — FTS5 不可用，检索改用 search_text LIKE ? + Python 打分

    ``conn`` 参数仅用于复用同一 sqlite3 模块；探测本身在 ``:memory:`` 连接上
    执行，避免在业务连接上 CREATE/DROP 虚拟表产生事务副作用。
    """
    # 参数 conn 仅用于复用 sqlite3 模块；不直接在业务连接上探测。
    del conn  # noqa: ARG001 — 显式标注不用
    probe = sqlite3.connect(":memory:")
    try:
        try:
            probe.execute("CREATE VIRTUAL TABLE _t USING fts5(c)")
        except sqlite3.OperationalError:
            return "fallback"
        try:
            probe.execute("CREATE VIRTUAL TABLE _t2 USING fts5(c, tokenize='trigram')")
            return "trigram"
        except sqlite3.OperationalError:
            return "fts5"
    finally:
        probe.close()


def run_pending(conn: sqlite3.Connection, *, fts_backend: str | None = None) -> int:
    """在已开连接内运行未应用的迁移；返回最终 schema_version。幂等。

    Args:
        conn: 已开 PRAGMA 的业务连接。
        fts_backend: FTS5 能力标识（'trigram'/'fts5'/'fallback'）；
            若为 None 则在此函数内探测（会额外开 ``:memory:`` 连接）。

    Returns:
        最终 schema_version（max(已应用, 已注册)）。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", "0"),
        )
        current = 0
    else:
        current = int(row[0])
    if fts_backend is None:
        fts_backend = _detect_fts_backend(conn)
    for version, name, fn in sorted(MIGRATIONS, key=lambda m: m[0]):
        if version <= current:
            continue
        logger.info("knowledge.schema_migration running v%s %s", version, name)
        fn(conn, fts_backend)
        conn.execute(
            "REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(version)),
        )
    return max([current] + [m[0] for m in MIGRATIONS])


@register(1, "initial_schema")
def _migrate_v1_initial_schema(conn: sqlite3.Connection, fts_backend: str) -> None:
    """v1：创建 5 张主表 + FTS5 虚拟表（若可用）+ 索引。

    表结构严格对齐 ``docs/DanmuAI_知识包功能_实现说明(1).md`` §5.2。
    FOREIGN KEY 仅作声明性文档（项目未启用 ``PRAGMA foreign_keys``），
    级联删除在应用层单事务内执行（见 ``repository.delete_package_for_db``）。
    """
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS knowledge_packages (
            id                  INTEGER PRIMARY KEY,
            public_id           TEXT UNIQUE NOT NULL,
            name                TEXT NOT NULL,
            description         TEXT NOT NULL DEFAULT '',
            content_kind        TEXT NOT NULL DEFAULT 'auto',
            scope_mode          TEXT NOT NULL DEFAULT 'global',
            scope_tags_json     TEXT NOT NULL DEFAULT '[]',
            enabled             INTEGER NOT NULL DEFAULT 1,
            priority            INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS knowledge_sources (
            id                  INTEGER PRIMARY KEY,
            public_id           TEXT UNIQUE NOT NULL,
            package_id          INTEGER NOT NULL,
            source_type         TEXT NOT NULL,
            display_name        TEXT NOT NULL,
            source_url          TEXT,
            raw_text            TEXT NOT NULL DEFAULT '',
            normalized_text     TEXT NOT NULL DEFAULT '',
            content_hash        TEXT NOT NULL,
            status              TEXT NOT NULL,
            error_message       TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            FOREIGN KEY(package_id) REFERENCES knowledge_packages(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS knowledge_chunks (
            id                  INTEGER PRIMARY KEY,
            source_id           INTEGER NOT NULL,
            sequence_no         INTEGER NOT NULL,
            heading             TEXT NOT NULL DEFAULT '',
            content             TEXT NOT NULL,
            content_hash        TEXT NOT NULL,
            status              TEXT NOT NULL DEFAULT 'pending',
            error_message       TEXT NOT NULL DEFAULT '',
            FOREIGN KEY(source_id) REFERENCES knowledge_sources(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS knowledge_items (
            id                  INTEGER PRIMARY KEY,
            public_id           TEXT UNIQUE NOT NULL,
            package_id          INTEGER NOT NULL,
            source_id           INTEGER NOT NULL,
            chunk_id            INTEGER,
            kind                TEXT NOT NULL,
            title               TEXT NOT NULL,
            content             TEXT NOT NULL,
            examples_json       TEXT NOT NULL DEFAULT '[]',
            triggers_json       TEXT NOT NULL DEFAULT '[]',
            tones_json          TEXT NOT NULL DEFAULT '[]',
            scopes_json         TEXT NOT NULL DEFAULT '[]',
            entities_json       TEXT NOT NULL DEFAULT '[]',
            search_text         TEXT NOT NULL,
            confidence          REAL NOT NULL DEFAULT 1.0,
            evidence            TEXT NOT NULL DEFAULT '',
            content_hash        TEXT NOT NULL,
            enabled             INTEGER NOT NULL DEFAULT 1,
            priority            INTEGER NOT NULL DEFAULT 0,
            last_used_at        TEXT,
            use_count           INTEGER NOT NULL DEFAULT 0,
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            FOREIGN KEY(package_id) REFERENCES knowledge_packages(id) ON DELETE CASCADE,
            FOREIGN KEY(source_id) REFERENCES knowledge_sources(id) ON DELETE CASCADE,
            FOREIGN KEY(chunk_id) REFERENCES knowledge_chunks(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS knowledge_jobs (
            id                  INTEGER PRIMARY KEY,
            public_id           TEXT UNIQUE NOT NULL,
            package_id          INTEGER NOT NULL,
            source_id           INTEGER NOT NULL,
            status              TEXT NOT NULL,
            stage               TEXT NOT NULL,
            total_chunks        INTEGER NOT NULL DEFAULT 0,
            processed_chunks    INTEGER NOT NULL DEFAULT 0,
            failed_chunks       INTEGER NOT NULL DEFAULT 0,
            generated_items     INTEGER NOT NULL DEFAULT 0,
            deduplicated_items  INTEGER NOT NULL DEFAULT 0,
            input_tokens        INTEGER NOT NULL DEFAULT 0,
            output_tokens       INTEGER NOT NULL DEFAULT 0,
            error_message       TEXT NOT NULL DEFAULT '',
            created_at          TEXT NOT NULL,
            updated_at          TEXT NOT NULL,
            finished_at         TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_packages_enabled ON knowledge_packages(enabled);
        CREATE INDEX IF NOT EXISTS idx_sources_package ON knowledge_sources(package_id);
        CREATE INDEX IF NOT EXISTS idx_chunks_source ON knowledge_chunks(source_id);
        CREATE INDEX IF NOT EXISTS idx_items_package ON knowledge_items(package_id);
        CREATE INDEX IF NOT EXISTS idx_items_source ON knowledge_items(source_id);
        CREATE INDEX IF NOT EXISTS idx_items_chunk ON knowledge_items(chunk_id);
        CREATE INDEX IF NOT EXISTS idx_items_kind ON knowledge_items(kind);
        CREATE INDEX IF NOT EXISTS idx_items_enabled ON knowledge_items(enabled);
        CREATE INDEX IF NOT EXISTS idx_jobs_package ON knowledge_jobs(package_id);
        CREATE INDEX IF NOT EXISTS idx_jobs_source ON knowledge_jobs(source_id);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON knowledge_jobs(status);
        """
    )

    # FTS5 虚拟表（external-content 表，仅在 FTS5 可用时创建）。
    # trigram 优先（支持中文子串匹配），普通 porter 次之，不可用时不创建。
    if fts_backend == "trigram":
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_items_fts USING fts5("
                "title, content, search_text, "
                "content='knowledge_items', content_rowid='id', "
                "tokenize='trigram'"
                ")"
            )
        except sqlite3.OperationalError as exc:
            logger.warning("knowledge.fts5 trigram creation failed: %s", exc)
    elif fts_backend == "fts5":
        try:
            conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_items_fts USING fts5("
                "title, content, search_text, "
                "content='knowledge_items', content_rowid='id'"
                ")"
            )
        except sqlite3.OperationalError as exc:
            logger.warning("knowledge.fts5 plain creation failed: %s", exc)


__all__ = [
    "MIGRATIONS",
    "register",
    "run_pending",
    "_detect_fts_backend",
]
