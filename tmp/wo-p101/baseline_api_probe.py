"""分级、脱敏的 API 探活；默认行为保持为最小 text probe。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.doubao_responses_stream import stream_doubao_responses
from app.errors import AppError
from app.model_providers import normalize_endpoint, normalize_mode
from app.openai_chat_stream import stream_openai_chat
from app.providers.model_discovery import discover_models
from app.providers.request_planner import GenerationRequest, plan_http_request
from app.translations import tr

_STAGES = {"local", "auth_model", "text", "vision", "audio", "stream"}
_CATEGORIES = {
    "invalid_endpoint", "auth_missing", "auth_invalid", "permission_denied", "model_not_found",
    "unsupported_api_family", "unsupported_parameter", "unsupported_modality", "invalid_content_part",
    "rate_limited", "quota_exhausted", "model_not_available_in_region", "timeout", "provider_unavailable", "malformed_stream",
    "empty_output", "unknown_provider_error",
}
_SILENT_WAV = "data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAACABAAZGF0YQAAAAA="
_PIXEL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/9pM5WQAAAABJRU5ErkJggg=="


@dataclass
class ProbeResult:
    ok: bool
    message: str
    status_code: int | None = None
    stage: str = "text"
    provider_id: str | None = None
    model_id: str | None = None
    error_category: str | None = None
    message_key: str | None = None
    capability_updates: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def probe_connection(endpoint: str, api_key: str, model_id: str, mode: str, *, stage: str = "text") -> ProbeResult:
    endpoint, api_key, model_id, mode = normalize_endpoint(endpoint), (api_key or "").strip(), (model_id or "").strip(), normalize_mode(mode)
    stage = (stage or "text").strip().lower()
    base = dict(stage=stage, provider_id=None, model_id=model_id or None)
    if stage not in _STAGES:
        return _result(False, "custom_model.test_failed", "unknown_provider_error", **base)
    if not endpoint:
        return _result(False, "custom_model.error_endpoint", "invalid_endpoint", **base)
    parts = urlsplit(endpoint)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return _result(False, "custom_model.error_endpoint", "invalid_endpoint", **base)
    if mode not in {"openai-compatible", "doubao"}:
        return _result(False, "ai.error_request_failed", "unsupported_api_family", **base)
    if not api_key:
        return _result(False, "custom_model.error_api_key", "auth_missing", **base)
    if not model_id:
        return _result(False, "custom_model.error_model_id", "model_not_found", **base)
    if stage == "local":
        try:
            planned = plan_http_request(GenerationRequest("connection_probe", model_id, endpoint, api_key, mode, user_text="ping", max_output_tokens=1, stream=False, force_thinking_off=True))
            return _result(True, "custom_model.test_ok", None, provider_id=planned.provider_id, model_id=model_id or None, stage=stage, warnings=planned.warnings)
        except Exception as exc:
            return _classify_exception(exc, **base)
    try:
        planned = plan_http_request(GenerationRequest(
            "connection_probe", model_id, endpoint, api_key, mode, user_text="ping", max_output_tokens=1,
            stream=stage in {"stream"}, force_thinking_off=True,
            image_data_uri=_PIXEL if stage == "vision" else None,
            audio_data_uri=_SILENT_WAV if stage == "audio" else None,
            supports_vision_override=True if stage == "vision" else None,
            supports_mic_override=True if stage == "audio" else None,
        ))
        base.update(provider_id=planned.provider_id)
        if stage == "auth_model":
            return _probe_models(endpoint, api_key, planned.provider_id, model_id, stage)
        return _post_probe(planned, **base)
    except Exception as exc:
        return _classify_exception(exc, **base)


def _probe_models(endpoint: str, api_key: str, provider_id: str, model_id: str, stage: str) -> ProbeResult:
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            discovery = discover_models(provider_id, api_key, endpoint=endpoint, http_client=client)
        models = tuple(getattr(discovery, "models", ()) or ())
        if getattr(discovery, "discovery_kind", "") != "account_discovery" or not models:
            category, status_code = _discovery_failure(discovery)
            return _result(False, "ai.error_request_failed", category, status_code, stage=stage, provider_id=provider_id, model_id=model_id, warnings=["models_unavailable"])
        visible = {str(getattr(item, "id", "")) for item in models}
        if model_id not in visible:
            return _result(False, "ai.error_request_failed", "model_not_found", stage=stage, provider_id=provider_id, model_id=model_id, capability_updates={"model_visible": False, "vision": None})
        return _result(True, "custom_model.test_ok", None, stage=stage, provider_id=provider_id, model_id=model_id, capability_updates={"model_visible": True, "vision": None}, warnings=["vision_not_verified"])
    except Exception as exc:
        return _classify_exception(exc, stage=stage, provider_id=provider_id, model_id=model_id)


def _discovery_failure(discovery) -> tuple[str, int | None]:
    """Map discovery's safe status markers without exposing warning text."""
    status = str(getattr(discovery, "status", "") or "").lower()
    warnings = tuple(str(item).lower() for item in (getattr(discovery, "warnings", ()) or ()))
    warning_text = " ".join(warnings)
    status_code = None
    marker = next((item for item in warnings if item.startswith("http_status:")), "")
    if marker:
        try:
            status_code = int(marker.split(":", 1)[1])
        except (TypeError, ValueError):
            status_code = None
    if status_code == 401:
        return "auth_invalid", status_code
    if status_code == 403:
        return "permission_denied", status_code
    if status_code == 404:
        return "model_not_found", status_code
    if status_code == 402:
        return "quota_exhausted", status_code
    if status_code == 429:
        return "rate_limited", status_code
    if status_code and status_code >= 500:
        return "provider_unavailable", status_code
    if any(token in status or token in warning_text for token in ("timeout", "timed out", "connect", "network", "request_error")):
        return "provider_unavailable", status_code
    return "model_not_found", status_code


