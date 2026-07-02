"""Tests for per-guard-session run log."""

import sqlite3
import time

from app.config_store import ConfigStore
from app.session_run_log import SessionRunLog


def test_complete_records_newest_first():
    log = SessionRunLog(max_entries=10)
    log.begin(started_at=1000.0, model="model-a")
    log.complete(
        ended_at=1060.0,
        input_tokens=100,
        output_tokens=50,
        danmu_count=3,
    )
    log.begin(started_at=2000.0, model="model-b")
    log.complete(
        ended_at=2100.0,
        input_tokens=10,
        output_tokens=5,
        danmu_count=1,
    )
    rows = log.list_dicts_newest_first()
    assert len(rows) == 2
    assert rows[0]["model"] == "model-b"
    assert rows[0]["total_tokens"] == 15
    assert rows[1]["model"] == "model-a"
    assert rows[1]["total_tokens"] == 150


def test_complete_without_begin_is_noop():
    log = SessionRunLog()
    assert log.complete(
        ended_at=time.time(),
        input_tokens=1,
        output_tokens=1,
        danmu_count=0,
    ) is None
    assert log.list_dicts_newest_first() == []


def test_max_entries_trims_oldest():
    log = SessionRunLog(max_entries=2)
    for i in range(3):
        log.begin(started_at=float(i), model=f"m{i}")
        log.complete(ended_at=float(i) + 1, input_tokens=1, output_tokens=0, danmu_count=0)
    models = [r["model"] for r in log.list_dicts_newest_first()]
    assert models == ["m2", "m1"]


def test_persists_and_reloads_from_config_db(tmp_path):
    db = tmp_path / "config.db"
    store = ConfigStore(db_path=db)
    log1 = SessionRunLog(store, max_entries=100)
    log1.begin(started_at=1000.0, model="persist-model")
    log1.complete(
        ended_at=1100.0,
        input_tokens=20,
        output_tokens=10,
        danmu_count=5,
    )
    store.close()

    store2 = ConfigStore(db_path=db)
    log2 = SessionRunLog(store2, max_entries=100)
    rows = log2.list_dicts_newest_first()
    assert len(rows) == 1
    assert rows[0]["model"] == "persist-model"
    assert rows[0]["total_tokens"] == 30
    assert rows[0]["danmu_count"] == 5
    store2.close()


def test_persist_trims_db_to_max_entries(tmp_path):
    db = tmp_path / "config.db"
    store = ConfigStore(db_path=db)
    log = SessionRunLog(store, max_entries=2)
    for i in range(3):
        log.begin(started_at=float(i), model=f"db{i}")
        log.complete(ended_at=float(i) + 1, input_tokens=1, output_tokens=0, danmu_count=0)
    count = store.conn.execute("SELECT COUNT(*) FROM session_runs").fetchone()[0]
    assert count == 2
    models = [r["model"] for r in log.list_dicts_newest_first()]
    assert models == ["db2", "db1"]
    store.close()

    store2 = ConfigStore(db_path=db)
    log2 = SessionRunLog(store2, max_entries=2)
    assert [r["model"] for r in log2.list_dicts_newest_first()] == ["db2", "db1"]
    store2.close()


def test_config_store_creates_session_runs_table(tmp_path):
    db = tmp_path / "config.db"
    store = ConfigStore(db_path=db)
    tables = {
        row[0]
        for row in store.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    assert "session_runs" in tables
    store.close()


def test_persist_swallows_database_error(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    inner = store.conn

    class _FailingConn:
        def execute(self, sql, params=()):
            if "INSERT INTO session_runs" in sql:
                raise sqlite3.DatabaseError("disk I/O error")
            return inner.execute(sql, params)

        def commit(self):
            return inner.commit()

        def rollback(self):
            return inner.rollback()

        def close(self):
            return inner.close()

    store.conn = _FailingConn()
    log = SessionRunLog(store, max_entries=100)
    log.begin(started_at=1000.0, model="persist-model")

    rec = log.complete(
        ended_at=1100.0,
        input_tokens=20,
        output_tokens=10,
        danmu_count=5,
    )

    assert rec is not None
    assert rec.model == "persist-model"
    rows = log.list_dicts_newest_first()
    assert len(rows) == 1
    assert rows[0]["model"] == "persist-model"
    count = inner.execute("SELECT COUNT(*) FROM session_runs").fetchone()[0]
    assert count == 0
    store.close()
