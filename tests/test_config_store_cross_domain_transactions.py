"""W-AUDIT-V2-BUG-005: unified write lock prevents cross-domain SQLite rollback pollution."""

from __future__ import annotations

import sqlite3
import threading
import time

import pytest

from app.config_store import ConfigStore


def test_pool_write_lock_is_write_lock_alias(tmp_path):
    store = ConfigStore(tmp_path / "alias.db")
    try:
        assert store._pool_write_lock is store._write_lock
        assert store._pool_write_lock is not None
    finally:
        store.close()


def test_close_acquires_write_lock_once_without_self_deadlock(tmp_path):
    """Unified alias must not nest pool+write locks in close() (non-reentrant Lock)."""
    store = ConfigStore(tmp_path / "close_once.db")
    store.set("k", "v")
    # Would hang forever if close still did with pool: with write:
    store.close()
    with pytest.raises(RuntimeError, match="close"):
        store.set("k", "again")


def test_mid_config_transaction_blocks_pool_until_release(tmp_path):
    """While config holds write lock mid-transaction, pool cannot enter / rollback."""
    store = ConfigStore(tmp_path / "serialize.db")
    order: list[str] = []
    errors: list[BaseException] = []
    barrier = threading.Barrier(2, timeout=5)
    hold_mid = threading.Event()
    release_mid = threading.Event()

    def config_mid_txn():
        try:
            barrier.wait()
            with store._write_lock:
                order.append("config_enter")
                store.conn.execute(
                    "REPLACE INTO config (key, value) VALUES (?, ?)",
                    ("mid_key", "mid_value"),
                )
                hold_mid.set()
                assert release_mid.wait(timeout=5.0)
                store.conn.commit()
                store._cache["mid_key"] = "mid_value"
                order.append("config_exit")
        except BaseException as exc:  # pragma: no cover - surface in assert
            errors.append(exc)

    def pool_after_config_starts():
        try:
            barrier.wait()
            assert hold_mid.wait(timeout=5.0)
            # Must block until config releases write lock
            entered = threading.Event()

            def try_pool():
                try:
                    with store._pool_write_lock:
                        entered.set()
                        order.append("pool_enter")
                        store.conn.execute(
                            "INSERT OR IGNORE INTO custom_danmu_pool_entries "
                            "(text, source, enabled, created_at, updated_at) "
                            "VALUES (?, 'manual', 1, ?, ?)",
                            ("pool_line", time.time(), time.time()),
                        )
                        store.conn.commit()
                        order.append("pool_exit")
                except BaseException as exc:
                    errors.append(exc)

            t = threading.Thread(target=try_pool, name="pool-waiter")
            t.start()
            # Still mid config txn: pool must not have entered yet
            time.sleep(0.15)
            assert not entered.is_set(), "pool must wait while config holds write lock"
            release_mid.set()
            t.join(timeout=5.0)
            assert not t.is_alive()
            assert entered.is_set()
        except BaseException as exc:
            errors.append(exc)
            release_mid.set()

    t_cfg = threading.Thread(target=config_mid_txn, name="config-mid")
    t_pool = threading.Thread(target=pool_after_config_starts, name="pool-coord")
    t_cfg.start()
    t_pool.start()
    t_cfg.join(timeout=10)
    t_pool.join(timeout=10)

    assert not errors, errors
    assert order == ["config_enter", "config_exit", "pool_enter", "pool_exit"]
    assert store.get("mid_key") == "mid_value"
    assert store.custom_danmu_contains_text("pool_line")

    db_path = store.db_path
    store.close()
    reopened = sqlite3.connect(str(db_path))
    try:
        row = reopened.execute(
            "SELECT value FROM config WHERE key = ?", ("mid_key",)
        ).fetchone()
        assert row is not None and row[0] == "mid_value"
        pool_row = reopened.execute(
            "SELECT text FROM custom_danmu_pool_entries WHERE text = ?",
            ("pool_line",),
        ).fetchone()
        assert pool_row is not None
    finally:
        reopened.close()


def test_pool_rollback_after_committed_config_does_not_drop_config(tmp_path):
    """After config commit, a failed pool write + rollback must leave config intact."""
    store = ConfigStore(tmp_path / "pool_rb.db")
    store.set("keep_me", "yes")

    with store._pool_write_lock:
        store.conn.execute(
            "INSERT OR IGNORE INTO custom_danmu_pool_entries "
            "(text, source, enabled, created_at, updated_at) "
            "VALUES (?, 'manual', 1, ?, ?)",
            ("doomed", time.time(), time.time()),
        )
        store.conn.rollback()
        assert store.conn.in_transaction is False

    assert store.get("keep_me") == "yes"
    assert not store.custom_danmu_contains_text("doomed")

    db_path = store.db_path
    store.close()
    reopened = sqlite3.connect(str(db_path))
    try:
        row = reopened.execute(
            "SELECT value FROM config WHERE key = ?", ("keep_me",)
        ).fetchone()
        assert row is not None and row[0] == "yes"
        assert (
            reopened.execute(
                "SELECT COUNT(*) FROM custom_danmu_pool_entries WHERE text = ?",
                ("doomed",),
            ).fetchone()[0]
            == 0
        )
    finally:
        reopened.close()


def test_failed_config_rollback_does_not_drop_committed_pool(tmp_path):
    store = ConfigStore(tmp_path / "cfg_rb.db")
    store.custom_danmu_insert_many(["kept_pool"])

    with store._write_lock:
        store.conn.execute(
            "REPLACE INTO config (key, value) VALUES (?, ?)",
            ("doomed_cfg", "x"),
        )
        store.conn.rollback()
        assert store.conn.in_transaction is False

    assert store.get("doomed_cfg", "") == ""
    assert store.custom_danmu_contains_text("kept_pool")

    db_path = store.db_path
    store.close()
    reopened = sqlite3.connect(str(db_path))
    try:
        assert (
            reopened.execute(
                "SELECT COUNT(*) FROM config WHERE key = ?", ("doomed_cfg",)
            ).fetchone()[0]
            == 0
        )
        assert (
            reopened.execute(
                "SELECT COUNT(*) FROM custom_danmu_pool_entries WHERE text = ?",
                ("kept_pool",),
            ).fetchone()[0]
            == 1
        )
    finally:
        reopened.close()


def test_concurrent_set_pool_write_and_close_no_deadlock(tmp_path):
    db_path = tmp_path / "race_close.db"
    store = ConfigStore(db_path)
    store.set("seed", "1")
    errors: list[BaseException] = []
    stop = threading.Event()

    def config_loop():
        i = 0
        while not stop.is_set() and i < 200:
            try:
                store.set("race_cfg", str(i))
                i += 1
            except RuntimeError:
                break
            except BaseException as exc:
                errors.append(exc)
                break

    def pool_loop():
        i = 0
        while not stop.is_set() and i < 50:
            try:
                store.custom_danmu_insert_many([f"race_pool_{i}"])
                i += 1
            except (RuntimeError, sqlite3.Error):
                break
            except BaseException as exc:
                errors.append(exc)
                break

    def closer():
        time.sleep(0.05)
        try:
            store.close()
        except BaseException as exc:
            errors.append(exc)
        finally:
            stop.set()

    threads = [
        threading.Thread(target=config_loop),
        threading.Thread(target=pool_loop),
        threading.Thread(target=closer),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=8)
        assert not t.is_alive(), "deadlock or hang detected"

    assert not errors, errors
    # DB file still openable
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("SELECT COUNT(*) FROM config").fetchone()
    finally:
        conn.close()
