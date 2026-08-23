"""知识包独立 SQLite 数据库（与 ``config.db`` 物理隔离）。

连接契约：一个 :class:`KnowledgeDatabase` 是数据库生命周期 owner，而不是一条可跨
线程共享的 sqlite connection。每个访问线程按需取得自己的连接；所有连接使用相同的
WAL、busy timeout、row factory 和 migration 后 schema。写事务仍由单一写锁串行化，
读操作通过 ``read_connection()`` 登记在生命周期闸门中。关闭时先拒绝新访问，等待
已登记的读/写访问退出，再关闭全部连接。
"""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.knowledge.migrations import _detect_fts_backend, run_pending

KNOWLEDGE_DB_PATH = Path(os.environ.get("APPDATA", ".")) / "DanmuAI" / "knowledge.db"
_SQLITE_CACHED_STATEMENTS = 256


class KnowledgeDatabase:
    """知识库 SQLite 生命周期 owner。

    ``conn`` 仅保留给已处于 ``read_connection`` 或 ``with_write_lock`` 访问范围内的
    repository 代码使用；它返回当前线程专属连接，不会再返回跨线程共享连接。
    """

    def __init__(
        self,
        path: Path,
        fts_backend: str,
        bootstrap_connection: sqlite3.Connection,
    ) -> None:
        self.path = path
        self.fts_backend = fts_backend
        self._write_lock = threading.Lock()
        self._state = threading.Condition(threading.Lock())
        self._connections: dict[int, sqlite3.Connection] = {
            threading.get_ident(): bootstrap_connection
        }
        self._active_accesses = 0
        self._closed = False

    @staticmethod
    def _new_connection(
        path: Path, *, initialize_wal: bool = False
    ) -> sqlite3.Connection:
        """创建并完整初始化一条线程专属连接。"""
        conn = sqlite3.connect(
            str(path),
            # 连接绝不在业务路径跨线程使用；关闭由数据库生命周期 owner 统一执行。
            check_same_thread=False,
            cached_statements=_SQLITE_CACHED_STATEMENTS,
        )
        conn.row_factory = sqlite3.Row
        # WAL 是数据库级持久设置；仅启动连接切换模式。每个后续连接仍会看到
        # 同一 WAL 模式，但避免在正在运行的读/写之间重复执行会请求排他锁的 PRAGMA。
        if initialize_wal:
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @classmethod
    def _detect_fts_backend(cls, conn: sqlite3.Connection) -> str:
        return _detect_fts_backend(conn)

    @classmethod
    def open(cls) -> "KnowledgeDatabase":
        return cls._open_at(KNOWLEDGE_DB_PATH)

    @classmethod
    def _open_at(cls, path: Path | str) -> "KnowledgeDatabase":
        """在指定路径打开数据库，并只在启动连接上执行幂等迁移。"""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        bootstrap_connection = cls._new_connection(path, initialize_wal=True)
        try:
            fts_backend = _detect_fts_backend(bootstrap_connection)
            run_pending(bootstrap_connection, fts_backend=fts_backend)
            # migration 可能留下隐式事务；在向其他线程暴露数据库前必须提交，
            # 否则首个 Web/worker 写连接会被启动连接自身锁住。
            bootstrap_connection.commit()
        except Exception:
            bootstrap_connection.close()
            raise
        return cls(path, fts_backend, bootstrap_connection)

    def _connection_for_current_thread(self) -> sqlite3.Connection:
        thread_id = threading.get_ident()
        with self._state:
            if self._closed:
                raise RuntimeError("knowledge database is closed")
            conn = self._connections.get(thread_id)
            if conn is None:
                conn = self._new_connection(self.path)
                self._connections[thread_id] = conn
            return conn

    @property
    def conn(self) -> sqlite3.Connection:
        """返回当前线程连接；调用方必须由数据库访问上下文包裹。"""
        return self._connection_for_current_thread()

    @contextmanager
    def read_connection(self) -> Iterator[sqlite3.Connection]:
        """登记一个读访问，使 ``close()`` 能等待其完成。"""
        with self._state:
            if self._closed:
                raise RuntimeError("knowledge database is closed")
            thread_id = threading.get_ident()
            conn = self._connections.get(thread_id)
            if conn is None:
                conn = self._new_connection(self.path)
                self._connections[thread_id] = conn
            self._active_accesses += 1
        try:
            yield conn
        finally:
            with self._state:
                self._active_accesses -= 1
                if self._active_accesses == 0:
                    self._state.notify_all()

    @contextmanager
    def with_write_lock(self) -> Iterator[None]:
        """串行化一个完整写事务，并将其纳入关闭闸门。"""
        with self._write_lock:
            with self.read_connection():
                yield

    def close(self) -> None:
        """幂等关闭：拒绝新访问、排空已登记访问、关闭全部线程连接。"""
        with self._state:
            if self._closed:
                return
            self._closed = True
            while self._active_accesses:
                self._state.wait()
            connections = list(self._connections.values())
            self._connections.clear()
        for conn in connections:
            try:
                conn.close()
            except sqlite3.ProgrammingError:
                # sqlite3.close 已幂等；兼容测试替身或外部提前关闭的连接。
                pass


__all__ = ["KnowledgeDatabase", "KNOWLEDGE_DB_PATH"]
