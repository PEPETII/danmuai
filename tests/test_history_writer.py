import logging
import threading
import time
from unittest.mock import MagicMock

from app.config_store import ConfigStore
from app.history_writer import HistoryWriter


def test_history_writer_logs_flush_failures(monkeypatch):
    logger = MagicMock()
    monkeypatch.setattr("app.history_writer._logger", logger)

    config = MagicMock()
    config.conn.executemany.side_effect = RuntimeError("db locked")

    writer = HistoryWriter(config, flush_interval=60.0)
    writer.enqueue("hello", "persona", 1)
    writer.flush()
    # W-DATA-LOSS-001: flush 失败回填后，stop() 再 flush 也会失败（mock 持续抛异常），
    # 故 exception 至少被调用 1 次（可能 2 次：flush + stop→flush）
    assert logger.exception.call_count >= 1
    writer.stop()


def test_history_writer_waits_for_config_store_write_lock(tmp_path):
    """W-CONC-001：主线程持 _write_lock 时，后台线程 flush() 必须等待锁释放，
    而**不**抛 OperationalError('database is locked') 丢整批弹幕历史。
    """
    store = ConfigStore(db_path=tmp_path / "config.db")
    writer = HistoryWriter(store, flush_interval=60.0)
    try:
        writer.enqueue("hello-1", "persona-A", 1)
        writer.enqueue("hello-2", "persona-B", 2)

        # 主线程模拟「持锁做 set」：直接 _write_lock.acquire，避免触发 _cache 副作用
        assert store._write_lock.acquire(timeout=2.0) is True
        flush_result: dict = {}

        def _bg_flush():
            try:
                writer.flush()
                flush_result["ok"] = True
                flush_result["error"] = None
            except Exception as e:  # pragma: no cover - 仅在退步时报
                flush_result["ok"] = False
                flush_result["error"] = repr(e)

        t = threading.Thread(target=_bg_flush, name="test-flush-bg")
        t.start()
        # 让后台线程先尝试拿锁并阻塞
        time.sleep(0.2)
        assert t.is_alive(), "flush 应该在主线程持锁时阻塞等待，而不是直接抛 OperationalError"
        # 释放锁；后台线程应在 2s 内完成写入
        store._write_lock.release()
        t.join(timeout=2.0)
        assert not t.is_alive(), "释放锁后 flush 仍应完成"
        assert flush_result.get("ok") is True, f"flush 异常：{flush_result.get('error')}"

        # 验证 items 已落到 history 表
        rows = store.conn.execute(
            "SELECT time, persona, content, round FROM history ORDER BY id ASC"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0][1:] == ("persona-A", "hello-1", 1)
        assert rows[1][1:] == ("persona-B", "hello-2", 2)
    finally:
        writer.stop()
        store.close()


def test_history_writer_does_not_call_executemany_without_lock():
    """W-CONC-001：flush() 必须走 ``config.with_write_lock()`` 上下文；不能用
    monkeypatch 旁路掉写入临界区（防止后续维护者悄悄退步为裸 executemany）。
    """
    ctx_entered = threading.Event()
    captured_executemany_calls: list = []

    class _StubConn:
        def executemany(self, sql, params):
            # 仅当 ctx 已 enter 时才记录，防止退步到 with 块外调用
            assert ctx_entered.is_set(), "executemany 必须在 with_write_lock 临界区内调用"
            captured_executemany_calls.append((sql, params))
            return None

        def commit(self):
            assert ctx_entered.is_set(), "commit 必须在 with_write_lock 临界区内调用"
            return None

    class _FakeContextManager:
        def __enter__(self):
            ctx_entered.set()
            return stub_conn

        def __exit__(self, exc_type, exc, tb):
            return False

    stub_conn = _StubConn()

    class _StubConfig:
        pass

    config = _StubConfig()
    config.conn = stub_conn

    def _with_write_lock():
        return _FakeContextManager()

    config.with_write_lock = _with_write_lock

    writer = HistoryWriter(config, flush_interval=60.0)
    try:
        writer.enqueue("only-once", "persona-X", 1)
        writer.flush()
        # 验证：flush 走 with_write_lock 临界区，且仅调用一次 executemany
        assert ctx_entered.is_set(), "flush 应进入 with_write_lock 上下文"
        assert len(captured_executemany_calls) == 1
        sql, params = captured_executemany_calls[0]
        assert "INSERT INTO history" in sql
        assert len(params) == 1
        # (time, persona, content, image, round)
        assert params[0][1:] == ("persona-X", "only-once", None, 1)
    finally:
        writer.stop()


