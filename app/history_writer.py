"""Bounded background queue that flushes entries to SQLite on a fixed interval.

W-PERF-MED-004 P-17: SQLite ``history`` rows are capped at ``DEFAULT_MAX_HISTORY_ROWS``
(oldest-by-id prune every ``PRUNE_EVERY_N_FLUSHES`` flushes).
"""

# W-CONC-001：flush 走 ConfigStore 写入临界区，避免主线程持锁时 database is locked 永久丢失

import logging
import sqlite3
import threading
from collections import deque
from datetime import datetime

_logger = logging.getLogger(__name__)

DEFAULT_HISTORY_BUFFER_MAX = 500
DEFAULT_MAX_HISTORY_ROWS = 10_000
PRUNE_EVERY_N_FLUSHES = 100


class HistoryWriter:
    def __init__(
        self,
        config,
        flush_interval: float = 2.0,
        buffer_max: int = DEFAULT_HISTORY_BUFFER_MAX,
        max_rows: int = DEFAULT_MAX_HISTORY_ROWS,
        prune_every: int = PRUNE_EVERY_N_FLUSHES,
    ):
        self.config = config
        self.flush_interval = flush_interval
        buffer_max = max(1, int(buffer_max))
        self._max_rows = max(1, int(max_rows))
        self._prune_every = max(1, int(prune_every))
        self._flush_count = 0
        self._buffer: deque[tuple] = deque(maxlen=buffer_max)
        self._dropped_total = 0
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="HistoryWriter")
        self._thread.start()

    @property
    def dropped_total(self) -> int:
        return self._dropped_total

    def buffer_size(self) -> int:
        with self._lock:
            return len(self._buffer)

    def enqueue(self, content: str, persona: str, round_num: int, image_bytes: bytes | None = None):
        """Buffer one history row. ``content`` must already match on-screen display (truncated)."""
        now = datetime.now().isoformat()
        with self._lock:
            if self._buffer.maxlen and len(self._buffer) >= self._buffer.maxlen:
                self._dropped_total += 1
                _logger.warning(
                    "history_writer buffer full: dropped=1 dropped_total=%s max_items=%s "
                    "reason=history_buffer_trim",
                    self._dropped_total,
                    self._buffer.maxlen,
                )
            self._buffer.append((now, persona, content, image_bytes, round_num))

    def _maybe_prune_rows(self) -> None:
        self._flush_count += 1
        if self._flush_count % self._prune_every != 0:
            return
        count = self.config.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        if count <= self._max_rows:
            return
        excess = count - self._max_rows
        self.config.conn.execute(
            "DELETE FROM history WHERE id IN "
            "(SELECT id FROM history ORDER BY id ASC LIMIT ?)",
            (excess,),
        )
        _logger.info(
            "history pruned rows=%d max_rows=%d remaining=%d",
            excess,
            self._max_rows,
            self._max_rows,
        )

    def flush(self):
        with self._lock:
            items = list(self._buffer)
            self._buffer.clear()
        if not items:
            return
        # W-CONC-001：通过 ConfigStore.with_write_lock() 与主线程 set/set_batch 共享
        # _write_lock，规避主线程持锁时本后台线程 executemany 抛 database is locked
        # 导致整批弹幕历史永久丢失（PRAGMA busy_timeout=5000 不足以覆盖截图/API 延宕）。
        # W-AUDIT-V2-BUG-007：commit/executemany 失败后须在持锁内 best-effort rollback，
        # 再回填 buffer；否则 active 事务未清，下次 flush 会重复 INSERT。
        rollback_ok = False
        try:
            with self.config.with_write_lock():
                try:
                    self.config.conn.executemany(
                        "INSERT INTO history (time, persona, content, image, round) VALUES (?,?,?,?,?)",
                        items,
                    )
                    self._maybe_prune_rows()
                    self.config.conn.commit()
                except sqlite3.Error:
                    try:
                        self.config.conn.rollback()
                        rollback_ok = True
                    except Exception:
                        _logger.exception(
                            "history flush rollback failed items=%d "
                            "reason=history_flush_rollback_failed; "
                            "items retained; connection may retain active transaction; "
                            "further writes may be unsafe",
                            len(items),
                        )
                    raise
        except sqlite3.Error:
            if rollback_ok:
                _logger.exception(
                    "history flush failed items=%d, will retry on next flush",
                    len(items),
                )
            else:
                _logger.exception(
                    "history flush failed items=%d; transaction not confirmed rolled back — "
                    "items retained, not claiming safe retry",
                    len(items),
                )
            # W-DATA-LOSS-001：回填失败批次到 buffer 队首，防止永久丢失
            with self._lock:
                for item in reversed(items):
                    if self._buffer.maxlen is None or len(self._buffer) < self._buffer.maxlen:
                        self._buffer.appendleft(item)
                    else:
                        self._dropped_total += 1
                        _logger.warning(
                            "history_writer retry backfill overflow: dropped=1 "
                            "dropped_total=%s max_items=%s reason=retry_backfill_trim",
                            self._dropped_total,
                            self._buffer.maxlen,
                        )

    def _run(self):
        while not self._stop_event.wait(self.flush_interval):
            self.flush()

    def stop(self):
        self._stop_event.set()
        self.flush()
        self._thread.join(timeout=3.0)
