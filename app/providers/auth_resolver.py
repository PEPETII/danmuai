"""Schema-driven authentication resolution for provider HTTP requests."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.providers.endpoint_resolver import extract_hostname
from app.providers.platform_definitions import AuthProfile
from app.providers.platform_registry import auth_profile_for_provider

_USER_HEADER_ALLOWLIST = frozenset(
    {"x-request-id", "x-correlation-id", "x-custom-metadata"}
)


@dataclass(frozen=True, repr=False)
class AuthResolution:
    """Resolved transport pieces; secret-bearing values are excluded from repr."""

    headers: dict[str, str] = field(default_factory=dict, repr=False)
    query_params: dict[str, str] = field(default_factory=dict, repr=False)

    def __repr__(self) -> str:
        return "AuthResolution(headers=<redacted>, query_params=<redacted>)"


def resolve_auth(
    token: str,
    profile: AuthProfile,
    *,
    extra_user_headers: dict[str, str] | None = None,
) -> AuthResolution:
    """Resolve credentials strictly according to the supplied ``AuthProfile``."""
    value = (token or "").strip()
    headers: dict[str, str] = {}
    query_params: dict[str, str] = {}
    if value:
        if profile.scheme == "bearer":
            name = profile.bearer_header or profile.header_name
            headers[name] = f"{profile.token_prefix}{value}"
        elif profile.scheme == "api_key_header":
            headers[profile.api_key_header or profile.header_name] = value
        elif profile.scheme == "query_key":
            if profile.query_key:
                query_params[profile.query_key] = value
        elif profile.scheme == "custom":
            # ``custom`` is an explicit header name, never an inferred protocol.
            if profile.custom:
                headers[profile.custom] = value
    for name, header_value in profile.extra_headers:
        if name and header_value is not None:
            headers[name] = str(header_value)
    if extra_user_headers:
        for name, header_value in extra_user_headers.items():
            normalized = (name or "").strip().lower()
            if normalized in _USER_HEADER_ALLOWLIST and header_value is not None:
                headers[name] = str(header_value)
    return AuthResolution(headers=headers, query_params=query_params)


def build_auth_headers(
    api_key: str,
    *,
    provider_id: str,
    endpoint: str = "",
    extra_user_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Backward-compatible header-only facade used by the request planner."""
    profile = auth_profile_for_provider(provider_id, default_endpoint=endpoint)
    headers = {"Content-Type": "application/json"}
    resolved = resolve_auth(
            api_key,
            profile,
            extra_user_headers=extra_user_headers,
        )
    headers.update(resolved.headers)
    if not (provider_id == "openrouter" and extract_hostname(endpoint) == "openrouter.ai"):
        headers.pop("HTTP-Referer", None)
        headers.pop("X-Title", None)
    headers.update(_attribution_headers(provider_id, endpoint))
    return headers


def _attribution_headers(provider_id: str, endpoint: str) -> dict[str, str]:
    """Return attribution only for the OpenRouter profile on its exact host."""
    if provider_id != "openrouter" or extract_hostname(endpoint) != "openrouter.ai":
        return {}
    return {
        "HTTP-Referer": "https://github.com/PEPETII/danmuai",
        "X-Title": "DanmuAI",
    }
