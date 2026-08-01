"""Offline-by-default account model discovery (Batch 4)."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit, urlunsplit

from app.model_catalog import get_catalog_for_provider
from app.model_providers import normalize_endpoint
from app.providers.endpoint_resolver import API_FAMILY_OPENAI_CHAT
from app.providers.platform_definitions import ModelDefinition, ModelPriceDefinition, OfficialSource
from app.providers.platform_registry import (
    get_provider_definition,
    list_model_definitions_for_provider,
)


@dataclass(frozen=True)
class DiscoveryResult:
    models: tuple[ModelDefinition, ...]
    discovery_kind: str
    source: str
    source_url: str | None
    verified_at: str | None
    fetched_at: str | None
    status: str
    warnings: tuple[str, ...] = ()
    request_url: str | None = None


class _NoNetworkClient:
    def get(self, *_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("network_disabled")


_CACHE: dict[tuple[str, str], tuple[float, DiscoveryResult]] = {}


def _timestamp(now: Callable[[], float]) -> str:
    return datetime.fromtimestamp(now(), tz=timezone.utc).isoformat()


def _fingerprint(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _models_url(endpoint: str, provider_id: str) -> str | None:
    normalized = normalize_endpoint(endpoint)
    parsed = urlsplit(normalized)
    if not parsed.scheme or not parsed.netloc:
        return None
    if provider_id == "openrouter":
        path = "/api/v1/models"
    else:
        path = (parsed.path.rstrip("/") + "/models") if parsed.path.rstrip("/") else "/models"
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _auth_headers(definition, api_key: str) -> dict[str, str]:
    auth = definition.auth
    headers = {key: value for key, value in auth.extra_headers}
    if auth.scheme == "bearer":
        headers[auth.header_name] = f"{auth.token_prefix}{api_key}"
    elif auth.scheme == "api_key_header":
        headers[auth.header_name] = api_key
    return headers


def _fallback(provider_id: str, *, status: str, warnings: tuple[str, ...], now: Callable[[], float]) -> DiscoveryResult:
    definition = list_model_definitions_for_provider(provider_id)
    catalog = get_catalog_for_provider(provider_id)
    source_url = (catalog or {}).get("source_url") if catalog else None
    return DiscoveryResult(definition, "curated_fallback", "curated", source_url, None, _timestamp(now), status, warnings)


def _parse_models(
    payload: Any,
    provider_id: str,
    source_url: str,
    request_url: str,
    fetched_at: str,
) -> DiscoveryResult:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("data"), list):
        return _fallback(provider_id, status="fallback_invalid_payload", warnings=("invalid_models_payload",), now=lambda: datetime.fromisoformat(fetched_at).timestamp())
    models: list[ModelDefinition] = []
    for item in payload["data"]:
        model_id = item.get("id") if isinstance(item, Mapping) else None
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        models.append(ModelDefinition(
            id=model_id, display_name=str(item.get("name") or model_id),
            # ModelPriceDefinition is legacy-typed as float, but has no runtime
            # validation; None is the honest value for undiscovered pricing.
            price=ModelPriceDefinition(None, None), modality="unknown",
            supports_vision=None, main_flow_recommended=False, provider_id=provider_id,
            status="discovered", input_modalities=(), output_modalities=(),
            source=OfficialSource(url=source_url, source_kind="account_discovery", verified_at=fetched_at),
            verified_at=fetched_at,
        ))
    if not models:
        return _fallback(provider_id, status="fallback_empty_payload", warnings=("no_valid_models",), now=lambda: datetime.fromisoformat(fetched_at).timestamp())
    return DiscoveryResult(tuple(models), "account_discovery", "account", source_url, fetched_at, fetched_at, "ok", request_url=request_url)


def discover_models(
    provider_id: str,
    api_key: str = "",
    *,
    endpoint: str | None = None,
    http_client: Any | None = None,
    ttl_seconds: float = 300.0,
    now: Callable[[], float] = time.time,
) -> DiscoveryResult:
    """Discover account models without network by default; failures return curated fallback."""
    definition = get_provider_definition(provider_id)
    selected_endpoint = endpoint or (definition.endpoint.base_url if definition else None)
    if definition is None or not selected_endpoint:
        return _fallback(provider_id, status="unknown", warnings=("unknown_provider_or_endpoint",), now=now)
    if definition.endpoint.api_family != API_FAMILY_OPENAI_CHAT and provider_id != "openrouter":
        return _fallback(provider_id, status="unknown", warnings=("unknown_endpoint_family",), now=now)
    url = _models_url(selected_endpoint, provider_id)
    if url is None:
        return _fallback(provider_id, status="unknown", warnings=("unknown_endpoint",), now=now)
    key = (url, _fingerprint(api_key))
    cached = _CACHE.get(key)
    if cached and now() - cached[0] < ttl_seconds:
        return cached[1]
    client = http_client or _NoNetworkClient()
    fetched_at = _timestamp(now)
    try:
        response = client.get(url, headers=_auth_headers(definition, api_key))
        status_code = getattr(response, "status_code", None)
        if status_code is not None and not 200 <= status_code < 300:
            result = _fallback(provider_id, status="fallback_http_error", warnings=(f"http_status:{status_code}",), now=now)
        else:
            payload = response.json() if hasattr(response, "json") else response
            official_url = definition.official_source.url or url
            result = _parse_models(payload, provider_id, official_url, url, fetched_at)
    except Exception as exc:
        category = exc.__class__.__name__.lower()
        result = _fallback(provider_id, status="fallback_request_error", warnings=(f"request_error:{category}",), now=now)
    if result.discovery_kind == "account_discovery":
        _CACHE[key] = (now(), result)
    return result


def clear_discovery_cache() -> None:
    _CACHE.clear()
