"""Platform model catalogs with pricing metadata for the Web console vision model picker.

四平台目录（按 ``_CATALOG_BY_PROVIDER`` key）：
- ``doubao``：火山方舟（豆包 Responses 模型）
- ``dashscope``：阿里云百炼（qwen-vl-* 等）
- ``siliconflow``：硅基流动（deepseek-ai/* 等）
- ``mimo``：小米 MiMo（仅 ``mimo-v2.5``）

每个 ``CatalogModel`` 含：name、displayName_zh/en、supportsVision、supportsMicAudio、price。
``ModelPrice`` 含 input/output/可选 audio（每千 token 元）。

价格元数据仅用于 Web「视觉模型选择器」的预估成本展示，**不**写入计费。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelPrice:
    input: float
    output: float
    audio: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "input": self.input,
            "audio": self.audio,
            "output": self.output,
        }


@dataclass(frozen=True)
class CatalogModel:
    name: str
    id: str
    price: ModelPrice

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "id": self.id,
            "price": self.price.to_dict(),
        }


@dataclass(frozen=True)
class PlatformCatalog:
    platform_id: str
    platform_label: str
    provider_id: str
    models: tuple[CatalogModel, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform_id": self.platform_id,
            "platform_label": self.platform_label,
            "provider_id": self.provider_id,
            "default_model_id": default_catalog_model_id(self.provider_id),
            "models": enrich_platform_models(self.models),
        }


DOUBAO_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Doubao-Seed-2.0-lite",
        "doubao-seed-2-0-lite-260428",
        ModelPrice(input=0.6, audio=9, output=3.6),
    ),
    CatalogModel(
        "Doubao-Seed-2.0-mini",
        "doubao-seed-2-0-mini-260428",
        ModelPrice(input=0.2, audio=3, output=2),
    ),
    CatalogModel(
        "Doubao-Seed-1.8",
        "doubao-seed-1-8-251228",
        ModelPrice(input=0.8, audio=None, output=2),
    ),
    CatalogModel(
        "Doubao-Seed-1.6",
        "doubao-seed-1-6-251015",
        ModelPrice(input=0.8, audio=None, output=2),
    ),
    CatalogModel(
        "Doubao-Seed-1.6-flash",
        "doubao-seed-1-6-flash-250828",
        ModelPrice(input=0.15, audio=None, output=1.5),
    ),
)

DASHSCOPE_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Qwen3-VL-Flash",
        "qwen3-vl-flash",
        ModelPrice(input=0.15, audio=None, output=1.5),
    ),
    CatalogModel(
        "Qwen3.5-Flash",
        "qwen3.5-flash",
        ModelPrice(input=0.2, audio=None, output=2),
    ),
    CatalogModel(
        "Qwen-VL-Plus",
        "qwen-vl-plus",
        ModelPrice(input=0.8, audio=None, output=2),
    ),
    CatalogModel(
        "Qwen3.5-Plus",
        "qwen3.5-plus",
        ModelPrice(input=0.8, audio=None, output=4.8),
    ),
    CatalogModel(
        "Qwen3.6-Flash",
        "qwen3.6-flash",
        ModelPrice(input=1.2, audio=None, output=7.2),
    ),
    CatalogModel(
        "Qwen-VL-Max",
        "qwen-vl-max",
        ModelPrice(input=1.6, audio=None, output=4),
    ),
)

# Vision/screenshot catalog: mimo-v2.5 only (official image input for screenshot danmu).
MIMO_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "MiMo-V2.5",
        "mimo-v2.5",
        ModelPrice(input=1.0, audio=1.0, output=2.0),
    ),
)

SILICONFLOW_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Qwen3-VL-8B-Instruct",
        "Qwen/Qwen3-VL-8B-Instruct",
        ModelPrice(input=0.5, audio=None, output=2),
    ),
    CatalogModel(
        "Qwen3-VL-8B-Thinking",
        "Qwen/Qwen3-VL-8B-Thinking",
        ModelPrice(input=0.5, audio=None, output=5),
    ),
    CatalogModel(
        "Qwen3-VL-30B-A3B-Instruct",
        "Qwen/Qwen3-VL-30B-A3B-Instruct",
        ModelPrice(input=0.7, audio=None, output=2.8),
    ),
    CatalogModel(
        "Qwen3-VL-30B-A3B-Thinking",
        "Qwen/Qwen3-VL-30B-A3B-Thinking",
        ModelPrice(input=0.7, audio=None, output=2.8),
    ),
    CatalogModel(
        "Qwen3-Omni-30B-A3B-Instruct",
        "Qwen/Qwen3-Omni-30B-A3B-Instruct",
        ModelPrice(input=0.7, audio=None, output=2.8),
    ),
    CatalogModel(
        "Qwen3-Omni-30B-A3B-Thinking",
        "Qwen/Qwen3-Omni-30B-A3B-Thinking",
        ModelPrice(input=0.7, audio=None, output=2.8),
    ),
    CatalogModel(
        "Qwen3-Omni-30B-A3B-Captioner",
        "Qwen/Qwen3-Omni-30B-A3B-Captioner",
        ModelPrice(input=0.7, audio=None, output=2.8),
    ),
    CatalogModel(
        "Qwen3-VL-32B-Instruct",
        "Qwen/Qwen3-VL-32B-Instruct",
        ModelPrice(input=1, audio=None, output=4),
    ),
    CatalogModel(
        "GLM-4.5V",
        "zai-org/GLM-4.5V",
        ModelPrice(input=1, audio=None, output=6),
    ),
)

PLATFORM_CATALOGS: tuple[PlatformCatalog, ...] = (
    PlatformCatalog(
        platform_id="doubao",
        platform_label="Doubao",
        provider_id="doubao",
        models=DOUBAO_MODELS,
    ),
    PlatformCatalog(
        platform_id="dashscope",
        platform_label="DashScope",
        provider_id="dashscope",
        models=DASHSCOPE_MODELS,
    ),
    PlatformCatalog(
        platform_id="siliconflow",
        platform_label="硅基流动",
        provider_id="siliconflow",
        models=SILICONFLOW_MODELS,
    ),
    PlatformCatalog(
        platform_id="mimo",
        platform_label="小米 MiMo",
        provider_id="mimo",
        models=MIMO_MODELS,
    ),
)

_CATALOG_BY_PROVIDER = {p.provider_id: p for p in PLATFORM_CATALOGS}
_CATALOG_BY_PLATFORM = {p.platform_id: p for p in PLATFORM_CATALOGS}


def enrich_platform_models(models: tuple[CatalogModel, ...] | list[CatalogModel]) -> list[dict[str, Any]]:
    """Attach ``cheapest`` and ``supports_mic`` flags for API / UI consumption."""
    items = list(models)
    if not items:
        return []

    min_input = min(m.price.input for m in items)
    cheapest_id: str | None = None
    for model in items:
        if model.price.input == min_input:
            cheapest_id = model.id
            break

    result: list[dict[str, Any]] = []
    for model in items:
        payload = model.to_dict()
        payload["supports_mic"] = model.price.audio is not None
        payload["cheapest"] = model.id == cheapest_id
        result.append(payload)
    return result


def list_platform_catalogs() -> list[dict[str, Any]]:
    return [platform.to_dict() for platform in PLATFORM_CATALOGS]


def get_catalog_for_provider(provider_id: str) -> dict[str, Any] | None:
    platform = _CATALOG_BY_PROVIDER.get((provider_id or "").strip())
    return platform.to_dict() if platform else None


def catalog_model_ids(provider_id: str) -> frozenset[str]:
    """Model IDs listed in the vision catalog for a provider preset."""
    platform = _CATALOG_BY_PROVIDER.get((provider_id or "").strip())
    if platform is None:
        return frozenset()
    return frozenset(m.id for m in platform.models)


_MIMO_DEFAULT_MODEL_ID = "mimo-v2.5"


def default_catalog_model_id(provider_id: str) -> str:
    """Default vision model when switching provider: cheapest in catalog, else first.

    MiMo catalog lists only ``mimo-v2.5``.
    """
    pid = (provider_id or "").strip()
    if pid == "mimo":
        return _MIMO_DEFAULT_MODEL_ID
    platform = _CATALOG_BY_PROVIDER.get(pid)
    if platform is None or not platform.models:
        return ""
    enriched = enrich_platform_models(platform.models)
    for model in enriched:
        if model.get("cheapest"):
            return str(model["id"])
    return platform.models[0].id


def is_catalog_model_for_provider(provider_id: str, model_id: str) -> bool:
    mid = (model_id or "").strip()
    if not mid:
        return False
    return mid in catalog_model_ids(provider_id)


def catalog_model_supports_mic(model_id: str) -> bool:
    """True when ``model_id`` is listed in a platform catalog with audio pricing."""
    mid = (model_id or "").strip()
    if not mid:
        return False
    for platform in PLATFORM_CATALOGS:
        for model in platform.models:
            if model.id == mid and model.price.audio is not None:
                return True
    return False