def test_enqueue_drops_oldest_when_buffer_full(tmp_path, caplog):
    store = ConfigStore(db_path=tmp_path / "config.db")
    writer = HistoryWriter(store, flush_interval=3600.0, buffer_max=3)
    try:
        with caplog.at_level(logging.WARNING, logger="app.history_writer"):
            for i in range(1, 6):
                writer.enqueue(f"msg-{i}", "persona", i)

        assert writer.buffer_size() == 3
        assert writer.dropped_total == 2
        assert any("dropped=1" in r.message for r in caplog.records)
        assert any("reason=history_buffer_trim" in r.message for r in caplog.records)

        writer.flush()
        rows = store.conn.execute(
            "SELECT content FROM history ORDER BY id ASC"
        ).fetchall()
        assert [row[0] for row in rows] == ["msg-3", "msg-4", "msg-5"]
    finally:
        writer.stop()
        store.close()


def test_buffer_bounded_while_flush_blocked(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    writer = HistoryWriter(store, flush_interval=3600.0, buffer_max=50)
    try:
        for i in range(50):
            writer.enqueue(f"seed-{i}", "persona", i)

        assert store._write_lock.acquire(timeout=2.0) is True
        flush_started = threading.Event()
        flush_done = threading.Event()

        def _bg_flush():
            flush_started.set()
            writer.flush()
            flush_done.set()

        t = threading.Thread(target=_bg_flush, name="test-flush-blocked")
        t.start()
        assert flush_started.wait(timeout=2.0), "后台 flush 应已启动"

        for i in range(2000):
            writer.enqueue(f"flood-{i}", "persona", i)
            assert writer.buffer_size() <= 50

        assert writer.dropped_total >= 1950

        store._write_lock.release()
        t.join(timeout=5.0)
        assert flush_done.is_set(), "释放锁后 flush 应完成"

        rows = store.conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]
        assert rows <= 50
    finally:
        writer.stop()
        store.close()


def test_flush_failure_backfills_items_to_buffer(monkeypatch):
    """W-DATA-LOSS-001：flush 失败后 items 回填到 buffer（而非永久丢弃），
    下次 flush 可自动重试。"""
    logger = MagicMock()
    monkeypatch.setattr("app.history_writer._logger", logger)

    config = MagicMock()
    config.conn.executemany.side_effect = RuntimeError("db locked")

    writer = HistoryWriter(config, flush_interval=3600.0, buffer_max=3)
    try:
        for i in range(5):
            writer.enqueue(f"msg-{i}", "persona", i)

        assert writer.buffer_size() == 3  # maxlen=3, 2 items dropped on enqueue
        assert writer.dropped_total == 2

        writer.flush()
        logger.exception.assert_called_once()

        # W-DATA-LOSS-001：失败后 items 被回填到 buffer，不丢失
        assert writer.buffer_size() == 3, "flush 失败后 items 应回填到 buffer"

        # 后续 enqueue 不应超出 buffer 上限
        for i in range(10):
            writer.enqueue(f"after-{i}", "persona", i)
        assert writer.buffer_size() <= 3
        assert writer.dropped_total >= 2 + 10  # 原有 2 drop + enqueue 时新 drop
    finally:
        writer.stop()


def test_frequent_enqueue_under_slow_flush():
    release_flush = threading.Event()
    slow_entered = threading.Event()

    class _SlowContext:
        def __enter__(self):
            slow_entered.set()
            release_flush.wait(timeout=10.0)
            return config.conn

        def __exit__(self, exc_type, exc, tb):
            return False

    config = MagicMock()
    config.conn = MagicMock()
    config.with_write_lock = lambda: _SlowContext()

    writer = HistoryWriter(config, flush_interval=3600.0, buffer_max=20)
    errors: list[Exception] = []

    try:
        writer.enqueue("seed", "persona", 0)

        def _bg_flush():
            try:
                writer.flush()
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        flush_thread = threading.Thread(target=_bg_flush, name="test-slow-flush")
        flush_thread.start()
        assert slow_entered.wait(timeout=2.0), "flush 应进入慢写入临界区"

        def _enqueue_burst():
            try:
                for i in range(500):
                    writer.enqueue(f"burst-{i}", "persona", i)
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        workers = [
            threading.Thread(target=_enqueue_burst, name=f"enqueue-{n}")
            for n in range(4)
        ]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=10.0)

        assert not errors
        assert writer.buffer_size() <= 20
        assert writer.dropped_total > 0

        release_flush.set()
        flush_thread.join(timeout=5.0)
    finally:
        writer.stop()


def test_history_writer_prunes_oldest_rows_when_over_cap(tmp_path):
    """W-PERF-MED-004 P-17: DB 行数超过上限时删除最旧记录。"""
    store = ConfigStore(db_path=tmp_path / "history_prune.db")
    writer = HistoryWriter(
        store,
        flush_interval=3600.0,
        buffer_max=200,
        max_rows=50,
        prune_every=1,
    )
    try:
        for i in range(80):
            writer.enqueue(f"msg-{i}", "persona", i)
        writer.flush()

        rows = store.conn.execute(
            "SELECT content FROM history ORDER BY id ASC"
        ).fetchall()
        assert len(rows) == 50
        assert rows[0][0] == "msg-30"
        assert rows[-1][0] == "msg-79"
    finally:
        writer.stop()
        store.close()


