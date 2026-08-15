"""Explicit TTS provider registry with no implicit provider fallback."""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from app.tts.providers.base import TtsProvider
from app.tts.types import ProviderDescriptor, TtsConfigurationError


class ProviderRegistry:
    """Own provider instances by stable provider ID."""

    def __init__(self, providers: Iterable[TtsProvider] = ()) -> None:
        self._providers: dict[str, TtsProvider] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: TtsProvider, *, replace: bool = False) -> None:
        descriptor = provider.descriptor
        provider_id = (descriptor.id or "").strip()
        if not provider_id:
            raise TtsConfigurationError("TTS provider descriptor must have an id")
        if provider_id in self._providers and not replace:
            raise TtsConfigurationError(f"TTS provider already registered: {provider_id}")
        self._providers[provider_id] = provider

    def unregister(self, provider_id: str) -> TtsProvider | None:
        return self._providers.pop((provider_id or "").strip(), None)

    def get(self, provider_id: str) -> TtsProvider | None:
        return self._providers.get((provider_id or "").strip())

    def require(self, provider_id: str) -> TtsProvider:
        provider = self.get(provider_id)
        if provider is None:
            raise TtsConfigurationError(f"Unknown TTS provider: {(provider_id or '').strip()}")
        return provider

    def ids(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def descriptors(self) -> tuple[ProviderDescriptor, ...]:
        return tuple(provider.descriptor for provider in self._providers.values())

    def __contains__(self, provider_id: object) -> bool:
        return isinstance(provider_id, str) and provider_id.strip() in self._providers

    def __iter__(self) -> Iterator[TtsProvider]:
        return iter(self._providers.values())


__all__ = ["ProviderRegistry"]
