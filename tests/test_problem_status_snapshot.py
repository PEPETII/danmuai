"""Tests for problem fields in /api/status snapshot."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.application.web_runtime_state import WebRuntimeState
from app.translations import tr
from main import DanmuApp

from tests.fakes import FakeConfig


def _make_app_with_problem(active_problem: dict | None, *, recent: list | None = None):
    return SimpleNamespace(
        engine=SimpleNamespace(running=False),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: 0,
        stats_state=None,
        web_runtime_state=WebRuntimeState(
            error_message=active_problem.get("summary", "") if active_problem else "",
            is_error=bool(active_problem),
            active_problem=active_problem,
            problem_event_id=str(active_problem.get("event_id", "")) if active_problem else "",
            recent_problems=list(recent or []),
        ),
        latest_displayed_round=0,
        latest_requested_screenshot_id=0,
        latest_queued_screenshot_id=0,
        latest_displayed_screenshot_id=0,
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig({"screen_index": "0"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: None,
        get_meme_barrage_status=MagicMock(return_value={}),
        _region_selection_state="idle",
    )


def test_status_snapshot_includes_structured_active_problem():
    active = {
        "event_id": "problem-100-1",
        "code": "AI-AUTH-001",
        "severity": "error",
        "category": "authentication",
        "title": tr("problem.aiAuth.title"),
        "summary": tr("problem.aiAuth.summary"),
        "cause": tr("problem.aiAuth.cause"),
        "impact": tr("problem.aiAuth.impact"),
        "suggestions": [tr("problem.aiAuth.suggestion.checkKey")],
        "actions": [],
        "technical_detail": "HTTP 401",
        "recoverable": True,
        "feedback_allowed": True,
        "occurred_at": 1.0,
        "last_occurred_at": 1.0,
        "occurrence_count": 1,
        "fingerprint": "AI-AUTH-001|provider_id=openai",
        "context": {"status_code": 401, "provider_id": "openai"},
    }
    status = DanmuApp.build_status_snapshot(_make_app_with_problem(active))

    assert status["active_problem"]["code"] == "AI-AUTH-001"
    assert status["problem_event_id"] == "problem-100-1"
    assert status["error_message"] == tr("problem.aiAuth.summary")
    assert status["is_error"] is True


def test_status_snapshot_does_not_contain_api_key():
    active = {
        "event_id": "problem-100-2",
        "code": "AI-AUTH-001",
        "severity": "error",
        "category": "authentication",
        "title": "x",
        "summary": "y",
        "technical_detail": "masked",
        "occurrence_count": 1,
        "context": {"provider_id": "openai"},
    }
    status = DanmuApp.build_status_snapshot(_make_app_with_problem(active))
    problem_payload = str(status.get("active_problem"))
    assert "sk-" not in problem_payload
    assert "Bearer " not in problem_payload


def test_status_snapshot_recent_problems_limited_to_five_summaries():
    recent = [
        {
            "event_id": f"problem-{index}",
            "code": "INTERNAL-001",
            "severity": "fatal",
            "category": "internal",
            "title": f"t{index}",
            "summary": f"s{index}",
            "occurrence_count": 1,
            "fingerprint": f"fp{index}",
            "last_occurred_at": float(index),
        }
        for index in range(7)
    ]
    status = DanmuApp.build_status_snapshot(_make_app_with_problem(None, recent=recent))
    assert len(status["recent_problems"]) == 5
    assert status["recent_problems"][0]["event_id"] == "problem-0"


def test_report_problem_maintains_legacy_error_fields():
    from main import DanmuApp

    app = DanmuApp.__new__(DanmuApp)
    app.web_bridge = None
    runtime = WebRuntimeState()
    object.__setattr__(app, "web_runtime_state", runtime)
    app._ensure_web_runtime_state = DanmuApp._ensure_web_runtime_state.__get__(app, DanmuApp)
    DanmuApp.report_problem(app, "AI-AUTH-001", technical_detail="HTTP 401")
    assert runtime.active_problem is not None
    assert runtime.error_message == runtime.active_problem["summary"]
    assert runtime.is_error is True
