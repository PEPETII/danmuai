"""Provider-neutral TTS domain types and error taxonomy."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, ClassVar


class TtsErrorCode(StrEnum):
    """Stable categories used by UI and logging boundaries."""

    AUTH = "auth"
    RATE_LIMIT = "rate_limit"
    QUOTA = "quota"
    INVALID_VOICE = "invalid_voice"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    PROVIDER_NETWORK = "provider_network"
    PROVIDER_RESPONSE = "provider_response"
    AUDIO_DECODE = "audio_decode"
    CONFIGURATION = "configuration"


TtsErrorKind = TtsErrorCode


class TtsError(Exception):
    """Base class for errors that can safely cross the TTS service boundary."""

    code: ClassVar[TtsErrorCode] = TtsErrorCode.PROVIDER_RESPONSE
    default_message: ClassVar[str] = "TTS provider request failed"

    def __init__(
        self,
        message: str | None = None,
        *,
        provider_request_id: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        self.provider_request_id = provider_request_id
        self.cause = cause
        super().__init__(message or self.default_message)

    @property
    def user_message(self) -> str:
        return str(self)


class TtsAuthError(TtsError):
    code = TtsErrorCode.AUTH
    default_message = "TTS credentials are invalid or missing"


class TtsRateLimitError(TtsError):
    code = TtsErrorCode.RATE_LIMIT
    default_message = "TTS provider rate limit exceeded"


class TtsQuotaError(TtsError):
    code = TtsErrorCode.QUOTA
    default_message = "TTS provider quota is unavailable"


class TtsInvalidVoiceError(TtsError, ValueError):
    code = TtsErrorCode.INVALID_VOICE
    default_message = "The selected TTS voice is unavailable"


class TtsUnsupportedCapabilityError(TtsError, ValueError):
    code = TtsErrorCode.UNSUPPORTED_CAPABILITY
    default_message = "The selected TTS model does not support this capability"

    def __init__(self, capability: str, message: str | None = None) -> None:
        self.capability = capability
        super().__init__(message or f"TTS capability is unsupported: {capability}")


class TtsProviderNetworkError(TtsError):
    code = TtsErrorCode.PROVIDER_NETWORK
    default_message = "TTS provider is temporarily unavailable"


class TtsProviderResponseError(TtsError):
    code = TtsErrorCode.PROVIDER_RESPONSE
    default_message = "TTS provider returned an invalid response"


class TtsAudioDecodeError(TtsError, ValueError):
    code = TtsErrorCode.AUDIO_DECODE
    default_message = "TTS audio data could not be decoded"


class TtsConfigurationError(TtsError, ValueError):
    code = TtsErrorCode.CONFIGURATION
    default_message = "TTS configuration is invalid"


def _status_code(error: BaseException) -> int | None:
    response = getattr(error, "response", None)
    value = getattr(response, "status_code", None)
    if value is None:
        value = getattr(error, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def classify_tts_error(error: BaseException) -> TtsError:
    """Convert provider/library failures to the stable TTS error taxonomy.

    The function deliberately uses duck-typed HTTP status attributes, so the
    core does not depend on a particular HTTP client or provider SDK.
    """

    if isinstance(error, TtsError):
        return error

    status = _status_code(error)
    if status in (401, 403):
        return TtsAuthError(cause=error)
    if status == 402:
        return TtsQuotaError(cause=error)
    if status == 429:
        return TtsRateLimitError(cause=error)
    if status in (408, 504):
        return TtsProviderNetworkError(cause=error)
    if status is not None and 400 <= status < 500:
        return TtsProviderResponseError(cause=error)
    if status is not None and status >= 500:
        return TtsProviderNetworkError(cause=error)
    if isinstance(error, (TimeoutError, ConnectionError, OSError)):
        return TtsProviderNetworkError(cause=error)
    return TtsProviderResponseError(cause=error)


@dataclass(frozen=True)
class TtsRequest:
    """The only synthesis request shape accepted by ``TtsManager``."""

    text: str
    provider_id: str
    model_id: str
    voice_id: str | None = None
    style_prompt: str | None = None
    emotion: str | None = None
    speed: float | None = None
    pitch: float | None = None
    volume: float | None = None
    output_format: str = "wav"
    streaming: bool = False


@dataclass(frozen=True)
class TtsResult:
    """Provider output before the manager's audio normalization step."""

    audio_bytes: bytes
    audio_format: str
    sample_rate: int | None = None
    provider_request_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.audio_bytes, bytes):
            object.__setattr__(self, "audio_bytes", bytes(self.audio_bytes))
        object.__setattr__(self, "audio_format", self.audio_format.strip().lower())


class VoiceSource(StrEnum):
    STATIC_CATALOG = "static_catalog"
    REMOTE_CATALOG = "remote_catalog"
    CACHED_REMOTE = "cached_remote"
    CUSTOM_ID = "custom_id"
    CLONED_VOICE = "cloned_voice"
    DESIGNED_VOICE = "designed_voice"


