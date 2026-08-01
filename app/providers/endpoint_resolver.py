"""Exact hostname endpoint resolution and API-family URL joining (Batch 3).

Replaces substring ``fragment in endpoint`` matching with ``urlparse().hostname``
equality (plus optional controlled suffix rules). Business code should use
``join_api_path`` instead of concatenating ``/chat/completions`` or ``/responses``.
"""

from __future__ import annotations

from urllib.parse import urlparse

from app.model_providers import normalize_endpoint

# API families (transport/protocol separation)
API_FAMILY_OPENAI_CHAT = "openai_chat_completions"
API_FAMILY_OPENAI_RESPONSES = "openai_responses"
API_FAMILY_ANTHROPIC_MESSAGES = "anthropic_messages"

_API_FAMILY_SUFFIX: dict[str, str] = {
    API_FAMILY_OPENAI_CHAT: "/chat/completions",
    API_FAMILY_OPENAI_RESPONSES: "/responses",
    API_FAMILY_ANTHROPIC_MESSAGES: "/messages",
}

# Controlled suffix rules: hostname must end with ``.<suffix>`` (leading dot required).
_HOST_SUFFIX_RULES: tuple[tuple[str, str], ...] = ()


def extract_hostname(endpoint: str) -> str | None:
    """Return lowercased hostname from endpoint URL (port stripped)."""
    parsed = urlparse(normalize_endpoint(endpoint))
    host = parsed.hostname
    return host.lower() if host else None


def extract_netloc(endpoint: str) -> str | None:
    """Return lowercased netloc (hostname[:port]) for local dev endpoints."""
    parsed = urlparse(normalize_endpoint(endpoint))
    netloc = (parsed.netloc or "").lower()
    return netloc or None


def hostname_matches(entry_hostname: str, endpoint: str) -> bool:
    """Exact hostname match; optional controlled ``.<suffix>`` rules."""
    hostname = extract_hostname(endpoint)
    if not hostname:
        return False
    key = (entry_hostname or "").lower()
    if not key:
        return False
    if hostname == key:
        return True
    for suffix, allowed_host in _HOST_SUFFIX_RULES:
        if key == allowed_host and hostname.endswith(suffix):
            return True
    return False


def resolve_api_family(*, transport: str) -> str:
    """Map legacy transport label to API family."""
    if transport == "doubao":
        return API_FAMILY_OPENAI_RESPONSES
    return API_FAMILY_OPENAI_CHAT


def join_api_path(base_url: str, api_family: str) -> str:
    """Join normalized base URL with the API-family path segment."""
    base = normalize_endpoint(base_url).rstrip("/")
    suffix = _API_FAMILY_SUFFIX.get(api_family, "/chat/completions")
    return f"{base}{suffix}"


def transport_for_api_family(api_family: str) -> str:
    if api_family == API_FAMILY_OPENAI_RESPONSES:
        return "doubao"
    return "openai"
