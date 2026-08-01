"""Auth header resolution from AuthProfile (Batch 3).

Centralizes Bearer / custom header shapes and provider attribution headers.
Business code must not assemble ``Authorization: Bearer`` directly.
"""

from __future__ import annotations

from app.providers.platform_definitions import AuthProfile
from app.providers.platform_registry import auth_profile_for_provider

# Safe user-supplied header names (lowercase keys after normalization).
_USER_HEADER_ALLOWLIST = frozenset(
    {
        "x-request-id",
        "x-correlation-id",
        "x-custom-metadata",
    }
)


def build_auth_headers(
    api_key: str,
    *,
    provider_id: str,
    endpoint: str = "",
    extra_user_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build HTTP headers for provider API calls (never logs the key)."""
    profile = auth_profile_for_provider(provider_id, default_endpoint=endpoint)
    headers: dict[str, str] = {"Content-Type": "application/json"}
    token = (api_key or "").strip()
    if token:
        headers.update(_token_header(profile, token))
    for name, value in profile.extra_headers:
        if name and value is not None:
            headers[name] = str(value)
    headers.update(_attribution_headers(provider_id, endpoint))
    if extra_user_headers:
        for name, value in extra_user_headers.items():
            key = (name or "").strip().lower()
            if key in _USER_HEADER_ALLOWLIST and value is not None:
                headers[name] = str(value)
    return headers


def _token_header(profile: AuthProfile, token: str) -> dict[str, str]:
    if profile.scheme == "bearer":
        prefix = profile.token_prefix or ""
        return {profile.header_name: f"{prefix}{token}"}
    return {profile.header_name: token}


def _attribution_headers(provider_id: str, endpoint: str) -> dict[str, str]:
    """Provider-specific optional headers (e.g. OpenRouter Referer/Title)."""
    from app.providers.endpoint_resolver import extract_hostname

    hostname = extract_hostname(endpoint)
    if provider_id == "openrouter" or hostname == "openrouter.ai":
        return {
            "HTTP-Referer": "https://github.com/PEPETII/danmuai",
            "X-Title": "DanmuAI",
        }
    return {}