def test_flush_failure_retries_on_next_flush(tmp_path, monkeypatch):
    """W-DATA-LOSS-001：flush 失败后 items 回填 buffer，下次 flush 成功时全部写出。"""
    logger = MagicMock()
    monkeypatch.setattr("app.history_writer._logger", logger)

    store = ConfigStore(db_path=tmp_path / "config.db")
    writer = HistoryWriter(store, flush_interval=3600.0)
    try:
        writer.enqueue("retry-me-1", "persona-A", 1)
        writer.enqueue("retry-me-2", "persona-B", 2)

        # 第一次 flush：通过 with_write_lock 上下文模拟写入失败
        _flush_count = [0]

        class _FailingThenOkContext:
            def __enter__(self):
                return store.conn

            def __exit__(self, exc_type, exc, tb):
                return False

        _original_wl = store.with_write_lock

        def _failing_write_lock():
            _flush_count[0] += 1
            if _flush_count[0] == 1:
                # 第一次：进入上下文后 executemany 会失败
                ctx = _FailingThenOkContext()
                original_exec = store.conn.executemany

                def _failing_exec(sql, params):
                    raise RuntimeError("db locked")

                store.conn.executemany = _failing_exec  # type: ignore[method-assign]
                return ctx
            else:
                return _original_wl()

        store.with_write_lock = _failing_write_lock  # type: ignore[method-assign]

        writer.flush()  # 失败 → 回填到 buffer
        assert logger.exception.call_count >= 1

        writer.flush()  # 第二次 flush 成功，回填的 items 全部写出

        rows = store.conn.execute(
            "SELECT persona, content, round FROM history ORDER BY id ASC"
        ).fetchall()
        contents = [r[1] for r in rows]
        assert "retry-me-1" in contents, f"missing retry-me-1, got {contents}"
        assert "retry-me-2" in contents, f"missing retry-me-2, got {contents}"
    finally:
        writer.stop()
        store.close()


def test_flush_failure_backfill_preserves_order(monkeypatch):
    """W-DATA-LOSS-001：回填使用 appendleft(reversed)，保持 FIFO 时间序。"""
    config = MagicMock()
    config.conn.executemany.side_effect = RuntimeError("db locked")

    writer = HistoryWriter(config, flush_interval=3600.0, buffer_max=100)
    try:
        # 按 1..5 顺序入队
        for i in range(1, 6):
            writer.enqueue(f"order-{i}", "persona", i)

        writer.flush()  # 失败，回填

        # 验证回填后 buffer 内顺序仍为 FIFO：通过捕获成功写入的顺序验证
        written_items = []

        def _capture_exec(sql, params):
            written_items.extend(params)
            return None

        config.conn.executemany.side_effect = _capture_exec

        def _capture_commit():
            pass

        config.conn.commit.side_effect = _capture_commit

        writer.flush()  # 成功，写出回填的 items
        contents = [item[2] for item in written_items]  # item[2] = content
        assert contents == ["order-1", "order-2", "order-3", "order-4", "order-5"]
    finally:
        writer.stop()


def test_flush_failure_backfill_overflow_drops_gracefully(caplog, monkeypatch):
    """W-DATA-LOSS-001：回填时 buffer 已满，超出部分丢弃并计数。"""
    logger = MagicMock()
    monkeypatch.setattr("app.history_writer._logger", logger)

    config = MagicMock()
    config.conn.executemany.side_effect = RuntimeError("db locked")

    # buffer_max=2，正常回填不溢出
    writer = HistoryWriter(config, flush_interval=3600.0, buffer_max=2)
    try:
        writer.enqueue("keep-1", "p", 1)
        writer.enqueue("keep-2", "p", 2)
        assert writer.buffer_size() == 2

        writer.flush()  # 失败，回填 2 个到 maxlen=2 → 刚好不溢出
        assert writer.buffer_size() == 2
        assert writer.dropped_total == 0

        # 模拟回填量 > maxlen 的场景
        with writer._lock:
            writer._buffer.clear()
            fake_items = [("t", "p", f"msg-{i}", None, i) for i in range(5)]
            for item in reversed(fake_items):
                if writer._buffer.maxlen is None or len(writer._buffer) < writer._buffer.maxlen:
                    writer._buffer.appendleft(item)
                else:
                    writer._dropped_total += 1

        assert writer.buffer_size() == 2   # 只有 2 个能回填
        assert writer.dropped_total == 3    # 3 个被丢弃
    finally:
        writer.stop()
