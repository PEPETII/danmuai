"""AI 请求构建与流式解析：豆包 Responses / OpenAI Chat Completions 双 API 路径。
默认关闭思考以降低延迟；用户开启 ``use_thinking`` 且模型目录声明 ``hybrid`` 时按各平台
官方参数注入（``thinking.type`` 或 ``enable_thinking``）。流式解析只收集 content，
忽略 reasoning_content（思考内容不应作为弹幕）。
MiMo 特殊路径：mimo-v2.5 走 Chat Completions input_audio + input_audio.data（data URI）。
"""
from __future__ import annotations

import logging

import httpx

from app.ai_client_support import (
    DEFAULT_MAX_TOKENS,
    AiProbeResult,
    _StreamAttemptResult,
    execute_stream_request_with_retry,
    format_credential_error,
    resolve_danmu_max_output_tokens,
)
from app.main_helpers import STREAM_FIRST_CONTENT_TIMEOUT_SEC
from app.model_catalog import catalog_model_supports_thinking_toggle
from app.model_providers import (
    get_capabilities_for_model,
    mic_audio_unsupported_message,
    model_supports_mic_audio,
    normalize_endpoint,
    resolve_supports_mic_declared,
)
from app.providers.request_planner import GenerationRequest, plan_http_request
from app.translations import tr

logger = logging.getLogger(__name__)


def _apply_mic_audio_policy(
    worker,
    model: str,
    endpoint: str,
    api_mode: str,
    audio_data_uri: str | None,
) -> tuple[str | None, bool | None, bool | None]:
    """Return (effective_audio_uri, supports_mic_override, supports_mic_declared)."""
    if not audio_data_uri:
        return None, None, None
    declared = resolve_supports_mic_declared(
        worker.config,
        model,
        endpoint=endpoint,
        api_mode=api_mode,
    )
    if model_supports_mic_audio(
        model,
        endpoint=endpoint,
        api_mode=api_mode,
        supports_mic_declared=declared,
    ):
        logger.info("request contains audio: model=%s purpose=mic_danmu", model)
        return audio_data_uri, True, declared
    logger.info(
        "mic audio stripped before request: model=%s endpoint=%s reason=%s",
        model,
        endpoint,
        mic_audio_unsupported_message(model),
    )
    return None, None, declared


def _effective_use_thinking(caps, model_id: str, config_use_thinking: bool) -> bool:
    return _effective_thinking_effort(
        caps,
        model_id,
        "medium" if config_use_thinking else "off",
    ) not in (None, "none")


def _configured_thinking_effort(config, model_id: str) -> str:
    """Read the model-profile selector, with legacy global fallback."""
    from app.model_providers import find_custom_model_profile

    profile = find_custom_model_profile(config.get_custom_models(), model_id)
    if profile is not None and "thinking_effort" in profile:
        value = str(profile.get("thinking_effort") or "off").strip().lower()
    else:
        # Old profiles have no per-model field. Preserve their previous global
        # behavior until the profile is edited and saved in the new UI.
        value = "medium" if config.get("use_thinking", "0") == "1" else "off"
    return value if value in {"off", "none", "minimal", "low", "medium", "high", "xhigh", "max"} else "off"


def _coerce_request_temperature(raw) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = str(raw).strip()
        if not text:
            return None
        try:
            value = float(text)
        except (TypeError, ValueError):
            return None
    if value < 0.0 or value > 2.0:
        return None
    return value


def _configured_temperature(config, model_id: str) -> float:
    """Read model-profile temperature, with legacy global fallback."""
    from app.model_providers import find_custom_model_profile

    profile = find_custom_model_profile(config.get_custom_models(), model_id)
    if profile is not None and "temperature" in profile:
        coerced = _coerce_request_temperature(profile.get("temperature"))
        if coerced is not None:
            return coerced
    return config.get_float("temperature", 0.8)


def _effective_thinking_effort(caps, model_id: str, configured: str) -> str | None:
    if (
        caps.thinking_param_style == "none"
        or not catalog_model_supports_thinking_toggle(model_id)
    ):
        return None
    allowed = getattr(caps, "reasoning_effort_values", ())
    if configured == "off":
        return "none" if "none" in allowed else None
    if allowed and configured not in allowed:
        return "medium" if "medium" in allowed else None
    return configured


def _resolve_request_timing(
    worker,
    *,
    deadline_at: float | None = None,
    started_at: float | None = None,
) -> tuple[float | None, float | None]:
    if deadline_at is None:
        deadline_at = getattr(worker, "_request_deadline_at", None)
    if started_at is None:
        started_at = getattr(worker, "_request_started_at", None)
    return deadline_at, started_at
