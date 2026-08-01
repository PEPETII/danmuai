"""Usage token normalization facade (Batch 3)."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from app.providers.capabilities import ProviderCapabilities


@dataclass(frozen=True)
class NormalizedUsage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    audio_tokens: int | None = None
    raw_usage: dict[str, Any] | None = None


def _number(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_usage_details(
    usage: dict | None,
    *,
    caps: ProviderCapabilities | None = None,
    adapter=None,
    usage_token_style: str | None = None,
) -> NormalizedUsage:
    if not isinstance(usage, dict) or not usage:
        return NormalizedUsage()
    style = usage_token_style or getattr(caps, "usage_token_style", "openai")
    input_value = usage.get("input_tokens") if style == "dashscope" else usage.get("prompt_tokens")
    output_value = usage.get("output_tokens") if style == "dashscope" else usage.get("completion_tokens")
    if input_value is None:
        input_value = usage.get("input_tokens")
    if output_value is None:
        output_value = usage.get("output_tokens")
    prompt_details = usage.get("prompt_tokens_details") or usage.get("input_token_details") or {}
    completion_details = usage.get("completion_tokens_details") or usage.get("output_token_details") or {}
    return NormalizedUsage(
        input_tokens=_number(input_value),
        output_tokens=_number(output_value),
        total_tokens=_number(usage.get("total_tokens")),
        cached_tokens=_number(prompt_details.get("cached_tokens") if isinstance(prompt_details, dict) else None),
        reasoning_tokens=_number(completion_details.get("reasoning_tokens") if isinstance(completion_details, dict) else None),
        audio_tokens=_number((prompt_details.get("audio_tokens") if isinstance(prompt_details, dict) else None) or (completion_details.get("audio_tokens") if isinstance(completion_details, dict) else None)),
        raw_usage=deepcopy(usage),
    )


def normalize_usage_tokens(
    usage: dict | None,
    *,
    caps: ProviderCapabilities,
    adapter=None,
) -> tuple[int, int]:
    """Normalize provider usage dict to ``(input_tokens, output_tokens)``."""
    details = normalize_usage_details(usage, caps=caps, adapter=adapter)
    return details.input_tokens or 0, details.output_tokens or 0


def normalize_usage_by_style(
    usage: dict | None,
    *,
    usage_token_style: str = "openai",
) -> tuple[int, int]:
    caps = ProviderCapabilities(usage_token_style=usage_token_style)
    return normalize_usage_tokens(usage, caps=caps)
