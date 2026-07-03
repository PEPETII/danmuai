"""AI 请求构建与流式解析：豆包 Responses / OpenAI Chat Completions 双 API 路径。

所有请求固定注入 thinking: {"type":"disabled"}（THINKING_DISABLED 常量），降低延迟并避免
MiMo 等模型返回空内容。流式解析只收集 content，忽略 reasoning_content（思考内容不应作为弹幕）。

MiMo 特殊路径：mimo-v2.5 走 Chat Completions input_audio + input_audio.data（data URI）。
"""

from __future__ import annotations

import json
import logging
import time

import httpx

from app.ai_client_support import (
    DEFAULT_MAX_TOKENS,
    AiProbeResult,
    format_http_status_error,
    resolve_danmu_max_output_tokens,
)
from app.main_helpers import STREAM_FIRST_CONTENT_TIMEOUT_SEC
from app.model_providers import (
    get_capabilities_for_model,
    get_openai_adapter_for_model,
    is_valid_endpoint,
    model_supports_mic_audio,
    normalize_endpoint,
    normalize_mode,
)
from app.providers import (
    get_capabilities_for_endpoint,
    get_openai_adapter,
    is_minimax_endpoint,
    provider_extra_headers,
)
from app.providers.constants import THINKING_DISABLED, THINKING_ENABLED
from app.translations import tr

logger = logging.getLogger(__name__)


def _request_wall_clock_exceeded(worker) -> bool:
    deadline = getattr(worker, "_request_deadline_at", None)
    if deadline is None:
        return False
    return time.monotonic() > float(deadline)


def _raise_if_wall_clock_exceeded(worker) -> None:
    if _request_wall_clock_exceeded(worker):
        raise httpx.TimeoutException("request wall clock exceeded")


def get_model_config(config) -> dict:
    default_model_id = (config.get_default_model_id() or "").strip()
    if not default_model_id:
        return {}
    custom_models = config.get_custom_models()
    for model in custom_models:
        entry_id = (model.get("default_model_id") or model.get("modelId") or "").strip()
        if entry_id == default_model_id:
            return model
    return {}


def resolve_request_credentials(config) -> tuple[str, str, str, str] | None:
    """Resolve visual AI credentials from the active custom_models profile.

    W-GLOBAL-VISUAL-APIKEY-REMOVE-001: legacy global api_key/api_endpoint/api_mode
    fallback removed. Returns None when no complete custom_models profile matches
    default_model_id; callers surface a credential-gap error to the user.
    """
    model_config = get_model_config(config)
    if not model_config:
        return None
    endpoint = normalize_endpoint(model_config.get("endpoint", ""))
    api_key = (model_config.get("apiKey") or "").strip()
    model_id = (
        model_config.get("default_model_id") or model_config.get("modelId") or ""
    ).strip()
    api_mode = normalize_mode(model_config.get("mode", ""))
    if not endpoint or not api_key or not model_id:
        return None
    return endpoint, api_key, model_id, api_mode


def visual_credentials_ready(config) -> bool:
    """True when visual AI requests can resolve endpoint, key, and model."""
    return resolve_request_credentials(config) is not None


def _read_persona_model_bindings(config) -> dict:
    """轻量内联 helper：直接 JSON 解析 persona_model_bindings，避免导入 PersonaManager（防循环依赖）。"""
    raw = config.get("persona_model_bindings", "{}")
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def resolve_request_credentials_for_persona(
    config, persona_id: str = ""
) -> tuple[str, str, str, str] | None:
    """W-PERSONA-MODEL-BIND-001：按人格绑定模型解析凭证。

    persona_id 非空 → 读 persona_model_bindings[persona_id]：
      - 绑定存在且对应 custom_model 档案完整（is_model_config_complete）→ 返回该档案 (endpoint, apiKey, default_model_id, mode)
      - 否则（未绑定/档案被删/档案不完整）→ 委托 resolve_request_credentials(config) 回退全局"使用"模型
    persona_id 为空 → 直接回退 resolve_request_credentials(config)
    """
    if persona_id:
        from app.model_providers import is_model_config_complete
        bound_id = (_read_persona_model_bindings(config).get(persona_id) or "").strip()
        if bound_id:
            for entry in config.get_custom_models():
                entry_id = (entry.get("default_model_id") or entry.get("modelId") or "").strip()
                if entry_id == bound_id and is_model_config_complete(entry):
                    endpoint = normalize_endpoint(entry.get("endpoint", ""))
                    api_key = (entry.get("apiKey") or "").strip()
                    model_id = (entry.get("default_model_id") or entry.get("modelId") or "").strip()
                    api_mode = normalize_mode(entry.get("mode", ""))
                    if endpoint and api_key and model_id:
                        return endpoint, api_key, model_id, api_mode
    return resolve_request_credentials(config)


