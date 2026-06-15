"""Tests for persisted lifetime counters."""

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from app.lifetime_stats import (
    STATS_LIFETIME_DANMU,
    STATS_LIFETIME_INPUT_TOKENS,
    STATS_LIFETIME_OUTPUT_TOKENS,
    STATS_LIFETIME_RUNTIME_SEC,
    STATS_LIFETIME_TOKENS,
    LifetimeStats,
)

from tests.fakes import FakeConfig


def _make_bridge_status_app(**attrs):
    """Minimal DanmuApp stand-in whose build_status_snapshot matches production."""
    from main import DanmuApp

    fields = {
        "engine": SimpleNamespace(running=False),
        "reply_buffer": SimpleNamespace(size=lambda: 0),
        "_visible_display_count": lambda: 0,
        "_total_input_tokens": 0,
        "_total_output_tokens": 0,
        "_start_time": 0.0,
        "_web_error_message": "",
        "_web_error_is_error": False,
        "danmu_count": 0,
        "personae": SimpleNamespace(get_active=lambda: []),
        "config": FakeConfig({"screen_index": "0", "_api_key": "sk-test"}),
        "lifetime_stats": SimpleNamespace(snapshot=lambda **_kwargs: {}),
        "session_run_log": SimpleNamespace(list_dicts_newest_first=lambda: []),
        "_build_live_status_snapshot": lambda: None,
        # WebConsoleBridge.__init__ wires these Qt slots/signals
        "start": MagicMock(),
        "stop": MagicMock(),
        "toggle": MagicMock(),
        "request_capture_region_selection": MagicMock(),
        "reset_capture_region": MagicMock(),
        "logger": MagicMock(),
        "state_changed": MagicMock(),
    }
    fields.update(attrs)
    app = SimpleNamespace(**fields)
    app.build_status_snapshot = lambda: DanmuApp.build_status_snapshot(app)
    return app


def test_lifetime_stats_loads_from_config():
    cfg = FakeConfig(
        {
            STATS_LIFETIME_DANMU: "12",
            STATS_LIFETIME_RUNTIME_SEC: "90.5",
            STATS_LIFETIME_TOKENS: "3000",
        }
    )
    stats = LifetimeStats(cfg)
    snap = stats.snapshot(session_runtime_sec=10.0)
    assert snap["lifetime_danmu_count"] == 12
    assert snap["lifetime_runtime_sec"] == 100.5
    assert snap["lifetime_total_tokens"] == 3000
    assert snap["lifetime_input_tokens"] == 0
    assert snap["lifetime_output_tokens"] == 0


def test_lifetime_stats_legacy_total_without_split_keys():
    cfg = FakeConfig({STATS_LIFETIME_TOKENS: "500"})
    stats = LifetimeStats(cfg)
    snap = stats.snapshot()
    assert snap["lifetime_total_tokens"] == 500
    assert snap["lifetime_input_tokens"] == 0
    assert snap["lifetime_output_tokens"] == 0


def test_lifetime_stats_persists_increments():
    cfg = FakeConfig()
    stats = LifetimeStats(cfg)
    stats.add_danmu(2)
    stats.add_tokens(100, 50)
    assert cfg.get(STATS_LIFETIME_DANMU, "") == ""
    stats.flush_pending()
    assert cfg.get(STATS_LIFETIME_DANMU) == "2"
    assert cfg.get(STATS_LIFETIME_INPUT_TOKENS) == "100"
    assert cfg.get(STATS_LIFETIME_OUTPUT_TOKENS) == "50"
    assert cfg.get(STATS_LIFETIME_TOKENS, "") == ""
    stats.flush_runtime(30.0)

    assert cfg.get(STATS_LIFETIME_DANMU) == "2"
    assert cfg.get(STATS_LIFETIME_TOKENS, "") == ""
    assert float(cfg.get(STATS_LIFETIME_RUNTIME_SEC)) == 30.0

    stats2 = LifetimeStats(cfg)
    snap = stats2.snapshot()
    assert snap["lifetime_danmu_count"] == 2
    assert snap["lifetime_input_tokens"] == 100
    assert snap["lifetime_output_tokens"] == 50
    assert snap["lifetime_total_tokens"] == 150


