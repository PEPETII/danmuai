"""AI 客户端辅助函数：纯逻辑、无 Qt 依赖，可安全用于单元测试。

职责：请求扩展构建、HTTP 错误格式化、Provider 特殊处理（MiMo 等）、输出 token 下限计算。
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.logger import (
    API_KEY_PATTERN,
    AUTH_HEADER_PATTERN,
    BASE64_AUDIO_PATTERN,
    BASE64_IMAGE_PATTERN,
    ENCRYPTED_KEY_PATTERN,
    GENERIC_API_KEY_PATTERN,
)
from app.providers import (
    get_capabilities_for_endpoint,
    get_openai_adapter,
    guess_provider_from_endpoint,
    provider_extra_body,
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
    data.update(provider_extra_body(endpoint))
    return data


def _http_error_message_and_code(exc: httpx.HTTPStatusError) -> tuple[str, object]:
    message = ""
    code: object = None
    try:
        body = exc.response.json()
        if isinstance(body, dict):
            code = body.get("code")
            raw = body.get("message")
            if isinstance(raw, str):
                message = raw.strip()
            if not message:
                err = body.get("error")
                if isinstance(err, dict):
                    code = code or err.get("code")
                    nested = err.get("message")
                    if isinstance(nested, str):
                        message = nested.strip()
    except Exception:
        pass
    return message, code


def sanitize_provider_error_snippet(message: str, max_len: int = HTTP_ERROR_MESSAGE_SNIPPET_MAX) -> str:
    text = str(message or "").strip()
    if not text:
        return ""
    text = API_KEY_PATTERN.sub("sk-****", text)
    text = BASE64_IMAGE_PATTERN.sub("data:image/***;base64,(hidden)", text)
    text = BASE64_AUDIO_PATTERN.sub("data:audio/***;base64,(hidden)", text)
    text = AUTH_HEADER_PATTERN.sub("Authorization: Bearer (hidden)", text)
    text = ENCRYPTED_KEY_PATTERN.sub("gAAAA****(hidden)", text)
    text = GENERIC_API_KEY_PATTERN.sub("(api_key: ****)", text)
    if len(text) <= max_len:
        return text
    return f"{text[:max_len]}…"


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
        display_message = message
        if len(message) > HTTP_ERROR_MESSAGE_DISPLAY_MAX:
            display_message = sanitize_provider_error_snippet(message)
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
