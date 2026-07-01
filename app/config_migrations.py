"""ConfigStore schema 迁移注册表（轻量，非框架）。

现有 per-key 懒迁移（_resolve_custom_model_api_key / _migrate_custom_model_shape）
保留为运行期回退；本模块仅负责启动期 schema_version 推进。

W-SCHEMA-MIGRATION-FOUNDATION-001：当前 MIGRATIONS 为空，仅建立版本追踪基线，
零行为回归。后续新增 schema 变更时用 @register(version, name) 装饰器加迁移函数，
迁移函数接收已开事务的 conn，需自行保证幂等（CREATE TABLE IF NOT EXISTS 等）。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable, List, Tuple

if TYPE_CHECKING:
    import sqlite3

logger = logging.getLogger(__name__)

# (version, name, fn(conn)) —— fn 在已开连接内运行，需幂等。
MIGRATIONS: List[Tuple[int, str, Callable[["sqlite3.Connection"], None]]] = []


def register(version: int, name: str):
    """装饰器：注册一个 schema 迁移函数。

    Args:
        version: 正整数 schema 版本；迁移按 version 升序运行。
        name: 人类可读名称，仅用于日志。

    Returns:
        装饰器，原函数原样返回。
    """

    def deco(fn: Callable[["sqlite3.Connection"], None]) -> Callable:
        MIGRATIONS.append((version, name, fn))
        return fn

    return deco


def run_pending(conn: "sqlite3.Connection") -> int:
    """在已开连接内运行未应用的迁移；返回最终 schema_version。幂等。

    调用方需在已开连接后调用（ConfigStore.__init__ 已开连接 + PRAGMA 已设置）。
    不自行 commit；依赖调用方或 SQLite 自动提交（ConfigStore 用 autocommit 默认行为）。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key='schema_version'"
    ).fetchone()
    if row is None:
        # 首次初始化：写入 schema_version=0 基线
        conn.execute(
            "INSERT INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", "0"),
        )
        current = 0
    else:
        current = int(row[0])
    for version, name, fn in sorted(MIGRATIONS, key=lambda m: m[0]):
        if version <= current:
            continue
        logger.info("config.schema_migration running v%s %s", version, name)
        fn(conn)
        conn.execute(
            "REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            ("schema_version", str(version)),
        )
    return max([current] + [m[0] for m in MIGRATIONS])


__all__ = ["MIGRATIONS", "register", "run_pending"]