def reset_worker_http_client(worker) -> httpx.Client:
    if hasattr(worker._thread_local, "client") and worker._thread_local.client is not None:
        try:
            worker._thread_local.client.close()
        except OSError:
            pass
        with worker._client_lock:
            worker._clients.discard(worker._thread_local.client)
        worker._thread_local.client = None
    try:
        client = worker._get_http_client()
    except (RuntimeError, OSError, httpx.HTTPError) as exc:
        logger.error("reset_worker_http_client: failed to create httpx client: %s", exc)
        raise RuntimeError("AI HTTP client reset failed") from exc
    if client is None:
        raise RuntimeError("AI HTTP client reset returned None")
    return client

def _deliver_request_error(
    worker,
    *,
    emit: bool,
    message: str,
    persona_id: str,
    request_round: int,
    screenshot_id: int,
    captured_at: float,
    scene_generation: int,
):
    return worker._deliver_outcome(
        emit=emit,
        signal_name="error",
        message=message,
        persona_id=persona_id,
        request_round=request_round,
        screenshot_id=screenshot_id,
        captured_at=captured_at,
        scene_generation=scene_generation,
    )


def _prepare_visual_request_context(
    worker,
    *,
    resolved: tuple[str, str, str, str] | None,
    emit: bool,
    persona_id: str,
    request_round: int,
    screenshot_id: int,
    captured_at: float,
    scene_generation: int,
    deadline_at: float | None,
    started_at: float | None,
):
    """Shared preflight for doubao/openai visual stream requests.

    Returns either an error AiProbeResult from _deliver_outcome, or a context
    tuple: (deadline_at, started_at, endpoint, api_key, model, api_mode, caps,
    effective_use_thinking, thinking_effort, max_tokens, temperature, http_client).
    """
    deadline_at, started_at = _resolve_request_timing(
        worker, deadline_at=deadline_at, started_at=started_at
    )
    if resolved is None:
        resolved = worker._resolve_request_credentials()
    if resolved is None:
        return _deliver_request_error(
            worker,
            emit=emit,
            message=format_credential_error(worker.config),
            persona_id=persona_id,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
        ), None
    endpoint, api_key, model, api_mode = resolved
    temperature = _configured_temperature(worker.config, model)
    configured_max = worker.config.get_int("max_tokens", DEFAULT_MAX_TOKENS)
    caps = get_capabilities_for_model(model, endpoint, api_mode)
    configured_thinking_effort = _configured_thinking_effort(worker.config, model)
    thinking_effort = _effective_thinking_effort(
        caps,
        model,
        configured_thinking_effort,
    )
    effective_use_thinking = thinking_effort not in (None, "none")
    max_tokens = resolve_danmu_max_output_tokens(
        configured_max,
        use_thinking=effective_use_thinking,
    )
    if not api_key:
        return _deliver_request_error(
            worker,
            emit=emit,
            message=tr("ai.error_api_key_missing"),
            persona_id=persona_id,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
        ), None
    http_client = worker._get_http_client()
    ctx = (
        deadline_at,
        started_at,
        endpoint,
        api_key,
        model,
        api_mode,
        caps,
        effective_use_thinking,
        thinking_effort,
        max_tokens,
        temperature,
        http_client,
    )
    return None, ctx


def _run_visual_stream_request(
    worker,
    *,
    http_client,
    deadline_at: float | None,
    emit: bool,
    persona_id: str,
    request_round: int,
    screenshot_id: int,
    captured_at: float,
    scene_generation: int,
    attempt_stream,
    empty_message,
):
    return execute_stream_request_with_retry(
        worker,
        http_client,
        deadline_at=deadline_at,
        emit=emit,
        persona_id=persona_id,
        request_round=request_round,
        screenshot_id=screenshot_id,
        captured_at=captured_at,
        scene_generation=scene_generation,
        attempt_stream=attempt_stream,
        empty_message=empty_message,
    )

