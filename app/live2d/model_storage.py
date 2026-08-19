"""Managed Live2D model storage under %APPDATA%/DanmuAI/live2d-models/."""

from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

_MODEL_SUFFIX = ".model3.json"
_SLUG_RE = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]+")

LIVE2D_MODELS_ROOT = (
    Path(os.environ.get("APPDATA", os.path.expanduser("~"))) / "DanmuAI" / "live2d-models"
)


@dataclass(frozen=True)
class DiscoveredModel:
    """One ``*.model3.json`` found during a folder scan."""

    name: str
    model_path: Path
    model_dir: Path

    @property
    def entry_relative(self) -> str:
        return self.model_path.relative_to(self.model_dir).as_posix()


def model_display_name(model: DiscoveredModel) -> str:
    return model.name.strip() or "未命名模型"


def model_selection_label(model: DiscoveredModel, models: list[DiscoveredModel]) -> str:
    base = model_display_name(model)
    duplicates = [item for item in models if model_display_name(item) == base]
    if len(duplicates) <= 1:
        return base
    parent = model.model_dir.name.strip() or "模型"
    return f"{base}（{parent}）"


def discover_models_in_folder(root: Path) -> list[DiscoveredModel]:
    """Recursively find ``*.model3.json`` files under *root*."""

    folder = Path(root).expanduser().resolve()
    if not folder.is_dir():
        return []

    discovered: list[DiscoveredModel] = []
    seen: set[Path] = set()
    for candidate in sorted(folder.rglob("*")):
        if not candidate.is_file():
            continue
        if not candidate.name.lower().endswith(_MODEL_SUFFIX):
            continue
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        stem = candidate.name[: -len(_MODEL_SUFFIX)] if candidate.name.lower().endswith(_MODEL_SUFFIX) else candidate.stem
        discovered.append(
            DiscoveredModel(
                name=stem or "未命名模型",
                model_path=resolved,
                model_dir=resolved.parent,
            )
        )
    return discovered


def slugify_model_id(value: str) -> str:
    normalized = _SLUG_RE.sub("-", str(value or "").strip()).strip("-._")
    return normalized or "model"


def allocate_model_id(model_name: str, root: Path = LIVE2D_MODELS_ROOT) -> str:
    base = slugify_model_id(model_name)
    candidate = base
    index = 2
    while (root / candidate).exists():
        candidate = f"{base}-{index}"
        index += 1
    return candidate


def copy_model_directory(
    source_dir: Path,
    *,
    model_id: str,
    root: Path = LIVE2D_MODELS_ROOT,
) -> Path:
    """Copy a model directory into managed storage."""

    source = Path(source_dir).expanduser().resolve()
    if not source.is_dir():
        raise ValueError("model_directory_invalid")

    destination_root = Path(root).expanduser().resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / model_id
    if destination.exists():
        raise FileExistsError(f"model_id_exists:{model_id}")

    shutil.copytree(source, destination)
    return destination.resolve()


def resolve_managed_model_path(
    model_id: str,
    entry_relative: str,
    *,
    root: Path = LIVE2D_MODELS_ROOT,
) -> Path:
    model_key = str(model_id or "").replace("\\", "/").strip()
    model_parts = model_key.split("/")
    if not model_key or model_key.startswith("/") or any(
        part in {"", ".", ".."} for part in model_parts
    ):
        raise ValueError("invalid_model_id")

    managed_root = Path(root).expanduser().resolve()
    destination_root = (managed_root / model_key).resolve()
    if destination_root.parent != managed_root:
        raise ValueError("invalid_model_id")

    entry = str(entry_relative or "").replace("\\", "/").strip()
    parts = entry.split("/")
    if not entry or entry.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("invalid_model_entry")

    candidate = (destination_root / Path(*parts)).resolve()
    if candidate != destination_root and destination_root not in candidate.parents:
        raise ValueError("invalid_model_entry")
    return candidate


__all__ = [
    "DiscoveredModel",
    "LIVE2D_MODELS_ROOT",
    "allocate_model_id",
    "copy_model_directory",
    "discover_models_in_folder",
    "model_display_name",
    "model_selection_label",
    "resolve_managed_model_path",
    "slugify_model_id",
]
