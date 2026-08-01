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
AuthScheme = Literal["bearer", "api_key_header", "query_key", "custom"]


@dataclass(frozen=True)
class OfficialSource:
    """Official documentation, product site, or migration notice URLs."""

    website: str | None = None
    docs_url: str | None = None
    migration_url: str | None = None
    source_kind: str = "unknown"
    url: str | None = None
    verified_at: str | None = None
    confidence: str | None = None


@dataclass(frozen=True)
class AuthProfile:
    """HTTP authentication shape for a provider preset."""

    scheme: AuthScheme = "bearer"
    header_name: str = "Authorization"
    token_prefix: str = "Bearer "
    extra_headers: tuple[tuple[str, str], ...] = ()
    bearer_header: str | None = None
    api_key_header: str | None = None
    query_key: str | None = None
    custom: str | None = None

    def __post_init__(self) -> None:
        if self.bearer_header is None and self.scheme == "bearer":
            object.__setattr__(self, "bearer_header", self.header_name)
        if self.api_key_header is None and self.scheme == "api_key_header":
            object.__setattr__(self, "api_key_header", self.header_name)


@dataclass(frozen=True)
class EndpointProfile:
    """Default API base URL and transport/mode locks."""

    default_url: str
    api_mode: str
    lock_endpoint: bool = True
    host_match_fragment: str | None = None
    id: str | None = None
    base_url: str | None = None
    exact_hosts: tuple[str, ...] = ()
    api_family: str | None = None
    path_prefix: str | None = None
    region: Region | None = None
    status: str | None = None

    def __post_init__(self) -> None:
        if self.base_url is None:
            object.__setattr__(self, "base_url", self.default_url)
        if not self.exact_hosts and self.host_match_fragment:
            object.__setattr__(self, "exact_hosts", (self.host_match_fragment,))
        if self.api_family is None:
            object.__setattr__(self, "api_family", self.api_mode)


@dataclass(frozen=True)
class CapabilityProfile:
    """Declarative request/response capability flags for a provider."""

    transport: str = ""
    vision: bool = True
    mic_audio: bool = False
    thinking_param: bool = False
    thinking_param_style: str = "none"
    supports_thinking: bool = False
    image_before_text: bool = False
    stream_usage_in_final_chunk: bool = True
    max_tokens_field: str = "max_tokens"
    usage_token_style: str = "openai"
    text_input: bool | None = None
    image_input: bool | None = None
    audio_input: bool | None = None
    video_input: bool | None = None
    file_input: bool | None = None
    structured_output: bool | None = None

    # Legacy aliases retained for existing callers of the first Batch 2 draft.
    @property
    def text(self) -> bool | None:
        return self.text_input

    @property
    def image(self) -> bool | None:
        return self.image_input

    @property
    def audio(self) -> bool | None:
        return self.audio_input

    @property
    def video(self) -> bool | None:
        return self.video_input

    @property
    def file(self) -> bool | None:
        return self.file_input


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
    supports_vision: bool | None = None
    main_flow_recommended: bool = True
    thinking_mode: ThinkingMode = "off"
    provider_id: str = ""
    platform_id: str = ""
    aliases: tuple[str, ...] = ()
    status: str = "unknown"
    replacement_model_id: str | None = None
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()
    api_families: tuple[str, ...] = ()
    capabilities: CapabilityProfile | None = None
    context_window: int | None = None
    max_output_tokens: int | None = None
    recommended_for: tuple[str, ...] = ()
    source: OfficialSource | None = None
    verified_at: str | None = None

    @property
    def supports_thinking_toggle(self) -> bool:
        return self.thinking_mode == "hybrid"

    @property
    def supports_mic(self) -> bool:
        return self.capabilities is not None and self.capabilities.audio_input is True

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
            "aliases": list(self.aliases),
            "status": self.status,
            "replacement_model_id": self.replacement_model_id,
            "input_modalities": list(self.input_modalities),
            "output_modalities": list(self.output_modalities),
            "api_families": list(self.api_families),
            "capabilities": _capability_profile_to_dict(self.capabilities)
            if self.capabilities is not None
            else None,
            "context_window": self.context_window,
            "max_output_tokens": self.max_output_tokens,
            "recommended_for": list(self.recommended_for),
            "source": _official_source_to_dict(self.source)
            if self.source is not None
            else None,
            "verified_at": self.verified_at,
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
    endpoint_profiles: tuple[EndpointProfile, ...] = ()
    auth_profiles: tuple[AuthProfile, ...] = ()
    api_families: tuple[str, ...] = ()
    preferred_api_family: str | None = None
    model_discovery: str | None = None
    status: str = "unknown"
    verified_at: str | None = None

    def __post_init__(self) -> None:
        if not self.endpoint_profiles:
            object.__setattr__(self, "endpoint_profiles", (self.endpoint,))
        if not self.auth_profiles:
            object.__setattr__(self, "auth_profiles", (self.auth,))
        if not self.api_families and self.endpoint.api_family:
            object.__setattr__(self, "api_families", (self.endpoint.api_family,))
        if self.preferred_api_family is None:
            object.__setattr__(self, "preferred_api_family", self.endpoint.api_family)

    @property
    def endpoints(self) -> tuple[EndpointProfile, ...]:
        """Plural alias for the extended endpoint profile collection."""
        return self.endpoint_profiles

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
                "id": self.endpoint.id,
                "base_url": self.endpoint.base_url,
                "exact_hosts": list(self.endpoint.exact_hosts),
                "api_family": self.endpoint.api_family,
                "path_prefix": self.endpoint.path_prefix,
                "region": self.endpoint.region,
                "status": self.endpoint.status,
            },
            "auth": {
                "scheme": self.auth.scheme,
                "header_name": self.auth.header_name,
                "token_prefix": self.auth.token_prefix,
                "extra_headers": list(self.auth.extra_headers),
                "bearer_header": self.auth.bearer_header,
                "api_key_header": self.auth.api_key_header,
                "query_key": self.auth.query_key,
                "custom": self.auth.custom,
            },
            "endpoint_profiles": [
                _endpoint_profile_to_dict(profile) for profile in self.endpoint_profiles
            ],
            "auth_profiles": [
                _auth_profile_to_dict(profile) for profile in self.auth_profiles
            ],
            "capabilities": _capability_profile_to_dict(self.capabilities),
            "official_source": _official_source_to_dict(self.official_source),
            "model_id_hint_zh": self.model_id_hint_zh,
            "model_id_hint_en": self.model_id_hint_en,
            "lock_mode": self.lock_mode,
            "lifecycle_status": self.lifecycle_status,
            "sunset_date": self.sunset_date,
            "notice_zh": self.notice_zh,
            "notice_en": self.notice_en,
            "api_families": list(self.api_families),
            "preferred_api_family": self.preferred_api_family,
            "model_discovery": self.model_discovery,
            "status": self.status,
            "verified_at": self.verified_at,
        }


