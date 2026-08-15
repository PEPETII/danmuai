"""Provider/model catalog and dynamic voice cache structures."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Iterable

from app.tts.types import (
    ModelDescriptor,
    ProviderDescriptor,
    TtsConfigurationError,
    VoiceDescriptor,
    VoiceSource,
    descriptor_to_dict,
)


@dataclass(frozen=True)
class VoiceCacheEntry:
    provider_id: str
    model_id: str
    voices: tuple[VoiceDescriptor, ...]
    cached_at: float
    ttl_sec: float = 3600.0
    source: VoiceSource | str = VoiceSource.CACHED_REMOTE

    def __post_init__(self) -> None:
        object.__setattr__(self, "voices", tuple(self.voices))

    def is_fresh(self, now: float | None = None) -> bool:
        current = time.monotonic() if now is None else now
        return current <= self.cached_at + max(0.0, self.ttl_sec)


class VoiceCache:
    """Thread-safe, provider/model-scoped cache with stale fallback support."""

    def __init__(self, *, default_ttl_sec: float = 3600.0) -> None:
        self.default_ttl_sec = max(0.0, default_ttl_sec)
        self._entries: dict[tuple[str, str], VoiceCacheEntry] = {}
        self._lock = threading.RLock()

    def get(self, provider_id: str, model_id: str, *, fresh_only: bool = True) -> VoiceCacheEntry | None:
        key = ((provider_id or "").strip(), (model_id or "").strip())
        with self._lock:
            entry = self._entries.get(key)
        if entry is None or (fresh_only and not entry.is_fresh()):
            return None
        return entry

    def put(
        self,
        provider_id: str,
        model_id: str,
        voices: Iterable[VoiceDescriptor],
        *,
        ttl_sec: float | None = None,
        cached_at: float | None = None,
    ) -> VoiceCacheEntry:
        entry = VoiceCacheEntry(
            provider_id=(provider_id or "").strip(),
            model_id=(model_id or "").strip(),
            voices=tuple(voices),
            cached_at=time.monotonic() if cached_at is None else cached_at,
            ttl_sec=self.default_ttl_sec if ttl_sec is None else max(0.0, ttl_sec),
        )
        with self._lock:
            self._entries[(entry.provider_id, entry.model_id)] = entry
        return entry

    def clear(self, provider_id: str | None = None, model_id: str | None = None) -> None:
        with self._lock:
            if provider_id is None and model_id is None:
                self._entries.clear()
                return
            provider = (provider_id or "").strip()
            model = (model_id or "").strip()
            for key in tuple(self._entries):
                if (provider and key[0] != provider) or (model and key[1] != model):
                    continue
                self._entries.pop(key, None)


class TtsCatalog:
    """Mutable composition-root catalog; it contains no built-in provider data."""

    def __init__(self, providers: Iterable[ProviderDescriptor] = ()) -> None:
        self._providers: dict[str, ProviderDescriptor] = {}
        for provider in providers:
            self.register_provider(provider)

    def register_provider(self, provider: ProviderDescriptor, *, replace: bool = False) -> None:
        provider_id = (provider.id or "").strip()
        if not provider_id:
            raise TtsConfigurationError("TTS provider descriptor must have an id")
        if provider_id in self._providers and not replace:
            raise TtsConfigurationError(f"TTS catalog provider already exists: {provider_id}")
        self._providers[provider_id] = provider

    def get_provider(self, provider_id: str) -> ProviderDescriptor | None:
        return self._providers.get((provider_id or "").strip())

    def require_provider(self, provider_id: str) -> ProviderDescriptor:
        provider = self.get_provider(provider_id)
        if provider is None:
            raise TtsConfigurationError(f"Unknown TTS catalog provider: {(provider_id or '').strip()}")
        return provider

    def require_model(self, provider_id: str, model_id: str) -> ModelDescriptor:
        provider = self.require_provider(provider_id)
        model_key = (model_id or "").strip()
        for model in provider.models:
            if model.id == model_key:
                return model
        raise TtsConfigurationError(
            f"Unknown TTS model '{model_key}' for provider '{provider.id}'"
        )

    def voices_for_model(self, provider_id: str, model_id: str) -> tuple[VoiceDescriptor, ...]:
        return self.require_model(provider_id, model_id).voices

    def require_voice(self, provider_id: str, model_id: str, voice_id: str) -> VoiceDescriptor:
        voice_key = (voice_id or "").strip()
        for voice in self.voices_for_model(provider_id, model_id):
            if voice.id == voice_key:
                return voice
        raise TtsConfigurationError(
            f"Unknown TTS voice '{voice_key}' for model '{(model_id or '').strip()}'"
        )

    def provider_ids(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def to_list(self) -> list[dict[str, object]]:
        return [descriptor_to_dict(provider) for provider in self._providers.values()]


ModelCatalog = TtsCatalog


__all__ = ["ModelCatalog", "TtsCatalog", "VoiceCache", "VoiceCacheEntry"]
