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
        store = ConfigStore(db_path=temp_db)

        # 先设置一个 base64 key
        with patch('app.config_store._HAS_CRYPTO', False):
            store.set_api_key("test_api_key_123")

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
