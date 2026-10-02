"""AI 请求构建与流式解析：豆包 Responses / OpenAI Chat Completions 双 API 路径。
默认关闭思考以降低延迟；用户开启 ``use_thinking`` 且模型目录声明 ``hybrid`` 时按各平台
官方参数注入（``thinking.type`` 或 ``enable_thinking``）。流式解析只收集 content，
忽略 reasoning_content（思考内容不应作为弹幕）。
MiMo 特殊路径：mimo-v2.5 走 Chat Completions input_audio + input_audio.data（data URI）。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Any

import httpx

from app.ai_client_support import (
    DEFAULT_MAX_TOKENS,
    AiProbeResult,
    _StreamAttemptResult,
    execute_stream_request_with_retry,
    format_credential_error,
    resolve_danmu_max_output_tokens,
    resolve_visual_request_context,
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
from app.providers.request_context import ResolvedRequestContext
from app.providers.request_planner import (
    GenerationRequest,
    PlannedHttpRequest,
    plan_http_request,
)
from app.translations import tr

logger = logging.getLogger(__name__)


def _apply_mic_audio_policy(
    worker,
    model: str,
    endpoint: str,
    api_mode: str,
    audio_data_uri: str | None,
    *,
    request_context: ResolvedRequestContext | None = None,
) -> tuple[str | None, bool | None, bool | None]:
    """Return (effective_audio_uri, supports_mic_override, supports_mic_declared)."""
    if not audio_data_uri:
        return None, None, None
    if request_context is not None:
        declared = request_context.supports_mic_declared
    else:
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


@dataclass(frozen=True)
class VisualRequestTuning:
    """正式视觉请求的 per-request tuning（档案参数 → provider 决策）。

    W-AUDIT-PROBE-PARITY-001：把「caps 归一 + thinking 决策 + token 下限」抽成
    单一纯函数，正式视觉链（``request_doubao`` / ``request_openai``）与连接探测
    的 ``vision_stream`` 阶段都调用它，避免 probe 复制一套会漂移的参数决策。
    """

    caps: Any
    temperature: float | None
    thinking_effort: str | None
    effective_use_thinking: bool
    max_output_tokens: int


def resolve_visual_tuning_from_params(
    *,
    model_id: str,
    endpoint: str,
    api_mode: str,
    temperature: float | None,
    thinking_effort: str,
    max_tokens: int,
) -> VisualRequestTuning:
    """从显式档案参数快照解析正式视觉请求的 tuning。

    参数由调用方给出（正式链读取 ``config`` 档案；probe 使用按 ``profile_id``
    定位的不可变档案快照），本函数只做无副作用的 provider 能力归一。
    """
    caps = get_capabilities_for_model(model_id, endpoint, api_mode)
    effort = _effective_thinking_effort(caps, model_id, thinking_effort)
    use_thinking = effort not in (None, "none")
    return VisualRequestTuning(
        caps=caps,
        temperature=temperature,
        thinking_effort=effort,
        effective_use_thinking=use_thinking,
        max_output_tokens=resolve_danmu_max_output_tokens(
            max_tokens, use_thinking=use_thinking
        ),
    )


def resolve_visual_request_tuning(
    config,
    model: str,
    endpoint: str,
    api_mode: str,
) -> VisualRequestTuning:
    """正式视觉链的 tuning 入口：从 config 读取档案参数后走同一决策函数。"""
    return resolve_visual_tuning_from_params(
        model_id=model,
        endpoint=endpoint,
        api_mode=api_mode,
        temperature=_configured_temperature(config, model),
        thinking_effort=_configured_thinking_effort(config, model),
        max_tokens=DEFAULT_MAX_TOKENS,
    )


def build_visual_planned_request(
    *,
    model: str,
    endpoint: str,
    api_key: str,
    api_mode: str,
    system_text: str,
    user_text: str,
    image_data_uri: str,
    max_output_tokens: int,
    temperature: float | None,
    reasoning_enabled: bool,
    reasoning_effort: str | None,
    audio_data_uri: str | None = None,
    supports_mic_override: bool | None = None,
    supports_mic_declared: bool | str | None = None,
    request_context: ResolvedRequestContext | None = None,
) -> PlannedHttpRequest:
    """构造正式视觉（可选麦克风）请求的 ``PlannedHttpRequest``。

    正式链与 probe 的 ``vision_stream`` 阶段共用这一个入口，保证图片消息格式、
    system/user 文本、thinking/streaming 决策与 request planner 路径完全一致。
    """
    return plan_http_request(
        GenerationRequest(
            purpose="mic_danmu" if audio_data_uri else "visual_danmu",
            model_id=model,
            endpoint=endpoint,
            api_key=api_key,
            api_mode=api_mode,
            system_text=system_text or None,
            user_text=user_text,
            image_data_uri=image_data_uri,
            audio_data_uri=audio_data_uri,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            reasoning_enabled=reasoning_enabled,
            reasoning_effort=reasoning_effort,
            stream=True,
            supports_mic_override=supports_mic_override,
            supports_mic_declared=supports_mic_declared,
            request_context=request_context,
        )
    )


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
    request_context: ResolvedRequestContext | None,
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
    tuple: (deadline_at, started_at, request_context, http_client).
    """
    deadline_at, started_at = _resolve_request_timing(
        worker, deadline_at=deadline_at, started_at=started_at
    )
    context_was_supplied = request_context is not None
    if request_context is None and resolved is None:
        resolved = worker._resolve_request_credentials(persona_id)
    if request_context is None:
        request_context = resolve_visual_request_context(
            worker.config,
            persona_id,
            resolved=resolved,
        )
    if request_context is None:
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
    if not context_was_supplied:
        # Preserve the historical direct-call seam where tests/integrations
        # override capability resolution before the context is dispatched.
        caps = get_capabilities_for_model(
            request_context.model_id,
            request_context.endpoint,
            request_context.api_mode,
        )
        if (
            caps.thinking_param_style == "none"
            or not getattr(caps, "supports_thinking", True)
        ):
            request_context = replace(
                request_context,
                thinking="off",
                thinking_enabled=False,
                reasoning_effort=None,
                max_output_tokens=resolve_danmu_max_output_tokens(
                    request_context.max_tokens,
                    use_thinking=False,
                ),
            )
    if not request_context.api_key:
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
    ctx = (deadline_at, started_at, request_context, http_client)
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
    request_context: ResolvedRequestContext | None = None,
    emit: bool = True,
    deadline_at: float | None = None,
    started_at: float | None = None,
) -> AiProbeResult | None:
    err, ctx = _prepare_visual_request_context(
        worker,
        resolved=resolved,
        request_context=request_context,
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
    deadline_at, started_at, request_context, http_client = ctx
    endpoint = request_context.endpoint
    api_mode = request_context.api_mode
    model = request_context.model_id
    api_key = request_context.api_key
    effective_use_thinking = request_context.thinking_enabled
    thinking_effort = request_context.reasoning_effort
    max_output_tokens = request_context.max_output_tokens
    temperature = request_context.temperature
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
        request_context=request_context,
    )
    planned = build_visual_planned_request(
        model=model,
        endpoint=endpoint,
        api_key=api_key,
        api_mode=api_mode,
        system_text=system_pt,
        user_text=user_pt,
        image_data_uri=image_data_uri,
        audio_data_uri=mic_audio,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        reasoning_enabled=effective_use_thinking,
        reasoning_effort=thinking_effort,
        supports_mic_override=mic_override,
        supports_mic_declared=mic_declared,
        request_context=request_context,
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
    request_context: ResolvedRequestContext | None = None,
    emit: bool = True,
    deadline_at: float | None = None,
    started_at: float | None = None,
) -> AiProbeResult | None:
    err, ctx = _prepare_visual_request_context(
        worker,
        resolved=resolved,
        request_context=request_context,
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
    deadline_at, started_at, request_context, http_client = ctx
    endpoint = request_context.endpoint
    api_mode = request_context.api_mode
    model = request_context.model_id
    api_key = request_context.api_key
    effective_use_thinking = request_context.thinking_enabled
    thinking_effort = request_context.reasoning_effort
    max_tokens = request_context.max_output_tokens
    temperature = request_context.temperature
    mic_audio, mic_override, mic_declared = _apply_mic_audio_policy(
        worker,
        model,
        endpoint,
        api_mode,
        audio_data_uri,
        request_context=request_context,
    )
    planned = build_visual_planned_request(
        model=model,
        endpoint=endpoint,
        api_key=api_key,
        api_mode=api_mode,
        system_text=system_pt,
        user_text=user_pt,
        image_data_uri=image_data_uri,
        audio_data_uri=mic_audio,
        max_output_tokens=max_tokens,
        temperature=temperature,
        reasoning_enabled=effective_use_thinking,
        reasoning_effort=thinking_effort,
        supports_mic_override=mic_override,
        supports_mic_declared=mic_declared,
        request_context=request_context,
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
