"""Tests for P1-004 (SQLite concurrency lock) and P1-005 (transaction protection)."""

import sqlite3
import threading
from unittest.mock import MagicMock, patch

import pytest
from app.config_store import ConfigStore


@pytest.fixture
def temp_db(tmp_path):
    """Create a temporary database for testing."""
    db_path = tmp_path / "test_config.db"
    return db_path


class MockConnection:
    """Wrapper around sqlite3.Connection to allow mocking."""

    def __init__(self, conn):
        self._conn = conn
        self._execute_failure_checks = []
        self._commit_failures = []
        self._execute_call_count = 0
        self._commit_call_count = 0

    def execute(self, sql, params=()):
        self._execute_call_count += 1
        for check in self._execute_failure_checks:
            if check(sql, params):
                raise sqlite3.OperationalError("database is locked")
        return self._conn.execute(sql, params)

    def executemany(self, sql, seq_of_parameters):
        for params in seq_of_parameters:
            self.execute(sql, params)

    def commit(self):
        self._commit_call_count += 1
        if self._commit_failures:
            should_fail = self._commit_failures.pop(0)
            if should_fail:
                raise sqlite3.OperationalError("commit failed")
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def __getattr__(self, name):
        return getattr(self._conn, name)


class TestP1004SQLiteConcurrency:
    """P1-004: SQLite 并发写无锁"""

    def test_write_lock_prevents_concurrent_writes(self, temp_db):
        """写锁确保同一时刻只有一个线程在执行写操作。"""
        store = ConfigStore(db_path=temp_db)

        errors = []
        success_count = [0]

        def write_config(thread_id):
            try:
                for i in range(10):
                    store.set(f"key_{thread_id}_{i}", f"value_{thread_id}_{i}")
                    success_count[0] += 1
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=write_config, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发写入出现错误: {errors}"
        assert success_count[0] == 50, "所有写入操作应该成功"

        store.close()

    def test_wal_mode_enabled(self, temp_db):
        """WAL 模式应该被启用。"""
        store = ConfigStore(db_path=temp_db)

        cursor = store.conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]

        assert mode == "wal", f"应该启用 WAL 模式，当前为: {mode}"

        store.close()

    def test_busy_timeout_set(self, temp_db):
        """busy_timeout 应该被设置为 5000ms。"""
        store = ConfigStore(db_path=temp_db)

        cursor = store.conn.execute("PRAGMA busy_timeout")
        timeout = cursor.fetchone()[0]

        assert timeout == 5000, f"busy_timeout 应该为 5000，当前为: {timeout}"

        store.close()

    def test_concurrent_read_write_no_lock(self, temp_db):
        """并发读写不应触发 database locked。"""
        store = ConfigStore(db_path=temp_db)

        # 预置一些数据
        for i in range(20):
            store.set(f"init_key_{i}", f"init_value_{i}")

        errors = []

        def reader():
            try:
                for _ in range(50):
                    store.get(f"init_key_{_ % 20}")
            except Exception as e:
                errors.append(f"read: {e}")

        def writer():
            try:
                for i in range(20):
                    store.set(f"concurrent_key_{i}", f"value_{i}")
            except Exception as e:
                errors.append(f"write: {e}")

        threads = []
        for _ in range(3):
            threads.append(threading.Thread(target=reader))
        for _ in range(2):
            threads.append(threading.Thread(target=writer))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"并发读写出现错误: {errors}"

        store.close()

    def test_write_error_handling(self, temp_db):
        """写入失败应该有错误处理并重新抛出异常。"""
        store = ConfigStore(db_path=temp_db)

        # Wrap connection with mock
        mock_conn = MockConnection(store.conn)
        mock_conn._execute_failure_checks.append(lambda sql, _: "REPLACE INTO config" in sql)
        store.conn = mock_conn

        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            store.set("test_key", "test_value")

        store.close()


