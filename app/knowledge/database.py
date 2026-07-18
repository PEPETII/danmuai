"""知识包独立 SQLite 数据库（与 ``config.db`` 物理隔离）。

设计要点（对齐 spec §5.1 与 AGENTS.md §A.5.1）：
- **%APPDATA%/DanmuAI/knowledge.db** 持久化；不与 ConfigStore 共享连接。
- **WAL + busy_timeout=5000**，**不**启用 ``PRAGMA foreign_keys``（项目约定；
  级联删除在应用层单事务内执行，见 ``repository.delete_package_for_db``）。
- **非可重入 threading.Lock() 写锁**（与 ``ConfigStore._write_lock`` 一致）；
  任何递归回调内再次获取会自死锁。新增写方法时须确认调用链无持锁递归。
- **check_same_thread=False, cached_statements=256**：跨线程共享连接，
  依赖写锁串行化写、WAL 允许并发读。
- **FTS5 能力探测**：trigram → fts5 → fallback，运行时确定（见
  ``migrations._detect_fts_backend``）。
- **schema_meta + run_pending** 迁移机制（仿 ``app/config_migrations.py``）。
- **row_factory = sqlite3.Row**：repository 函数可直接 ``dict(row)`` 取字段。

调用方：``KnowledgeRepository``、后续 ``KnowledgeRetriever`` / ``ImportOrchestrator``。
"""
from __future__ import annotations

import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from app.knowledge.migrations import _detect_fts_backend, run_pending

logger = logging.getLogger(__name__)

# %APPDATA%/DanmuAI/knowledge.db（与 config.db 同目录、不同文件）
KNOWLEDGE_DB_PATH = Path(os.environ.get("APPDATA", ".")) / "DanmuAI" / "knowledge.db"
# Python 3.12 默认 cached_statements=128；显式放大以覆盖知识条目高频查询变体。
_SQLITE_CACHED_STATEMENTS = 256


class KnowledgeDatabase:
    """知识包 SQLite 数据库门面。

    **非可重入写锁**：``self._write_lock`` 是 ``threading.Lock()``（**非** ``RLock``）。
    任何在写锁内回调其他持锁方法的代码会自死锁。新增写方法时须确认调用链
    无持锁递归（与 ``ConfigStore._write_lock`` 约定一致，AGENTS.md §A.5.1）。

    线程模型：
        - 主线程持有 ``KnowledgeDatabase`` 实例；
        - 导入任务线程与检索线程通过同一实例访问；
        - 写操作由 ``_write_lock`` 串行化；
        - 读操作不持锁，依赖 WAL 不阻塞写。
    """

    def __init__(self, path: Path, conn: sqlite3.Connection, fts_backend: str):
        self.path = path
        self.conn = conn
        self.fts_backend = fts_backend
        # 非可重入写锁（与 ConfigStore 一致）；递归获取会自死锁。
        self._write_lock = threading.Lock()
        self._closed = False

    # ------------------------------------------------------------------
    # 工厂
    # ------------------------------------------------------------------

    @classmethod
    def _detect_fts_backend(cls, conn: sqlite3.Connection) -> str:
        """探测 SQLite FTS5 能力，返回 'trigram' / 'fts5' / 'fallback'。

        委托 ``migrations._detect_fts_backend``（在独立 ``:memory:`` 连接探测，
        不污染业务连接）。
        """
        return _detect_fts_backend(conn)

    @classmethod
    def open(cls) -> "KnowledgeDatabase":
        """打开默认路径的知识库（``%APPDATA%/DanmuAI/knowledge.db``）。

        首次启动时创建文件、应用 PRAGMA、运行迁移；不抛异常。
        """
        return cls._open_at(KNOWLEDGE_DB_PATH)

    @classmethod
    def _open_at(cls, path: Path | str) -> "KnowledgeDatabase":
        """在指定路径打开知识库（测试用）。

        Args:
            path: 数据库文件路径；父目录会自动创建。

        Returns:
            已完成 PRAGMA + 迁移的 ``KnowledgeDatabase`` 实例。
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            str(path),
            check_same_thread=False,
            cached_statements=_SQLITE_CACHED_STATEMENTS,
        )
        # row_factory = sqlite3.Row：repository 函数可直接 dict(row) 取字段。
        conn.row_factory = sqlite3.Row
        # WAL：读不阻塞写、写不阻塞读；导入任务线程与检索线程并发场景减少
        # database is locked。
        conn.execute("PRAGMA journal_mode=WAL")
        # 写冲突时等待最多 5s 而非立即失败（与 _write_lock 双保险）。
        conn.execute("PRAGMA busy_timeout=5000")
        # 不启用 PRAGMA foreign_keys（项目约定；级联删除在应用层执行）。
        fts_backend = _detect_fts_backend(conn)
        run_pending(conn, fts_backend=fts_backend)
        return cls(path, conn, fts_backend)

    # ------------------------------------------------------------------
    # 写锁
    # ------------------------------------------------------------------

    @contextmanager
    def with_write_lock(self):
        """获取写锁的上下文管理器。

        **非可重入**：在 with 块内再次获取会自死锁。写方法应在此上下文内
        执行 REPLACE/INSERT/DELETE/UPDATE + commit。

        与 ``ConfigStore._write_lock`` 一致：所有写操作串行化，保证事务原子性
        与 FTS 索引同步的一致性。
        """
        with self._write_lock:
            yield

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    def close(self) -> None:
        """关闭连接（在写锁内完成，避免并发写丢失，仿 ``ConfigStore.close``）。

        BUG-016 同款修复：conn.close() 必须在写锁内完成，否则并发写会在
        close 出锁后、conn.close() 完成前拿到锁并丢写。
        """
        with self._write_lock:
            self._closed = True
            try:
                self.conn.close()
            except sqlite3.ProgrammingError:
                pass


__all__ = ["KnowledgeDatabase", "KNOWLEDGE_DB_PATH"]
