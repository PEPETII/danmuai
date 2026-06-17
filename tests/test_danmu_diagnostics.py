from app.application.danmu_diagnostics import DanmuDiagnostics


def test_danmu_diagnostics_records_top_reason_and_recent_events():
    diagnostics = DanmuDiagnostics(max_events=3)
    diagnostics.record(
        "empty_parse",
        stage="parse",
        detail="text_len=10 raw_count=0",
        screenshot_id=7,
        request_round=3,
        at=100.0,
    )
    diagnostics.record("duplicate", stage="display", screenshot_id=8, request_round=4, at=105.0)
    diagnostics.record("empty_parse", stage="parse", screenshot_id=9, request_round=5, at=110.0)

    snapshot = diagnostics.snapshot(now=112.0)

    assert snapshot["recent_count"] == 3
    assert snapshot["total_recorded"] == 3
    assert snapshot["top_reasons"][0] == {
        "reason": "empty_parse",
        "label": "AI 回复解析为空",
        "count": 2,
    }
    assert snapshot["latest"]["reason"] == "empty_parse"
    assert snapshot["latest"]["age_sec"] == 2.0
    assert snapshot["recent"][0]["screenshot_id"] == 9


def test_danmu_diagnostics_coalesces_repeated_events():
    diagnostics = DanmuDiagnostics()
    diagnostics.record("floating_panel_spacing", stage="display", screenshot_id=11, at=100.0)
    diagnostics.record(
        "floating_panel_spacing",
        stage="display",
        detail="delay_ms=300",
        screenshot_id=12,
        at=101.0,
    )

    snapshot = diagnostics.snapshot(now=101.5)

    assert snapshot["recent_count"] == 1
    assert snapshot["total_recorded"] == 2
    assert snapshot["latest"]["repeat_count"] == 2
    assert snapshot["latest"]["screenshot_id"] == 12
    assert snapshot["latest"]["detail"] == "delay_ms=300"
