"""W-AUDIT-V2-BUG-006: custom pool insert/delete commit failure must rollback.

Fault-inject commit() once, assert the connection leaves the transaction, and
verify a later successful write does not flush the first-round failed rows.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest


class _CommitProxy:
    """Delegate to a real sqlite3.Connection; optionally fail commit/rollback."""

    def __init__(
        self,
        inner: sqlite3.Connection,
        *,
        fail_commits: int = 0,
        fail_rollbacks: int = 0,
    ) -> None:
        self._inner = inner
        self.fail_commits = fail_commits
        self.fail_rollbacks = fail_rollbacks
        self.commit_calls = 0
        self.rollback_calls = 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def commit(self) -> None:
        self.commit_calls += 1
        if self.fail_commits > 0:
            self.fail_commits -= 1
            raise sqlite3.OperationalError("disk I/O error")
        self._inner.commit()

    def rollback(self) -> None:
        self.rollback_calls += 1
        if self.fail_rollbacks > 0:
            self.fail_rollbacks -= 1
            raise sqlite3.OperationalError("rollback failed")
        self._inner.rollback()


def _pool_texts(store) -> list[str]:
    rows = store.conn.execute(
        "SELECT text FROM custom_danmu_pool_entries ORDER BY id ASC"
    ).fetchall()
    return [str(r[0]) for r in rows if r and r[0] is not None]


def test_insert_many_commit_fail_rolls_back_and_isolates_next_write(tmp_path):
    from app.config_store import ConfigStore
    from app.danmu_pool import (
        custom_danmu_insert_many_for_store,
        get_custom_danmu_pool_for_store,
    )

    store = ConfigStore(db_path=tmp_path / "insert_rollback.db")
    proxy = _CommitProxy(store.conn, fail_commits=1)
    store.conn = proxy

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        custom_danmu_insert_many_for_store(store, ["reported_failed"])

    assert proxy.rollback_calls == 1
    assert proxy._inner.in_transaction is False
    assert "reported_failed" not in _pool_texts(store)

    # Second round succeeds; failed first-round row must not appear.
    stats = custom_danmu_insert_many_for_store(store, ["later_success"])
    assert stats["added"] == 1
    assert get_custom_danmu_pool_for_store(store) == ["later_success"]
    assert "reported_failed" not in get_custom_danmu_pool_for_store(store)
    store.close()


def test_delete_ids_commit_fail_rolls_back_and_isolates_next_write(tmp_path):
    from app.config_store import ConfigStore
    from app.danmu_pool import (
        custom_danmu_delete_ids_for_store,
        custom_danmu_insert_many_for_store,
        get_custom_danmu_pool_for_store,
    )

    store = ConfigStore(db_path=tmp_path / "delete_ids_rollback.db")
    custom_danmu_insert_many_for_store(store, ["keep_a", "delete_target", "keep_b"])
    rows = store.conn.execute(
        "SELECT id, text FROM custom_danmu_pool_entries ORDER BY id ASC"
    ).fetchall()
    by_text = {str(r[1]): int(r[0]) for r in rows}
    target_id = by_text["delete_target"]

    proxy = _CommitProxy(store.conn, fail_commits=1)
    store.conn = proxy

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        custom_danmu_delete_ids_for_store(store, [target_id])

    assert proxy.rollback_calls == 1
    assert proxy._inner.in_transaction is False
    assert set(get_custom_danmu_pool_for_store(store)) == {
        "keep_a",
        "delete_target",
        "keep_b",
    }

    # Second delete (by text of keep_b) succeeds without replaying failed delete.
    removed = custom_danmu_delete_ids_for_store(store, [by_text["keep_b"]])
    assert removed == 1
    assert set(get_custom_danmu_pool_for_store(store)) == {"keep_a", "delete_target"}
    store.close()


def test_delete_texts_commit_fail_rolls_back_and_isolates_next_write(tmp_path):
    from app.config_store import ConfigStore
    from app.danmu_pool import (
        custom_danmu_delete_texts_for_store,
        custom_danmu_insert_many_for_store,
        get_custom_danmu_pool_for_store,
    )

    store = ConfigStore(db_path=tmp_path / "delete_texts_rollback.db")
    custom_danmu_insert_many_for_store(store, ["alpha", "beta", "gamma"])

    proxy = _CommitProxy(store.conn, fail_commits=1)
    store.conn = proxy

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        custom_danmu_delete_texts_for_store(store, ["beta"])

    assert proxy.rollback_calls == 1
    assert proxy._inner.in_transaction is False
    assert set(get_custom_danmu_pool_for_store(store)) == {"alpha", "beta", "gamma"}

    removed = custom_danmu_delete_texts_for_store(store, ["gamma"])
    assert removed == 1
    assert set(get_custom_danmu_pool_for_store(store)) == {"alpha", "beta"}
    store.close()


def test_insert_commit_fail_does_not_invalidate_formula_cache(tmp_path, monkeypatch):
    from app.config_store import ConfigStore
    from app import danmu_pool

    store = ConfigStore(db_path=tmp_path / "insert_no_invalidate.db")
    store.custom_danmu_insert_many(["seed"])
    # Warm id cache via public façade path.
    _ = danmu_pool._custom_pool_id_list(store)
    assert store in danmu_pool._formula_custom_ids

    calls: list[Any] = []

    def _track_invalidate(config=None):
        calls.append(config)

    monkeypatch.setattr(store, "_invalidate_formula_text_cache", _track_invalidate)

    proxy = _CommitProxy(store.conn, fail_commits=1)
    store.conn = proxy

    with pytest.raises(sqlite3.OperationalError):
        danmu_pool.custom_danmu_insert_many_for_store(store, ["should_not_land"])

    assert calls == []
    assert "should_not_land" not in _pool_texts(store)
    store.close()


def test_commit_fail_then_rollback_fail_raises_and_does_not_return_success(tmp_path, caplog):
    from app.config_store import ConfigStore
    from app.danmu_pool import custom_danmu_insert_many_for_store

    store = ConfigStore(db_path=tmp_path / "rollback_fail.db")
    proxy = _CommitProxy(store.conn, fail_commits=1, fail_rollbacks=1)
    store.conn = proxy

    with caplog.at_level("ERROR"):
        with pytest.raises(sqlite3.OperationalError, match="rollback failed"):
            custom_danmu_insert_many_for_store(store, ["orphan_row"])

    assert proxy.rollback_calls == 1
    assert any("rollback failed" in rec.message for rec in caplog.records)
    # Must not report success path stats (exception raised, no return).
    # Connection may still be in_transaction if rollback itself failed — do not
    # claim it is safe; only assert we did not return success / commit the row
    # via a second successful write path in this test.
    store.close()
