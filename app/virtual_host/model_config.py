"""虚拟主播独立视觉/TTS 模型选择与解析（不拥有 provider 实现）。

只保存对现有 custom_models / TtsManager 所选模型的引用；解析与 adapter 注入
由外围运行时完成，``VirtualHostSession`` 不持有模型。
"""

from __future__ import annotations

from typing import Any

from app.model_catalog import lookup_catalog_model
from app.model_providers import (
    find_custom_model_profile,
    is_model_config_complete,
    normalize_endpoint,
    normalize_mode,
    resolve_api_transport,
)
from app.providers.capabilities import get_capabilities_for_endpoint
from app.providers.capability_resolver import resolve_capabilities
from app.tts.types import ModelDescriptor, TtsCapabilities, TtsRequest
from app.tts_catalog import default_voice_for_provider
from app.tts_providers import canonical_tts_model_id, canonical_tts_provider_id, get_tts_manager
from app.virtual_host.audio import TtsBinding, resolve_tts_binding

VISION_MODEL_KEY = "virtual_host_vision_model_id"
TTS_PROVIDER_KEY = "virtual_host_tts_provider"
TTS_MODEL_KEY = "virtual_host_tts_model_id"
TTS_OPTION_SEP = "|"


def _profile_label(profile: dict[str, Any]) -> str:
    model_id = (profile.get("default_model_id") or "").strip()
    name = (profile.get("name") or "").strip()
    return name or model_id


def custom_profile_supports_vision(profile: dict[str, Any]) -> bool:
    """复用 capability_resolver；豆包视觉传输层按 endpoint provider 能力放行。"""

    if not is_model_config_complete(profile):
        return False
    model_id = (profile.get("default_model_id") or "").strip()
    if not model_id:
        return False
    endpoint = normalize_endpoint(profile.get("endpoint") or "")
    mode = normalize_mode(profile.get("mode") or "")
    caps = resolve_capabilities(model_id, endpoint, mode)
    if caps.vision is True or caps.image_input is True:
        return True
    catalog = lookup_catalog_model(model_id)
    if catalog is not None and catalog.supports_vision is True:
        return True
    if resolve_api_transport(endpoint, mode) == "doubao":
        return get_capabilities_for_endpoint(endpoint, mode).vision is True
    return False


def list_vision_model_options(config) -> list[dict[str, str]]:
    get_models = getattr(config, "get_custom_models", None)
    if not callable(get_models):
        return []
    options: list[dict[str, str]] = []
    for profile in get_models():
        if not isinstance(profile, dict):
            continue
        if not custom_profile_supports_vision(profile):
            continue
        model_id = (profile.get("default_model_id") or "").strip()
        if not model_id:
            continue
        options.append(
            {
                "id": model_id,
                "label": _profile_label(profile),
                "model_id": model_id,
            }
        )
    return options


def _stored_tts_credentials(config, provider_id: str) -> dict[str, str]:
    from app.tts.config_credentials import stored_tts_credentials

    return stored_tts_credentials(config, provider_id)


def tts_provider_credentials_ready(config, provider_id: str) -> bool:
    canonical = canonical_tts_provider_id(provider_id)
    if not canonical:
        return False
    descriptor = get_tts_manager().catalog.get_provider(canonical)
    if descriptor is None:
        return False
    credentials = _stored_tts_credentials(config, canonical)
    for field in descriptor.auth.fields:
        if field.required and not str(credentials.get(field.id) or "").strip():
            return False
    return True


def _output_format_for_validation(capabilities: TtsCapabilities) -> str:
    """Pick a supported output format for catalog validation (not synthesis defaults)."""

    formats = capabilities.output_formats
    for preferred in ("wav", "mp3", "pcm", "pcm16"):
        if preferred in formats:
            return preferred
    if formats:
        return sorted(formats)[0]
    return "wav"


def _tts_model_selectable(manager: Any, canonical_provider: str, model_id: str) -> bool:
    try:
        model = manager.catalog.require_model(canonical_provider, model_id)
    except (AttributeError, ValueError):
        return False
    if model.status != "active":
        return False
    output_format = _output_format_for_validation(model.capabilities)
    try:
        manager.validate_request(
            TtsRequest(
                text="virtual host option validation",
                provider_id=canonical_provider,
                model_id=model_id,
                output_format=output_format,
            )
        )
    except Exception:
        return False
    return True