def resolve_mic_request_credentials(config) -> tuple[str, str, str, str] | None:
    """Credentials for mic insert / mic probe (independent when mic_use_visual_model=0)."""
    if config.get("mic_use_visual_model", "1") == "1":
        return resolve_request_credentials(config)
    endpoint = normalize_endpoint(config.get("mic_api_endpoint", ""))
    api_key = (config.get_mic_api_key() or "").strip()
    model_id = (config.get("mic_model") or "").strip()
    api_mode = normalize_mode(config.get("mic_api_mode", "doubao"))
    if not endpoint or not api_key or not model_id:
        return None
    return endpoint, api_key, model_id, api_mode


def credential_gap_translation_keys(config) -> list[str]:
    """Translation keys for missing visual/custom-model credential fields.

    W-GLOBAL-VISUAL-APIKEY-REMOVE-001: legacy global fallback removed. When no
    custom_models profile matches, all three fields are reported as missing.
    """
    model_config = get_model_config(config)
    if model_config:
        gaps: list[str] = []
        endpoint = normalize_endpoint(model_config.get("endpoint", ""))
        if not endpoint or not is_valid_endpoint(endpoint):
            gaps.append("custom_model.error_endpoint")
        if not (model_config.get("apiKey") or "").strip():
            gaps.append("custom_model.error_api_key")
        if not (model_config.get("modelId") or "").strip():
            gaps.append("custom_model.error_model_id")
        return gaps
    return [
        "custom_model.error_endpoint",
        "custom_model.error_api_key",
        "custom_model.error_model_id",
    ]


