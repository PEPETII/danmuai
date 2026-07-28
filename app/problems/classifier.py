"""Classify exceptions and configuration gaps into stable problem codes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.problems.sanitizer import sanitize_context, sanitize_technical_detail

_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2, "fatal": 3}


@dataclass(frozen=True)
class ProblemClassification:
    code: str
    technical_detail: str = ""
    context: dict[str, Any] | None = None


def _looks_like_model_not_found(status: int, code: object, message: str) -> bool:
    if status == 404:
        return True
    if code in (20012, "ModelNotFound", "InvalidEndpointOrModel.NotFound"):
        return True
    lower = message.lower()
    if "model does not exist" in lower or "model not found" in lower:
        return True
    if "模型" in message and ("不存在" in message or "未找到" in message or "无效" in message):
        return True
    return False


def _extract_http_message(exc: httpx.HTTPStatusError) -> str:
    try:
        body = exc.response.json()
        if isinstance(body, dict):
            message = body.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
            err = body.get("error")
            if isinstance(err, dict):
                nested = err.get("message")
                if isinstance(nested, str) and nested.strip():
                    return nested.strip()
            elif isinstance(err, str) and err.strip():
                return err.strip()
    except Exception:
        pass
    return ""


def problem_code_for_http_error(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    if status in (401, 403):
        return "AI-AUTH-001"
    if status == 402:
        return "AI-BALANCE-001"
    if status == 429:
        return "AI-RATE-001"
    if status == 504:
        return "AI-TIMEOUT-001"
    message = _extract_http_message(exc)
    code = None
    try:
        body = exc.response.json()
        if isinstance(body, dict):
            code = body.get("code")
            err = body.get("error")
            if isinstance(err, dict) and err.get("code") is not None:
                code = code or err.get("code")
    except Exception:
        pass
    if _looks_like_model_not_found(status, code, message):
        return "AI-MODEL-001"
    return "INTERNAL-001"


def classify_http_status_error(
    exc: httpx.HTTPStatusError,
    *,
    provider_id: str = "",
    model_id: str = "",
) -> ProblemClassification:
    code = problem_code_for_http_error(exc)
    detail = sanitize_technical_detail(f"HTTP {exc.response.status_code}")
    context = sanitize_context(
        {
            "status_code": exc.response.status_code,
            "provider_id": provider_id,
            "model_id": model_id,
        }
    )
    return ProblemClassification(code=code, technical_detail=detail, context=context)


def classify_network_error(
    exc: Exception,
    *,
    provider_id: str = "",
    model_id: str = "",
) -> ProblemClassification:
    if isinstance(exc, httpx.TimeoutException):
        return ProblemClassification(
            code="AI-TIMEOUT-001",
            technical_detail=sanitize_technical_detail(type(exc).__name__),
            context=sanitize_context({"provider_id": provider_id, "model_id": model_id}),
        )
    if isinstance(exc, httpx.HTTPStatusError):
        return classify_http_status_error(exc, provider_id=provider_id, model_id=model_id)
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError, httpx.RemoteProtocolError)):
        return ProblemClassification(
            code="NETWORK-001",
            technical_detail=sanitize_technical_detail(type(exc).__name__),
            context=sanitize_context({"provider_id": provider_id, "model_id": model_id}),
        )
    return ProblemClassification(
        code="INTERNAL-001",
        technical_detail=sanitize_technical_detail(str(exc)),
        context=sanitize_context({"provider_id": provider_id, "model_id": model_id}),
    )


def classify_configuration_gap(*, missing_model_profile: bool = False, missing_credentials: bool = False) -> str:
    if missing_model_profile or missing_credentials:
        return "CONFIG-001"
    return "CONFIG-001"


def problem_code_from_error_message(message: str) -> ProblemClassification:
    """Map backend user-facing error text (tr()) to stable problem codes."""
    from app.translations import tr

    msg = str(message or "").strip()
    if not msg:
        return ProblemClassification(code="INTERNAL-001")

    exact_map: list[tuple[str, str]] = [
        (tr("ai.error_auth_failed"), "AI-AUTH-001"),
        (tr("ai.error_insufficient_balance"), "AI-BALANCE-001"),
        (tr("ai.error_rate_limited"), "AI-RATE-001"),
        (tr("ai.error_gateway_timeout"), "AI-TIMEOUT-001"),
        (tr("ai.error_model_not_found"), "AI-MODEL-001"),
        (tr("ai.error_timeout"), "AI-TIMEOUT-001"),
        (tr("app.capture_failed_repeated"), "CAPTURE-001"),
    ]
    for known, code in exact_map:
        if msg == known:
            return ProblemClassification(code=code, technical_detail=sanitize_technical_detail(msg))

    lower = msg.lower()
    if any(token in lower for token in ("401", "403", "unauthorized", "invalid api key")):
        return ProblemClassification(code="AI-AUTH-001", technical_detail=sanitize_technical_detail(msg))
    if any(token in msg for token in ("402", "余额", "欠费")) or "balance" in lower:
        return ProblemClassification(code="AI-BALANCE-001", technical_detail=sanitize_technical_detail(msg))
    if "429" in msg or tr("ai.error_rate_limited") in msg:
        return ProblemClassification(code="AI-RATE-001", technical_detail=sanitize_technical_detail(msg))
    if tr("ai.error_model_not_found") in msg or "model not found" in lower:
        return ProblemClassification(code="AI-MODEL-001", technical_detail=sanitize_technical_detail(msg))
    if tr("ai.error_timeout") in msg or "timeout" in lower or "504" in msg:
        return ProblemClassification(code="AI-TIMEOUT-001", technical_detail=sanitize_technical_detail(msg))
    if any(token in lower for token in ("connection", "network", "dns", "tls", "connect")):
        return ProblemClassification(code="NETWORK-001", technical_detail=sanitize_technical_detail(msg))
    if any(token in msg for token in ("未配置", "not configured")) or "endpoint" in lower:
        return ProblemClassification(code="CONFIG-001", technical_detail=sanitize_technical_detail(msg))

    return ProblemClassification(
        code="INTERNAL-001",
        technical_detail=sanitize_technical_detail(msg),
    )


def severity_rank(severity: str) -> int:
    return _SEVERITY_RANK.get(str(severity or "").lower(), 0)
