"""AI 请求构建与流式解析：豆包 Responses / OpenAI Chat Completions 双 API 路径。

所有请求固定注入 thinking: {"type":"disabled"}（THINKING_DISABLED 常量），降低延迟并避免
MiMo 等模型返回空内容。流式解析只收集 content，忽略 reasoning_content（思考内容不应作为弹幕）。

MiMo 特殊路径：mimo-v2.5 走 Chat Completions input_audio + input_audio.data（data URI）。
"""

from __future__ import annotations

import json
import logging

import httpx

from app.ai_client_support import (
    DEFAULT_MAX_TOKENS,
    AiProbeResult,
    format_http_status_error,
    resolve_danmu_max_output_tokens,
)
from app.model_providers import (
    get_capabilities_for_model,
    get_openai_adapter_for_model,
    model_supports_mic_audio,
    normalize_endpoint,
    normalize_mode,
)
from app.providers import get_capabilities_for_endpoint, get_openai_adapter
from app.providers.constants import THINKING_DISABLED
from app.translations import tr

logger = logging.getLogger(__name__)


def get_model_config(config) -> dict:
    default_model_id = config.get_default_model_id()
    if not default_model_id:
        return {}
    custom_models = config.get_custom_models()
    for model in custom_models:
        if model.get("modelId") == default_model_id:
            return model
    return {}


def resolve_request_credentials(config) -> tuple[str, str, str, str] | None:
    model_config = get_model_config(config)
    if model_config:
        endpoint = normalize_endpoint(model_config.get("endpoint", ""))
        api_key = (model_config.get("apiKey") or "").strip()
        model_id = (model_config.get("modelId") or "").strip()
        api_mode = normalize_mode(model_config.get("mode", ""))
        if not endpoint or not api_key or not model_id:
            return None
        return endpoint, api_key, model_id, api_mode

    endpoint = normalize_endpoint(
        config.get("api_endpoint", "https://ark.cn-beijing.volces.com/api/v3")
    )
    api_key = (config.get_api_key() or "").strip()
    model_id = (
        config.get_default_model_id()
        or config.get("model", "doubao-seed-1-6-flash-250828")
    )
    api_mode = normalize_mode(config.get("api_mode", "doubao"))
    return endpoint, api_key, model_id, api_mode


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


def reset_worker_http_client(worker) -> httpx.Client:
    if hasattr(worker._thread_local, "client") and worker._thread_local.client is not None:
        try:
            worker._thread_local.client.close()
        except Exception:
            pass
        with worker._client_lock:
            worker._clients.discard(worker._thread_local.client)
        worker._thread_local.client = None
    return worker._get_http_client()


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
            message=tr("custom_model.error_incomplete"),
            persona_id=persona_id,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
        )
    endpoint, api_key, model, _ = resolved
    temperature = worker.config.get_float("temperature", 0.7)
    configured_max = worker.config.get_int("max_tokens", DEFAULT_MAX_TOKENS)
    max_output_tokens = resolve_danmu_max_output_tokens(configured_max, use_thinking=False)

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
    if temperature:
        data["temperature"] = temperature
    data["thinking"] = dict(THINKING_DISABLED)  # 固定关闭思考模式：降低延迟，避免 MiMo 返回空内容
    data["max_output_tokens"] = max_output_tokens

    url = f"{endpoint}/responses"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    http_client = worker._get_http_client()
    for attempt in range(2):
        try:
            text, input_tokens, output_tokens, stream_error = worker._stream_doubao(
                http_client,
                url,
                headers,
                data,
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
        except Exception as exc:
            if attempt < 1:
                http_client = reset_worker_http_client(worker)
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


def stream_doubao(worker, http_client, url: str, headers: dict, data: dict) -> tuple[str, int, int, str]:
    from app.doubao_responses_stream import stream_doubao_responses

    result = stream_doubao_responses(http_client, url, headers, data)
    if not result.text:
        logger.warning(
            "doubao stream 返回空文本: input_tokens=%s output_tokens=%s "
            "stream_events=%s error=%r",
            result.input_tokens,
            result.output_tokens,
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
            message=tr("custom_model.error_incomplete"),
            persona_id=persona_id,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
        )
    endpoint, api_key, model, api_mode = resolved
    temperature = worker.config.get_float("temperature", 0.7)
    configured_max = worker.config.get_int("max_tokens", DEFAULT_MAX_TOKENS)
    caps = get_capabilities_for_model(model, endpoint, api_mode)
    max_tokens = resolve_danmu_max_output_tokens(
        configured_max,
        use_thinking=caps.thinking_param,
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
    url = f"{endpoint}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(2):
        try:
            text, input_tokens, output_tokens = worker._stream_openai(
                http_client,
                url,
                headers,
                data,
                endpoint=endpoint,
                api_mode=api_mode,
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
        except Exception as exc:
            if attempt < 1:
                http_client = reset_worker_http_client(worker)
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
) -> tuple[str, int, int]:
    collected: list[str] = []
    reasoning_parts: list[str] = []
    input_tokens = 0
    output_tokens = 0
    caps = get_capabilities_for_endpoint(endpoint, api_mode)
    adapter = get_openai_adapter(endpoint, api_mode)
    with http_client.stream("POST", url, headers=headers, json=data) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if worker._stopping:
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
                    collected.append(content)
                reasoning = delta.get("reasoning_content", "")  # 忽略：豆包/OpenAI 思考内容不应作为弹幕
                if reasoning:
                    reasoning_parts.append(reasoning)  # 仅用于诊断日志
                if not content and not reasoning:
                    message = choice.get("message", {})
                    message_content = message.get("content", "")
                    if message_content:
                        collected.append(message_content)
                    message_reasoning = message.get("reasoning_content", "")
                    if message_reasoning:
                        reasoning_parts.append(message_reasoning)
            except (json.JSONDecodeError, IndexError, KeyError):
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