def test_lifetime_stats_persists_legacy_aggregate_when_untracked_tokens():
    cfg = FakeConfig(
        {
            STATS_LIFETIME_TOKENS: "420",
            STATS_LIFETIME_INPUT_TOKENS: "100",
            STATS_LIFETIME_OUTPUT_TOKENS: "40",
        }
    )
    stats = LifetimeStats(cfg)
    assert stats._untracked_tokens == 280
    stats.add_tokens(5, 0)
    stats.flush_pending()
    assert cfg.get(STATS_LIFETIME_TOKENS) == "425"


def test_refresh_status_includes_lifetime_fields():
    from app.web_console import WebConsoleBridge

    app = _make_bridge_status_app(
        lifetime_stats=LifetimeStats(
            FakeConfig({STATS_LIFETIME_DANMU: "7", STATS_LIFETIME_TOKENS: "42"})
        ),
        _start_time=0,
    )
    bridge = WebConsoleBridge(app)
    status = bridge.refresh_status()

    assert status.lifetime_danmu_count == 7
    assert status.lifetime_total_tokens == 42
    assert status.lifetime_input_tokens == 0
    assert status.lifetime_output_tokens == 0
    assert status.lifetime_runtime_sec == 0.0


def test_refresh_status_preserves_legacy_lifetime_extra_alongside_split_fields():
    from app.web_console import WebConsoleBridge

    app = _make_bridge_status_app(
        lifetime_stats=LifetimeStats(
            FakeConfig(
                {
                    STATS_LIFETIME_TOKENS: "420",
                    STATS_LIFETIME_INPUT_TOKENS: "100",
                    STATS_LIFETIME_OUTPUT_TOKENS: "40",
                }
            )
        ),
        _start_time=0,
    )
    bridge = WebConsoleBridge(app)
    status = bridge.refresh_status()

    assert status.lifetime_total_tokens == 420
    assert status.lifetime_input_tokens == 100
    assert status.lifetime_output_tokens == 40


def test_refresh_status_exposes_session_input_output_tokens():
    from app.web_console import WebConsoleBridge

    app = _make_bridge_status_app(
        _total_input_tokens=120,
        _total_output_tokens=30,
    )
    bridge = WebConsoleBridge(app)
    status = bridge.refresh_status()
    assert status.input_tokens == 120
    assert status.output_tokens == 30
    assert status.total_tokens == 150


def test_flush_runtime_preserves_session_when_set_batch_fails():
    cfg = FakeConfig({STATS_LIFETIME_RUNTIME_SEC: "10.0"})
    stats = LifetimeStats(cfg)
    assert stats._runtime_sec == 10.0

    with patch.object(cfg, "set_batch", side_effect=sqlite3.OperationalError("database is locked")):
        with pytest.raises(sqlite3.OperationalError):
            stats.flush_runtime(25.0)

    assert stats._runtime_sec == 10.0
    assert cfg.get(STATS_LIFETIME_RUNTIME_SEC) == "10.0"


def test_flush_runtime_persists_before_mutating_memory():
    cfg = FakeConfig({STATS_LIFETIME_RUNTIME_SEC: "5.0"})
    stats = LifetimeStats(cfg)
    observed: list[float] = []

    original_set_batch = cfg.set_batch

    def track_set_batch(items):
        observed.append(stats._runtime_sec)
        original_set_batch(items)

    cfg.set_batch = track_set_batch
    assert stats.flush_runtime(12.5) is True
    assert observed == [5.0]
    assert stats._runtime_sec == 17.5
    assert float(cfg.get(STATS_LIFETIME_RUNTIME_SEC)) == 17.5

    stats2 = LifetimeStats(cfg)
    assert stats2.snapshot()["lifetime_runtime_sec"] == 17.5


def test_add_danmu_negative_raises():
    stats = LifetimeStats(FakeConfig())
    with pytest.raises(ValueError):
        stats.add_danmu(-1)


def test_add_tokens_negative_raises():
    stats = LifetimeStats(FakeConfig())
    with pytest.raises(ValueError):
        stats.add_tokens(input_tokens=-1)
