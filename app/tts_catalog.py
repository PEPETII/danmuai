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


DASHSCOPE_VOICES = tuple(
    TtsVoiceSpec(id, label)
    for id, label in (
        ("Cherry", "芊悦"), ("Serena", "苏瑶"), ("Ethan", "晨煦"),
        ("Chelsie", "千雪"), ("Momo", "茉兔"), ("Vivian", "十三"),
        ("Kai", "凯"), ("Bella", "萌宝"), ("longanyang", "龙安洋"),
        ("longanhuan_v3", "龙安欢 V3"),
    )
)
MIMO_VOICES = tuple(
    TtsVoiceSpec(value, value)
    for value in ("mimo_default", "冰糖", "茉莉", "苏打", "白桦", "Mia", "Chloe", "Milo", "Dean")
)

# Legacy projection retained for callers that need the old dataclasses.
TTS_CATALOG = (
    TtsProviderCatalog(
        id="mimo",
        label_zh="小米 MiMo（默认）",
        models=(TtsModelSpec("mimo-v2.5-tts", "mimo-v2.5-tts", MIMO_VOICES, transport="chat_audio"),),
    ),
    TtsProviderCatalog(
        id="dashscope_qwen",
        label_zh="阿里百炼 Qwen3",
        models=(
            TtsModelSpec("qwen3-tts-flash-2025-11-27", "Qwen3-TTS Flash", DASHSCOPE_VOICES),
            TtsModelSpec("qwen3-tts-flash-realtime", "Qwen3-TTS Flash Realtime", DASHSCOPE_VOICES, transport="websocket"),
            TtsModelSpec("qwen3-tts-instruct-flash-realtime", "Qwen3-TTS Instruct Realtime", DASHSCOPE_VOICES, supports_style=True, transport="websocket"),
        ),
    ),
)
_CATALOG_BY_ID = {provider.id: provider for provider in TTS_CATALOG}


def get_tts_catalog_provider(provider_id: str) -> TtsProviderCatalog | None:
    return _CATALOG_BY_ID.get((provider_id or "").strip())


def _v2_descriptors() -> list[Any]:
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


def list_catalog_for_api() -> list[dict[str, Any]]:
    """Return V2 catalog data while retaining legacy fields used by old UI code."""
    out: list[dict[str, Any]] = []
    for provider in _v2_descriptors():
        data = descriptor_to_dict(provider)
        for model in data["models"]:
            model["supports_style"] = bool(model["capabilities"].get("style_prompt"))
            model["voices"] = [
                {
                    "id": voice["id"],
                    "label": voice["name"],
                    "supports_style": model["supports_style"],
                    "source": voice["source"],
                    "preview_url": voice.get("preview_url"),
                }
                for voice in model["voices"]
            ]
            model["pricing"] = dict(model["pricing"])
            model["pricing"].setdefault("verified_at", "2026-08-16")
            model["pricing"].setdefault("source_url", model["pricing"].get("source"))
            model["description"] = model["label"]
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
        out.insert(1, alias)
    return out


def default_model_for_provider(provider_id: str) -> str:
    provider = (provider_id or "").strip()
    if provider == "dashscope_qwen":
        return "qwen3-tts-flash-2025-11-27"
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
    for provider in list_catalog_for_api():
        if provider["id"] != (provider_id or "").strip():
            continue
        for model in provider["models"]:
            if model["id"] == model_id:
                return frozenset(voice["id"] for voice in model["voices"] if voice["id"])
    legacy = get_tts_catalog_provider(provider_id)
    if legacy:
        for model in legacy.models:
            if model.id == model_id:
                return frozenset(voice.id for voice in model.voices)
    return frozenset()


def model_supports_style(provider_id: str, model_id: str) -> bool:
    return any(
        provider["id"] == provider_id
        and model["id"] == model_id
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
