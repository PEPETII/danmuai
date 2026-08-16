"""兼容旧 TTS catalog API，并投影 TTS V2 provider descriptors。

旧调用方仍使用 ``Tts*Spec`` 和 ``normalize_catalog_voice``；V2 的模型、能力、
凭据 schema 与价格由 ``app.tts`` provider descriptor 作为新事实来源。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.tts.types import descriptor_to_dict

DASHSCOPE_REALTIME_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"


@dataclass(frozen=True)
class TtsVoiceSpec:
    id: str
    label_zh: str
    supports_style: bool = False


@dataclass(frozen=True)
class TtsModelSpec:
    id: str
    label_zh: str
    voices: tuple[TtsVoiceSpec, ...]
    supports_style: bool = False
    transport: str = "http"


@dataclass(frozen=True)
class TtsProviderCatalog:
    id: str
    label_zh: str
    models: tuple[TtsModelSpec, ...]
    needs_app_id: bool = False


def get_tts_catalog_provider(provider_id: str) -> TtsProviderCatalog | None:
    return _CATALOG_BY_ID.get((provider_id or "").strip())


def _v2_descriptors() -> list[Any]:
    # The manager is the composition root and therefore carries the exact
    # provider descriptors used by synthesis, including official pricing.
    try:
        from app.tts_providers import get_tts_v2_descriptors

        return list(get_tts_v2_descriptors())
    except (ImportError, RuntimeError, ValueError):
        from app.tts.providers.dashscope import DashScopeProvider
        from app.tts.providers.doubao import DoubaoProvider
        from app.tts.providers.mimo import MimoProvider
        from app.tts.providers.minimax import MiniMaxProvider

        return [
            MimoProvider().descriptor,
            DashScopeProvider().descriptor,
            MiniMaxProvider().descriptor,
            DoubaoProvider().descriptor,
        ]


def _legacy_voice_spec(voice: dict[str, Any], *, supports_style: bool) -> TtsVoiceSpec:
    return TtsVoiceSpec(
        id=str(voice.get("id") or ""),
        label_zh=str(voice.get("name") or voice.get("id") or ""),
        supports_style=supports_style,
    )


def _canonical_model_id(provider_id: str, model_id: str) -> str:
    """Resolve legacy model aliases before consulting the selectable catalog."""
    # Keep the alias table in app.tts_providers as the single compatibility
    # source.  The import is local because that module imports this bridge
    # lazily for legacy voice normalization.
    from app.tts_providers import canonical_tts_model_id

    return canonical_tts_model_id(provider_id, model_id)


def _legacy_catalog_from_descriptors() -> tuple[TtsProviderCatalog, ...]:
    descriptors = _v2_descriptors()
    result: list[TtsProviderCatalog] = []
    for descriptor in descriptors:
        models: list[TtsModelSpec] = []
        for model in descriptor.models:
            if model.status != "active":
                continue
            model_data = descriptor_to_dict(model)
            supports_style = bool(model_data["capabilities"].get("style_prompt"))
            models.append(
                TtsModelSpec(
                    id=model.id,
                    label_zh=model.label,
                    voices=tuple(
                        _legacy_voice_spec(voice, supports_style=supports_style)
                        for voice in model_data["voices"]
                    ),
                    supports_style=supports_style,
                    transport=model.transport,
                )
            )
        provider_id = "dashscope_qwen" if descriptor.id == "dashscope" else descriptor.id
        result.append(
            TtsProviderCatalog(
                id=provider_id,
                label_zh=descriptor.label,
                models=tuple(models),
                needs_app_id=any(field.id == "app_id" for field in descriptor.auth.fields),
            )
        )
    return tuple(result)


# These names remain import-compatible, but are projected from provider
# descriptors instead of maintaining a second voice/price source of truth.
_LEGACY_CATALOG = _legacy_catalog_from_descriptors()
TTS_CATALOG = _LEGACY_CATALOG
_CATALOG_BY_ID = {provider.id: provider for provider in TTS_CATALOG}
_DASHSCOPE_LEGACY = get_tts_catalog_provider("dashscope_qwen")
_MIMO_LEGACY = get_tts_catalog_provider("mimo")
DASHSCOPE_VOICES = _DASHSCOPE_LEGACY.models[0].voices if _DASHSCOPE_LEGACY else ()
MIMO_VOICES = _MIMO_LEGACY.models[0].voices if _MIMO_LEGACY else ()


def list_catalog_for_api() -> list[dict[str, Any]]:
    """Return only selectable V2 models for the UI/API catalog.

    Historical and catalog-only descriptors stay in the provider registry for
    diagnostics and legacy resolution, but they are not user-selectable.
    """
    out: list[dict[str, Any]] = []
    for provider in _v2_descriptors():
        data = descriptor_to_dict(provider)
        data["models"] = [
            model for model in data["models"] if model.get("status") == "active"
        ]
        for model in data["models"]:
            model["supports_style"] = bool(model["capabilities"].get("style_prompt"))
            model["voices"] = [
                {
                    **voice,
                    "label": voice.get("name") or voice.get("id"),
                    "supports_style": model["supports_style"],
                }
                for voice in model["voices"]
            ]
            model["description"] = model.get("description") or model["label"]
        out.append({
            "id": data["id"],
            "label": data["label"],
            "needs_app_id": any(field["id"] == "app_id" for field in data["auth_schema"]["fields"]),
            "auth_schema": data["auth_schema"],
            "models": data["models"],
            "status": data["status"],
        })
    # Keep the old alias addressable without duplicating a provider in the V2 registry.
    dashscope = next((item for item in out if item["id"] == "dashscope"), None)
    if dashscope is not None:
        alias = dict(dashscope)
        alias["id"] = "dashscope_qwen"
        alias["wire_id"] = "dashscope"
        out.insert(1, alias)
    return out


def default_model_for_provider(provider_id: str) -> str:
    provider = (provider_id or "").strip()
    for item in list_catalog_for_api():
        if item["id"] == provider and item["models"]:
            return item["models"][0]["id"]
    legacy = get_tts_catalog_provider(provider)
    return legacy.models[0].id if legacy and legacy.models else ""


def default_voice_for_provider(provider_id: str, model_id: str | None = None) -> str:
    for provider in list_catalog_for_api():
        if provider["id"] != (provider_id or "").strip():
            continue
        models = provider["models"]
        model = next((m for m in models if model_id and m["id"] == model_id), models[0] if models else None)
        if model and model["voices"]:
            return model["voices"][0]["id"]
    return "冰糖"


def voice_ids_for(provider_id: str, model_id: str) -> frozenset[str]:
    model_key = _canonical_model_id(provider_id, model_id)
    for provider in list_catalog_for_api():
        if provider["id"] != (provider_id or "").strip():
            continue
        for model in provider["models"]:
            if model["id"] == model_key:
                return frozenset(voice["id"] for voice in model["voices"] if voice["id"])
    legacy = get_tts_catalog_provider(provider_id)
    if legacy:
        for model in legacy.models:
            if model.id == model_key:
                return frozenset(voice.id for voice in model.voices)
    return frozenset()


def model_supports_style(provider_id: str, model_id: str) -> bool:
    model_key = _canonical_model_id(provider_id, model_id)
    return any(
        provider["id"] == provider_id
        and model["id"] == model_key
        and bool(model.get("supports_style"))
        for provider in list_catalog_for_api()
        for model in provider["models"]
    )


def normalize_catalog_voice(voice: str | None, *, provider_id: str, model_id: str) -> str:
    raw = (voice or "").strip()
    allowed = voice_ids_for(provider_id, model_id)
    if raw in allowed or not allowed:
        return raw
    return default_voice_for_provider(provider_id, model_id)


__all__ = [
    "DASHSCOPE_REALTIME_URL", "DASHSCOPE_VOICES", "MIMO_VOICES", "TTS_CATALOG",
    "TtsModelSpec", "TtsProviderCatalog", "TtsVoiceSpec", "default_model_for_provider",
    "default_voice_for_provider", "get_tts_catalog_provider", "list_catalog_for_api",
    "model_supports_style", "normalize_catalog_voice", "voice_ids_for",
]