def _official_source_to_dict(source: OfficialSource) -> dict[str, Any]:
    return {
        "website": source.website,
        "docs_url": source.docs_url,
        "migration_url": source.migration_url,
        "source_kind": source.source_kind,
        "url": source.url,
        "verified_at": source.verified_at,
        "confidence": source.confidence,
    }


def _auth_profile_to_dict(auth: AuthProfile) -> dict[str, Any]:
    return {
        "scheme": auth.scheme,
        "header_name": auth.header_name,
        "token_prefix": auth.token_prefix,
        "extra_headers": list(auth.extra_headers),
        "bearer_header": auth.bearer_header,
        "api_key_header": auth.api_key_header,
        "query_key": auth.query_key,
        "custom": auth.custom,
    }


def _endpoint_profile_to_dict(endpoint: EndpointProfile) -> dict[str, Any]:
    return {
        "default_url": endpoint.default_url,
        "api_mode": endpoint.api_mode,
        "lock_endpoint": endpoint.lock_endpoint,
        "host_match_fragment": endpoint.host_match_fragment,
        "id": endpoint.id,
        "base_url": endpoint.base_url,
        "exact_hosts": list(endpoint.exact_hosts),
        "api_family": endpoint.api_family,
        "path_prefix": endpoint.path_prefix,
        "region": endpoint.region,
        "status": endpoint.status,
    }


def _capability_profile_to_dict(caps: CapabilityProfile) -> dict[str, Any]:
    return {
        "transport": caps.transport,
        "vision": caps.vision,
        "mic_audio": caps.mic_audio,
        "thinking_param": caps.thinking_param,
        "thinking_param_style": caps.thinking_param_style,
        "supports_thinking": caps.supports_thinking,
        "image_before_text": caps.image_before_text,
        "stream_usage_in_final_chunk": caps.stream_usage_in_final_chunk,
        "max_tokens_field": caps.max_tokens_field,
        "usage_token_style": caps.usage_token_style,
        "text_input": caps.text_input,
        "image_input": caps.image_input,
        "audio_input": caps.audio_input,
        "video_input": caps.video_input,
        "file_input": caps.file_input,
        "text": caps.text_input,
        "image": caps.image_input,
        "audio": caps.audio_input,
        "video": caps.video_input,
        "file": caps.file_input,
        "structured_output": caps.structured_output,
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
    supports_mic = getattr(model, "supports_mic", False)
    source_url = getattr(model, "source_url", None)
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
        supports_vision=getattr(model, "supports_vision", None),
        main_flow_recommended=model.main_flow_recommended,
        thinking_mode=model.thinking_mode,
        capabilities=CapabilityProfile(audio_input=supports_mic),
        provider_id=provider_id,
        platform_id=platform_id,
        status=getattr(model, "status", "unknown"),
        replacement_model_id=getattr(model, "replacement_model_id", None),
        input_modalities=getattr(model, "input_modalities", ()),
        output_modalities=getattr(model, "output_modalities", ()),
        source=(
            OfficialSource(
                url=source_url,
                source_kind=getattr(model, "source_kind", "unknown"),
                verified_at=getattr(model, "verified_at", None),
            )
            if source_url
            else None
        ),
        verified_at=getattr(model, "verified_at", None),
    )