def _post_probe(planned, stage: str, **base) -> ProbeResult:
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            if stage == "stream":
                return _stream_probe(client, planned, **base)
            response = client.post(planned.url, headers=planned.headers, json=planned.json_body)
        response.raise_for_status()
        return _result(True, "custom_model.test_ok", None, response.status_code, request_id=_request_id(response), warnings=planned.warnings, capability_updates=_stage_capabilities(stage), stage=stage, **base)
    except Exception as exc:
        return _classify_exception(exc, stage=stage, **base)


def _stream_probe(client, planned, **base) -> ProbeResult:
    if planned.api_family == "openai_responses":
        parsed = stream_doubao_responses(client, planned.url, planned.headers, planned.json_body)
    else:
        parsed = stream_openai_chat(client, planned.url, planned.headers, planned.json_body, endpoint=planned.url)
    text = str(getattr(parsed, "text", "") or "").strip()
    parser_error = bool(str(getattr(parsed, "error", "") or "").strip())
    reasoning_only = bool(getattr(parsed, "reasoning_only", False))
    updates = {
        "input_tokens": int(getattr(parsed, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(parsed, "output_tokens", 0) or 0),
    }
    if not text:
        if parser_error:
            return _result(False, "ai.error_request_failed", "malformed_stream", capability_updates={"stream": True, **updates}, warnings=["stream_parser_error"], stage="stream", **base)
        if reasoning_only:
            return _result(True, "custom_model.test_ok", None, capability_updates={"stream": True, **updates}, warnings=["reasoning_only", "no_visible_content"], stage="stream", **base)
        return _result(False, "ai.error_request_failed", "empty_output", capability_updates={"stream": True, **updates}, warnings=["empty_stream_content"], stage="stream", **base)
    warnings = list(getattr(planned, "warnings", ()) or ())
    if reasoning_only:
        warnings.append("reasoning_only")
    return _result(True, "custom_model.test_ok", None, capability_updates={"stream": True, **updates}, warnings=warnings, stage="stream", **base)


def _stage_capabilities(stage: str) -> dict[str, bool]:
    return {
        "text": {"text_input": True},
        "vision": {"vision": True, "image_input": True},
        "audio": {"mic_audio": True, "audio_input": True},
    }.get(stage, {})


def _classify_exception(exc: Exception, **base) -> ProbeResult:
    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    category = {400: "invalid_content_part", 401: "auth_invalid", 403: "permission_denied", 404: "model_not_found", 408: "timeout", 413: "unsupported_modality", 415: "unsupported_modality", 422: "unsupported_parameter", 429: "rate_limited", 402: "quota_exhausted"}.get(status)
    provider_hint = _private_error_hint(response) or str(exc).lower()
    if any(token in provider_hint for token in ("region", "geo", "location", "not available in your country")):
        category = "model_not_available_in_region"
    if status and status >= 500:
        category = "provider_unavailable"
    if isinstance(exc, (httpx.TimeoutException, httpx.ConnectTimeout)):
        category = "timeout"
    if isinstance(exc, (httpx.ConnectError, httpx.NetworkError)):
        category = "provider_unavailable"
    category = category or ("unknown_provider_error" if not isinstance(exc, AppError) else "unknown_provider_error")
    key = "ai.error_timeout" if category == "timeout" else ("ai.error_connection_failed" if isinstance(exc, httpx.ConnectError) else "ai.error_request_failed")
    return _result(False, key, category, status, request_id=_request_id(response), **base)


def _private_error_hint(response) -> str:
    """Read only bounded classification hints; never return or log the payload."""
    if response is None:
        return ""
    try:
        text = response.text
    except Exception:
        return ""
    if not isinstance(text, str):
        return ""
    return text[:2048].lower()


def _result(ok: bool, key: str, category: str | None, status_code: int | None = None, **kwargs) -> ProbeResult:
    message = tr(key)
    if key == "ai.error_request_failed":
        message = tr(key).format(error=category or "request failed")
    return ProbeResult(ok, message, status_code, error_category=category, message_key=key, **kwargs)


def _request_id(response) -> str | None:
    if response is None:
        return None
    for key in ("x-request-id", "request-id", "x-amzn-requestid"):
        value = response.headers.get(key)
        if isinstance(value, str) and value and len(value) <= 128 and all(ord(c) >= 32 for c in value):
            return value
    return None
