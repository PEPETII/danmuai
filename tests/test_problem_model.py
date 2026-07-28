"""Tests for ProblemDescriptor and ProblemAction."""

from app.problems.model import ProblemAction, ProblemDescriptor


def test_problem_action_is_immutable():
    action = ProblemAction(type="navigate", label_key="problem.action.openModelSettings", target="settings/api")
    assert action.type == "navigate"
    assert action.label_key == "problem.action.openModelSettings"
    assert action.target == "settings/api"
    assert action.payload == {}


def test_problem_descriptor_is_immutable():
    problem = ProblemDescriptor(
        event_id="problem-1-1",
        code="AI-AUTH-001",
        severity="error",
        category="authentication",
        title_key="problem.aiAuth.title",
        summary_key="problem.aiAuth.summary",
        cause_key="problem.aiAuth.cause",
        impact_key="problem.aiAuth.impact",
        suggestion_keys=("problem.aiAuth.suggestion.checkKey",),
        actions=(ProblemAction(type="probe_connection", label_key="problem.action.retryConnection"),),
        technical_detail="HTTP 401",
        fingerprint="AI-AUTH-001|provider_id=openai",
        context={"status_code": 401},
    )
    assert problem.code == "AI-AUTH-001"
    assert problem.occurrence_count == 1
    assert problem.actions[0].type == "probe_connection"
