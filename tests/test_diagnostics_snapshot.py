from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import app.api_schedule as api_schedule
import main
import pytest
from app.web_api.routes import register_web_routes
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.diagnostics_helpers import (
    DiagnosticSnapshotBuilder,
    build_diagnostic_report,
    make_diagnostic_app,
)
from tests.fakes import FakeConfig


def test_diagnostic_snapshot_is_read_only(monkeypatch: pytest.MonkeyPatch):
    app = make_diagnostic_app()
    scheduler = app.get_request_scheduler()
    timing = app.get_request_timing_service()
    scheduler.last_api_trigger_at = 100.0
    timing.request_started_at_by_id[7] = 10.0
    timing.rtt_history.clear()
    timing.rtt_history.extend([1.0, 2.0, 3.0])

    before_last_trigger = scheduler.last_api_trigger_at
    before_started = dict(timing.request_started_at_by_id)
    before_history = list(timing.rtt_history)

    monkeypatch.setattr(api_schedule.time, "monotonic", lambda: 102.0)
    monkeypatch.setattr("app.application.diagnostic_snapshot.time.monotonic", lambda: 102.0)

    snapshot = app.build_diagnostic_snapshot()

    assert snapshot["scheduler"]["last_api_trigger_at"] == 100.0
    assert scheduler.last_api_trigger_at == before_last_trigger
    assert timing.request_started_at_by_id == before_started
    assert list(timing.rtt_history) == before_history


def test_request_scheduler_diagnostics_match_current_block_reason(monkeypatch: pytest.MonkeyPatch):
    app = make_diagnostic_app()
    app.get_request_scheduler().last_api_trigger_at = 50.0

    monkeypatch.setenv("DANMU_MIN_API_INTERVAL_MS", "800")
    monkeypatch.setattr(api_schedule.time, "monotonic", lambda: 50.5)
    monkeypatch.setattr("app.application.diagnostic_snapshot.time.monotonic", lambda: 50.5)

    snapshot = DiagnosticSnapshotBuilder(app).build()

    assert snapshot["scheduler"] == {
        "last_api_trigger_at": 50.0,
        "seconds_since_last_trigger": 0.5,
        "min_interval_blocked": True,
        "block_reason": "min_api_interval",
    }
    assert app.get_request_scheduler().last_api_trigger_at == 50.0


def test_request_timing_diagnostics_match_current_avg_and_cooldown(monkeypatch: pytest.MonkeyPatch):
    app = make_diagnostic_app(config=FakeConfig({"screenshot_interval": "3"}))
    timing = app.get_request_timing_service()
    timing.request_started_at_by_id[1] = 10.0
    timing.request_started_at_by_id[2] = 11.0
    timing.rtt_history.clear()
    timing.rtt_history.extend([1.0, 2.0, 3.0, 4.0])

    monkeypatch.setattr(api_schedule.time, "monotonic", lambda: 15.0)
    monkeypatch.setattr("app.application.diagnostic_snapshot.time.monotonic", lambda: 15.0)

    snapshot = app.build_diagnostic_snapshot()
    timing = snapshot["timing"]
    diagnosis = snapshot["diagnosis"]

    assert timing["request_started_count"] == 2
    assert timing["rtt_history_len"] == 4
    assert timing["avg_rtt"] == app._rtt_avg()
    assert timing["smart_cooldown_ms"] == app._smart_cooldown_ms()
    assert timing["recent_rtt_samples"] == [1.0, 2.0, 3.0, 4.0]
    assert diagnosis == {
        "scheduler_blocked": False,
        "high_rtt": False,
        "has_pending_timing": True,
    }


