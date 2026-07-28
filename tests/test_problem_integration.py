"""Integration tests for problem reporting from AI error paths."""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
from app.problems.classifier import problem_code_from_error_message
from app.translations import tr
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app


def test_problem_code_from_auth_message():
    classification = problem_code_from_error_message(tr("ai.error_auth_failed"))
    assert classification.code == "AI-AUTH-001"


def test_http_401_classifier():
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = httpx.Response(401, request=request)
    exc = httpx.HTTPStatusError("auth", request=request, response=response)
    from app.problems.classifier import problem_code_for_http_error

    assert problem_code_for_http_error(exc) == "AI-AUTH-001"


def test_report_problem_from_ai_error_message(qapp):
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app)
    app.web_bridge = MagicMock()
    classification = problem_code_from_error_message(tr("ai.error_rate_limited"))
    app.report_problem(
        classification.code,
        technical_detail=classification.technical_detail or tr("ai.error_rate_limited"),
    )
    active = app.get_active_problem()
    assert active is not None
    assert active["code"] == "AI-RATE-001"
    assert app._ensure_web_runtime_state().is_error is True
