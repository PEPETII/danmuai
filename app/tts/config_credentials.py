"""Read TTS provider credentials from ConfigStore (shared by读弹幕与虚拟主播)."""

from __future__ import annotations

from app.application.config_service import MASKED_API_KEY
from app.tts_providers import TTS_PROVIDER_MIMO, canonical_tts_provider_id, get_tts_manager


def stored_tts_credentials(config, provider: str) -> dict[str, str]:
    """读取 provider-scoped 凭据；旧的全局 TTS key 仅作为兼容回退。"""

    canonical = canonical_tts_provider_id(provider) or TTS_PROVIDER_MIMO
    credentials: dict[str, str] = {}
    try:
        descriptor = get_tts_manager().catalog.get_provider(canonical)
        fields = descriptor.auth.fields if descriptor is not None else ()
        for field in fields:
            value = config.get_tts_secret(canonical, field.id)
            if value:
                credentials[field.id] = value
    except (AttributeError, OSError, ValueError):
        pass
    if not credentials.get("api_key"):
        try:
            legacy_key = config.get_tts_api_key()
        except AttributeError:
            legacy_key = ""
        if legacy_key:
            credentials["api_key"] = legacy_key
    return credentials


def masked_tts_credentials(config, provider: str) -> dict[str, str]:
    canonical = canonical_tts_provider_id(provider) or TTS_PROVIDER_MIMO
    result: dict[str, str] = {}
    try:
        descriptor = get_tts_manager().catalog.get_provider(canonical)
        fields = descriptor.auth.fields if descriptor is not None else ()
        for field in fields:
            value = config.get_tts_secret_masked(canonical, field.id)
            if value:
                result[field.id] = value
    except (AttributeError, OSError, ValueError):
        pass
    if canonical == TTS_PROVIDER_MIMO and not result.get("api_key"):
        try:
            if config.get_tts_api_key():
                result["api_key"] = MASKED_API_KEY
        except AttributeError:
            pass
    return result


__all__ = ["masked_tts_credentials", "stored_tts_credentials"]