class TestP1005TransactionProtection:
    """P1-005: ConfigStore 缺少事务保护"""

    def test_set_batch_all_or_nothing(self, temp_db):
        """批量更新要么全部成功，要么全部回滚。"""
        store = ConfigStore(db_path=temp_db)

        items = {
            "batch_key_1": "value_1",
            "batch_key_2": "value_2",
            "batch_key_3": "value_3",
        }

        store.set_batch(items)

        # 验证所有 key 都已写入
        for k, v in items.items():
            assert store.get(k) == v

        store.close()

    def test_set_batch_rollback_on_failure(self, temp_db):
        """批量写入失败时应该回滚，缓存不应更新。"""
        store = ConfigStore(db_path=temp_db)

        # 预置一个 key
        store.set("existing_key", "existing_value")

        # Wrap connection with mock
        mock_conn = MockConnection(store.conn)
        call_count = [0]
        def fail_on_second(sql, _):
            call_count[0] += 1
            # set_batch calls execute for each item, fail on second item
            return "REPLACE INTO config" in sql and call_count[0] == 2
        mock_conn._execute_failure_checks.append(fail_on_second)
        store.conn = mock_conn

        items = {
            "new_key_1": "value_1",
            "new_key_2": "value_2",
            "new_key_3": "value_3",
        }

        with pytest.raises(sqlite3.OperationalError):
            store.set_batch(items)

        # 验证缓存中没有新 key
        assert "new_key_1" not in store._cache
        assert "new_key_2" not in store._cache
        assert "new_key_3" not in store._cache

        # 验证数据库中也没有新 key（回滚了）
        cursor = store.conn._conn.execute("SELECT key, value FROM config WHERE key LIKE 'new_key_%'")
        rows = cursor.fetchall()
        assert len(rows) == 0, "数据库中不应该有新 key（已回滚）"

        # 验证原有 key 仍然存在
        assert store.get("existing_key") == "existing_value"

        store.close()

    def test_set_region_uses_transaction(self, temp_db):
        """set_region 应该使用 set_batch 享受事务保护。"""
        store = ConfigStore(db_path=temp_db)

        store.set_region(100, 200, 300, 400)

        assert store.get("region_x") == "100"
        assert store.get("region_y") == "200"
        assert store.get("region_w") == "300"
        assert store.get("region_h") == "400"

        store.close()

    def test_set_region_atomic_write(self, temp_db):
        """set_region 四个坐标值应该原子写入。"""
        store = ConfigStore(db_path=temp_db)

        # Wrap connection with mock
        mock_conn = MockConnection(store.conn)
        call_count = [0]
        def fail_on_third(sql, _):
            call_count[0] += 1
            # set_region calls set_batch which calls execute for each region key, fail on third
            return "REPLACE INTO config" in sql and call_count[0] == 3
        mock_conn._execute_failure_checks.append(fail_on_third)
        store.conn = mock_conn

        with pytest.raises(sqlite3.OperationalError):
            store.set_region(100, 200, 300, 400)

        # 验证所有 region key 都不存在（回滚了）
        assert store.get("region_x") == ""
        assert store.get("region_y") == ""
        assert store.get("region_w") == ""
        assert store.get("region_h") == ""

        store.close()

    def test_set_api_key_transaction(self, temp_db):
        """set_api_key 中加密写入和旧 key 删除应该在同一事务中。"""
        from base64 import b64encode

        store = ConfigStore(db_path=temp_db)

        encoded = b64encode(b"test_api_key_123").decode()
        store.conn.execute(
            "REPLACE INTO config (key, value) VALUES (?, ?)",
            ("api_key_encoded", encoded),
        )
        store.conn.commit()
        store._cache["api_key_encoded"] = encoded

        assert store.get("api_key_encoded") != ""

        # 现在启用加密并设置新 key
        mock_fernet = MagicMock()
        mock_fernet.encrypt.return_value = b"encrypted_key"
        store._fernet = mock_fernet

        with patch('app.config_store._HAS_CRYPTO', True):
            store.set_api_key("new_api_key_456")

        # 验证加密 key 已设置，base64 key 已删除
        assert store.get("api_key_encrypted") == "encrypted_key"
        assert store.get("api_key_encoded") == ""

        store.close()

    def test_cache_updated_after_commit(self, temp_db):
        """缓存应该在 commit 成功后才更新。"""
        store = ConfigStore(db_path=temp_db)

        # Wrap connection with mock
        mock_conn = MockConnection(store.conn)
        mock_conn._commit_failures.append(True)  # Fail on first commit
        store.conn = mock_conn

        items = {
            "commit_key_1": "value_1",
            "commit_key_2": "value_2",
        }

        with pytest.raises(sqlite3.OperationalError):
            store.set_batch(items)

        # 验证缓存中没有新 key（commit 失败，缓存不应更新）
        assert "commit_key_1" not in store._cache
        assert "commit_key_2" not in store._cache

        store.close()


