"""Tests for ProblemService."""

from unittest.mock import patch

from app.problems.service import PROBLEM_DEDUP_WINDOW_SEC, ProblemService


def test_same_fingerprint_within_window_increments_count():
    service = ProblemService()
    first = service.report(
        "AI-AUTH-001",
        technical_detail="HTTP 401",
        context={"provider_id": "openai", "model_id": "gpt-test"},
    )
    second = service.report(
        "AI-AUTH-001",
        technical_detail="HTTP 401",
        context={"provider_id": "openai", "model_id": "gpt-test"},
    )
    assert first.event_id == second.event_id
    assert second.occurrence_count == 2


def test_different_codes_create_different_events():
    service = ProblemService()
    first = service.report("AI-AUTH-001", context={"provider_id": "openai"})
    second = service.report("AI-RATE-001", context={"provider_id": "openai"})
    assert first.event_id != second.event_id
    assert first.code != second.code


def test_dedup_window_expired_creates_new_event():
    service = ProblemService()
    with patch("app.problems.service.time.time", return_value=1000.0):
        first = service.report("AI-AUTH-001", context={"provider_id": "openai"})
    with patch("app.problems.service.time.time", return_value=1000.0 + PROBLEM_DEDUP_WINDOW_SEC + 1):
        second = service.report("AI-AUTH-001", context={"provider_id": "openai"})
    assert first.event_id != second.event_id
    assert second.occurrence_count == 1


def test_clear_removes_active_problem():
    service = ProblemService()
    service.report("NETWORK-001")
    assert service.active_problem() is not None
    service.clear()
    assert service.active_problem() is None


def test_clear_by_code_only_clears_matching_active_problem():
    service = ProblemService()
    service.report("NETWORK-001")
    service.clear(code="AI-AUTH-001")
    assert service.active_problem() is not None
    service.clear(code="NETWORK-001")
    assert service.active_problem() is None


def test_recent_problems_keeps_history():
    service = ProblemService()
    service.report("AI-AUTH-001", context={"provider_id": "a"})
    service.report("AI-RATE-001", context={"provider_id": "b"}, force_new_event=True)
    recent = service.recent_problems(limit=5)
    assert len(recent) == 2
    assert {item.code for item in recent} == {"AI-AUTH-001", "AI-RATE-001"}
