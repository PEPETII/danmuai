"""Unified v2 platform/model definition types (Batch 2).

These dataclasses compose provider preset metadata, endpoint/auth profiles,
capability flags, and catalog model entries into a single registry view.
Legacy ``ProviderSpec`` / ``CatalogModel`` remain the persistence-facing shapes;
v2 types are built from them via ``platform_registry`` and exposed through the
compatibility facade in ``app.model_providers`` / ``app.model_catalog``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

Region = Literal["china", "international", "global"]
ThinkingMode = Literal["off", "hybrid", "always"]
AuthScheme = Literal["bearer"]


@dataclass(frozen=True)
class OfficialSource:
    """Official documentation, product site, or migration notice URLs."""

    website: str | None = None
    docs_url: str | None = None
    migration_url: str | None = None


@dataclass(frozen=True)
class AuthProfile:
    """HTTP authentication shape for a provider preset."""

    scheme: AuthScheme = "bearer"
    header_name: str = "Authorization"
    token_prefix: str = "Bearer "
    extra_headers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class EndpointProfile:
    """Default API base URL and transport/mode locks."""

    default_url: str
    api_mode: str
    lock_endpoint: bool = True
    host_match_fragment: str | None = None


@dataclass(frozen=True)
class CapabilityProfile:
    """Declarative request/response capability flags for a provider."""

    transport: str
    vision: bool = True
    mic_audio: bool = False
    thinking_param: bool = False
    thinking_param_style: str = "none"
    supports_thinking: bool = False
    image_before_text: bool = False
    stream_usage_in_final_chunk: bool = True
    max_tokens_field: str = "max_tokens"
    usage_token_style: str = "openai"


@dataclass(frozen=True)
class ModelPriceDefinition:
    input: float
    output: float
    audio: float | None = None
    currency: str = "CNY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "audio": self.audio,
            "output": self.output,
            "currency": self.currency,
        }


@dataclass(frozen=True)
class ModelDefinition:
    """Vision catalog model entry in v2 form."""

    id: str
    display_name: str
    price: ModelPriceDefinition
    modality: str = "图片输入 + 文本输入 → 文本输出"
    supports_vision: bool = True
    main_flow_recommended: bool = True
    thinking_mode: ThinkingMode = "off"
    provider_id: str = ""
    platform_id: str = ""

    @property
    def supports_thinking_toggle(self) -> bool:
        return self.thinking_mode == "hybrid"

    @property
    def supports_mic(self) -> bool:
        return self.price.audio is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.display_name,
            "id": self.id,
            "price": self.price.to_dict(),
            "modality": self.modality,
            "supports_vision": self.supports_vision,
            "main_flow_recommended": self.main_flow_recommended,
            "thinking_mode": self.thinking_mode,
            "supports_thinking_toggle": self.supports_thinking_toggle,
            "supports_mic": self.supports_mic,
            "provider_id": self.provider_id,
            "platform_id": self.platform_id,
        }


@dataclass(frozen=True)
class ProviderDefinition:
    """Full provider preset: labels, endpoint, auth, capabilities, lifecycle."""

    id: str
    label_zh: str
    label_en: str
    region: Region
    endpoint: EndpointProfile
    auth: AuthProfile
    capabilities: CapabilityProfile
    official_source: OfficialSource
    model_id_hint_zh: str
    model_id_hint_en: str
    lock_mode: bool = True
    lifecycle_status: str | None = None
    sunset_date: str | None = None
    notice_zh: str | None = None
    notice_en: str | None = None
    platform_id: str | None = None

    def to_provider_spec(self):
        """Project to legacy ``ProviderSpec`` (import deferred to avoid cycles)."""
        from app.model_providers import ProviderSpec

        return ProviderSpec(
            id=self.id,
            label_zh=self.label_zh,
            label_en=self.label_en,
            default_endpoint=self.endpoint.default_url,
            mode=self.endpoint.api_mode,
            model_id_hint_zh=self.model_id_hint_zh,
            model_id_hint_en=self.model_id_hint_en,
            region=self.region,
            lock_mode=self.lock_mode,
            lock_endpoint=self.endpoint.lock_endpoint,
            website=self.official_source.website,
            lifecycle_status=self.lifecycle_status,
            sunset_date=self.sunset_date,
            migration_url=self.official_source.migration_url,
            notice_zh=self.notice_zh,
            notice_en=self.notice_en,
        )

    def to_api_dict(self, lang: str = "zh") -> dict[str, Any]:
        """Serialize for GET /api/providers (matches ``provider_for_api``)."""
        from app.model_providers import provider_for_api

        return provider_for_api(self.to_provider_spec(), lang)

    def to_export_dict(self) -> dict[str, Any]:
        """Structured export for audit baseline snapshots."""
        return {
            "id": self.id,
            "label_zh": self.label_zh,
            "label_en": self.label_en,
            "region": self.region,
            "platform_id": self.platform_id,
            "endpoint": {
                "default_url": self.endpoint.default_url,
                "api_mode": self.endpoint.api_mode,
                "lock_endpoint": self.endpoint.lock_endpoint,
                "host_match_fragment": self.endpoint.host_match_fragment,
            },
            "auth": {
                "scheme": self.auth.scheme,
                "header_name": self.auth.header_name,
                "token_prefix": self.auth.token_prefix,
                "extra_headers": list(self.auth.extra_headers),
            },
            "capabilities": {
                "transport": self.capabilities.transport,
                "vision": self.capabilities.vision,
                "mic_audio": self.capabilities.mic_audio,
                "thinking_param": self.capabilities.thinking_param,
                "thinking_param_style": self.capabilities.thinking_param_style,
                "supports_thinking": self.capabilities.supports_thinking,
                "image_before_text": self.capabilities.image_before_text,
                "stream_usage_in_final_chunk": self.capabilities.stream_usage_in_final_chunk,
                "max_tokens_field": self.capabilities.max_tokens_field,
                "usage_token_style": self.capabilities.usage_token_style,
            },
            "official_source": {
                "website": self.official_source.website,
                "docs_url": self.official_source.docs_url,
                "migration_url": self.official_source.migration_url,
            },
            "model_id_hint_zh": self.model_id_hint_zh,
            "model_id_hint_en": self.model_id_hint_en,
            "lock_mode": self.lock_mode,
            "lifecycle_status": self.lifecycle_status,
            "sunset_date": self.sunset_date,
            "notice_zh": self.notice_zh,
            "notice_en": self.notice_en,
        }


def capability_profile_from_provider_capabilities(caps) -> CapabilityProfile:
    """Map ``ProviderCapabilities`` to v2 ``CapabilityProfile``."""
    return CapabilityProfile(
        transport=caps.transport,
        vision=caps.vision,
        mic_audio=caps.mic_audio,
        thinking_param=caps.thinking_param,
        thinking_param_style=caps.thinking_param_style,
        supports_thinking=caps.supports_thinking,
        image_before_text=caps.image_before_text,
        stream_usage_in_final_chunk=caps.stream_usage_in_final_chunk,
        max_tokens_field=caps.max_tokens_field,
        usage_token_style=caps.usage_token_style,
    )


def model_definition_from_catalog_model(model, *, provider_id: str = "", platform_id: str = "") -> ModelDefinition:
    """Map legacy ``CatalogModel`` to v2 ``ModelDefinition``."""
    return ModelDefinition(
        id=model.id,
        display_name=model.name,
        price=ModelPriceDefinition(
            input=model.price.input,
            output=model.price.output,
            audio=model.price.audio,
            currency=model.price.currency,
        ),
        modality=model.modality,
        supports_vision=model.supports_vision,
        main_flow_recommended=model.main_flow_recommended,
        thinking_mode=model.thinking_mode,
        provider_id=provider_id,
        platform_id=platform_id,
    )
