"""Tests for persisted lifetime counters."""

from app.lifetime_stats import (
    STATS_LIFETIME_DANMU,
    STATS_LIFETIME_INPUT_TOKENS,
    STATS_LIFETIME_OUTPUT_TOKENS,
    STATS_LIFETIME_RUNTIME_SEC,
    STATS_LIFETIME_TOKENS,
    LifetimeStats,
)

from tests.test_web_console import FakeConfig


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
    assert cfg.get(STATS_LIFETIME_TOKENS) == "150"
    stats.flush_runtime(30.0)

    assert cfg.get(STATS_LIFETIME_DANMU) == "2"
    assert cfg.get(STATS_LIFETIME_TOKENS) == "150"
    assert float(cfg.get(STATS_LIFETIME_RUNTIME_SEC)) == 30.0

    stats2 = LifetimeStats(cfg)
    snap = stats2.snapshot()
    assert snap["lifetime_danmu_count"] == 2
    assert snap["lifetime_input_tokens"] == 100
    assert snap["lifetime_output_tokens"] == 50
    assert snap["lifetime_total_tokens"] == 150


def test_refresh_status_includes_lifetime_fields():
    from app.web_console import WebConsoleBridge

    from tests.test_web_console import _make_status_app

    app = _make_status_app()
    app.lifetime_stats = LifetimeStats(FakeConfig({STATS_LIFETIME_DANMU: "7", STATS_LIFETIME_TOKENS: "42"}))
    app._start_time = 0

    bridge = WebConsoleBridge(app)
    status = bridge.refresh_status()

    assert status.lifetime_danmu_count == 7
    assert status.lifetime_total_tokens == 42
    assert status.lifetime_input_tokens == 0
    assert status.lifetime_output_tokens == 0
    assert status.lifetime_runtime_sec == 0.0


def test_refresh_status_exposes_session_input_output_tokens():
    from app.web_console import WebConsoleBridge

    from tests.test_web_console import _make_status_app

    app = _make_status_app()
    app._total_input_tokens = 120
    app._total_output_tokens = 30
    bridge = WebConsoleBridge(app)
    status = bridge.refresh_status()
    assert status.input_tokens == 120
    assert status.output_tokens == 30
    assert status.total_tokens == 150