def request_doubao(
    worker,
    image_data_uri: str,
    system_pt: str,
    user_pt: str,
    persona_id: str,
    request_round: int,
    screenshot_id: int,
    captured_at: float,
    scene_generation: int,
    *,
    audio_data_uri: str | None = None,
    resolved: tuple[str, str, str, str] | None = None,
    emit: bool = True,
    deadline_at: float | None = None,
    started_at: float | None = None,
) -> AiProbeResult | None:
    err, ctx = _prepare_visual_request_context(
        worker,
        resolved=resolved,
        emit=emit,
        persona_id=persona_id,
        request_round=request_round,
        screenshot_id=screenshot_id,
        captured_at=captured_at,
        scene_generation=scene_generation,
        deadline_at=deadline_at,
        started_at=started_at,
    )
    if ctx is None:
        return err
    (
        deadline_at,
        started_at,
        endpoint,
        api_key,
        model,
        api_mode,
        caps,
        effective_use_thinking,
        thinking_effort,
        max_output_tokens,
        temperature,
        http_client,
    ) = ctx
    if not image_data_uri or not image_data_uri.startswith("data:"):
        return _deliver_request_error(
            worker,
            emit=emit,
            message=tr("ai.error_request_failed").format(error="empty or invalid image"),
            persona_id=persona_id,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
        )
    mic_audio, mic_override, mic_declared = _apply_mic_audio_policy(
        worker,
        model,
        endpoint,
        api_mode,
        audio_data_uri,
    )
    purpose = "mic_danmu" if mic_audio else "visual_danmu"
    planned = plan_http_request(
        GenerationRequest(
            purpose=purpose,
            model_id=model,
            endpoint=endpoint,
            api_key=api_key,
            api_mode=api_mode,
            system_text=system_pt or None,
            user_text=user_pt,
            image_data_uri=image_data_uri,
            audio_data_uri=mic_audio,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            reasoning_enabled=effective_use_thinking,
            reasoning_effort=thinking_effort,
            stream=True,
            supports_mic_override=mic_override,
            supports_mic_declared=mic_declared,
        )
    )
    url = planned.url
    headers = planned.headers
    data = planned.json_body

    def _attempt_stream(client: httpx.Client) -> _StreamAttemptResult:
        text, input_tokens, output_tokens, stream_error = stream_doubao(
            worker,
            client,
            url,
            headers,
            data,
            first_content_timeout=STREAM_FIRST_CONTENT_TIMEOUT_SEC,
            deadline_at=deadline_at,
            started_at=started_at,
        )
        return _StreamAttemptResult(text, input_tokens, output_tokens, stream_error)

    return _run_visual_stream_request(
        worker,
        http_client=http_client,
        deadline_at=deadline_at,
        emit=emit,
        persona_id=persona_id,
        request_round=request_round,
        screenshot_id=screenshot_id,
        captured_at=captured_at,
        scene_generation=scene_generation,
        attempt_stream=_attempt_stream,
        empty_message=lambda result: result.stream_error or tr("ai.error_empty_response"),
    )

def stream_doubao(
    worker,
    http_client,
    url: str,
    headers: dict,
    data: dict,
    *,
    first_content_timeout: float | None = None,
    deadline_at: float | None = None,
    started_at: float | None = None,
) -> tuple[str, int, int, str]:
    from app.doubao_responses_stream import stream_doubao_responses
    deadline_at, started_at = _resolve_request_timing(
        worker, deadline_at=deadline_at, started_at=started_at
    )
    result = stream_doubao_responses(
        http_client,
        url,
        headers,
        data,
        deadline_at=deadline_at,
        first_content_timeout=first_content_timeout,
        started_at=started_at,
        stopping=worker._stopping.is_set,
    )
    if not result.text:
        logger.warning(
            "doubao stream 返回空文本: input_tokens=%s output_tokens=%s "
            "reasoning_only=%s stream_events=%s error=%r",
            result.input_tokens,
            result.output_tokens,
            result.reasoning_only,
            result.stream_events,
            result.error,
        )
    return result.text, result.input_tokens, result.output_tokens, result.error

