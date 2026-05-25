"""Latest-frame-first freshness policy tests."""

import time
from unittest.mock import Mock

from app.live_freshness import (
    LiveStatusSnapshot,
    build_local_fallback_batch,
    is_model_slow,
    screenshot_interval_ms,
    should_backoff_screenshot,
)

from tests.fakes import FakeTimer
from tests.test_p0_main_flow import _make_minimal_app


def test_superseded_by_newer_frame_without_new_request():
    app = _make_minimal_app()
    app._latest_screenshot_id = 12
    app._latest_requested_screenshot_id = 10
    stale, reason = app._is_reply_stale(10, time.monotonic(), 0)
    assert stale is True
    assert reason == "superseded_by_newer_frame"


def test_capture_holds_screenshot_id_during_in_flight_request(monkeypatch):
    app = _make_minimal_app()
    app.engine.running = True
    app._latest_screenshot_id = 5
    app.ai_in_flight = 1
    app._is_generating = True
    pixmap = Mock(width=Mock(return_value=100), height=Mock(return_value=100))
    app.capturer = Mock(grab=Mock(return_value=pixmap))
    monkeypatch.setattr("main.fingerprint_from_pixmap", lambda pixmap, probe_size=64: 0)
    app._capture_screenshot()
    assert app._latest_screenshot_id == 5
    assert app._latest_screenshot is pixmap


def test_trigger_api_call_increments_in_flight(monkeypatch):
    app = _make_minimal_app()
    app.engine.running = True
    app._latest_screenshot = object()
    app._latest_screenshot_id = 3
    app._latest_screenshot_time = time.monotonic()
    app.personae = Mock(pick_random=Mock(return_value="吐槽型"), get_prompt=Mock(return_value=("sys", "user")))

    pool = Mock()
    pool.start = Mock()
    monkeypatch.setattr(
        "PyQt6.QtCore.QThreadPool",
        Mock(globalInstance=Mock(return_value=pool)),
    )
    monkeypatch.setattr("app.runnable.AiRunnable", lambda *a, **k: Mock())

    app._trigger_api_call()
    assert app.ai_in_flight == 1
    assert app._is_generating is True
    assert app._inflight_screenshot_id == 3
    pool.start.assert_called_once()


def test_stale_burst_raises_screenshot_interval():
    app = _make_minimal_app()
    app.screenshot_timer = FakeTimer()
    now = time.monotonic()
    app._stale_drop_times = [now - i for i in range(4)]
    app._record_stale_drop()
    assert app._screenshot_backoff_level >= 1
    assert app.screenshot_timer._interval >= 2000


def test_local_fallback_batch_has_five_items():
    items = build_local_fallback_batch()
    assert len(items) == 5
    assert len(items) == len(set(items))
    assert all(isinstance(x, str) and x for x in items)


def test_local_fallback_is_marked_replaceable():
    app = _make_minimal_app()
    app._batch_id = 7
    app._enqueue_reply_batch(
        "persona-1",
        10,
        20,
        time.monotonic(),
        0,
        ["fallback-a", "fallback-b"],
        from_local_fallback=True,
    )

    queued = list(app.reply_buffer._items)
    assert queued
    assert all(item.is_fallback is True for item in queued)
    assert all(item.source == "fallback" for item in queued)
    assert all(item.replaceable is True for item in queued)
    assert all(item.batch_id == 7 for item in queued)
    assert all(item.request_id == "10:20:0" for item in queued)


def test_real_ai_reply_replaces_matching_fallback():
    app = _make_minimal_app()
    app.ai_in_flight = 1
    app.reply_timer.active = True
    app._queue_low_watermark = 99
    app._batch_id = 7
    captured_at = time.monotonic()

    app._enqueue_reply_batch(
        "persona-1",
        10,
        20,
        captured_at,
        0,
        ["fallback-a", "fallback-b"],
        from_local_fallback=True,
    )
    assert any(item.is_fallback for item in app.reply_buffer._items)

    app._on_ai_reply('["real-a", "real-b"]', "persona-1", 10, 20, captured_at, 0)

    queued = list(app.reply_buffer._items)
    assert queued
    assert all(item.is_fallback is False for item in queued)
    assert all(item.source == "ai" for item in queued)
    assert all(item.replaceable is False for item in queued)
    assert all("fallback" not in item.content for item in queued)
    assert queued[0].content == "real-a"


def test_live_status_snapshot_messages():
    snap = LiveStatusSnapshot(analyzing=True, delay_sec=2.3, stale_drops=4)
    assert "2.3" in snap.detail_message()
    assert "4" in snap.detail_message()


def test_is_model_slow_when_inflight_elapsed():
    assert is_model_slow([], 5.0, in_flight=True) is True


def test_screenshot_interval_ms_scales_with_backoff():
    assert screenshot_interval_ms(2, 0) == 2000
    assert screenshot_interval_ms(2, 2) == 4000


def test_should_backoff_after_burst():
    now = time.monotonic()
    times = [now - i for i in range(4)]
    assert should_backoff_screenshot(times, now) is True
