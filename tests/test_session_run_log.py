"""Tests for per-guard-session run log."""

import time

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
