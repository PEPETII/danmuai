"""Exact hostname endpoint resolution and API-family URL joining (Batch 3).

Replaces substring ``fragment in endpoint`` matching with ``urlparse().hostname``
equality (plus optional controlled suffix rules). Business code should use
``join_api_path`` instead of concatenating ``/chat/completions`` or ``/responses``.
"""

from __future__ import annotations

from urllib.parse import urlparse, urlsplit, urlunsplit

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
DEFAULT_PATH_JOIN_POLICY = "preserve_base_path"


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


def resolve_api_family(*, transport: str = "", endpoint: str | None = None,
                       profile=None, api_family: str | None = None) -> str | None:
    """Resolve the HTTP family, with explicit endpoint/profile metadata first."""
    explicit = api_family or getattr(profile, "api_family", None)
    if explicit:
        return explicit if explicit in _API_FAMILY_SUFFIX else None
    endpoint_family = getattr(profile, "endpoint_api_family", None)
    if endpoint_family:
        return endpoint_family if endpoint_family in _API_FAMILY_SUFFIX else None
    if transport == "doubao":
        return API_FAMILY_OPENAI_RESPONSES
    if transport in ("openai", "openai-compatible", ""):
        return API_FAMILY_OPENAI_CHAT
    return None


def join_api_path(base_url: str, api_family: str | None = None, *, profile=None,
                  path_policy: str | None = None, preserve_query: bool | None = None,
                  preserve_fragment: bool | None = None) -> str | None:
    """Join a base URL without discarding meaningful path or URL metadata."""
    family = resolve_api_family(transport="", profile=profile, api_family=api_family)
    suffix = _API_FAMILY_SUFFIX.get(family or "")
    if suffix is None:
        return None
    parsed = urlsplit(normalize_endpoint(base_url))
    path = parsed.path.rstrip("/")
    # Remove only a complete API suffix; '/messages-extra' must remain a base path.
    for known_suffix in _API_FAMILY_SUFFIX.values():
        if path.endswith(known_suffix):
            path = path[:-len(known_suffix)].rstrip("/")
            break
    policy = path_policy or getattr(profile, "path_join_policy", DEFAULT_PATH_JOIN_POLICY)
    if policy == "root_path":
        path = ""
    elif policy not in ("preserve_base_path", "root_path"):
        return None
    query = parsed.query if (preserve_query if preserve_query is not None else getattr(profile, "preserve_query", False)) else ""
    fragment = parsed.fragment if (preserve_fragment if preserve_fragment is not None else getattr(profile, "preserve_fragment", False)) else ""
    return urlunsplit((parsed.scheme, parsed.netloc, f"{path}/{suffix.lstrip('/')}" if path else suffix, query, fragment))


def transport_for_api_family(api_family: str) -> str:
    if api_family == API_FAMILY_OPENAI_RESPONSES:
        return "doubao"
    return "openai"
