"""W-INFLIGHT-RECOVER-001：视觉 in-flight 死锁强制恢复（S-011 / S-024）。"""

import time

from app.application.request_timing_service import RequestTimingService
from app.main_helpers import VISUAL_INFLIGHT_RECOVER_SEC

from tests.conftest import bind_minimal_danmu_app, make_minimal_danmu_app


def test_recover_stale_visual_inflight_clears_slot_and_meta():
    app = make_minimal_danmu_app()
    bind_minimal_danmu_app(
        app,
        ai_in_flight=1,
        _is_generating=True,
        _inflight_screenshot_id=7,
        _inflight_scene_generation=0,
        _inflight_started_at=time.monotonic() - VISUAL_INFLIGHT_RECOVER_SEC - 2.0,
        _pending_request_meta={"3:7:0": {"source": "visual"}},
        _consecutive_failures=0,
    )
    object.__setattr__(app, "_request_timing_service", RequestTimingService())
    app._get_request_timing_service().mark_started(request_id="3:7:0", now=time.monotonic() - 50.0)

    assert app._try_recover_stale_visual_inflight() is True
    assert app.ai_in_flight == 0
    assert app._inflight_started_at == 0.0
    assert app._pending_request_meta == {}
    assert app._get_request_timing_service().request_started_at_by_id == {}
    assert app._consecutive_failures == 1
    assert any(
        "inflight_watchdog_recover" in msg for msg in app.logger.error_messages
    )


def test_recover_stale_visual_inflight_skips_when_not_expired():
    app = make_minimal_danmu_app()
    bind_minimal_danmu_app(
        app,
        ai_in_flight=1,
        _is_generating=True,
        _inflight_screenshot_id=7,
        _inflight_scene_generation=0,
        _inflight_started_at=time.monotonic() - 5.0,
        _pending_request_meta={"3:7:0": {"source": "visual"}},
    )

    assert app._try_recover_stale_visual_inflight() is False
    assert app.ai_in_flight == 1
    assert "3:7:0" in app._pending_request_meta


def test_on_normal_capture_tick_recovers_stale_inflight(monkeypatch):
    app = make_minimal_danmu_app()
    bind_minimal_danmu_app(
        app,
        ai_in_flight=1,
        _is_generating=True,
        _inflight_screenshot_id=9,
        _inflight_scene_generation=0,
        _inflight_started_at=time.monotonic() - VISUAL_INFLIGHT_RECOVER_SEC - 1.0,
        engine_running=True,
    )
    capture_called = []

    def _capture():
        capture_called.append(True)

    monkeypatch.setattr(app, "_schedule_capture", _capture)
    monkeypatch.setattr(app, "_maybe_inject_local_fallback", lambda: None)

    app._on_normal_capture_tick()

    assert app.ai_in_flight == 0
    assert not capture_called
