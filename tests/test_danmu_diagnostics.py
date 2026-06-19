"""Tests for app.application.danmu_diagnostics (W-PR-INTAKE-021)."""
from __future__ import annotations

from app.application.danmu_diagnostics import DanmuDiagnosticsRecorder


def test_record_single_event():
    recorder = DanmuDiagnosticsRecorder()
    recorder.record("empty_parse", persona_id="吐槽型")
    snap = recorder.snapshot()
    assert snap.recent_count == 1
    assert snap.total_count == 1
    assert snap.latest_reason == "empty_parse"
    assert snap.top_reason == "empty_parse"
    assert snap.top_reason_count == 1


def test_record_multiple_events_aggregates():
    recorder = DanmuDiagnosticsRecorder()
    recorder.record("duplicate")
    recorder.record("duplicate")
    recorder.record("layout_rejection")
    snap = recorder.snapshot()
    assert snap.recent_count == 3
    assert snap.total_count == 3
    assert snap.latest_reason == "layout_rejection"
    assert snap.top_reason == "duplicate"
    assert snap.top_reason_count == 2
    assert snap.reason_counts["duplicate"] == 2
    assert snap.reason_counts["layout_rejection"] == 1


def test_recent_events_capped():
    recorder = DanmuDiagnosticsRecorder(max_recent=3)
    for i in range(5):
        recorder.record("empty_parse")
    snap = recorder.snapshot()
    assert snap.recent_count == 3
    assert snap.total_count == 5


def test_reset_clears_all():
    recorder = DanmuDiagnosticsRecorder()
    recorder.record("capture_failure")
    recorder.record("ai_request_failure")
    recorder.reset()
    snap = recorder.snapshot()
    assert snap.recent_count == 0
    assert snap.total_count == 0
    assert snap.latest_reason == ""
    assert snap.top_reason == ""


def test_snapshot_to_dict_serializable():
    recorder = DanmuDiagnosticsRecorder()
    recorder.record("empty_text", persona_id="测试")
    snap = recorder.snapshot()
    d = snap.to_dict()
    assert d["recent_count"] == 1
    assert d["total_count"] == 1
    assert d["latest_reason"] == "empty_text"
    assert d["recent_events"][0]["persona_id"] == "测试"
    assert "reason" in d["recent_events"][0]
    assert "timestamp" in d["recent_events"][0]


def test_empty_reason_ignored():
    recorder = DanmuDiagnosticsRecorder()
    recorder.record("")
    snap = recorder.snapshot()
    assert snap.total_count == 0


def test_thread_safety():
    """Recorder should be safe for concurrent record + snapshot calls."""
    import threading

    recorder = DanmuDiagnosticsRecorder()
    errors: list[Exception] = []

    def worker():
        try:
            for _ in range(100):
                recorder.record("duplicate")
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    snap = recorder.snapshot()
    assert snap.total_count == 400
    assert snap.top_reason == "duplicate"
