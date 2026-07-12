"""AI 客户端辅助函数：纯逻辑、无 Qt 依赖，可安全用于单元测试。

职责：请求扩展构建、HTTP 错误格式化、Provider 特殊处理（MiMo 等）、输出 token 下限计算。
"""

from __future__ import annotations

import json
import logging
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
    return sanitize_sensitive_text(text, max_len=max_len)


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


def resolve_danmu_max_output_tokens(configured: int, *, use_thinking: bool = False) -> int:
    floor = DANMU_MIN_OUTPUT_TOKENS_THINKING if use_thinking else DANMU_MIN_OUTPUT_TOKENS
    if configured <= 0:
        return floor
    return max(configured, floor)


def parse_stream_usage(usage: dict | None, *, usage_token_style: str = "openai") -> tuple[int, int]:
    from app.providers.adapters.default_openai import DefaultOpenAIAdapter
    from app.providers.capabilities import ProviderCapabilities

    caps = ProviderCapabilities(usage_token_style=usage_token_style)
    return DefaultOpenAIAdapter().normalize_usage(usage, caps=caps)


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
            return worker._deliver_outcome(
                emit=emit,
                signal_name="error",
                message=empty_message(result),
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


def get_model_config(config) -> dict:
    from app.model_providers import find_custom_model_profile

    default_model_id = (config.get_default_model_id() or "").strip()
    if not default_model_id:
        return {}
    profile = find_custom_model_profile(config.get_custom_models(), default_model_id)
    return profile or {}


def resolve_request_credentials(config) -> tuple[str, str, str, str] | None:
    """Resolve visual AI credentials from the active custom_models profile."""
    model_config = get_model_config(config)
    if not model_config:
        return None
    from app.model_providers import normalize_endpoint, normalize_mode

    endpoint = normalize_endpoint(model_config.get("endpoint", ""))
    api_key = (model_config.get("apiKey") or "").strip()
    model_id = (model_config.get("default_model_id") or "").strip()
    api_mode = normalize_mode(model_config.get("mode", ""))
    if not endpoint or not api_key or not model_id:
        return None
    return endpoint, api_key, model_id, api_mode


def visual_credentials_ready(config) -> bool:
    return resolve_request_credentials(config) is not None


def _read_persona_model_bindings(config) -> dict:
    raw = config.get("persona_model_bindings", "{}")
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def resolve_request_credentials_for_persona(
    config, persona_id: str = ""
) -> tuple[str, str, str, str] | None:
    if persona_id:
        from app.model_providers import (
            is_model_config_complete,
            normalize_endpoint,
            normalize_mode,
        )

        bound_id = (_read_persona_model_bindings(config).get(persona_id) or "").strip()
        if bound_id:
            from app.model_providers import find_custom_model_profile

            entry = find_custom_model_profile(config.get_custom_models(), bound_id)
            if entry is not None and is_model_config_complete(entry):
                endpoint = normalize_endpoint(entry.get("endpoint", ""))
                api_key = (entry.get("apiKey") or "").strip()
                model_id = (entry.get("default_model_id") or "").strip()
                api_mode = normalize_mode(entry.get("mode", ""))
                if endpoint and api_key and model_id:
                    return endpoint, api_key, model_id, api_mode
    return resolve_request_credentials(config)


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
