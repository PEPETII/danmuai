"""Live freshness helpers and normal-mode reply policy tests."""

import time
from unittest.mock import Mock

from app.live_freshness import (
    LiveStatusSnapshot,
    build_local_fallback_batch,
    is_model_slow,
    screenshot_interval_ms,
    should_backoff_screenshot,
)
from main import DanmuApp

from tests.fakes import FakeConfig, FakeTimer
from tests.test_p0_main_flow import _make_minimal_app


def test_is_reply_stale_never_stale_in_normal_mode():
    """生产主链路不触发 _log_reply_drop；见 test_on_ai_reply_enqueues_despite_stale_screenshot_id。"""
    app = _make_minimal_app()
    app._latest_screenshot_id = 12
    app._latest_requested_screenshot_id = 10
    stale, reason = app._is_reply_stale(10, time.monotonic(), 0)
    assert stale is False
    assert reason == ""


def test_capture_advances_screenshot_id_even_when_in_flight():
    app = _make_minimal_app()
    app.engine.running = True
    app._latest_screenshot_id = 5
    app.ai_in_flight = 1
    app._is_generating = True
    pixmap = Mock(width=Mock(return_value=100), height=Mock(return_value=100))
    pixmap.isNull = Mock(return_value=False)
    app.capturer = Mock(grab=Mock(return_value=pixmap))
    app._capture_screenshot()
    assert app._latest_screenshot_id == 6
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


def test_stale_drops_field_is_wired_to_main_pipeline():
    """BUG-027: dormant 路径 _log_reply_drop → _stale_drop_count → LiveStatusSnapshot.stale_drops。"""
    app = _make_minimal_app()
    app._build_live_status_snapshot = DanmuApp._build_live_status_snapshot.__get__(app, DanmuApp)

    app._log_reply_drop("stale_scene_in_flight", screenshot_id=1, request_round=10, scene_generation=0)
    assert app._stale_scene_inflight_drop_count == 1
    assert app._stale_scene_consume_drop_count == 0
    assert app._stale_drop_count == 1

    app._log_reply_drop("stale_scene", screenshot_id=2, request_round=11, scene_generation=0)
    assert app._stale_scene_inflight_drop_count == 1
    assert app._stale_scene_consume_drop_count == 1
    assert app._stale_drop_count == 2

    snap = app._build_live_status_snapshot()
    assert snap.stale_drops == 2


def test_stale_burst_raises_screenshot_interval():
    app = _make_minimal_app()
    app._record_stale_drop = DanmuApp._record_stale_drop.__get__(app, DanmuApp)
    app.config = FakeConfig({"normal_recognition_interval_sec": "5"})
    app.screenshot_timer = FakeTimer()
    now = time.monotonic()
    app._stale_drop_times = [now - i for i in range(4)]
    app._record_stale_drop()
    level = app._screenshot_backoff_level
    assert level >= 1
    assert app.screenshot_timer._interval == screenshot_interval_ms(5, level)


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


def test_real_ai_reply_appends_after_fallback():
    app = _make_minimal_app()
    app.ai_in_flight = 1
    app.reply_timer.active = True
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

    app._on_ai_reply('["real-a", "real-b"]', "persona-1", 10, 20, captured_at, 0)

    queued = list(app.reply_buffer._items)
    assert queued
    assert any(item.source == "ai" for item in queued)
    assert any(item.content == "real-a" for item in queued)


def test_live_status_snapshot_messages():
    snap = LiveStatusSnapshot(analyzing=True, delay_sec=2.3, stale_drops=4)
    assert "2.3" in snap.detail_message()
    assert "4" in snap.detail_message()


def test_is_model_slow_when_inflight_elapsed():
    assert is_model_slow([], 5.0, in_flight=True) is True


def test_screenshot_interval_ms_scales_with_backoff():
    assert screenshot_interval_ms(2, 0) == 2000
    assert screenshot_interval_ms(2, 2) == 4000


def test_should_backoff_screenshot_after_burst():
    now = time.monotonic()
    times = [now - i for i in range(4)]
    assert should_backoff_screenshot(times, now) is True
