"""RequestTimingService 单元测试（W-MEDLOW-001 / AP-002）。"""

from __future__ import annotations

from app.application.request_timing_service import RequestTimingService


def test_purge_stale_removes_orphan_started_entries():
    svc = RequestTimingService()
    svc.mark_started(request_id="1:1:0", now=100.0)
    svc.mark_started(request_id="2:2:0", now=500.0)

    removed = svc.purge_stale(now=600.0, max_age_sec=120.0)

    assert removed == 1
    assert "1:1:0" not in svc.request_started_at_by_id
    assert "2:2:0" in svc.request_started_at_by_id


def test_consume_timing_still_pops_active_entry():
    svc = RequestTimingService()
    svc.mark_started(request_id="9:9:1", now=1000.0)
    rtt = svc.consume_timing(request_id="9:9:1", now=1001.5)

    assert rtt == 1.5
    assert "9:9:1" not in svc.request_started_at_by_id


def test_record_rtt_deque_maxlen_drops_oldest():
    svc = RequestTimingService()
    for index in range(21):
        svc.record_rtt(rtt=float(index))
    assert len(svc.rtt_history) == 20
    assert svc.rtt_history[0] == 1.0
    assert svc.rtt_history[-1] == 20.0
