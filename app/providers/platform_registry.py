"""V2 provider registry built from legacy presets + capabilities + auth rules.

Single composed view: ``ProviderDefinition`` aggregates ``ProviderSpec`` fields,
``CapabilityProfile`` from ``app.providers.capabilities``, and ``AuthProfile``
from registry header rules. Legacy ``PROVIDERS`` remains the preset data source
for Batch 2; v2 is derived at first access.
"""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import urlparse

from app.providers.endpoint_resolver import (
    API_FAMILY_OPENAI_CHAT,
    API_FAMILY_OPENAI_RESPONSES,
    extract_hostname,
)
from app.providers.platform_definitions import (
    AuthProfile,
    EndpointProfile,
    ModelDefinition,
    OfficialSource,
    ProviderDefinition,
    capability_profile_from_provider_capabilities,
    model_definition_from_catalog_model,
)

_PROVIDER_DEFINITIONS: tuple[ProviderDefinition, ...] | None = None
_DEFINITION_BY_ID: dict[str, ProviderDefinition] | None = None
_MODEL_DEFINITIONS_BY_PROVIDER: dict[str, tuple[ModelDefinition, ...]] | None = None

_OPENROUTER_EXTRA_HEADERS: tuple[tuple[str, str], ...] = (
    ("HTTP-Referer", "https://github.com/PEPETII/danmuai"),
    ("X-Title", "DanmuAI"),
)

_PROVIDER_PLATFORM_ID: dict[str, str] = {}
_VERIFIED_AT = "2026-08-01"


class _ProviderDefinitionCompat(ProviderDefinition):
    """Keep the legacy migration field while exposing the corrected source URL."""

    _legacy_migration_url: str | None = None

    def to_provider_spec(self):
        spec = super().to_provider_spec()
        return replace(spec, migration_url=self._legacy_migration_url)


def _endpoint_profile_for_spec(spec) -> EndpointProfile:
    """Build the enriched profile without inventing endpoints for customs."""
    url = spec.default_endpoint or ""
    hostname = _endpoint_host_fragment(url) if url else None
    parsed = urlparse(url) if url else None
    family = (
        API_FAMILY_OPENAI_RESPONSES
        if spec.mode == "doubao"
        else API_FAMILY_OPENAI_CHAT
    )
    status = getattr(spec, "lifecycle_status", None) or ("unknown" if not url else "active")
    return EndpointProfile(
        default_url=url,
        api_mode=spec.mode,
        lock_endpoint=spec.lock_endpoint,
        host_match_fragment=hostname,
        id=f"{spec.id}-default" if url else None,
        base_url=url or None,
        exact_hosts=(hostname,) if hostname else (),
        api_family=family,
        path_prefix=(parsed.path.rstrip("/") or "/") if parsed else None,
        region=spec.region,
        status=status,
    )


def _official_source_for_spec(spec) -> OfficialSource:
    docs = {
        "openrouter": "https://openrouter.ai/docs/quick-start",
        "stepfun": "https://platform.stepfun.com/docs/zh/api-reference/chat/chat-completion-create",
        "hunyuan": "https://cloud.tencent.com/document/product/1729/111007",
    }.get(spec.id)
    migration_url = getattr(spec, "migration_url", None)
    if spec.id == "hunyuan":
        migration_url = "https://cloud.tencent.com/document/product/1729/131925"
    return OfficialSource(
        website=spec.website,
        docs_url=docs,
        migration_url=migration_url,
        source_kind="official" if (docs or migration_url) else "unknown",
        url=docs or spec.website,
        verified_at=_VERIFIED_AT if (docs or migration_url) else None,
    )


def _endpoint_host_fragment(url: str) -> str | None:
    from app.model_providers import normalize_endpoint

    return extract_hostname(normalize_endpoint(url))


def auth_profile_for_provider(provider_id: str, *, default_endpoint: str = "") -> AuthProfile:
    """Resolve auth profile; OpenRouter injects Referer/Title on official host."""
    extra: tuple[tuple[str, str], ...] = ()
    if provider_id == "openrouter":
        extra = _OPENROUTER_EXTRA_HEADERS
    return AuthProfile(extra_headers=extra)


