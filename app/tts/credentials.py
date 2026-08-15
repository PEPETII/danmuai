"""Provider-scoped credential contracts.

Persistence is intentionally not implemented here.  The application can adapt
its existing encrypted store to ``CredentialStore`` without making secrets part
of catalog or request objects.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from app.tts.types import AuthDescriptor, TtsAuthError

MASKED_CREDENTIAL = "********"


class CredentialStore(Protocol):
    def get(self, provider_id: str) -> Mapping[str, str]: ...


class InMemoryCredentialStore:
    """Small adapter useful for tests and composition roots; not persistence."""

    def __init__(self) -> None:
        self._values: dict[str, dict[str, str]] = {}

    def get(self, provider_id: str) -> Mapping[str, str]:
        return dict(self._values.get(provider_id.strip(), {}))

    def set(self, provider_id: str, values: Mapping[str, str]) -> None:
        self._values[provider_id.strip()] = {
            str(key): str(value) for key, value in values.items() if str(value).strip()
        }

    def delete(self, provider_id: str) -> None:
        self._values.pop(provider_id.strip(), None)


class CredentialResolver:
    """Resolve credentials by provider, with optional per-call overrides."""

    def __init__(self, store: CredentialStore | Mapping[str, Mapping[str, str]] | None = None):
        self._store = store if store is not None else InMemoryCredentialStore()

    def resolve(
        self,
        provider_id: str,
        override: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        if override is not None:
            return {str(key): str(value) for key, value in override.items() if str(value).strip()}
        if isinstance(self._store, Mapping):
            values = self._store.get(provider_id, {})
        else:
            values = self._store.get(provider_id)
        return {str(key): str(value) for key, value in values.items() if str(value).strip()}

    def require(self, provider_id: str, auth: AuthDescriptor) -> dict[str, str]:
        values = self.resolve(provider_id)
        missing = [field.id for field in auth.required_fields if not values.get(field.id, "").strip()]
        if missing:
            raise TtsAuthError(f"Missing credentials for TTS provider: {', '.join(missing)}")
        return values

    def masked(self, provider_id: str, auth: AuthDescriptor | None = None) -> dict[str, str]:
        values = self.resolve(provider_id)
        secret_fields = (
            {field.id for field in auth.fields if field.secret}
            if auth
            else set(values)
        )
        return {
            key: MASKED_CREDENTIAL if key in secret_fields else value
            for key, value in values.items()
        }


def mask_credentials(
    values: Mapping[str, str],
    *,
    secret_fields: set[str] | frozenset[str] | None = None,
) -> dict[str, str]:
    fields = secret_fields if secret_fields is not None else set(values)
    return {
        str(key): MASKED_CREDENTIAL if str(key) in fields else str(value)
        for key, value in values.items()
    }


__all__ = [
    "CredentialResolver",
    "CredentialStore",
    "InMemoryCredentialStore",
    "MASKED_CREDENTIAL",
    "mask_credentials",
]
