"""Tests for ApplicationStatsState (app launch → quit, in-memory)."""

import time

from app.application.application_stats_state import ApplicationStatsState


def test_application_stats_state_defaults_and_runtime():
    before = time.monotonic()
    state = ApplicationStatsState(start_time=before)
    assert state.danmu_count == 0
    assert state.total_input_tokens == 0
    assert state.total_output_tokens == 0
    assert state.runtime_sec(now=before + 5.0) >= 5.0


def test_application_stats_state_accumulates():
    state = ApplicationStatsState(start_time=time.monotonic())
    state.add_danmu(3)
    state.add_tokens(100, 50)
    assert state.danmu_count == 3
    assert state.total_input_tokens == 100
    assert state.total_output_tokens == 50


def test_application_stats_state_has_no_reset():
    assert not hasattr(ApplicationStatsState, "reset_session")
    assert not hasattr(ApplicationStatsState, "clear_runtime")


def test_application_stats_state_add_danmu_ignores_zero():
    state = ApplicationStatsState(start_time=time.monotonic())
    state.add_danmu(0)
    assert state.danmu_count == 0


def test_application_stats_state_add_tokens_ignores_none():
    state = ApplicationStatsState(start_time=time.monotonic())
    state.add_tokens(None, None)
    assert state.total_input_tokens == 0
    assert state.total_output_tokens == 0