def encode_tts_option_id(provider_id: str, model_id: str) -> str:
    provider = canonical_tts_provider_id(provider_id)
    model = canonical_tts_model_id(provider, model_id)
    return f"{provider}{TTS_OPTION_SEP}{model}"


def decode_tts_option_id(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return "", ""
    if TTS_OPTION_SEP not in raw:
        return "", raw
    provider, model = raw.split(TTS_OPTION_SEP, 1)
    return provider.strip(), model.strip()


def list_tts_model_options(config) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    manager = get_tts_manager()
    seen: set[tuple[str, str]] = set()
    for provider_id in manager.catalog.provider_ids():
        canonical = canonical_tts_provider_id(provider_id)
        if not canonical or not tts_provider_credentials_ready(config, canonical):
            continue
        descriptor = manager.catalog.get_provider(canonical)
        if descriptor is None:
            continue
        label_prefix = descriptor.label
        for model in descriptor.models:
            if not isinstance(model, ModelDescriptor) or model.status != "active":
                continue
            model_id = canonical_tts_model_id(canonical, model.id)
            if not model_id:
                continue
            dedupe_key = (canonical, model_id)
            if dedupe_key in seen:
                continue
            if not _tts_model_selectable(manager, canonical, model_id):
                continue
            seen.add(dedupe_key)
            options.append(
                {
                    "id": encode_tts_option_id(canonical, model_id),
                    "label": f"{label_prefix} · {model.label}",
                    "provider_id": canonical,
                    "model_id": model_id,
                }
            )
    return options


def _sanitize_vision_model_id(config) -> str:
    stored = str(config.get(VISION_MODEL_KEY, "") or "").strip()
    if not stored:
        return ""
    allowed = {item["id"] for item in list_vision_model_options(config)}
    if stored in allowed:
        return stored
    return ""


def _sanitize_tts_selection(config) -> tuple[str, str]:
    provider = canonical_tts_provider_id(config.get(TTS_PROVIDER_KEY, ""))
    model_id = canonical_tts_model_id(
        provider,
        str(config.get(TTS_MODEL_KEY, "") or "").strip(),
    )
    if not provider or not model_id:
        return "", ""
    option_id = encode_tts_option_id(provider, model_id)
    allowed = {item["id"] for item in list_tts_model_options(config)}
    if option_id in allowed:
        return provider, model_id
    return "", ""


def sanitize_virtual_host_model_config(config, *, persist: bool = False) -> dict[str, str]:
    """将悬空 ID 回落为「无」；``persist=True`` 时写回 ConfigStore。"""

    vision_model_id = _sanitize_vision_model_id(config)
    tts_provider, tts_model_id = _sanitize_tts_selection(config)
    normalized = {
        VISION_MODEL_KEY: vision_model_id,
        TTS_PROVIDER_KEY: tts_provider,
        TTS_MODEL_KEY: tts_model_id,
    }
    if persist:
        setter = getattr(config, "set_batch", None)
        if callable(setter):
            setter(normalized)
    return normalized


def virtual_host_vision_enabled(config) -> bool:
    return bool(_sanitize_vision_model_id(config))


def virtual_host_tts_enabled(config) -> bool:
    provider, model_id = _sanitize_tts_selection(config)
    return bool(provider and model_id)


def resolve_virtual_host_vision_profile(config) -> dict[str, Any] | None:
    """返回完整 custom_models 档案；未配置或无效时返回 ``None``（无 fallback）。"""

    model_id = _sanitize_vision_model_id(config)
    if not model_id:
        return None
    get_models = getattr(config, "get_custom_models", None)
    if not callable(get_models):
        return None
    profile = find_custom_model_profile(get_models(), model_id)
    if profile is None or not is_model_config_complete(profile):
        return None
    if not custom_profile_supports_vision(profile):
        return None
    return profile


def resolve_virtual_host_vision_credentials(config) -> tuple[str, str, str, str] | None:
    profile = resolve_virtual_host_vision_profile(config)
    if profile is None:
        return None
    endpoint = normalize_endpoint(profile.get("endpoint") or "")
    api_key = str(profile.get("apiKey") or "").strip()
    model_id = str(profile.get("default_model_id") or "").strip()
    api_mode = normalize_mode(profile.get("mode") or "")
    if not endpoint or not api_key or not model_id:
        return None
    return endpoint, api_key, model_id, api_mode


def resolve_virtual_host_tts_binding(config, manager: Any | None = None) -> TtsBinding | None:
    provider, model_id = _sanitize_tts_selection(config)
    if not provider or not model_id:
        return None
    active_manager = manager or get_tts_manager()
    voice_id = ""
    try:
        model = active_manager.catalog.require_model(provider, model_id)
        if model.voices:
            voice_id = model.voices[0].id
    except (AttributeError, ValueError):
        voice_id = default_voice_for_provider(provider, model_id)
    credentials = _stored_tts_credentials(config, provider)
    return resolve_tts_binding(
        active_manager,
        provider_id=provider,
        model_id=model_id,
        voice_id=voice_id,
        source="virtual_host",
        credentials=credentials,
    )


def export_virtual_host_model_config(config) -> dict[str, object]:
    normalized = sanitize_virtual_host_model_config(config)
    vision_options = list_vision_model_options(config)
    tts_options = list_tts_model_options(config)
    tts_provider = str(normalized[TTS_PROVIDER_KEY] or "")
    tts_model_id = str(normalized[TTS_MODEL_KEY] or "")
    return {
        "vision_model_id": normalized[VISION_MODEL_KEY],
        "tts_provider": tts_provider,
        "tts_model_id": tts_model_id,
        "tts_option_id": encode_tts_option_id(tts_provider, tts_model_id)
        if tts_provider and tts_model_id
        else "",
        "vision_enabled": bool(normalized[VISION_MODEL_KEY]),
        "tts_enabled": bool(tts_provider and tts_model_id),
        "vision_options": vision_options,
        "tts_options": tts_options,
    }


def apply_virtual_host_model_config(config, patch: dict[str, Any]) -> dict[str, object]:
    if not isinstance(patch, dict):
        raise ValueError("payload must be an object")
    items: dict[str, str] = {}
    if "vision_model_id" in patch:
        value = str(patch.get("vision_model_id") or "").strip()
        if value:
            allowed = {item["id"] for item in list_vision_model_options(config)}
            if value not in allowed:
                raise ValueError("virtual_host_vision_model_unavailable")
        items[VISION_MODEL_KEY] = value
    if "tts_option_id" in patch:
        provider, model_id = decode_tts_option_id(str(patch.get("tts_option_id") or ""))
        if provider or model_id:
            option_id = encode_tts_option_id(provider, model_id)
            allowed = {item["id"] for item in list_tts_model_options(config)}
            if option_id not in allowed:
                raise ValueError("virtual_host_tts_model_unavailable")
        items[TTS_PROVIDER_KEY] = provider
        items[TTS_MODEL_KEY] = model_id
    elif "tts_provider" in patch or "tts_model_id" in patch:
        provider = canonical_tts_provider_id(str(patch.get("tts_provider") or "").strip())
        model_id = canonical_tts_model_id(
            provider,
            str(patch.get("tts_model_id") or "").strip(),
        )
        if provider or model_id:
            option_id = encode_tts_option_id(provider, model_id)
            allowed = {item["id"] for item in list_tts_model_options(config)}
            if option_id not in allowed:
                raise ValueError("virtual_host_tts_model_unavailable")
        items[TTS_PROVIDER_KEY] = provider
        items[TTS_MODEL_KEY] = model_id
    if not items:
        return export_virtual_host_model_config(config)
    setter = getattr(config, "set_batch", None)
    if not callable(setter):
        raise RuntimeError("config store unavailable")
    setter(items)
    return export_virtual_host_model_config(config)


def purge_virtual_host_model_refs(config, model_id: str) -> None:
    """删除 custom model 后清理虚拟主播视觉模型引用。"""

    mid = str(model_id or "").strip()
    if not mid:
        return
    if str(config.get(VISION_MODEL_KEY, "") or "").strip() != mid:
        return
    setter = getattr(config, "set_batch", None)
    if callable(setter):
        setter({VISION_MODEL_KEY: ""})


__all__ = [
    "TTS_MODEL_KEY",
    "TTS_PROVIDER_KEY",
    "VISION_MODEL_KEY",
    "apply_virtual_host_model_config",
    "custom_profile_supports_vision",
    "decode_tts_option_id",
    "encode_tts_option_id",
    "export_virtual_host_model_config",
    "list_tts_model_options",
    "list_vision_model_options",
    "purge_virtual_host_model_refs",
    "resolve_virtual_host_tts_binding",
    "resolve_virtual_host_vision_credentials",
    "resolve_virtual_host_vision_profile",
    "sanitize_virtual_host_model_config",
    "virtual_host_tts_enabled",
    "virtual_host_vision_enabled",
]
