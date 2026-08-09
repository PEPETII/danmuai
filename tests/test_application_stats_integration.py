"""Integration tests for app-session stats across danmu rounds."""

import time
from types import SimpleNamespace

from app.application.application_stats_state import ApplicationStatsState
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.lifetime_stats import STATS_LIFETIME_DANMU, LifetimeStats
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig


def _make_snapshot_app(**overrides):
    fields = {
        "engine": SimpleNamespace(running=False),
        "reply_buffer": SimpleNamespace(size=lambda: 0),
        "visible_display_count": lambda: 0,
        "stats_state": StatsState(),
        "application_stats_state": ApplicationStatsState(start_time=time.monotonic()),
        "web_runtime_state": WebRuntimeState(),
        "personae": SimpleNamespace(get_active=lambda: []),
        "config": FakeConfig({"screen_index": "0", "_api_key": "sk-test", "danmu_render_mode": "scrolling"}),
        "lifetime_stats": SimpleNamespace(snapshot=lambda **_kwargs: {}),
        "session_run_log": SimpleNamespace(list_dicts_newest_first=lambda: []),
        "build_live_status_snapshot": lambda: None,
        "latest_displayed_round": 0,
        "latest_requested_screenshot_id": 0,
        "latest_queued_screenshot_id": 0,
        "latest_displayed_screenshot_id": 0,
        "_region_selection_state": "idle",
    }
    fields.update(overrides)
    app = SimpleNamespace(**fields)
    app.build_status_snapshot = lambda: DanmuApp.build_status_snapshot(app)
    return app


def test_status_snapshot_exposes_app_session_fields_at_startup():
    app_stats = ApplicationStatsState(start_time=time.monotonic() - 12.0)
    app = _make_snapshot_app(
        application_stats_state=app_stats,
        stats_state=StatsState(),
    )
    status = DanmuApp.build_status_snapshot(app)

    assert status["app_session_danmu_count"] == 0
    assert status["app_session_input_tokens"] == 0
    assert status["app_session_output_tokens"] == 0
    assert status["app_session_runtime_sec"] >= 10.0
    assert status["danmu_count"] == 0
    assert status["queue_count"] == 0
    assert status["display_count"] == 0


def test_app_session_accumulates_across_danmu_rounds():
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        stats_state=StatsState(),
        application_stats_state=ApplicationStatsState(start_time=time.monotonic()),
        personae=SimpleNamespace(get_active=lambda: []),
    )
    object.__setattr__(
        app,
        "_update_stats",
        DanmuApp._update_stats.__get__(app, DanmuApp),
    )
    object.__setattr__(
        app,
        "_account_reply_token_usage",
        DanmuApp._account_reply_token_usage.__get__(app, DanmuApp),
    )
    object.__setattr__(
        app,
        "_ensure_application_stats_state",
        DanmuApp._ensure_application_stats_state.__get__(app, DanmuApp),
    )
    object.__setattr__(app, "build_live_status_snapshot", lambda: None)
    object.__setattr__(app, "_region_selection_state", "idle")

    DanmuApp._update_stats(app, success=True, count=2)
    DanmuApp._account_reply_token_usage(app, 100, 40)

    status_round1 = DanmuApp.build_status_snapshot(app)
    assert status_round1["app_session_danmu_count"] == 2
    assert status_round1["app_session_input_tokens"] == 100
    assert status_round1["app_session_output_tokens"] == 40
    assert status_round1["danmu_count"] == 2
    assert status_round1["input_tokens"] == 100

    app.stats_state.reset_session(start_time=time.monotonic())
    status_after_reset = DanmuApp.build_status_snapshot(app)
    assert status_after_reset["danmu_count"] == 0
    assert status_after_reset["input_tokens"] == 0
    assert status_after_reset["output_tokens"] == 0
    assert status_after_reset["app_session_danmu_count"] == 2
    assert status_after_reset["app_session_input_tokens"] == 100
    assert status_after_reset["app_session_output_tokens"] == 40

    DanmuApp._update_stats(app, success=True, count=1)
    DanmuApp._account_reply_token_usage(app, 20, 10)
    status_round2 = DanmuApp.build_status_snapshot(app)
    assert status_round2["danmu_count"] == 1
    assert status_round2["input_tokens"] == 20
    assert status_round2["app_session_danmu_count"] == 3
    assert status_round2["app_session_input_tokens"] == 120
    assert status_round2["app_session_output_tokens"] == 50


def test_new_application_stats_state_resets_app_session_only():
    lifetime = LifetimeStats(FakeConfig({STATS_LIFETIME_DANMU: "99"}))
    app_stats = ApplicationStatsState(start_time=time.monotonic())
    app_stats.add_danmu(5)
    app_stats.add_tokens(10, 5)

    app = _make_snapshot_app(
        application_stats_state=app_stats,
        lifetime_stats=lifetime,
    )
    status_before = DanmuApp.build_status_snapshot(app)
    assert status_before["app_session_danmu_count"] == 5
    assert status_before["lifetime_danmu_count"] == 99

    fresh_app = _make_snapshot_app(
        application_stats_state=ApplicationStatsState(start_time=time.monotonic()),
        lifetime_stats=lifetime,
    )
    status_after = DanmuApp.build_status_snapshot(fresh_app)
    assert status_after["app_session_danmu_count"] == 0
    assert status_after["app_session_input_tokens"] == 0
    assert status_after["lifetime_danmu_count"] == 99


def test_stop_session_run_log_uses_round_stats_not_app_session():
    from app.config_store import ConfigStore
    from app.session_run_log import SessionRunLog

    store = ConfigStore()
    session_log = SessionRunLog(store)
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=store,
        stats_state=StatsState(
            danmu_count=7,
            total_input_tokens=100,
            total_output_tokens=30,
            start_time=time.monotonic(),
        ),
        application_stats_state=ApplicationStatsState(start_time=time.monotonic()),
        session_run_log=session_log,
    )
    session_log.begin(started_at=time.time(), model="test-model")
    session_log.complete(
        ended_at=time.time(),
        input_tokens=app.stats_state.total_input_tokens,
        output_tokens=app.stats_state.total_output_tokens,
        danmu_count=app.stats_state.danmu_count,
    )
    runs = session_log.list_dicts_newest_first()
    assert runs[0]["danmu_count"] == 7
    assert runs[0]["input_tokens"] == 100
    assert runs[0]["output_tokens"] == 30
