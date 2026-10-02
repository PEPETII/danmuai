"""AI 客户端辅助函数：纯逻辑、无 Qt 依赖，可安全用于单元测试。

职责：请求扩展构建、HTTP 错误格式化、Provider 特殊处理（MiMo 等）、输出 token 下限计算。
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

import httpx

from app.logger import sanitize_sensitive_text
from app.providers import (
    get_capabilities_for_endpoint,
    get_openai_adapter,
    guess_provider_from_endpoint,
)
from app.providers.request_context import (
    RequestCredentials,
    ResolvedRequestContext,
)
from app.translations import tr

HTTP_ERROR_MESSAGE_DISPLAY_MAX = 240
HTTP_ERROR_MESSAGE_SNIPPET_MAX = 200
DEFAULT_MAX_TOKENS = 512
DANMU_MIN_OUTPUT_TOKENS = 512
DANMU_MIN_OUTPUT_TOKENS_THINKING = 1024


def is_mimo_endpoint(endpoint: str) -> bool:
    return guess_provider_from_endpoint(endpoint) == "mimo"


def build_openai_vision_user_content(endpoint: str, user_pt: str, image_data_uri: str) -> list[dict]:
    adapter = get_openai_adapter(endpoint, "openai-compatible")
    return adapter.build_vision_user_content(user_pt, image_data_uri)


def openai_compatible_request_extensions(endpoint: str, *, max_tokens: int = 0) -> dict[str, object]:
    adapter = get_openai_adapter(endpoint, "openai-compatible")
    caps = get_capabilities_for_endpoint(endpoint, "openai-compatible")
    data: dict[str, object] = {}
    if max_tokens > 0:
        data["max_tokens"] = max_tokens
    adapter.patch_probe_body(data, caps=caps)
    return data


def _parse_http_status_error_body(exc: httpx.HTTPStatusError) -> tuple[str, object, str, object]:
    """解析 HTTP 错误响应 JSON；返回 (message, code, error_as_str, error_dict_code)。"""
    message = ""
    code: object = None
    error_as_str = ""
    error_dict_code: object = None
    try:
        body = exc.response.json()
        if not isinstance(body, dict):
            return "", None, "", None
        code = body.get("code")
        raw = body.get("message")
        if isinstance(raw, str):
            message = raw.strip()
        err = body.get("error")
        if isinstance(err, dict):
            error_dict_code = err.get("code")
            code = code or error_dict_code
            if not message:
                nested = err.get("message")
                if isinstance(nested, str):
                    message = nested.strip()
        elif isinstance(err, str) and err.strip():
            error_as_str = err.strip()
    except (json.JSONDecodeError, ValueError):
        pass
    return message, code, error_as_str, error_dict_code


def _http_error_message_and_code(exc: httpx.HTTPStatusError) -> tuple[str, object]:
    message, code, _, _ = _parse_http_status_error_body(exc)
    return message, code


def extract_http_error_message(exc: httpx.HTTPStatusError) -> str:
    message, _, error_as_str, error_dict_code = _parse_http_status_error_body(exc)
    if message:
        return message
    if error_dict_code is not None:
        return str(error_dict_code)
    return error_as_str


def sanitize_provider_error_snippet(message: str, max_len: int = HTTP_ERROR_MESSAGE_SNIPPET_MAX) -> str:
    text = str(message or "").strip()
    if not text:
        return ""
    safe = sanitize_sensitive_text(text)
    # Provider stream errors are untrusted input and may contain short test
    # keys or headers that do not match the logger's length-based patterns.
    safe = re.sub(
        r"(?i)\bAuthorization['\"]?\s*[:=]\s*['\"]?(?!(?:Bearer\s+)?(?:\(hidden\)|\[redacted\]))(?:Bearer\s+)?[^\s,;}\"']+",
        "Authorization: [redacted]",
        safe,
    )
    safe = re.sub(
        r"(?i)\bBearer\s+(?!(?:\(hidden\)|\[redacted\]))[^\s,;}\"']+",
        "Bearer [redacted]",
        safe,
    )
    safe = re.sub(
        r"(?i)\b(?:api[_-]?key|apikey)['\"]?\s*[:=]\s*['\"]?(?!(?:\*+|\(hidden\)|\[redacted\]))[^\s,;}\"']+",
        "api_key=[redacted]",
        safe,
    )
    safe = re.sub(r"(?i)\bsk-[A-Za-z0-9._~+/-]{8,}=*", "[redacted]", safe)
    if len(safe) > max_len:
        return f"{safe[:max_len]}…"
    return safe


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


def format_http_status_error(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    if status == 401:
        return tr("ai.error_auth_failed")
    if status == 429:
        return tr("ai.error_rate_limited")
    if status == 402:
        return tr("ai.error_insufficient_balance")
    if status == 504:
        return tr("ai.error_gateway_timeout")
    message, code = _http_error_message_and_code(exc)
    if _looks_like_model_not_found(status, code, message):
        return tr("ai.error_model_not_found")
    if message:
        max_len = (
            HTTP_ERROR_MESSAGE_SNIPPET_MAX
            if len(message) > HTTP_ERROR_MESSAGE_DISPLAY_MAX
            else None
        )
        display_message = sanitize_sensitive_text(message, max_len=max_len)
        if display_message:
            return tr("ai.error_http_with_message").format(
                status_code=status,
                message=display_message,
            )
    return tr("ai.error_http_hidden").format(status_code=status)


def format_openai_http_error(exc: httpx.HTTPStatusError) -> str:
    return format_http_status_error(exc)


def problem_code_for_http_error(exc: httpx.HTTPStatusError) -> str:
    from app.problems.classifier import problem_code_for_http_error as _classify_code

    return _classify_code(exc)


def classify_http_status_error(
    exc: httpx.HTTPStatusError,
    *,
    provider_id: str = "",
    model_id: str = "",
):
    from app.problems.classifier import classify_http_status_error as _classify

    return _classify(exc, provider_id=provider_id, model_id=model_id)


def classify_network_error(
    exc: Exception,
    *,
    provider_id: str = "",
    model_id: str = "",
):
    from app.problems.classifier import classify_network_error as _classify

    return _classify(exc, provider_id=provider_id, model_id=model_id)


def resolve_danmu_max_output_tokens(configured: int, *, use_thinking: bool = False) -> int:
    floor = DANMU_MIN_OUTPUT_TOKENS_THINKING if use_thinking else DANMU_MIN_OUTPUT_TOKENS
    if configured <= 0:
        return floor
    return max(configured, floor)


def parse_stream_usage(usage: dict | None, *, usage_token_style: str = "openai") -> tuple[int, int]:
    from app.providers.usage_normalizer import normalize_usage_by_style

    return normalize_usage_by_style(usage, usage_token_style=usage_token_style)


@dataclass(frozen=True)
class AiProbeResult:
    signal: str
    message: str
    input_tokens: int = 0
    output_tokens: int = 0


def _request_wall_clock_exceeded(*, deadline_at: float | None) -> bool:
    if deadline_at is None:
        return False
    return time.monotonic() > float(deadline_at)


@dataclass
class _StreamAttemptResult:
    text: str
    input_tokens: int
    output_tokens: int
    stream_error: str = ""
    finish_reason: str = ""
    stream_completed: bool = False
    terminated_by: str = ""


def _stream_eof_is_retriable(result: _StreamAttemptResult) -> bool:
    """Transport EOF without [DONE] may retry once; semantic length must not."""
    if result.terminated_by != "eof":
        return False
    if not result.stream_error:
        return False
    finish_reason = (result.finish_reason or "").strip().lower()
    if finish_reason in {"length", "content_filter", "max_tokens", "model_length", "incomplete"}:
        return False
    return "eof_without_done" in result.stream_error


def execute_stream_request_with_retry(
    worker,
    http_client,
    *,
    deadline_at: float | None,
    emit: bool,
    persona_id: str,
    request_round: int,
    screenshot_id: int,
    captured_at: float,
    scene_generation: int,
    attempt_stream: Callable[[httpx.Client], _StreamAttemptResult],
    empty_message: Callable[[_StreamAttemptResult], str],
) -> AiProbeResult | None:
    for attempt in range(2):
        if _request_wall_clock_exceeded(deadline_at=deadline_at):
            return worker._deliver_outcome(
                emit=emit,
                signal_name="error",
                message=tr("ai.error_timeout"),
                persona_id=persona_id,
                request_round=request_round,
                screenshot_id=screenshot_id,
                captured_at=captured_at,
                scene_generation=scene_generation,
            )
        try:
            result = attempt_stream(http_client)
            if result.stream_error and attempt < 1 and _stream_eof_is_retriable(result):
                try:
                    from app.ai_client_requests import reset_worker_http_client

                    http_client = reset_worker_http_client(worker)
                except RuntimeError:
                    pass
                else:
                    continue
            if result.stream_error:
                message = sanitize_provider_error_snippet(result.stream_error)
                return worker._deliver_outcome(
                    emit=emit,
                    signal_name="error",
                    message=message or tr("ai.error_empty_response"),
                    persona_id=persona_id,
                    request_round=request_round,
                    screenshot_id=screenshot_id,
                    captured_at=captured_at,
                    scene_generation=scene_generation,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )
            if result.text:
                return worker._deliver_outcome(
                    emit=emit,
                    signal_name="finished",
                    message=result.text.strip(),
                    persona_id=persona_id,
                    request_round=request_round,
                    screenshot_id=screenshot_id,
                    captured_at=captured_at,
                    scene_generation=scene_generation,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                )
            message = sanitize_provider_error_snippet(empty_message(result))
            return worker._deliver_outcome(
                emit=emit,
                signal_name="error",
                message=message or tr("ai.error_empty_response"),
                persona_id=persona_id,
                request_round=request_round,
                screenshot_id=screenshot_id,
                captured_at=captured_at,
                scene_generation=scene_generation,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
            )
        except httpx.TimeoutException:
            if attempt < 1:
                continue
            return worker._deliver_outcome(
                emit=emit,
                signal_name="error",
                message=tr("ai.error_timeout"),
                persona_id=persona_id,
                request_round=request_round,
                screenshot_id=screenshot_id,
                captured_at=captured_at,
                scene_generation=scene_generation,
            )
        except httpx.HTTPStatusError as exc:
            return worker._deliver_outcome(
                emit=emit,
                signal_name="error",
                message=format_http_status_error(exc),
                persona_id=persona_id,
                request_round=request_round,
                screenshot_id=screenshot_id,
                captured_at=captured_at,
                scene_generation=scene_generation,
            )
        except Exception as exc:  # boundary: retry once after client reset
            if attempt < 1:
                try:
                    from app.ai_client_requests import reset_worker_http_client

                    http_client = reset_worker_http_client(worker)
                except RuntimeError as reset_exc:
                    return worker._deliver_outcome(
                        emit=emit,
                        signal_name="error",
                        message=tr("ai.error_request_failed").format(error=reset_exc),
                        persona_id=persona_id,
                        request_round=request_round,
                        screenshot_id=screenshot_id,
                        captured_at=captured_at,
                        scene_generation=scene_generation,
                    )
                continue
            return worker._deliver_outcome(
                emit=emit,
                signal_name="error",
                message=tr("ai.error_request_failed").format(error=exc),
                persona_id=persona_id,
                request_round=request_round,
                screenshot_id=screenshot_id,
                captured_at=captured_at,
                scene_generation=scene_generation,
            )
    return worker._deliver_outcome(
        emit=emit,
        signal_name="error",
        message=tr("ai.error_empty_response"),
        persona_id=persona_id,
        request_round=request_round,
        screenshot_id=screenshot_id,
        captured_at=captured_at,
        scene_generation=scene_generation,
    )


class RequestContextResolutionError(ValueError):
    """请求档案无法唯一解析时抛出，不携带 endpoint/key 等敏感值。"""

    def __init__(self, code: str, message: str):
        super().__init__(code, message)
        self.code = code


def _custom_model_profiles(config) -> list[tuple[int, dict]]:
    getter = getattr(config, "get_custom_models", None)
    if not callable(getter):
        return []
    return [
        (index, entry)
        for index, entry in enumerate(getter())
        if isinstance(entry, dict)
    ]


def _profile_model_ids(profile: dict) -> list[str]:
    model_ids = profile.get("model_ids")
    if isinstance(model_ids, list):
        values = [str(value or "").strip() for value in model_ids]
        return [value for value in values if value]
    model_id = str(
        profile.get("default_model_id")
        or profile.get("modelId")
        or profile.get("model_id")
        or ""
    ).strip()
    return [model_id] if model_id else []


def _profile_model_id(profile: dict) -> str:
    model_ids = _profile_model_ids(profile)
    default = str(profile.get("default_model_id") or "").strip()
    return default or (model_ids[0] if model_ids else "")


def _profile_identity(profile: dict, index: int) -> str:
    from app.model_providers import custom_model_profile_identity

    identity = custom_model_profile_identity(profile)
    return identity or f"legacy:{index}"


def _resolve_visual_profile(config, persona_id: str = ""):
    """Resolve the one global profile; ``persona_id`` is compatibility-only."""
    profiles = _custom_model_profiles(config)
    if not profiles:
        return None
    from app.model_selection import resolve_active_model_profile

    profile = resolve_active_model_profile(config)
    if profile is None:
        return None
    for index, candidate in profiles:
        if candidate is profile or candidate == profile:
            return profile, _profile_model_id(profile), _profile_identity(profile, index)
    raise RequestContextResolutionError("profile_missing", "全局模型档案已失效")


def _profile_credentials(profile: dict, model_id: str):
    from app.model_providers import normalize_endpoint, normalize_mode

    endpoint = normalize_endpoint(profile.get("endpoint", ""))
    api_key = str(profile.get("apiKey") or "").strip()
    api_mode = normalize_mode(profile.get("mode") or profile.get("api_mode") or "")
    if not endpoint or not api_key or not model_id:
        return None
    return endpoint, api_key, model_id, api_mode


def get_model_config(config) -> dict:
    resolved = _resolve_visual_profile(config)
    return resolved[0] if resolved is not None else {}


def resolve_request_credentials(config) -> tuple[str, str, str, str] | None:
    """Resolve visual credentials from the explicit default profile."""
    resolved = _resolve_visual_profile(config)
    if resolved is None:
        return None
    return _profile_credentials(resolved[0], resolved[1])


def resolve_request_credentials_for_persona(
    config, persona_id: str = ""
) -> tuple[str, str, str, str] | None:
    """Compatibility wrapper; persona identity no longer changes model selection."""
    del persona_id
    return resolve_request_credentials(config)


def visual_credentials_ready(config) -> bool:
    return resolve_request_credentials(config) is not None


def _coerce_request_temperature(raw) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if 0.0 <= value <= 2.0 else None


def _profile_max_tokens(config, profile: dict | None) -> int:
    raw = profile.get("max_tokens") if profile is not None else None
    if raw is None:
        return DEFAULT_MAX_TOKENS
    try:
        return int(raw)
    except (TypeError, ValueError):
        return DEFAULT_MAX_TOKENS


def _profile_temperature(config, profile: dict | None) -> float:
    if profile is not None and "temperature" in profile:
        value = _coerce_request_temperature(profile.get("temperature"))
        if value is not None:
            return value
    return config.get_float("temperature", 0.8)


def _profile_thinking(config, profile: dict | None) -> str:
    raw = profile.get("thinking_effort") if profile is not None else None
    if raw is None and profile is not None:
        raw = profile.get("thinking")
    if isinstance(raw, bool):
        raw = "medium" if raw else "off"
    if raw is None:
        raw = "medium" if config.get("use_thinking", "0") == "1" else "off"
    value = str(raw or "off").strip().lower()
    allowed = {"off", "none", "minimal", "low", "medium", "high", "xhigh", "max"}
    return value if value in allowed else "off"


def _effective_thinking_effort(caps, model_id: str, configured: str) -> str | None:
    from app.model_catalog import catalog_model_supports_thinking_toggle

    if (
        caps.thinking_param_style == "none"
        or not catalog_model_supports_thinking_toggle(model_id)
    ):
        return None
    allowed = getattr(caps, "reasoning_effort_values", ())
    if configured in ("off", "none"):
        return "none" if "none" in allowed else None
    if allowed and configured not in allowed:
        return "medium" if "medium" in allowed else None
    return configured


def resolve_visual_request_context(
    config,
    persona_id: str = "",
    *,
    resolved: tuple[str, str, str, str] | None = None,
) -> ResolvedRequestContext | None:
    """在 provider dispatch 前一次性冻结视觉请求所需的解析结果。"""
    from app.model_providers import (
        guess_provider_from_endpoint,
        normalize_endpoint,
        normalize_mode,
        resolve_api_transport,
    )
    from app.providers.capabilities import capabilities_for_api_family
    from app.providers.capability_resolver import resolve_capabilities
    from app.providers.endpoint_resolver import extract_hostname, resolve_api_family

    selected = _resolve_visual_profile(config, persona_id)
    profile = selected[0] if selected is not None else None
    profile_id = selected[2] if selected is not None else "legacy:resolved"
    if resolved is None:
        if selected is None:
            return None
        resolved = _profile_credentials(profile, selected[1])
        if resolved is None:
            return None
    endpoint, api_key, model_id, api_mode = resolved
    endpoint = normalize_endpoint(endpoint)
    api_mode = normalize_mode(api_mode)
    if not endpoint or not api_key or not model_id:
        return None

    provider_id = ""
    profile_family = None
    if profile is not None:
        provider_id = str(
            profile.get("provider_id") or profile.get("provider") or ""
        ).strip()
        profile_family = str(profile.get("api_family") or "").strip() or None
    provider_id = provider_id or guess_provider_from_endpoint(endpoint, api_mode)
    api_family = resolve_api_family(
        transport=resolve_api_transport(endpoint, api_mode),
        api_family=profile_family,
    )
    if not api_family:
        raise RequestContextResolutionError(
            "api_family_unknown", "无法解析模型请求 API family"
        )
    caps = resolve_capabilities(
        model_id,
        endpoint,
        api_mode,
        provider_id=provider_id,
    )
    caps = capabilities_for_api_family(caps, api_family)
    configured_thinking = _profile_thinking(config, profile)
    reasoning_effort = _effective_thinking_effort(
        caps, model_id, configured_thinking
    )
    thinking_enabled = reasoning_effort not in (None, "none")
    configured_max_tokens = _profile_max_tokens(config, profile)
    max_output_tokens = resolve_danmu_max_output_tokens(
        configured_max_tokens,
        use_thinking=thinking_enabled,
    )
    supports_mic_declared = (
        profile.get("supportsMic") if profile is not None else None
    )
    if supports_mic_declared is None and profile is None:
        from app.model_providers import resolve_supports_mic_declared

        supports_mic_declared = resolve_supports_mic_declared(
            config,
            model_id,
            endpoint=endpoint,
            api_mode=api_mode,
        )
    return ResolvedRequestContext(
        profile_id=profile_id,
        model_id=model_id,
        provider_id=provider_id,
        api_family=api_family,
        endpoint=endpoint,
        endpoint_host=extract_hostname(endpoint) or "",
        api_mode=api_mode,
        max_tokens=configured_max_tokens,
        max_output_tokens=max_output_tokens,
        temperature=_profile_temperature(config, profile),
        thinking=(
            reasoning_effort if reasoning_effort not in (None, "none") else "off"
        ),
        thinking_enabled=thinking_enabled,
        reasoning_effort=reasoning_effort,
        supports_mic_declared=supports_mic_declared,
        credentials=RequestCredentials(api_key=api_key),
    )

def resolve_mic_request_credentials(config) -> tuple[str, str, str, str] | None:
    if config.get("mic_use_visual_model", "1") == "1":
        return resolve_request_credentials(config)
    from app.model_providers import normalize_endpoint, normalize_mode

    endpoint = normalize_endpoint(config.get("mic_api_endpoint", ""))
    api_key = (config.get_mic_api_key() or "").strip()
    model_id = (config.get("mic_model") or "").strip()
    api_mode = normalize_mode(config.get("mic_api_mode", "doubao"))
    if not endpoint or not api_key or not model_id:
        return None
    return endpoint, api_key, model_id, api_mode


def credential_gap_translation_keys(config) -> list[str]:
    from app.model_providers import is_valid_endpoint, normalize_endpoint

    model_config = get_model_config(config)
    if model_config:
        gaps: list[str] = []
        endpoint = normalize_endpoint(model_config.get("endpoint", ""))
        if not endpoint or not is_valid_endpoint(endpoint):
            gaps.append("custom_model.error_endpoint")
        if not (model_config.get("apiKey") or "").strip():
            gaps.append("custom_model.error_api_key")
        if not (model_config.get("default_model_id") or "").strip():
            gaps.append("custom_model.error_model_id")
        return gaps
    return [
        "custom_model.error_endpoint",
        "custom_model.error_api_key",
        "custom_model.error_model_id",
    ]


def mic_credential_gap_translation_keys(config) -> list[str]:
    from app.model_providers import is_valid_endpoint, normalize_endpoint

    if config.get("mic_use_visual_model", "1") == "1":
        return credential_gap_translation_keys(config)
    gaps: list[str] = []
    endpoint = normalize_endpoint(config.get("mic_api_endpoint", ""))
    if not endpoint or not is_valid_endpoint(endpoint):
        gaps.append("custom_model.error_endpoint")
    if not (config.get_mic_api_key() or "").strip():
        gaps.append("custom_model.error_api_key")
    if not (config.get("mic_model") or "").strip():
        gaps.append("custom_model.error_model_id")
    return gaps


def _format_gap_error(config, gap_keys_fn) -> str:
    gaps = gap_keys_fn(config)
    if not gaps:
        return tr("custom_model.error_incomplete")
    fields = "、".join(tr(key) for key in gaps)
    return tr("custom_model.error_incomplete_fields").format(fields=fields)


def format_credential_error(config) -> str:
    return _format_gap_error(config, credential_gap_translation_keys)


def format_mic_credential_error(config) -> str:
    return _format_gap_error(config, mic_credential_gap_translation_keys)
