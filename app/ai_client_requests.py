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
    format_mic_credential_error,
    get_model_config,
    resolve_danmu_max_output_tokens,
    resolve_mic_request_credentials,
    resolve_request_credentials,
    resolve_request_credentials_for_persona,
    visual_credentials_ready,
)
from app.main_helpers import STREAM_FIRST_CONTENT_TIMEOUT_SEC
from app.model_providers import (
    get_capabilities_for_model,
    get_openai_adapter_for_model,
    model_supports_mic_audio,
    normalize_endpoint,
)
from app.providers import (
    is_minimax_endpoint,
    provider_extra_headers,
)
from app.model_catalog import catalog_model_supports_thinking_toggle
from app.providers.constants import THINKING_DISABLED, THINKING_ENABLED
from app.providers.thinking import apply_thinking_mode
from app.translations import tr
logger = logging.getLogger(__name__)
def _effective_use_thinking(caps, model_id: str, config_use_thinking: bool) -> bool:
    return (
        config_use_thinking
        and caps.thinking_param_style != "none"
        and catalog_model_supports_thinking_toggle(model_id)
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
    effective_use_thinking, max_tokens, temperature, http_client).
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
    temperature = worker.config.get_float("temperature", 0.8)
    configured_max = worker.config.get_int("max_tokens", DEFAULT_MAX_TOKENS)
    caps = get_capabilities_for_model(model, endpoint, api_mode)
    config_use_thinking = worker.config.get("use_thinking", "0") == "1"
    effective_use_thinking = _effective_use_thinking(caps, model, config_use_thinking)
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
        max_output_tokens,
        temperature,
        http_client,
    ) = ctx
    user_content: list[dict] = [
        {"type": "input_image", "image_url": image_data_uri},
        {"type": "input_text", "text": user_pt},
    ]
    if audio_data_uri:
        user_content.append({"type": "input_audio", "audio_url": audio_data_uri})
    input_messages = [
        {
            "type": "message",
            "role": "user",
            "content": user_content,
        }
    ]
    data = {
        "model": model,
        "input": input_messages,
        "stream": True,
    }
    if system_pt:
        data["instructions"] = system_pt
    if temperature is not None and temperature >= 0:
        data["temperature"] = temperature
    data["thinking"] = (
        dict(THINKING_ENABLED) if effective_use_thinking else dict(THINKING_DISABLED)
    )
    data["max_output_tokens"] = max_output_tokens
    url = f"{endpoint}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

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
        max_tokens,
        temperature,
        http_client,
    ) = ctx
    mic_audio = audio_data_uri
    if mic_audio and not model_supports_mic_audio(model, endpoint=endpoint, api_mode=api_mode):
        from app.model_providers import mic_audio_unsupported_message

        logger.info(
            "mic audio stripped before openai request: model=%s endpoint=%s reason=%s",
            model,
            endpoint,
            mic_audio_unsupported_message(model),
        )
        mic_audio = None
    adapter = get_openai_adapter_for_model(model, endpoint, api_mode)
    data: dict[str, object] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_pt},
            {
                "role": "user",
                "content": adapter.build_vision_user_content(
                    user_pt,
                    image_data_uri,
                    audio_data_uri=mic_audio,
                ),
            },
        ],
        "temperature": temperature,
        "stream": True,
    }
    adapter.patch_openai_chat_body(data, max_tokens=max_tokens, caps=caps)
    if catalog_model_supports_thinking_toggle(model) and caps.thinking_param_style != "none":
        apply_thinking_mode(data, enabled=effective_use_thinking, caps=caps)
    elif caps.thinking_param and caps.thinking_param_style != "none":
        apply_thinking_mode(data, enabled=False, caps=caps)
    if is_minimax_endpoint(endpoint):
        data["reasoning_split"] = True
    url = f"{endpoint}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    headers.update(provider_extra_headers(endpoint))

    def _attempt_stream(client: httpx.Client) -> _StreamAttemptResult:
        text, input_tokens, output_tokens = stream_openai(
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
        )
        return _StreamAttemptResult(text, input_tokens, output_tokens)

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
        empty_message=lambda _result: tr("ai.error_empty_response"),
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
) -> tuple[str, int, int]:
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
    return result.text, result.input_tokens, result.output_tokens