@dataclass(frozen=True)
class VoiceDescriptor:
    id: str
    name: str
    gender: str | None = None
    age_group: str | None = None
    languages: tuple[str, ...] = ()
    emotions: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    preview_url: str | None = None
    source: VoiceSource | str = VoiceSource.STATIC_CATALOG

    def __post_init__(self) -> None:
        for field_name in ("languages", "emotions", "tags"):
            object.__setattr__(self, field_name, tuple(getattr(self, field_name)))


@dataclass(frozen=True)
class PricingDescriptor:
    """Pricing metadata shape; an empty instance means unknown, not free."""

    kind: str = "unknown"
    currency: str | None = None
    amount: float | None = None
    unit: str | None = None
    display: str | None = None
    note: str | None = None
    verified_at: str | None = None
    source: str | None = None


Pricing = PricingDescriptor


@dataclass(frozen=True)
class AuthFieldDescriptor:
    id: str
    label: str
    required: bool = True
    secret: bool = True
    placeholder: str | None = None


@dataclass(frozen=True)
class AuthDescriptor:
    fields: tuple[AuthFieldDescriptor, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "fields", tuple(self.fields))

    @property
    def required_fields(self) -> tuple[AuthFieldDescriptor, ...]:
        return tuple(field for field in self.fields if field.required)


@dataclass(frozen=True)
class TtsCapabilities:
    streaming: bool = False
    style_prompt: bool = False
    emotion: bool = False
    speed: bool = False
    pitch: bool = False
    volume: bool = False
    voice_list: bool = False
    voice_preview: bool = False
    custom_voice_id: bool = False
    voice_clone: bool = False
    voice_design: bool = False
    output_formats: frozenset[str] = field(default_factory=lambda: frozenset({"wav"}))

    def __post_init__(self) -> None:
        formats = frozenset(str(value).strip().lower() for value in self.output_formats)
        object.__setattr__(self, "output_formats", formats)


@dataclass(frozen=True)
class ModelDescriptor:
    id: str
    label: str
    recommended: bool = False
    tags: tuple[str, ...] = ()
    transport: str = "http"
    capabilities: TtsCapabilities = field(default_factory=TtsCapabilities)
    pricing: PricingDescriptor = field(default_factory=PricingDescriptor)
    voices: tuple[VoiceDescriptor, ...] = ()
    status: str = "active"

    def __post_init__(self) -> None:
        object.__setattr__(self, "tags", tuple(self.tags))
        object.__setattr__(self, "voices", tuple(self.voices))


@dataclass(frozen=True)
class ProviderDescriptor:
    id: str
    label: str
    auth: AuthDescriptor = field(default_factory=AuthDescriptor)
    models: tuple[ModelDescriptor, ...] = ()
    status: str = "active"

    def __post_init__(self) -> None:
        object.__setattr__(self, "models", tuple(self.models))

    @property
    def auth_schema(self) -> tuple[AuthFieldDescriptor, ...]:
        return self.auth.fields


def descriptor_to_dict(descriptor: Any) -> dict[str, Any]:
    """Serialize descriptors without exposing credentials or provider objects."""

    if isinstance(descriptor, VoiceDescriptor):
        return {
            "id": descriptor.id,
            "name": descriptor.name,
            "gender": descriptor.gender,
            "age_group": descriptor.age_group,
            "languages": list(descriptor.languages),
            "emotions": list(descriptor.emotions),
            "tags": list(descriptor.tags),
            "preview_url": descriptor.preview_url,
            "source": str(descriptor.source),
        }
    if isinstance(descriptor, PricingDescriptor):
        return {
            "kind": descriptor.kind,
            "currency": descriptor.currency,
            "amount": descriptor.amount,
            "unit": descriptor.unit,
            "display": descriptor.display,
            "note": descriptor.note,
            "verified_at": descriptor.verified_at,
            "source": descriptor.source,
        }
    if isinstance(descriptor, AuthFieldDescriptor):
        return {
            "id": descriptor.id,
            "label": descriptor.label,
            "required": descriptor.required,
            "secret": descriptor.secret,
            "placeholder": descriptor.placeholder,
        }
    if isinstance(descriptor, AuthDescriptor):
        return {"fields": [descriptor_to_dict(field) for field in descriptor.fields]}
    if isinstance(descriptor, TtsCapabilities):
        return {
            name: value for name, value in descriptor.__dict__.items()
            if name != "output_formats"
        } | {"output_formats": sorted(descriptor.output_formats)}
    if isinstance(descriptor, ModelDescriptor):
        return {
            "id": descriptor.id,
            "label": descriptor.label,
            "recommended": descriptor.recommended,
            "tags": list(descriptor.tags),
            "transport": descriptor.transport,
            "capabilities": descriptor_to_dict(descriptor.capabilities),
            "pricing": descriptor_to_dict(descriptor.pricing),
            "voices": [descriptor_to_dict(voice) for voice in descriptor.voices],
            "status": descriptor.status,
        }
    if isinstance(descriptor, ProviderDescriptor):
        return {
            "id": descriptor.id,
            "label": descriptor.label,
            "auth_schema": descriptor_to_dict(descriptor.auth),
            "models": [descriptor_to_dict(model) for model in descriptor.models],
            "status": descriptor.status,
        }
    raise TypeError(f"unsupported TTS descriptor: {type(descriptor)!r}")
