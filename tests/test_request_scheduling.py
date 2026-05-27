"""Phase 4-B scheduling and timing regression tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import app.api_schedule as api_schedule
import main
import pytest
from app.application.request_scheduler import RequestScheduler
from app.application.request_timing_service import RequestTimingService
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import (
    FakeConfig,
    FakeEngine,
    FakeHistoryWriter,
    FakeLifetimeStats,
    FakeLogger,
    FakeTimer,
)


def _make_request_app(**overrides):
    app = DanmuApp.__new__(DanmuApp)
    defaults = {
        "logger": FakeLogger(),
        "engine": FakeEngine(),
        "config": FakeConfig(),
        "history_writer": FakeHistoryWriter(),
        "lifetime_stats": FakeLifetimeStats(),
        "MAX_CONSECUTIVE_FAILURES": 5,
    }
    defaults.update(overrides)
    bind_minimal_danmu_app(app, **defaults)

    object.__setattr__(app, "screenshot_timer", FakeTimer())
    object.__setattr__(app, "_live_status_timer", FakeTimer())
    object.__setattr__(app, "_mic_service", SimpleNamespace(stop=lambda: None))
    object.__setattr__(app, "overlay", SimpleNamespace(stop_render_loop=lambda: None, hide=lambda: None))
    object.__setattr__(app, "tray", SimpleNamespace(update_state=lambda running: None))
    object.__setattr__(app, "state_changed", SimpleNamespace(emit=lambda running: None))
    object.__setattr__(app, "ai_worker", Mock(mark_stopping=lambda: None))
    object.__setattr__(app, "personae", SimpleNamespace(pick_random=lambda: "p1", get_prompt=lambda _p: ("sys", "user")))
    object.__setattr__(app, "capturer", SimpleNamespace(grab=lambda: None))

    for name in (
        "_has_visual_request_in_flight",
        "_scene_api_block_reason",
        "_api_schedule_block_reason",
        "_consume_request_timing",
        "_rtt_avg",
        "_smart_cooldown_ms",
        "_reply_request_id",
        "_register_request_meta",
        "_pop_request_meta",
        "_release_inflight_for_source",
        "_ensure_stats_state",
        "_on_ai_reply",
        "_on_ai_error",
    ):
        object.__setattr__(app, name, getattr(DanmuApp, name).__get__(app, DanmuApp))

    object.__setattr__(app, "_log_api_schedule", lambda **_kwargs: None)
    object.__setattr__(app, "_publish_live_status", lambda: None)
    object.__setattr__(app, "_should_request_new_batch", lambda: True)
    object.__setattr__(app, "_set_error_status_safe", lambda *_args, **_kwargs: None)
    object.__setattr__(app, "_apply_screenshot_interval_backoff", lambda: None)
    object.__setattr__(app, "_record_scene_memory_display", lambda *_args, **_kwargs: None)
    object.__setattr__(app, "_memory_enabled", lambda: False)
    object.__setattr__(app, "_current_persona", "p1")
    object.__setattr__(app, "_visible_display_count", lambda: 0)
    app.engine.running = True
    return app


def test_min_api_interval_blocks_and_then_allows(monkeypatch):
    app = _make_request_app()
    app._last_api_trigger_at = 100.0

    monkeypatch.setenv("DANMU_MIN_API_INTERVAL_MS", "800")
    monkeypatch.setattr(api_schedule.time, "monotonic", lambda: 100.5)
    assert app._api_schedule_block_reason(enforce_min_interval=True) == "min_api_interval"

    monkeypatch.setattr(api_schedule.time, "monotonic", lambda: 100.81)
    assert app._api_schedule_block_reason(enforce_min_interval=True) == ""


def test_consume_request_timing_updates_history_and_clears_id(monkeypatch):
    app = _make_request_app()
    request_id = app._reply_request_id(2, 7, 0)
    app._request_started_at_by_id[request_id] = 10.0
    app._register_request_meta(2, 7, 0, "visual")
    monkeypatch.setattr(main.time, "monotonic", lambda: 11.5)

    app._consume_request_timing(2, 7, 0)

    assert request_id not in app._request_started_at_by_id
    assert app._rtt_history == pytest.approx([1.5])


def test_request_timing_keys_do_not_collide_for_mic_and_visual(monkeypatch):
    app = _make_request_app()
    visual_id = app._reply_request_id(3, 5, 0)
    mic_id = app._reply_request_id(-1, 5, 0)
    assert visual_id != mic_id

    app._get_request_timing_service().mark_started(request_id=visual_id, now=10.0)
    app._get_request_timing_service().mark_started(request_id=mic_id, now=20.0)
    monkeypatch.setattr(main.time, "monotonic", lambda: 21.5)

    visual_rtt = app._get_request_timing_service().consume_timing(request_id=visual_id, now=21.5)
    assert visual_rtt == pytest.approx(11.5)
    assert mic_id in app._request_started_at_by_id


def test_request_scheduler_records_trigger_time():
    app = _make_request_app()
    scheduler = RequestScheduler()
    object.__setattr__(app, "_request_scheduler", scheduler)

    scheduler.record_trigger_time(now=42.0)
    assert scheduler.last_api_trigger_at == 42.0


def test_request_timing_service_avg_rtt():
    service = RequestTimingService()
    service.rtt_history = [1.0, 2.0, 3.0]
    assert service.avg_rtt() == pytest.approx(2.0)


def test_rtt_history_facade_stays_in_sync(monkeypatch):
    app = _make_request_app()
    request_id = app._reply_request_id(1, 1, 0)
    app._request_started_at_by_id[request_id] = 0.0
    monkeypatch.setattr(main.time, "monotonic", lambda: 1.0)

    app._consume_request_timing(1, 1, 0)

    assert app._rtt_history == [1.0]
    assert app._get_request_timing_service().rtt_history == [1.0]


def test_on_ai_reply_consumes_timing_on_success_path(monkeypatch):
    app = _make_request_app()
    app.ai_in_flight = 1
    app._is_generating = True
    request_id = app._reply_request_id(3, 5, 0)
    app._request_started_at_by_id[request_id] = 10.0
    app._register_request_meta(3, 5, 0, "visual")
    app._is_reply_stale = lambda *_args, **_kwargs: (False, "")  # type: ignore[method-assign]
    app._enqueue_reply_batch = Mock()
    app._consume_reply_queue = Mock()
    app.reply_timer.active = False
    monkeypatch.setattr(main.time, "monotonic", lambda: 11.2)
    monkeypatch.setattr(main, "parse_ai_reply_with_memory", lambda text, scene_generation: (["A"], None))
    monkeypatch.setattr(main, "normalize_reply_batch", lambda raw_items, **_kwargs: raw_items)

    app._on_ai_reply('["A"]', "p1", 3, 5, 10.0, 0)

    assert request_id not in app._request_started_at_by_id
    assert app._rtt_history == pytest.approx([1.2])
    assert app._enqueue_reply_batch.called
    app._consume_reply_queue.assert_called_once_with()


def test_on_ai_error_consumes_timing_on_error_path(monkeypatch):
    app = _make_request_app()
    app.ai_in_flight = 1
    app._is_generating = True
    request_id = app._reply_request_id(4, 8, 0)
    app._request_started_at_by_id[request_id] = 20.0
    app._register_request_meta(4, 8, 0, "visual")
    monkeypatch.setattr(main.time, "monotonic", lambda: 21.5)

    app._on_ai_error("boom", "p1", 4, 8, 20.0, 0)

    assert request_id not in app._request_started_at_by_id
    assert app._rtt_history == pytest.approx([1.5])
