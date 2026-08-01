"""Usage token normalization facade (Batch 3)."""

from __future__ import annotations

from app.providers.adapters.default_openai import DefaultOpenAIAdapter
from app.providers.capabilities import ProviderCapabilities


def normalize_usage_tokens(
    usage: dict | None,
    *,
    caps: ProviderCapabilities,
    adapter=None,
) -> tuple[int, int]:
    """Normalize provider usage dict to ``(input_tokens, output_tokens)``."""
    if adapter is None:
        adapter = DefaultOpenAIAdapter()
    return adapter.normalize_usage(usage, caps=caps)


def normalize_usage_by_style(
    usage: dict | None,
    *,
    usage_token_style: str = "openai",
) -> tuple[int, int]:
    caps = ProviderCapabilities(usage_token_style=usage_token_style)
    return normalize_usage_tokens(usage, caps=caps)
