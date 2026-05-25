"""API rhythm scheduling: in-flight gate, cold-start interval, scene cooldown."""

import time
from unittest.mock import MagicMock

import pytest
from app.api_schedule import ENGINE_BASE_FPS, min_api_interval_ms, time_to_anchor_boundary
from app.live_freshness import SCENE_RHYTHM_PAUSE_SEC
from main import BatchTracker

from tests.test_p0_main_flow import FakeLogger, _make_minimal_app


def _bind_schedule(app, **overrides):
    defaults = {
        "engine": MagicMock(running=True),
        "_failure_backoff_paused": False,
        "_latest_screenshot": object(),
        "_latest_screenshot_id": 1,
        "_latest_requested_screenshot_id": 0,
        "_scene_generation": 0,
        "_scene_rhythm_pause_until": 0.0,
        "_scene_captures_after_change": 0,
        "_scene_api_gate_active": False,
        "_last_api_trigger_at": 0.0,
        "_is_generating": False,
        "ai_in_flight": 0,
        "_rtt_history": [],
        "personae": MagicMock(pick_random=MagicMock(return_value="p1"), get_prompt=MagicMock(return_value=("s", "u"))),
        "_publish_live_status": lambda: None,
        "config": MagicMock(
            get_int=MagicMock(side_effect=lambda k, d=0: d),
            get_float=MagicMock(return_value=2.2),
        ),
        "screenshot_round": 0,
        "_batch_id": 0,
        "_latest_screenshot_time": time.monotonic(),
        "logger": FakeLogger(),
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        object.__setattr__(app, key, value)


@pytest.fixture
def schedule_app():
    app = _make_minimal_app()
    calls = []

    def _record(source="unknown"):
        block = app._api_schedule_block_reason(enforce_min_interval=True)
        if block:
            return
        app._last_api_trigger_at = time.monotonic()
        calls.append(source)

    _bind_schedule(app)
    app._trigger_api_call = _record  # type: ignore[method-assign]
    app._visible_display_count = lambda: 0  # type: ignore[method-assign]
    app._rtt_avg = lambda: 0.0  # type: ignore[method-assign]
    app.calls = calls
    return app


def test_max_in_flight_no_concurrent_burst(schedule_app):
    schedule_app.ai_in_flight = 1
    schedule_app._is_generating = True
    for _ in range(10):
        schedule_app._check_rhythm_trigger()
    assert schedule_app.calls == []


def test_cold_start_min_interval(monkeypatch, schedule_app):
    times = [1000.0]

    def mono():
        return times[-1]

    monkeypatch.setattr("main.time.monotonic", mono)
    schedule_app._check_rhythm_trigger()
    assert schedule_app.calls == ["cold_start"]

    schedule_app._is_generating = False
    schedule_app.ai_in_flight = 0
    times.append(1000.2)
    schedule_app._check_rhythm_trigger()
    assert schedule_app.calls == ["cold_start"]

    times.append(1000.0 + min_api_interval_ms() / 1000.0 + 0.05)
    schedule_app._check_rhythm_trigger()
    assert schedule_app.calls == ["cold_start", "cold_start"]


def test_rhythm_once_per_batch(schedule_app):
    batch = BatchTracker(batch_id=1)
    batch.next_generation_time = 0.0
    batch.next_generation_triggered = False
    schedule_app._current_batch = batch

    schedule_app._check_rhythm_trigger()
    assert schedule_app.calls == ["rhythm"]
    assert batch.next_generation_triggered is True

    schedule_app._check_rhythm_trigger()
    assert schedule_app.calls == ["rhythm"]


def test_if_ready_respects_in_flight(schedule_app):
    schedule_app.ai_in_flight = 1
    schedule_app.reply_buffer.clear()
    schedule_app._trigger_api_call_if_ready()
    assert schedule_app.calls == []


def test_scene_cooldown_blocks_rhythm(monkeypatch, schedule_app):
    t = 2000.0
    monkeypatch.setattr("main.time.monotonic", lambda: t)
    schedule_app._scene_rhythm_pause_until = t + SCENE_RHYTHM_PAUSE_SEC
    schedule_app._check_rhythm_trigger()
    assert schedule_app.calls == []


def test_scene_settle_blocks_until_capture(schedule_app):
    schedule_app._scene_api_gate_active = True
    schedule_app._scene_captures_after_change = 0
    schedule_app._check_rhythm_trigger()
    assert schedule_app.calls == []


def test_anchor_uses_60fps_baseline():
    distance = 500.0
    speed = 2.2
    expected = distance / (speed * ENGINE_BASE_FPS)
    assert time_to_anchor_boundary(distance, speed) == pytest.approx(expected, rel=1e-5)


def test_time_to_anchor_boundary_zero_distance():
    assert time_to_anchor_boundary(0.0, 2.2) == 0.0