def mic_credential_gap_translation_keys(config) -> list[str]:
    """Translation keys for missing mic credential fields."""
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
) -> AiProbeResult | None:
    if resolved is None:
        resolved = worker._resolve_request_credentials()
    if resolved is None:
        return worker._deliver_outcome(
            emit=emit,
            signal_name="error",
            message=format_credential_error(worker.config),
            persona_id=persona_id,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
        )
    endpoint, api_key, model, api_mode = resolved
    temperature = worker.config.get_float("temperature", 0.8)
    configured_max = worker.config.get_int("max_tokens", DEFAULT_MAX_TOKENS)
    caps = get_capabilities_for_model(model, endpoint, api_mode)
    config_use_thinking = worker.config.get("use_thinking", "0") == "1"
    effective_use_thinking = caps.supports_thinking and config_use_thinking
    max_output_tokens = resolve_danmu_max_output_tokens(
        configured_max,
        use_thinking=effective_use_thinking,
    )

    if not api_key:
        return worker._deliver_outcome(
            emit=emit,
            signal_name="error",
            message=tr("ai.error_api_key_missing"),
            persona_id=persona_id,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
        )

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

    http_client = worker._get_http_client()
    for attempt in range(2):
        if _request_wall_clock_exceeded(worker):
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
            text, input_tokens, output_tokens, stream_error = worker._stream_doubao(
                http_client,
                url,
                headers,
                data,
                first_content_timeout=STREAM_FIRST_CONTENT_TIMEOUT_SEC,
            )
            if text:
                return worker._deliver_outcome(
                    emit=emit,
                    signal_name="finished",
                    message=text.strip(),
                    persona_id=persona_id,
                    request_round=request_round,
                    screenshot_id=screenshot_id,
                    captured_at=captured_at,
                    scene_generation=scene_generation,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                )
            msg = stream_error or tr("ai.error_empty_response")
            return worker._deliver_outcome(
                emit=emit,
                signal_name="error",
                message=msg,
                persona_id=persona_id,
                request_round=request_round,
                screenshot_id=screenshot_id,
                captured_at=captured_at,
                scene_generation=scene_generation,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
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


def stream_doubao(worker, http_client, url: str, headers: dict, data: dict, *, first_content_timeout: float | None = None) -> tuple[str, int, int, str]:
    from app.doubao_responses_stream import stream_doubao_responses

    deadline_at = getattr(worker, "_request_deadline_at", None)
    started_at = getattr(worker, "_request_started_at", None)
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
) -> AiProbeResult | None:
    if resolved is None:
        resolved = worker._resolve_request_credentials()
    if resolved is None:
        return worker._deliver_outcome(
            emit=emit,
            signal_name="error",
            message=format_credential_error(worker.config),
            persona_id=persona_id,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
        )
    endpoint, api_key, model, api_mode = resolved
    temperature = worker.config.get_float("temperature", 0.8)
    configured_max = worker.config.get_int("max_tokens", DEFAULT_MAX_TOKENS)
    caps = get_capabilities_for_model(model, endpoint, api_mode)
    config_use_thinking = worker.config.get("use_thinking", "0") == "1"
    effective_use_thinking = caps.thinking_param or (caps.supports_thinking and config_use_thinking)
    max_tokens = resolve_danmu_max_output_tokens(
        configured_max,
        use_thinking=effective_use_thinking,
    )

    if not api_key:
        return worker._deliver_outcome(
            emit=emit,
            signal_name="error",
            message=tr("ai.error_api_key_missing"),
            persona_id=persona_id,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
        )

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

    http_client = worker._get_http_client()
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
    # 思考模式扩展：supports_thinking 的 provider 响应 use_thinking 开关
    if caps.supports_thinking and config_use_thinking:
        data["thinking"] = dict(THINKING_ENABLED)
    if is_minimax_endpoint(endpoint):
        data["reasoning_split"] = True
    url = f"{endpoint}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    headers.update(provider_extra_headers(endpoint))

    for attempt in range(2):
        if _request_wall_clock_exceeded(worker):
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
            text, input_tokens, output_tokens = worker._stream_openai(
                http_client,
                url,
                headers,
                data,
                endpoint=endpoint,
                api_mode=api_mode,
                first_content_timeout=STREAM_FIRST_CONTENT_TIMEOUT_SEC,
            )
            if text:
                return worker._deliver_outcome(
                    emit=emit,
                    signal_name="finished",
                    message=text.strip(),
                    persona_id=persona_id,
                    request_round=request_round,
                    screenshot_id=screenshot_id,
                    captured_at=captured_at,
                    scene_generation=scene_generation,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
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
                input_tokens=input_tokens,
                output_tokens=output_tokens,
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
) -> tuple[str, int, int]:
    collected: list[str] = []
    reasoning_parts: list[str] = []
    input_tokens = 0
    output_tokens = 0
    got_first_content = False
    caps = get_capabilities_for_endpoint(endpoint, api_mode)
    adapter = get_openai_adapter(endpoint, api_mode)
    with http_client.stream("POST", url, headers=headers, json=data) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if worker._stopping.is_set():
                break
            _raise_if_wall_clock_exceeded(worker)
            # W-PERF-STREAM-001：首内容超时检查
            if first_content_timeout is not None and not got_first_content:
                started_at = getattr(worker, "_request_started_at", None)
                if started_at is not None and time.monotonic() - started_at > first_content_timeout:
                    logger.warning(
                        "openai stream first content timeout: %.1fs elapsed, no content delta received, endpoint=%s",
                        first_content_timeout,
                        normalize_endpoint(endpoint) if endpoint else url,
                    )
                    break
            if not line or not line.startswith("data: "):
                continue
            payload = line[6:]
            if payload.strip() == "[DONE]":
                break
            try:
                chunk = json.loads(payload)
                usage = chunk.get("usage")
                if usage:
                    input_tokens, output_tokens = adapter.normalize_usage(usage, caps=caps)
                choice = chunk.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                content = delta.get("content", "")
                if content:
                    got_first_content = True
                    collected.append(content)
                reasoning = delta.get("reasoning_content", "")  # 忽略：豆包/OpenAI 思考内容不应作为弹幕
                if reasoning:
                    reasoning_parts.append(reasoning)  # 仅用于诊断日志
                if not content and not reasoning:
                    message = choice.get("message", {})
                    message_content = message.get("content", "")
                    if message_content:
                        got_first_content = True
                        collected.append(message_content)
                    message_reasoning = message.get("reasoning_content", "")
                    if message_reasoning:
                        reasoning_parts.append(message_reasoning)
            except (json.JSONDecodeError, IndexError, KeyError) as exc:
                logger.debug("stream chunk parse skipped: %r payload=%.80s", exc, payload)
                continue
    text = "".join(collected)
    if not text and reasoning_parts:
        reasoning_len = sum(len(part) for part in reasoning_parts)
        logger.warning(
            "openai stream 只有 reasoning_content 没有 content "
            "(thinking:disabled 未生效，已通过增大 max_completion_tokens 缓解): "
            "input_tokens=%s output_tokens=%s reasoning_chars=%s endpoint=%s",
            input_tokens,
            output_tokens,
            reasoning_len,
            normalize_endpoint(endpoint) if endpoint else url,
        )
    if not text:
        logger.warning(
            "openai stream 返回空文本: input_tokens=%s output_tokens=%s endpoint=%s",
            input_tokens,
            output_tokens,
            normalize_endpoint(endpoint) if endpoint else url,
        )
    return text, input_tokens, output_tokens
