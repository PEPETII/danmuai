"""Tests for problem classifiers."""

import httpx
from app.ai_client_support import classify_network_error, problem_code_for_http_error
from app.problems.classifier import classify_http_status_error


def _http_error(status_code: int, *, json_body: dict | None = None) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request, json=json_body or {})
    return httpx.HTTPStatusError("error", request=request, response=response)


def test_http_401_maps_to_ai_auth():
    assert problem_code_for_http_error(_http_error(401)) == "AI-AUTH-001"


def test_http_402_maps_to_ai_balance():
    assert problem_code_for_http_error(_http_error(402)) == "AI-BALANCE-001"


def test_http_429_maps_to_ai_rate():
    assert problem_code_for_http_error(_http_error(429)) == "AI-RATE-001"


def test_http_504_maps_to_ai_timeout():
    assert problem_code_for_http_error(_http_error(504)) == "AI-TIMEOUT-001"


def test_model_not_found_maps_to_ai_model():
    exc = _http_error(
        404,
        json_body={"error": {"message": "model does not exist", "code": "ModelNotFound"}},
    )
    assert problem_code_for_http_error(exc) == "AI-MODEL-001"


def test_timeout_exception_maps_to_ai_timeout():
    classification = classify_network_error(httpx.TimeoutException("timeout"))
    assert classification.code == "AI-TIMEOUT-001"


def test_connect_error_maps_to_network():
    request = httpx.Request("POST", "https://api.example.com/v1/chat/completions")
    exc = httpx.ConnectError("connection refused", request=request)
    classification = classify_network_error(exc)
    assert classification.code == "NETWORK-001"


def test_unknown_exception_maps_to_internal():
    classification = classify_network_error(RuntimeError("boom"))
    assert classification.code == "INTERNAL-001"


def test_classify_http_status_error_includes_safe_context():
    classification = classify_http_status_error(
        _http_error(401),
        provider_id="openai",
        model_id="gpt-test",
    )
    assert classification.code == "AI-AUTH-001"
    assert classification.context["status_code"] == 401
    assert classification.context["provider_id"] == "openai"
    assert "api_key" not in classification.context


def test_problem_code_from_error_message_auth():
    from app.problems.classifier import problem_code_from_error_message
    from app.translations import tr

    assert problem_code_from_error_message(tr("ai.error_auth_failed")).code == "AI-AUTH-001"