def request_openai(
    worker,
    image_data_uri: str,
    system_pt: str,
    user_pt: str,
    persona_id: str,
    request_round: int,
    screenshot_id: int,
    captured_at: float,
    scene_generation: int,
    *,
    audio_data_uri: str | None = None,
    resolved: tuple[str, str, str, str] | None = None,
    emit: bool = True,
    deadline_at: float | None = None,
    started_at: float | None = None,
) -> AiProbeResult | None:
    err, ctx = _prepare_visual_request_context(
        worker,
        resolved=resolved,
        emit=emit,
        persona_id=persona_id,
        request_round=request_round,
        screenshot_id=screenshot_id,
        captured_at=captured_at,
        scene_generation=scene_generation,
        deadline_at=deadline_at,
        started_at=started_at,
    )
    if ctx is None:
        return err
    (
        deadline_at,
        started_at,
        endpoint,
        api_key,
        model,
        api_mode,
        caps,
        effective_use_thinking,
        thinking_effort,
        max_tokens,
        temperature,
        http_client,
    ) = ctx
    mic_audio, mic_override, mic_declared = _apply_mic_audio_policy(
        worker,
        model,
        endpoint,
        api_mode,
        audio_data_uri,
    )
    purpose = "mic_danmu" if mic_audio else "visual_danmu"
    planned = plan_http_request(
        GenerationRequest(
            purpose=purpose,
            model_id=model,
            endpoint=endpoint,
            api_key=api_key,
            api_mode=api_mode,
            system_text=system_pt or None,
            user_text=user_pt,
            image_data_uri=image_data_uri,
            audio_data_uri=mic_audio,
            max_output_tokens=max_tokens,
            temperature=temperature,
            reasoning_enabled=effective_use_thinking,
            reasoning_effort=thinking_effort,
            stream=True,
            supports_mic_override=mic_override,
            supports_mic_declared=mic_declared,
        )
    )
    url = planned.url
    headers = planned.headers
    data = planned.json_body

    def _attempt_stream(client: httpx.Client) -> _StreamAttemptResult:
        stream_result = stream_openai(
            worker,
            client,
            url,
            headers,
            data,
            endpoint=endpoint,
            api_mode=api_mode,
            first_content_timeout=STREAM_FIRST_CONTENT_TIMEOUT_SEC,
            deadline_at=deadline_at,
            started_at=started_at,
            include_error=True,
            return_result=True,
        )
        if isinstance(stream_result, tuple):
            text, input_tokens, output_tokens = stream_result[:3]
            stream_error = stream_result[3] if len(stream_result) > 3 else ""
            return _StreamAttemptResult(text, input_tokens, output_tokens, stream_error)
        return _StreamAttemptResult(
            stream_result.text,
            stream_result.input_tokens,
            stream_result.output_tokens,
            stream_result.error,
            finish_reason=stream_result.finish_reason,
            stream_completed=stream_result.stream_completed,
            terminated_by=stream_result.terminated_by,
        )

    return _run_visual_stream_request(
        worker,
        http_client=http_client,
        deadline_at=deadline_at,
        emit=emit,
        persona_id=persona_id,
        request_round=request_round,
        screenshot_id=screenshot_id,
        captured_at=captured_at,
        scene_generation=scene_generation,
        attempt_stream=_attempt_stream,
        empty_message=lambda result: result.stream_error or tr("ai.error_empty_response"),
    )

def stream_openai(
    worker,
    http_client,
    url: str,
    headers: dict,
    data: dict,
    *,
    endpoint: str = "",
    api_mode: str = "",
    first_content_timeout: float | None = None,
    deadline_at: float | None = None,
    started_at: float | None = None,
    include_error: bool = False,
    return_result: bool = False,
):
    from app.openai_chat_stream import stream_openai_chat
    deadline_at, started_at = _resolve_request_timing(
        worker, deadline_at=deadline_at, started_at=started_at
    )
    result = stream_openai_chat(
        http_client,
        url,
        headers,
        data,
        endpoint=endpoint,
        api_mode=api_mode,
        deadline_at=deadline_at,
        first_content_timeout=first_content_timeout,
        started_at=started_at,
        stopping=worker._stopping.is_set,
    )
    if not result.text:
        logger.warning(
            "openai stream 返回空文本: input_tokens=%s output_tokens=%s endpoint=%s",
            result.input_tokens,
            result.output_tokens,
            normalize_endpoint(endpoint) if endpoint else url,
        )
    if return_result:
        return result
    values = (result.text, result.input_tokens, result.output_tokens)
    if include_error:
        return (*values, result.error)
    return values


# Re-export credential helpers for historical import paths (``app.ai_client`` façade).
from app.ai_client_support import (  # noqa: E402
    format_mic_credential_error,
    get_model_config,
    resolve_mic_request_credentials,
    resolve_request_credentials,
    resolve_request_credentials_for_persona,
    visual_credentials_ready,
)

__all__ = [
    "format_credential_error",
    "format_mic_credential_error",
    "get_model_config",
    "request_doubao",
    "request_openai",
    "reset_worker_http_client",
    "resolve_mic_request_credentials",
    "resolve_request_credentials",
    "resolve_request_credentials_for_persona",
    "stream_doubao",
    "stream_openai",
    "visual_credentials_ready",
]
