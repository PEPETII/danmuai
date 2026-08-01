"""Model-level capability resolution with conservative unknown defaults (Batch 3).

Merge priority:
  user profile override > catalog model > provider/endpoint default > unknown
"""

from __future__ import annotations

from dataclasses import replace

from app.providers.capabilities import (
    ProviderCapabilities,
    get_capabilities,
    get_capabilities_for_endpoint,
)

_UNKNOWN_CAPS = ProviderCapabilities(
    vision=False,
    mic_audio=False,
    thinking_param=False,
    thinking_param_style="none",
    supports_thinking=False,
    stream_usage_in_final_chunk=False,
)


def resolve_capabilities(
    model_id: str,
    endpoint: str,
    api_mode: str = "",
    *,
    supports_vision_override: bool | None = None,
    supports_mic_override: bool | None = None,
    provider_id: str | None = None,
) -> ProviderCapabilities:
    """Resolve effective capabilities for a model at an endpoint."""
    from app.model_catalog import catalog_model_supports_mic, lookup_catalog_model
    from app.model_providers import resolve_openai_provider_id

    pid = provider_id or resolve_openai_provider_id(model_id, endpoint, api_mode)
    base = get_capabilities_for_endpoint(endpoint, api_mode)
    if pid == "mimo":
        base = get_capabilities("mimo")

    catalog = lookup_catalog_model(model_id)
    if catalog is not None:
        base = replace(
            base,
            vision=catalog.supports_vision,
        )

    if supports_vision_override is not None:
        base = replace(base, vision=supports_vision_override)
    if supports_mic_override is not None:
        base = replace(base, mic_audio=supports_mic_override)
    elif catalog is not None and catalog_model_supports_mic(model_id):
        base = replace(base, mic_audio=True)

    if catalog is None and pid in ("custom_openai", "custom_doubao"):
        return _merge_unknown_transport(base, endpoint, api_mode)

    return base


def _merge_unknown_transport(
    base: ProviderCapabilities,
    endpoint: str,
    api_mode: str,
) -> ProviderCapabilities:
    """Custom providers without catalog model: conservative caps + transport."""
    from app.providers.registry import guess_provider_from_endpoint, resolve_api_transport

    if guess_provider_from_endpoint(endpoint, api_mode) in ("custom_openai", "custom_doubao"):
        transport = resolve_api_transport(endpoint, api_mode)
        merged = replace(_UNKNOWN_CAPS, transport=transport)
        if transport == "doubao":
            return replace(
                merged,
                max_tokens_field="max_output_tokens",
                thinking_param_style="thinking_type",
                supports_thinking=True,
            )
        return merged
    return base


def unknown_capabilities() -> ProviderCapabilities:
    return _UNKNOWN_CAPS
