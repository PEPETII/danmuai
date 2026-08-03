"""Unified HTTP request planning for visual, probe, and knowledge flows (Batch 3)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from app.model_catalog import catalog_model_supports_thinking_toggle
from app.model_providers import (
    get_openai_adapter_for_model,
    model_supports_mic_audio,
    normalize_endpoint,
    resolve_api_transport,
)
from app.providers.adapters.default_openai import DefaultOpenAIAdapter
from app.providers.adapters.mimo import MimoOpenAIAdapter
from app.providers.adapters.responses import ResponsesAdapter
from app.providers.auth_resolver import resolve_auth
from app.providers.capabilities import ProviderCapabilities
from app.providers.capability_resolver import resolve_capabilities
from app.providers.constants import THINKING_DISABLED, THINKING_ENABLED
from app.providers.endpoint_resolver import (
    API_FAMILY_OPENAI_CHAT,
    API_FAMILY_OPENAI_RESPONSES,
    extract_hostname,
    join_api_path,
    resolve_api_family,
)
from app.providers.platform_registry import auth_profile_for_provider, get_provider_definition
from app.providers.registry import guess_provider_from_endpoint, is_minimax_endpoint
from app.providers.stream_parser import parser_id_for_api_family, usage_normalizer_id_for_caps
from app.providers.thinking import apply_thinking_disabled, apply_thinking_mode

logger = logging.getLogger(__name__)

Purpose = Literal[
    "visual_danmu",
    "mic_danmu",
    "knowledge_organize",
    "connection_probe",
    "model_capability_probe",
]


@dataclass
class GenerationRequest:
    purpose: Purpose
    model_id: str
    endpoint: str
    api_key: str
    api_mode: str = ""
    provider_id: str | None = None
    system_text: str | None = None
    user_text: str = ""
    image_data_uri: str | None = None
    audio_data_uri: str | None = None
    max_output_tokens: int | None = None
    temperature: float | None = None
    reasoning_enabled: bool | None = None
    stream: bool = True
    force_thinking_off: bool = False
    supports_vision_override: bool | None = None
    supports_mic_override: bool | None = None
    supports_mic_declared: bool | str | None = None
    api_family: str | None = None
    reasoning_effort: str | None = None
    response_format: dict | None = None
    structured_output: dict | None = None
    extra_user_headers: dict[str, str] | None = None
    stream_options: dict | None = None


@dataclass
class PlannedHttpRequest:
    provider_id: str
    model_id: str
    api_family: str
    url: str
    headers: dict[str, str]
    json_body: dict
    parser_id: str
    usage_normalizer_id: str
    warnings: list[str] = field(default_factory=list)
    applied_capabilities: ProviderCapabilities | None = None


def plan_http_request(req: GenerationRequest) -> PlannedHttpRequest:
    """Plan URL, auth headers, and JSON body for one provider HTTP call."""
    endpoint = normalize_endpoint(req.endpoint)
    api_mode = req.api_mode or ""
    provider_id = (req.provider_id or guess_provider_from_endpoint(endpoint, api_mode)).strip()
    transport = resolve_api_transport(endpoint, api_mode)
    profile = get_provider_definition(provider_id)
    profile_family = getattr(profile.endpoint, "api_family", None) if profile else None
    valid_profile_family = profile_family if profile_family in (
        API_FAMILY_OPENAI_CHAT, API_FAMILY_OPENAI_RESPONSES
    ) else None
    api_family = resolve_api_family(
        transport=transport,
        profile=replace(profile.endpoint, api_family=valid_profile_family) if profile and valid_profile_family else None,
        api_family=req.api_family,
    )
    if not api_family:
        raise ValueError(f"unknown api family: {req.api_family!r}")
    caps = resolve_capabilities(
        req.model_id,
        endpoint,
        api_mode,
        provider_id=provider_id,
        supports_vision_override=req.supports_vision_override,
        supports_mic_override=req.supports_mic_override,
    )
    warnings: list[str] = []
    auth_profile = profile.auth if profile else auth_profile_for_provider(provider_id, default_endpoint=endpoint)
    if provider_id == "openrouter" and extract_hostname(endpoint) != "openrouter.ai":
        auth_profile = replace(auth_profile, extra_headers=())
    resolved_auth = resolve_auth(req.api_key, auth_profile, extra_user_headers=req.extra_user_headers)
    headers = {"Content-Type": "application/json", **resolved_auth.headers}
    url = join_api_path(endpoint, api_family)
    if url is None:
        raise ValueError(f"unknown api family: {api_family!r}")
    url = _merge_query(url, resolved_auth.query_params)
    adapter = ResponsesAdapter() if api_family == API_FAMILY_OPENAI_RESPONSES else (
        MimoOpenAIAdapter() if provider_id == "mimo" else DefaultOpenAIAdapter()
    )
    effective_req = req
    if (
        req.audio_data_uri
        and req.supports_mic_override is not True
        and not model_supports_mic_audio(
            req.model_id,
            endpoint=endpoint,
            api_mode=api_mode,
            supports_mic_declared=req.supports_mic_declared,
        )
    ):
        warnings.append("mic_audio_stripped")
        logger.warning(
            "mic_audio_stripped: model=%s endpoint=%s",
            req.model_id,
            endpoint,
        )
        effective_req = replace(req, audio_data_uri=None)
    body = adapter.build_body(effective_req, caps, warnings) if hasattr(adapter, "build_body") else _plan_openai_chat_body(effective_req, endpoint, api_mode, caps, warnings)
    if not req.stream_options:
        body.pop("stream_options", None)
    elif caps.stream_usage_in_final_chunk and req.stream:
        body["stream_options"] = dict(req.stream_options)
    else:
        body.pop("stream_options", None)
    return PlannedHttpRequest(
        provider_id=provider_id,
        model_id=req.model_id,
        api_family=api_family,
        url=url,
        headers=headers,
        json_body=body,
        parser_id=parser_id_for_api_family(api_family),
        usage_normalizer_id=usage_normalizer_id_for_caps(caps),
        warnings=warnings,
        applied_capabilities=caps,
    )


def _merge_query(url: str, params: dict[str, str]) -> str:
    if not params:
        return url
    parts = urlsplit(url)
    merged = dict(parse_qsl(parts.query, keep_blank_values=True))
    merged.update(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(merged), parts.fragment))


def _plan_doubao_body(
    req: GenerationRequest,
    caps: ProviderCapabilities,
    warnings: list[str],
) -> dict:
    user_content: list[dict] = []
    if req.image_data_uri:
        user_content.append({"type": "input_image", "image_url": req.image_data_uri})
    if req.user_text:
        user_content.append({"type": "input_text", "text": req.user_text})
    if req.audio_data_uri:
        user_content.append({"type": "input_audio", "audio_url": req.audio_data_uri})
    if not user_content and req.purpose == "connection_probe":
        user_content = [{"type": "input_text", "text": req.user_text or "ping"}]
    data: dict = {
        "model": req.model_id,
        "input": [
            {
                "type": "message",
                "role": "user",
                "content": user_content,
            }
        ],
        "stream": req.stream,
    }
    if req.system_text:
        data["instructions"] = req.system_text
    if req.max_output_tokens and req.max_output_tokens > 0:
        data["max_output_tokens"] = req.max_output_tokens
    if req.temperature is not None and req.temperature >= 0:
        data["temperature"] = req.temperature
    if req.force_thinking_off or req.purpose in ("connection_probe", "knowledge_organize"):
        data["thinking"] = dict(THINKING_DISABLED)
    elif req.reasoning_enabled is not None and caps.thinking_param_style == "thinking_type":
        data["thinking"] = dict(THINKING_ENABLED if req.reasoning_enabled else THINKING_DISABLED)
    return data


def _plan_openai_chat_body(
    req: GenerationRequest,
    endpoint: str,
    api_mode: str,
    caps: ProviderCapabilities,
    warnings: list[str],
) -> dict:
    adapter = get_openai_adapter_for_model(req.model_id, endpoint, api_mode)
    messages = _build_openai_messages(req, endpoint, api_mode, caps, warnings)
    data: dict = {
        "model": req.model_id,
        "messages": messages,
        "stream": req.stream,
    }
    max_tokens = req.max_output_tokens or 0
    if req.purpose == "connection_probe" and max_tokens <= 0:
        max_tokens = 1
    if req.temperature is not None and req.temperature >= 0:
        data["temperature"] = req.temperature
    if max_tokens > 0:
        adapter.patch_openai_chat_body(data, max_tokens=max_tokens, caps=caps)
    elif req.purpose == "connection_probe":
        adapter.patch_probe_body(data, caps=caps)
    if req.force_thinking_off or req.purpose in ("connection_probe", "knowledge_organize"):
        apply_thinking_disabled(data, caps=caps)
    elif req.reasoning_enabled is not None:
        if catalog_model_supports_thinking_toggle(req.model_id) and caps.thinking_param_style != "none":
            apply_thinking_mode(data, enabled=bool(req.reasoning_enabled), caps=caps)
        elif caps.thinking_param and caps.thinking_param_style != "none":
            apply_thinking_mode(data, enabled=False, caps=caps)
    elif caps.thinking_param and caps.thinking_param_style != "none" and req.purpose == "visual_danmu":
        apply_thinking_mode(data, enabled=False, caps=caps)
    if is_minimax_endpoint(endpoint):
        data["reasoning_split"] = True
    return data


def _build_openai_messages(
    req: GenerationRequest,
    endpoint: str,
    api_mode: str,
    caps: ProviderCapabilities,
    warnings: list[str],
) -> list[dict]:
    if req.purpose == "connection_probe":
        return [{"role": "user", "content": req.user_text or "ping"}]
    if req.purpose == "knowledge_organize":
        return [
            {"role": "system", "content": req.system_text or ""},
            {"role": "user", "content": req.user_text},
        ]
    adapter = get_openai_adapter_for_model(req.model_id, endpoint, api_mode)
    mic_audio = req.audio_data_uri
    if (
        mic_audio
        and req.supports_mic_override is not True
        and not model_supports_mic_audio(
            req.model_id,
            endpoint=endpoint,
            api_mode=api_mode,
            supports_mic_declared=req.supports_mic_declared,
        )
    ):
        warnings.append("mic_audio_stripped")
        logger.warning(
            "mic_audio_stripped: model=%s endpoint=%s",
            req.model_id,
            endpoint,
        )
        mic_audio = None
    messages: list[dict] = []
    if req.system_text:
        messages.append({"role": "system", "content": req.system_text})
    user_content = adapter.build_vision_user_content(
        req.user_text,
        req.image_data_uri or "",
        audio_data_uri=mic_audio,
    )
    messages.append({"role": "user", "content": user_content})
    return messages
