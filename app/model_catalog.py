"""Platform model catalogs with pricing metadata for the Web console vision model picker."""

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
            "models": enrich_platform_models(self.models),
        }


DOUBAO_MODELS: tuple[CatalogModel, ...] = (
    CatalogModel(
        "Doubao-Seed-2.0-pro",
        "doubao-seed-2-0-pro-260215",
        ModelPrice(input=3.2, audio=None, output=16),
    ),
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
        "Qwen-Omni-Turbo",
        "qwen-omni-turbo",
        ModelPrice(input=0.4, audio=25, output=1.6),
    ),
    CatalogModel(
        "Qwen2.5-Omni-7B",
        "qwen2.5-omni-7b",
        ModelPrice(input=0.6, audio=38, output=2.4),
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
        platform_label="轨迹流动",
        provider_id="siliconflow",
        models=SILICONFLOW_MODELS,
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


def get_catalog_for_platform(platform_id: str) -> dict[str, Any] | None:
    platform = _CATALOG_BY_PLATFORM.get((platform_id or "").strip())
    return platform.to_dict() if platform else None
