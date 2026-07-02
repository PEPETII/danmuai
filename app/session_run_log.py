"""Completed danmu guard sessions (start → stop); persisted in config.db when configured.

每一轮 start → stop 记一条 session_run（start_at/end_at/runtime_sec/danmu_count/input_tokens/output_tokens/
persona_set 等字段），存于 config.db 的 ``session_runs`` 表（最近 100 条，超出时按 end_at 截断）。

约束：必须在 ``DanmuApp.quit()`` 同步 flush；进程被 kill 时 SQLite 可能丢本条记录，开发者需
接受这个不完美（不主动写 retry）。
"""

from __future__ import annotations

import logging
import sqlite3
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from app.config_store import ConfigStore


@dataclass(frozen=True)
class SessionRunRecord:
    started_at: float
    ended_at: float
    model: str
    input_tokens: int
    output_tokens: int
    danmu_count: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["total_tokens"] = self.total_tokens
        return data


class SessionRunLog:
    def __init__(self, config: ConfigStore | None = None, max_entries: int = 100) -> None:
        self._config = config
        self._max = max(1, max_entries)
        self._entries: list[SessionRunRecord] = []
        self._pending_started_at: float = 0.0
        self._pending_model: str = ""
        if self._config is not None:
            self._load_recent()

    def begin(self, *, started_at: float, model: str) -> None:
        self._pending_started_at = started_at
        self._pending_model = model or ""

    def complete(
        self,
        *,
        ended_at: float,
        input_tokens: int,
        output_tokens: int,
        danmu_count: int,
    ) -> SessionRunRecord | None:
        if input_tokens < 0 or output_tokens < 0 or danmu_count < 0:
            raise ValueError("session run counters must be non-negative")
        if self._pending_started_at <= 0:
            return None
        rec = SessionRunRecord(
            started_at=self._pending_started_at,
            ended_at=ended_at,
            model=self._pending_model,
            input_tokens=max(0, input_tokens),
            output_tokens=max(0, output_tokens),
            danmu_count=max(0, danmu_count),
        )
        self._entries.append(rec)
        if len(self._entries) > self._max:
            self._entries = self._entries[-self._max :]
        self._pending_started_at = 0.0
        self._pending_model = ""
        self._persist(rec)
        return rec

    def list_dicts_newest_first(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in reversed(self._entries)]

    def _load_recent(self) -> None:
        config = self._config
        if config is None:
            return
        rows = config.conn.execute(
            "SELECT started_at, ended_at, model, input_tokens, output_tokens, danmu_count "
            "FROM session_runs ORDER BY ended_at DESC LIMIT ?",
            (self._max,),
        ).fetchall()
        loaded: list[SessionRunRecord] = []
        for row in reversed(rows):
            loaded.append(
                SessionRunRecord(
                    started_at=float(row[0]),
                    ended_at=float(row[1]),
                    model=row[2] or "",
                    input_tokens=int(row[3]),
                    output_tokens=int(row[4]),
                    danmu_count=int(row[5]),
                )
            )
        self._entries = loaded

    def _persist(self, rec: SessionRunRecord) -> None:
        config = self._config
        if config is None:
            return
        try:
            with config._write_lock:
                config.conn.execute(
                    "INSERT INTO session_runs "
                    "(started_at, ended_at, model, input_tokens, output_tokens, danmu_count) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        rec.started_at,
                        rec.ended_at,
                        rec.model,
                        rec.input_tokens,
                        rec.output_tokens,
                        rec.danmu_count,
                    ),
                )
                excess = config.conn.execute("SELECT COUNT(*) FROM session_runs").fetchone()
                count = int(excess[0]) if excess else 0
                if count > self._max:
                    trim = count - self._max
                    config.conn.execute(
                        "DELETE FROM session_runs WHERE id IN ("
                        "SELECT id FROM session_runs ORDER BY ended_at ASC LIMIT ?"
                        ")",
                        (trim,),
                    )
                config.conn.commit()
        except sqlite3.DatabaseError as exc:
            try:
                config.conn.rollback()
            except sqlite3.Error:
                pass
            logger.error(
                "session_run persist failed model=%s error=%s",
                rec.model,
                exc,
            )
