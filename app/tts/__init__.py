"""TTS V2 core framework.

This package contains provider-neutral contracts only.  Concrete provider
adapters and official catalog entries are intentionally kept out of the core.
"""

from app.tts.audio import AudioNormalizer, normalize_audio, normalize_tts_result, pcm_to_wav
from app.tts.capabilities import CapabilityResolver
from app.tts.catalog import ModelCatalog, TtsCatalog, VoiceCache, VoiceCacheEntry
from app.tts.credentials import (
    CredentialResolver,
    CredentialStore,
    InMemoryCredentialStore,
    mask_credentials,
)
from app.tts.manager import TtsManager
from app.tts.providers.base import BaseTtsProvider, TtsProvider
from app.tts.registry import ProviderRegistry
from app.tts.types import (
    AuthDescriptor,
    AuthFieldDescriptor,
    ModelDescriptor,
    Pricing,
    PricingDescriptor,
    ProviderDescriptor,
    TtsAudioDecodeError,
    TtsAuthError,
    TtsCapabilities,
    TtsConfigurationError,
    TtsError,
    TtsErrorCode,
    TtsErrorKind,
    TtsInvalidVoiceError,
    TtsProviderNetworkError,
    TtsProviderResponseError,
    TtsQuotaError,
    TtsRateLimitError,
    TtsRequest,
    TtsResult,
    TtsUnsupportedCapabilityError,
    VoiceDescriptor,
    VoiceSource,
    classify_tts_error,
)

__all__ = [
    "AudioNormalizer",
    "AuthDescriptor",
    "AuthFieldDescriptor",
    "BaseTtsProvider",
    "CapabilityResolver",
    "CredentialResolver",
    "CredentialStore",
    "InMemoryCredentialStore",
    "ModelCatalog",
    "ModelDescriptor",
    "Pricing",
    "PricingDescriptor",
    "ProviderDescriptor",
    "ProviderRegistry",
    "TtsAudioDecodeError",
    "TtsAuthError",
    "TtsCapabilities",
    "TtsCatalog",
    "TtsConfigurationError",
    "TtsError",
    "TtsErrorCode",
    "TtsErrorKind",
    "TtsInvalidVoiceError",
    "TtsManager",
    "TtsProviderNetworkError",
    "TtsProviderResponseError",
    "TtsQuotaError",
    "TtsRateLimitError",
    "TtsRequest",
    "TtsResult",
    "TtsUnsupportedCapabilityError",
    "TtsProvider",
    "VoiceCache",
    "VoiceCacheEntry",
    "VoiceDescriptor",
    "VoiceSource",
    "classify_tts_error",
    "mask_credentials",
    "normalize_audio",
    "normalize_tts_result",
    "pcm_to_wav",
]