def test_runtime_diagnostics_summarize_runtime_state_without_polluting_status_snapshot(
    monkeypatch: pytest.MonkeyPatch,
):
    app = make_diagnostic_app()
    app.stats_state.danmu_count = 12
    app.stats_state.total_input_tokens = 34
    app.stats_state.total_output_tokens = 56
    app.stats_state.start_time = 90.0
    app.web_runtime_state.set_error_status("warn", is_error=True)
    app.web_runtime_state.set_overlay_cache(danmu_lines=8, layout_mode="compact")
    app._latest_displayed_round = 4
    app._latest_requested_screenshot_id = 101
    app._latest_queued_screenshot_id = 102
    app._latest_displayed_screenshot_id = 103

    monkeypatch.setattr(api_schedule.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr(main.time, "monotonic", lambda: 100.0)
    monkeypatch.setattr("app.application.diagnostic_snapshot.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("app.application.runtime_state.time.monotonic", lambda: 100.0)

    app.config.values.update(
        {
            "api_endpoint": "https://ark.cn-beijing.volces.com/api/v3",
            "api_mode": "doubao",
            "model": "doubao-seed-1-6-flash-250828",
            "default_model_id": "doubao-seed-1-6-flash-250828",
        }
    )

    snapshot = app.build_diagnostic_snapshot()
    status = app.build_status_snapshot()

    assert snapshot["config_context"]["active_model_id"] == "doubao-seed-1-6-flash-250828"
    assert snapshot["config_context"]["provider_id"] == "doubao"
    assert snapshot["config_context"]["api_endpoint_host"] == "ark.cn-beijing.volces.com"
    assert snapshot["config_context"]["api_mode"] == "doubao"
    assert snapshot["runtime_state"]["web_runtime"] == {
        "error_message": "warn",
        "is_error": True,
        "cached_danmu_lines": 8,
        "cached_layout_mode": "compact",
    }
    assert snapshot["runtime_state"]["stats"] == {
        "danmu_count": 12,
        "total_input_tokens": 34,
        "total_output_tokens": 56,
        "runtime_sec": 10.0,
    }
    assert snapshot["runtime_state"]["generation_pipeline"] == {
        "latest_displayed_round": 4,
        "latest_requested_screenshot_id": 101,
        "latest_queued_screenshot_id": 102,
        "latest_displayed_screenshot_id": 103,
    }
    assert "config_context" not in status
    assert "scheduler" not in status
    assert "timing" not in status
    assert "diagnosis" not in status


def test_diagnostics_api_returns_independent_read_only_payload(monkeypatch: pytest.MonkeyPatch):
    app = make_diagnostic_app(config=FakeConfig({"screenshot_interval": "3"}))
    scheduler = app.get_request_scheduler()
    timing = app.get_request_timing_service()
    scheduler.last_api_trigger_at = 100.0
    timing.request_started_at_by_id[7] = 10.0
    timing.rtt_history.clear()
    timing.rtt_history.extend([4.0, 4.0, 4.0])

    before_last_trigger = scheduler.last_api_trigger_at
    before_started = dict(timing.request_started_at_by_id)
    before_history = list(timing.rtt_history)
    status_payload = app.build_status_snapshot()

    monkeypatch.setenv("DANMU_MIN_API_INTERVAL_MS", "800")
    monkeypatch.setattr(api_schedule.time, "monotonic", lambda: 100.5)
    monkeypatch.setattr(main.time, "monotonic", lambda: 100.5)
    monkeypatch.setattr("app.application.diagnostic_snapshot.time.monotonic", lambda: 100.5)
    monkeypatch.setattr("app.application.runtime_state.time.monotonic", lambda: 100.5)

    fastapi_app = FastAPI()
    bridge = SimpleNamespace(danmu_app=app)
    register_web_routes(fastapi_app, bridge, lambda _authorization=None: None)

    @fastapi_app.get("/api/status")
    def status():
        return status_payload

    client = TestClient(fastapi_app)
    diagnostics_res = client.get("/api/diagnostics")
    status_res = client.get("/api/status")

    assert diagnostics_res.status_code == 200
    assert diagnostics_res.json() == {
        "ok": True,
        "diagnostics": {
            "config_context": {
                "active_model_id": "",
                "provider_id": "custom_doubao",
                "api_endpoint_host": "",
                "api_mode": "doubao",
                "model_name": "",
                "api_endpoint": "",
            },
            "scheduler": {
                "last_api_trigger_at": 100.0,
                "seconds_since_last_trigger": 0.5,
                "min_interval_blocked": True,
                "block_reason": "min_api_interval",
            },
            "timing": {
                "request_started_count": 1,
                "rtt_history_len": 3,
                "avg_rtt": 4.0,
                "smart_cooldown_ms": 3600,
                "recent_rtt_samples": [4.0, 4.0, 4.0],
            },
            "runtime_state": {
                "web_runtime": {
                    "error_message": "",
                    "is_error": False,
                    "cached_danmu_lines": 0,
                    "cached_layout_mode": "fullscreen",
                },
                "stats": {
                    "danmu_count": 0,
                    "total_input_tokens": 0,
                    "total_output_tokens": 0,
                    "runtime_sec": 0.0,
                },
                "generation_pipeline": {
                    "latest_displayed_round": 0,
                    "latest_requested_screenshot_id": 0,
                    "latest_queued_screenshot_id": 0,
                    "latest_displayed_screenshot_id": 0,
                },
            },
            "diagnosis": {
                "scheduler_blocked": True,
                "high_rtt": True,
                "has_pending_timing": True,
            },
            "undisplayed": {},
            "knowledge": {
                "enabled": False,
                "fts_backend": "",
                "packages_count": 0,
                "enabled_packages_count": 0,
                "items_count": 0,
                "enabled_items_count": 0,
                "last_injected_count": 0,
            },
        },
    }
    assert diagnostics_res.status_code == 200
    assert status_res.status_code == 200
    assert status_res.json() == status_payload
    assert "diagnostics" not in status_res.json()
    assert scheduler.last_api_trigger_at == before_last_trigger
    assert timing.request_started_at_by_id == before_started
    assert list(timing.rtt_history) == before_history


def test_diagnostics_api_uses_public_app_facade():
    from tests.fakes import FakeConfig

    fastapi_app = FastAPI()
    danmu_app = SimpleNamespace(
        config=FakeConfig(),
        build_diagnostic_snapshot=MagicMock(
            return_value={"scheduler": {}, "timing": {}, "runtime_state": {}, "diagnosis": {}}
        ),
    )
    bridge = SimpleNamespace(danmu_app=danmu_app)
    register_web_routes(fastapi_app, bridge, lambda _authorization=None: None)
    client = TestClient(fastapi_app)

    response = client.get("/api/diagnostics")

    assert response.status_code == 200
    assert response.json()["ok"] is True
    danmu_app.build_diagnostic_snapshot.assert_called_once_with()


def test_diagnostic_report_is_read_only_and_contains_recommendations(monkeypatch: pytest.MonkeyPatch):
    app = make_diagnostic_app(config=FakeConfig({"screenshot_interval": "3"}))
    scheduler = app.get_request_scheduler()
    timing = app.get_request_timing_service()
    scheduler.last_api_trigger_at = 100.0
    timing.request_started_at_by_id[5] = 10.0
    timing.rtt_history.clear()
    timing.rtt_history.extend([4.0, 4.0, 4.0])

    before_last_trigger = scheduler.last_api_trigger_at
    before_started = dict(timing.request_started_at_by_id)
    before_history = list(timing.rtt_history)

    monkeypatch.setenv("DANMU_MIN_API_INTERVAL_MS", "800")
    monkeypatch.setattr(api_schedule.time, "monotonic", lambda: 100.5)
    monkeypatch.setattr("app.application.diagnostic_snapshot.time.monotonic", lambda: 100.5)

    report = app.build_diagnostic_report()

    assert "DanmuAI Diagnostic Report" in report
    assert "block_reason: min_api_interval" in report
    assert "avg_rtt: 4.0" in report
    assert "recommended_next_steps" in report
    assert "Inspect scheduler block reason" in report
    assert scheduler.last_api_trigger_at == before_last_trigger
    assert timing.request_started_at_by_id == before_started
    assert list(timing.rtt_history) == before_history


def test_build_diagnostic_report_formats_existing_snapshot():
    report = build_diagnostic_report(
        {
            "scheduler": {"block_reason": "", "seconds_since_last_trigger": 1.0},
            "timing": {"request_started_count": 0, "avg_rtt": 0.0, "smart_cooldown_ms": 3000, "recent_rtt_samples": []},
            "runtime_state": {"web_runtime": {}, "stats": {}, "generation_pipeline": {}},
            "diagnosis": {
                "scheduler_blocked": False,
                "high_rtt": False,
                "has_pending_timing": False,
            },
        }
    )

    assert "No immediate scheduler/timing anomaly detected" in report



def test_diagnostics_requires_auth():
    """W-SECURITY-001: /api/diagnostics 无 Token 应返回 401。"""
    from fastapi import HTTPException

    from tests.fakes import FakeConfig

    def _check_token(authorization=None):
        if not authorization:
            raise HTTPException(status_code=401, detail="Missing token")

    fastapi_app = FastAPI()
    danmu_app = SimpleNamespace(
        config=FakeConfig(),
        build_diagnostic_snapshot=MagicMock(return_value={}),
    )
    bridge = SimpleNamespace(danmu_app=danmu_app)
    register_web_routes(fastapi_app, bridge, _check_token)
    client = TestClient(fastapi_app, raise_server_exceptions=False)

    response = client.get("/api/diagnostics")
    assert response.status_code == 401


def test_diagnostics_accepts_valid_token():
    """W-SECURITY-001: /api/diagnostics 有 Token 应返回 200。"""
    from tests.fakes import FakeConfig

    fastapi_app = FastAPI()
    danmu_app = SimpleNamespace(
        config=FakeConfig(),
        build_diagnostic_snapshot=MagicMock(return_value={"scheduler": {}}),
    )
    bridge = SimpleNamespace(danmu_app=danmu_app)
    register_web_routes(fastapi_app, bridge, lambda _authorization=None: None)
    client = TestClient(fastapi_app)

    response = client.get("/api/diagnostics", headers={"Authorization": "Bearer test-token"})
    assert response.status_code == 200
    assert response.json()["ok"] is True

def test_diagnostic_report_text_helper_exists_for_error_reporting():
    """W-DIAGNOSTICS-PANEL-REMOVE-001: 面板删除后报告文本 helper 仍供错误上报。"""
    from app.bundle_paths import project_root

    root = project_root()
    helper = (root / "web" / "static" / "modules" / "diagnostic-report-text.js").read_text(
        encoding="utf-8",
    )
    error_js = (root / "web" / "static" / "modules" / "app-error-reporting.js").read_text(
        encoding="utf-8",
    )
    assert "export function buildDiagnosticReportText" in helper
    assert "diagnostic-report-text.js" in error_js
    assert "/api/diagnostics" in error_js