def provider_definition_from_spec(spec) -> ProviderDefinition:
    """Compose v2 definition from legacy ``ProviderSpec`` + capabilities."""
    from app.providers.capabilities import get_capabilities

    caps = get_capabilities(spec.id)
    endpoint = _endpoint_profile_for_spec(spec)
    official = _official_source_for_spec(spec)
    api_family = endpoint.api_family
    definition = _ProviderDefinitionCompat(
        id=spec.id,
        label_zh=spec.label_zh,
        label_en=spec.label_en,
        region=spec.region,
        endpoint=endpoint,
        auth=auth_profile_for_provider(spec.id, default_endpoint=spec.default_endpoint),
        capabilities=capability_profile_from_provider_capabilities(caps),
        official_source=official,
        model_id_hint_zh=spec.model_id_hint_zh,
        model_id_hint_en=spec.model_id_hint_en,
        lock_mode=spec.lock_mode,
        lifecycle_status=getattr(spec, "lifecycle_status", None),
        sunset_date=getattr(spec, "sunset_date", None),
        notice_zh=getattr(spec, "notice_zh", None),
        notice_en=getattr(spec, "notice_en", None),
        platform_id=_PROVIDER_PLATFORM_ID.get(spec.id),
        endpoint_profiles=(endpoint,),
        auth_profiles=(auth_profile_for_provider(spec.id, default_endpoint=spec.default_endpoint),),
        api_families=(api_family,) if api_family else (),
        preferred_api_family=api_family,
        model_discovery="unknown",
        status=getattr(spec, "lifecycle_status", None) or ("unknown" if not spec.default_endpoint else "active"),
        verified_at=_VERIFIED_AT if spec.default_endpoint else None,
    )
    object.__setattr__(definition, "_legacy_migration_url", getattr(spec, "migration_url", None))
    return definition


def _load_platform_id_map() -> None:
    global _PROVIDER_PLATFORM_ID
    if _PROVIDER_PLATFORM_ID:
        return
    from app.model_catalog import PLATFORM_CATALOGS

    _PROVIDER_PLATFORM_ID = {p.provider_id: p.platform_id for p in PLATFORM_CATALOGS}


def _build_provider_definitions() -> tuple[ProviderDefinition, ...]:
    from app.model_providers import PROVIDERS

    _load_platform_id_map()
    return tuple(provider_definition_from_spec(spec) for spec in PROVIDERS)


def _ensure_definitions_loaded() -> None:
    global _PROVIDER_DEFINITIONS, _DEFINITION_BY_ID
    if _PROVIDER_DEFINITIONS is not None:
        return
    _PROVIDER_DEFINITIONS = _build_provider_definitions()
    _DEFINITION_BY_ID = {d.id: d for d in _PROVIDER_DEFINITIONS}


def list_provider_definitions() -> tuple[ProviderDefinition, ...]:
    _ensure_definitions_loaded()
    assert _PROVIDER_DEFINITIONS is not None
    return _PROVIDER_DEFINITIONS


def get_provider_definition(provider_id: str) -> ProviderDefinition | None:
    _ensure_definitions_loaded()
    assert _DEFINITION_BY_ID is not None
    return _DEFINITION_BY_ID.get(provider_id)


def legacy_provider_specs_from_definitions() -> tuple:
    """Rebuild legacy ``ProviderSpec`` tuple from v2 (round-trip check / export)."""
    return tuple(d.to_provider_spec() for d in list_provider_definitions())


def _build_model_definitions_by_provider() -> dict[str, tuple[ModelDefinition, ...]]:
    from app.model_catalog import PLATFORM_CATALOGS

    result: dict[str, tuple[ModelDefinition, ...]] = {}
    for platform in PLATFORM_CATALOGS:
        models = tuple(
            model_definition_from_catalog_model(
                model,
                provider_id=platform.provider_id,
                platform_id=platform.platform_id,
            )
            for model in platform.models
        )
        result[platform.provider_id] = models
    return result


def list_model_definitions_for_provider(provider_id: str) -> tuple[ModelDefinition, ...]:
    global _MODEL_DEFINITIONS_BY_PROVIDER
    if _MODEL_DEFINITIONS_BY_PROVIDER is None:
        _MODEL_DEFINITIONS_BY_PROVIDER = _build_model_definitions_by_provider()
    return _MODEL_DEFINITIONS_BY_PROVIDER.get((provider_id or "").strip(), ())


def export_v2_snapshot() -> dict:
    """Full v2 registry snapshot for audit baseline export."""
    _ensure_definitions_loaded()
    from app.model_catalog import PLATFORM_CATALOGS

    providers = [d.to_export_dict() for d in list_provider_definitions()]
    catalogs = []
    for platform in PLATFORM_CATALOGS:
        models = list_model_definitions_for_provider(platform.provider_id)
        catalogs.append(
            {
                "platform_id": platform.platform_id,
                "platform_label": platform.platform_label,
                "provider_id": platform.provider_id,
                "models": [m.to_dict() for m in models],
            }
        )
    return {
        "schema_version": 2,
        "provider_count": len(providers),
        "catalog_platform_count": len(catalogs),
        "providers": providers,
        "catalogs": catalogs,
    }


def invalidate_registry_cache() -> None:
    """Test helper: force rebuild after legacy preset mutation."""
    global _PROVIDER_DEFINITIONS, _DEFINITION_BY_ID, _MODEL_DEFINITIONS_BY_PROVIDER
    _PROVIDER_DEFINITIONS = None
    _DEFINITION_BY_ID = None
    _MODEL_DEFINITIONS_BY_PROVIDER = None
    _PROVIDER_PLATFORM_ID.clear()
