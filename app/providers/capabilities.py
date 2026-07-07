"""Declarative per-provider capabilities.

职责：
- 按 ``provider_id`` 声明式注册每个服务商的能力（transport/vision/mic_audio/thinking_param/...）。
- ``get_capabilities`` 查表；未命中返回 ``_DEFAULT_OPENAI``。
- ``get_capabilities_for_endpoint`` 先经 ``registry.guess_provider_from_endpoint`` 推断
  provider_id，再做 transport 校验：若 ``caps.transport != transport`` 时回退到
  ``_DEFAULT_DOUBAO`` 或 ``_DEFAULT_OPENAI``，避免给非豆包 endpoint 强加豆包请求结构。

设计取舍：
- ``stream_usage_in_final_chunk=False``（豆包/小米）走终结 chunk 内 usage；
  ``True``（OpenAI 默认）走 ``stream_options.include_usage``。
- ``thinking_param=True``（mimo）默认请求须注入关闭 thinking，避免空响应；
  与 ``thinking_param_style``（API 字段形态）解耦。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.model_providers import PROVIDERS

ThinkingParamStyle = Literal["none", "thinking_type", "enable_thinking"]

# Per preset provider_id; custom_* fall back to matched host or OpenAI defaults.
_CAPABILITIES_BY_ID: dict[str, ProviderCapabilities] = {}


@dataclass(frozen=True)
class ProviderCapabilities:
  transport: str = "openai"  # "doubao" | "openai"
  vision: bool = True
  mic_audio: bool = False
  thinking_param: bool = False
  thinking_param_style: ThinkingParamStyle = "none"
  supports_thinking: bool = False
  image_before_text: bool = False
  stream_usage_in_final_chunk: bool = True
  max_tokens_field: str = "max_tokens"
  usage_token_style: str = "openai"  # "dashscope" uses input_tokens/output_tokens first


def _register(
    provider_id: str,
    *,
    transport: str = "openai",
    thinking_param: bool = False,
    thinking_param_style: ThinkingParamStyle = "none",
    supports_thinking: bool | None = None,
    image_before_text: bool = False,
    stream_usage_in_final_chunk: bool = True,
    max_tokens_field: str = "max_tokens",
    usage_token_style: str = "openai",
    mic_audio: bool = False,
) -> None:
    if supports_thinking is None:
        supports_thinking = thinking_param_style != "none"
    _CAPABILITIES_BY_ID[provider_id] = ProviderCapabilities(
        transport=transport,
        thinking_param=thinking_param,
        thinking_param_style=thinking_param_style,
        supports_thinking=supports_thinking,
        image_before_text=image_before_text,
        stream_usage_in_final_chunk=stream_usage_in_final_chunk,
        max_tokens_field=max_tokens_field,
        usage_token_style=usage_token_style,
        mic_audio=mic_audio,
    )


_register(
    "doubao",
    transport="doubao",
    stream_usage_in_final_chunk=False,
    max_tokens_field="max_output_tokens",
    thinking_param_style="thinking_type",
)
_register(
    "dashscope",
    usage_token_style="dashscope",
    thinking_param_style="enable_thinking",
)
_register("zai", thinking_param_style="thinking_type")
_register("zhipu", thinking_param_style="thinking_type")
_register("moonshot", thinking_param_style="thinking_type")
_register("siliconflow", thinking_param_style="enable_thinking")
_register(
    "mimo",
    thinking_param=True,
    thinking_param_style="thinking_type",
    image_before_text=True,
    stream_usage_in_final_chunk=False,
    max_tokens_field="max_completion_tokens",
    mic_audio=True,
)
_register("hunyuan", thinking_param_style="thinking_type")
_register("stepfun", thinking_param_style="enable_thinking")
_register(
    "baidu_cloud",
    thinking_param_style="enable_thinking",
    usage_token_style="dashscope",
)
_register("openrouter", thinking_param_style="none", supports_thinking=False)
_register("modelscope", thinking_param_style="none", supports_thinking=False)
_register("custom_openai", thinking_param_style="none", supports_thinking=False)
_register(
    "custom_doubao",
    transport="doubao",
    stream_usage_in_final_chunk=False,
    max_tokens_field="max_output_tokens",
    thinking_param_style="thinking_type",
)

_DEFAULT_OPENAI = ProviderCapabilities()
_DEFAULT_DOUBAO = ProviderCapabilities(
    transport="doubao",
    stream_usage_in_final_chunk=False,
    max_tokens_field="max_output_tokens",
    thinking_param_style="thinking_type",
    supports_thinking=True,
)


def get_capabilities(provider_id: str) -> ProviderCapabilities:
    return _CAPABILITIES_BY_ID.get(provider_id, _DEFAULT_OPENAI)


def get_capabilities_for_endpoint(endpoint: str, api_mode: str = "") -> ProviderCapabilities:
    from app.providers.registry import guess_provider_from_endpoint, resolve_api_transport

    provider_id = guess_provider_from_endpoint(endpoint, api_mode)
    caps = get_capabilities(provider_id)
    transport = resolve_api_transport(endpoint, api_mode)
    if transport == "doubao" and caps.transport != "doubao":
        return _DEFAULT_DOUBAO
    if transport != caps.transport:
        if transport == "doubao":
            return _DEFAULT_DOUBAO
        return _DEFAULT_OPENAI
    return caps


def list_registered_provider_ids() -> list[str]:
    return [p.id for p in PROVIDERS if p.id in _CAPABILITIES_BY_ID]