class _CloseDelayConn:
    """包装真实 sqlite3.Connection，在 close() 上注入延迟/观察。

    sqlite3.Connection.close 是只读 C 属性，无法用 unittest.mock.patch.object 替换；
    改用包装类委托其他属性（仿同文件 MockConnection 模式）。
    """

    def __init__(self, real_conn, *, on_entered=None, can_finish=None, order=None):
        self._real = real_conn
        self._on_entered = on_entered
        self._can_finish = can_finish
        self._order = order

    def close(self):
        if self._on_entered is not None:
            self._on_entered.set()
        if self._can_finish is not None:
            self._can_finish.wait(timeout=2.0)
        if self._order is not None:
            self._order.append("conn_close_start")
        self._real.close()
        if self._order is not None:
            self._order.append("conn_close_end")

    def __getattr__(self, name):
        return getattr(self._real, name)


class TestBUG016CloseWriteRace:
    """BUG-016: close() 必须持锁完成 conn.close()，且写后关必须抛 RuntimeError 而非静默跳过。"""

    def test_set_batch_during_close_raises_runtime_error(self, temp_db):
        """并发线程在 close() 期间尝试 set_batch，必须抛 RuntimeError 而非静默跳过。

        复现路径：
        1. 线程 A 调 close()，用 _CloseDelayConn 包装 store.conn 让 close 阻塞制造持锁窗口。
        2. 线程 B 在 A 持锁期间调 set_batch。
        3. close 已设置 _closed=True，set_batch 的 fast-path 检查会立即抛 RuntimeError
           （旧行为是静默 warning + return，导致用户配置静默丢失）。

        注意：fast-path 检查发生在 ``with self._write_lock`` 之前，因此 writer 不会阻塞
        在锁上——它看到 _closed=True 就直接 raise。本测试主要验证「不静默丢写」契约。
        """
        store = ConfigStore(db_path=temp_db)
        store.set("init_key", "init_value")

        close_entered = threading.Event()
        close_can_finish = threading.Event()
        store.conn = _CloseDelayConn(
            store.conn, on_entered=close_entered, can_finish=close_can_finish
        )

        close_thread = threading.Thread(target=store.close)
        close_thread.start()
        assert close_entered.wait(timeout=2.0), "close() 未进入持锁阶段"

        # 此时 close 已设置 _closed=True 并持有 _write_lock 调用 conn.close()
        errors: list[Exception] = []
        result: list[str] = []

        def writer():
            try:
                store.set_batch({"raced_key": "raced_value"})
                result.append("ok")
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        writer_thread = threading.Thread(target=writer)
        writer_thread.start()

        close_can_finish.set()
        close_thread.join(timeout=2.0)
        writer_thread.join(timeout=2.0)

        # 期望：writer 抛 RuntimeError（fast-path 看到已关闭），而非静默成功
        assert len(errors) == 1, f"期望恰好 1 个异常，得到 errors={errors} result={result}"
        assert isinstance(errors[0], RuntimeError), f"期望 RuntimeError，得到 {type(errors[0])}"
        assert "called after close" in str(errors[0])

        # 验证数据未写入（重新打开 DB 确认）
        store2 = ConfigStore(db_path=temp_db)
        assert store2.get("raced_key", "") == ""
        store2.close()

    def test_close_holds_lock_until_conn_closed(self, temp_db):
        """close() 期间 conn.close() 在 _write_lock 内完成，确认持锁顺序。"""
        store = ConfigStore(db_path=temp_db)
        store.set("init_key", "init_value")

        call_order: list[str] = []
        store.conn = _CloseDelayConn(store.conn, order=call_order)
        store.close()

        # conn.close() 在锁内完成；call_order 应连续（中间没有其他写操作插入）
        assert call_order == ["conn_close_start", "conn_close_end"]
        assert store._closed is True

