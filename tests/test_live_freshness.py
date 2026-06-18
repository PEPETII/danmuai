"""Live freshness helpers and normal-mode reply policy tests."""

import time
from unittest.mock import Mock

from app.live_freshness import LiveStatusSnapshot, build_local_fallback_batch, is_model_slow
from main import DanmuApp

from tests.conftest import make_minimal_danmu_app
from tests.fakes import FakeConfig


def test_capture_advances_screenshot_id_even_when_in_flight():
    app = make_minimal_danmu_app()
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
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._latest_screenshot = object()
    app._latest_screenshot_id = 3
    app._latest_screenshot_time = time.monotonic()
    app.personae = Mock(pick_random=Mock(return_value="吐槽型"), get_prompt=Mock(return_value=("sys", "user")))

    pool = Mock()
    pool.start = Mock()
    monkeypatch.setattr("app.worker_pools.ai_worker_pool", lambda: pool)
    monkeypatch.setattr("app.runnable.AiRunnable", lambda *a, **k: Mock())

    app._trigger_api_call()
    assert app.ai_in_flight == 1
    assert app._is_generating is True
    assert app._inflight_screenshot_id == 3
    pool.start.assert_called_once()


def test_local_fallback_field_is_wired_to_main_pipeline():
    """BUG-013: slow in-flight → _maybe_inject_local_fallback → local_fallback snapshot + queue."""
    app = make_minimal_danmu_app()
    app.config = FakeConfig({"danmu_pool_use_custom": "1"})
    app.config.set_custom_danmu_pool([f"兜底句{i}" for i in range(10)])
    app.engine.running = True
    app._build_live_status_snapshot = DanmuApp._build_live_status_snapshot.__get__(app, DanmuApp)
    app._maybe_inject_local_fallback = DanmuApp._maybe_inject_local_fallback.__get__(app, DanmuApp)

    app.ai_in_flight = 1
    app._is_generating = True
    app._inflight_started_at = time.monotonic() - 5.0
    app._inflight_screenshot_id = 3
    app._inflight_scene_generation = 0
    app.screenshot_round = 10

    snap_before = app._build_live_status_snapshot()
    assert snap_before.local_fallback is False

    app._maybe_inject_local_fallback()

    snap_after = app._build_live_status_snapshot()
    assert snap_after.local_fallback is True
    queued = list(app.reply_buffer._items)
    assert queued
    assert all(item.source == "fallback" for item in queued)
    assert all(item.is_fallback is True for item in queued)


def test_local_fallback_batch_has_five_items():
    cfg = FakeConfig({"danmu_pool_use_custom": "1"})
    cfg.set_custom_danmu_pool([f"兜底句{i}" for i in range(10)])
    items = build_local_fallback_batch(config=cfg)
    assert len(items) == 5
    assert len(items) == len(set(items))
    assert all(isinstance(x, str) and x for x in items)


def test_local_fallback_is_marked_replaceable():
    app = make_minimal_danmu_app()
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
    app = make_minimal_danmu_app()
    app.ai_in_flight = 1
    app.reply_timer.active = True
    app._batch_id = 7
    captured_at = time.monotonic()
    app._register_request_meta(10, 20, 0, "visual")  # W-RACE-001: 需预注册 meta

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
    snap = LiveStatusSnapshot(analyzing=True, delay_sec=2.3)
    detail = snap.detail_message()
    assert "2.3" in detail
    assert "丢弃" not in detail
    assert "dropped" not in detail.lower()


def test_is_model_slow_when_inflight_elapsed():
    assert is_model_slow([], 5.0, in_flight=True) is True
