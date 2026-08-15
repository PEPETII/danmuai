"""Provider-neutral TTS orchestration and request validation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Callable

from app.tts.audio import AudioNormalizer
from app.tts.capabilities import CapabilityResolver
from app.tts.catalog import TtsCatalog, VoiceCache
from app.tts.credentials import CredentialResolver
from app.tts.registry import ProviderRegistry
from app.tts.types import (
    ModelDescriptor,
    TtsConfigurationError,
    TtsInvalidVoiceError,
    TtsProviderResponseError,
    TtsRequest,
    TtsResult,
    VoiceDescriptor,
    VoiceSource,
    classify_tts_error,
)


class TtsManager:
    """Validate a unified request, dispatch one registered provider, normalize audio."""

    def __init__(
        self,
        registry: ProviderRegistry,
        catalog: TtsCatalog | None = None,
        credential_resolver: CredentialResolver | None = None,
        voice_cache: VoiceCache | None = None,
        audio_normalizer: AudioNormalizer | None = None,
        *,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self.registry = registry
        self.catalog = catalog or TtsCatalog()
        for provider in registry:
            if self.catalog.get_provider(provider.descriptor.id) is None:
                self.catalog.register_provider(provider.descriptor)
        self.credentials = credential_resolver or CredentialResolver()
        self.voice_cache = voice_cache or VoiceCache()
        self.audio_normalizer = audio_normalizer or AudioNormalizer()
        self.capabilities = CapabilityResolver()
        self._clock = clock

    def validate_request(self, request: TtsRequest) -> tuple[object, ModelDescriptor]:
        provider = self.registry.require(request.provider_id)
        provider_descriptor = provider.descriptor
        if request.provider_id.strip() != provider_descriptor.id:
            raise TtsConfigurationError("TTS request provider does not match its descriptor")
        model = self.catalog.require_model(provider_descriptor.id, request.model_id)
        self.capabilities.validate_request(request, model.capabilities)
        self._validate_voice(request, model)
        if not request.text or not request.text.strip():
            raise TtsConfigurationError("TTS text must not be empty")
        return provider, model

    def _validate_voice(self, request: TtsRequest, model: ModelDescriptor) -> None:
        voice_id = (request.voice_id or "").strip()
        if not voice_id:
            return
        if any(voice.id == voice_id for voice in model.voices):
            return
        cached = self.voice_cache.get(
            request.provider_id,
            request.model_id,
            fresh_only=False,
        )
        if cached is not None and any(voice.id == voice_id for voice in cached.voices):
            return
        if model.capabilities.custom_voice_id:
            return
        # With dynamic voice listing and no loaded source, the provider remains
        # authoritative; rejecting here would recreate a static whitelist.
        if model.capabilities.voice_list and not model.voices and cached is None:
            return
        raise TtsInvalidVoiceError(f"Unknown TTS voice: {voice_id}")

    def synthesize(
        self,
        request: TtsRequest,
        *,
        credentials: Mapping[str, str] | None = None,
        timeout_sec: float = 60.0,
    ) -> TtsResult:
        provider, _model = self.validate_request(request)
        try:
            provider_credentials = (
                dict(credentials)
                if credentials is not None
                else self.credentials.resolve(request.provider_id)
            )
            provider.validate_credentials(provider_credentials)
            result = provider.synthesize(
                provider_credentials,
                request,
                timeout_sec=timeout_sec,
            )
            if not isinstance(result, TtsResult):
                raise TtsProviderResponseError("TTS provider did not return TtsResult")
            return self.audio_normalizer.normalize(result)
        except Exception as exc:
            classified = classify_tts_error(exc)
            if classified is exc:
                raise
            raise classified from exc

    def list_voices(
        self,
        provider_id: str,
        model_id: str,
        *,
        credentials: Mapping[str, str] | None = None,
        force_refresh: bool = False,
    ) -> list[VoiceDescriptor]:
        provider = self.registry.require(provider_id)
        model = self.catalog.require_model(provider_id, model_id)
        if not model.capabilities.voice_list:
            return list(model.voices)
        if not force_refresh:
            cached = self.voice_cache.get(provider_id, model_id)
            if cached is not None:
                return list(cached.voices)
        values = (
            dict(credentials)
            if credentials is not None
            else self.credentials.resolve(provider_id)
        )
        try:
            provider.validate_credentials(values)
            voices = list(
                provider.list_voices(
                    values,
                    model_id=model_id,
                    force_refresh=force_refresh,
                )
            )
            normalized = [
                voice
                if voice.source != VoiceSource.STATIC_CATALOG
                else replace(voice, source=VoiceSource.REMOTE_CATALOG)
                for voice in voices
            ]
            self.voice_cache.put(
                provider_id,
                model_id,
                normalized,
            )
            return normalized
        except Exception as exc:
            stale = self.voice_cache.get(provider_id, model_id, fresh_only=False)
            if stale is not None:
                return list(stale.voices)
            if model.voices:
                return list(model.voices)
            raise classify_tts_error(exc) from exc


__all__ = ["TtsManager"]
