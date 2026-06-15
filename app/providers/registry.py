"""Single host registry: endpoint guess and API transport from PROVIDERS.

职责：
- ``HOST_ENTRIES`` 由 ``PROVIDERS`` 预设 default_endpoint 提取 netloc 片段并去重，
  按片段长度降序排序（更长的优先匹配，例如 ``api.xiaomimimo.com`` 早于 ``xiaomimimo.com``）。
- ``match_host_entry`` 在 endpoint 字符串中做子串匹配；``HOST_ENTRIES`` 顺序决定优先级。
- ``guess_provider_from_endpoint`` 先看 host 匹配；未命中时按 ``api_mode`` 返回
  ``custom_doubao``，否则回退 ``DEFAULT_PROVIDER_ID``。
- ``resolve_api_transport`` 选择 ``doubao``（Responses）或 ``openai``（Chat Completions）。

约束：与 ``app.model_providers.PROVIDERS`` 严格对齐；新增服务商需在 ``_build_host_entries``
中可被自动收录（仅需 ``default_endpoint`` 非空）。
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from app.model_providers import (
    DEFAULT_PROVIDER_ID,
    PROVIDERS,
    is_doubao_mode,
    normalize_endpoint,
    normalize_mode,
)


@dataclass(frozen=True)
class HostEntry:
    fragment: str
    provider_id: str
    transport: str  # "doubao" | "openai"


def _mode_to_transport(mode: str) -> str:
    return "doubao" if mode == "doubao" else "openai"


def _endpoint_netloc_fragment(url: str) -> str:
    parsed = urlparse(normalize_endpoint(url))
    return (parsed.netloc or "").lower()


def _build_host_entries() -> tuple[HostEntry, ...]:
    entries: list[HostEntry] = []
    seen: set[str] = set()
    for spec in PROVIDERS:
        if not spec.default_endpoint:
            continue
        fragment = _endpoint_netloc_fragment(spec.default_endpoint)
        if not fragment or fragment in seen:
            continue
        seen.add(fragment)
        entries.append(
            HostEntry(
                fragment=fragment,
                provider_id=spec.id,
                transport=_mode_to_transport(spec.mode),
            )
        )
    return tuple(sorted(entries, key=lambda e: -len(e.fragment)))


HOST_ENTRIES: tuple[HostEntry, ...] = _build_host_entries()


def match_host_entry(endpoint: str) -> HostEntry | None:
    normalized = normalize_endpoint(endpoint).lower() if endpoint else ""
    if not normalized:
        return None
    for entry in HOST_ENTRIES:
        if entry.fragment in normalized:
            return entry
    return None


def guess_provider_from_endpoint(endpoint: str, mode: str = "") -> str:
    entry = match_host_entry(endpoint)
    if entry is not None:
        return entry.provider_id
    if normalize_mode(mode) == "doubao":
        return "custom_doubao"
    return DEFAULT_PROVIDER_ID


def resolve_api_transport(endpoint: str, api_mode: str) -> str:
    """Choose Responses (``doubao``) vs Chat Completions (``openai``)."""
    entry = match_host_entry(endpoint)
    if entry is not None:
        return entry.transport
    if is_doubao_mode(api_mode):
        return "doubao"
    return "openai"


def normalize_api_mode_for_select(mode: str, endpoint: str = "") -> str:
    """Map stored api_mode + endpoint to UI select value (``doubao`` | ``openai``)."""
    transport = resolve_api_transport(endpoint, mode)
    return "doubao" if transport == "doubao" else "openai"


def provider_rules_for_api() -> dict:
    """Structured host rules for web settings UI (single source of truth)."""
    return {
        "host_entries": [
            {
                "fragment": entry.fragment,
                "provider_id": entry.provider_id,
                "transport": entry.transport,
            }
            for entry in HOST_ENTRIES
        ],
        "default_provider_id": DEFAULT_PROVIDER_ID,
        "editable_api_mode_provider_ids": [
            spec.id for spec in PROVIDERS if not spec.lock_mode
        ],
    }


def resolve_provider_for_ui(endpoint: str, api_mode: str = "") -> dict:
    """Resolve provider_id, transport, and api_mode_select for settings UI."""
    provider_id = guess_provider_from_endpoint(endpoint, api_mode)
    transport = resolve_api_transport(endpoint, api_mode)
    return {
        "provider_id": provider_id,
        "transport": transport,
        "api_mode_select": normalize_api_mode_for_select(api_mode, endpoint),
    }


# OpenRouter recommends Referer/Title for rate-limit priority; applied only when host matches.
_OPENROUTER_REFERER = "https://github.com/PEPETII/danmuai"
_OPENROUTER_APP_TITLE = "DanmuAI"


def provider_extra_headers(endpoint: str) -> dict[str, str]:
    """Optional provider-specific HTTP headers (e.g. OpenRouter Referer/Title)."""
    normalized = normalize_endpoint(endpoint).lower()
    if "openrouter.ai" in normalized:
        return {
            "HTTP-Referer": _OPENROUTER_REFERER,
            "X-Title": _OPENROUTER_APP_TITLE,
        }
    return {}
