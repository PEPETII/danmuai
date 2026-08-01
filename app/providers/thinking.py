"""Per-provider thinking mode request body injection.

Official parameter shapes (see completion report for doc URLs):
- ``thinking_type``: ``thinking: {"type": "enabled"|"disabled"}``
- ``enable_thinking``: ``enable_thinking: true|false``
- ``reasoning_effort_flat``: ``reasoning_effort: "low"|"medium"|"high"``
- ``reasoning_object``: ``reasoning: {"effort": "medium"}``
- ``reasoning_enabled``: ``reasoning: {"enabled": false}``
- ``chat_template_kwargs``: ``chat_template_kwargs: {"enable_thinking": false}``
- ``always_on``: effort-only adjustments (no disable)
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.providers.capabilities import ProviderCapabilities

_REASONING_EFFORT_VALUES = frozenset({"low", "medium", "high"})


def apply_thinking_mode(
    data: dict,
    *,
    enabled: bool,
    caps: ProviderCapabilities,
    effort: str | None = None,
) -> None:
    """Set or clear thinking-related fields on an OpenAI-compat or probe body."""
    _clear_thinking_fields(data)
    style = caps.thinking_param_style
    if style == "none":
        return
    if style == "thinking_type":
        data["thinking"] = {"type": "enabled" if enabled else "disabled"}
        return
    if style == "enable_thinking":
        data["enable_thinking"] = bool(enabled)
        return
    if style == "reasoning_effort_flat":
        if enabled:
            data["reasoning_effort"] = _normalize_effort(effort)
        return
    if style == "reasoning_object":
        if enabled:
            data["reasoning"] = {"effort": _normalize_effort(effort)}
        else:
            data["reasoning"] = {"enabled": False}
        return
    if style == "reasoning_enabled":
        data["reasoning"] = {"enabled": bool(enabled)}
        return
    if style == "chat_template_kwargs":
        data["chat_template_kwargs"] = {"enable_thinking": bool(enabled)}
        return
    if style == "always_on":
        data["reasoning_effort"] = _normalize_effort(effort or "high")


def apply_thinking_disabled(data: dict, *, caps: ProviderCapabilities) -> None:
    """Force thinking off using the provider's native parameter shape."""
    if caps.thinking_param_style == "always_on":
        return
    apply_thinking_mode(data, enabled=False, caps=caps)


def _clear_thinking_fields(data: dict) -> None:
    for key in (
        "thinking",
        "enable_thinking",
        "reasoning_effort",
        "reasoning",
        "chat_template_kwargs",
    ):
        data.pop(key, None)


def _normalize_effort(effort: str | None) -> str:
    value = (effort or "medium").strip().lower()
    if value not in _REASONING_EFFORT_VALUES:
        return "medium"
    return value

