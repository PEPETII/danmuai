"""Abstract/provider-neutral TTS adapter contract."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Protocol, runtime_checkable

from app.tts.types import (
    ProviderDescriptor,
    TtsAuthError,
    TtsRequest,
    TtsResult,
    VoiceDescriptor,
)


@runtime_checkable
class TtsProvider(Protocol):
    @property
    def descriptor(self) -> ProviderDescriptor: ...

    def validate_credentials(self, credentials: Mapping[str, str]) -> None: ...

    def list_voices(
        self,
        credentials: Mapping[str, str],
        *,
        model_id: str,
        force_refresh: bool = False,
    ) -> list[VoiceDescriptor]: ...

    def synthesize(
        self,
        credentials: Mapping[str, str],
        request: TtsRequest,
        *,
        timeout_sec: float = 60.0,
    ) -> TtsResult: ...


class BaseTtsProvider(ABC):
    """Convenience base for adapters; vendor payload logic belongs in subclasses."""

    def __init__(self, descriptor: ProviderDescriptor) -> None:
        self._descriptor = descriptor

    @property
    def descriptor(self) -> ProviderDescriptor:
        return self._descriptor

    def validate_credentials(self, credentials: Mapping[str, str]) -> None:
        missing = [
            field.id
            for field in self.descriptor.auth.required_fields
            if not str(credentials.get(field.id, "")).strip()
        ]
        if missing:
            raise TtsAuthError(
                f"Missing credentials for TTS provider: {', '.join(missing)}"
            )

    def list_voices(
        self,
        credentials: Mapping[str, str],
        *,
        model_id: str,
        force_refresh: bool = False,
    ) -> list[VoiceDescriptor]:
        del credentials, force_refresh
        for model in self.descriptor.models:
            if model.id == model_id:
                return list(model.voices)
        return []

    @abstractmethod
    def synthesize(
        self,
        credentials: Mapping[str, str],
        request: TtsRequest,
        *,
        timeout_sec: float = 60.0,
    ) -> TtsResult:
        raise NotImplementedError


__all__ = ["BaseTtsProvider", "TtsProvider"]
