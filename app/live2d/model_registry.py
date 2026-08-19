"""Persistent selection and capability snapshot for external Live2D models."""

from __future__ import annotations

import copy
import json
import mimetypes
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from .model_loader import Live2DModelLoader, ModelCapabilities, ModelLoadResult
from .model_storage import (
    DiscoveredModel,
    allocate_model_id,
    copy_model_directory,
    discover_models_in_folder,
    model_selection_label,
    resolve_managed_model_path,
)

LIVE2D_MODEL_PATH_KEY = "live2d_model_path"
LIVE2D_MODEL_ID_KEY = "live2d_model_id"
LIVE2D_MODEL_NAME_KEY = "live2d_model_name"
LIVE2D_MODEL_ENTRY_KEY = "live2d_model_entry"
LIVE2D_MODEL_CATALOG_KEY = "live2d_model_catalog"
_MODEL_SUFFIX = ".model3.json"
_MODEL_RESOURCE_URL = "/api/live2d/resource/model.json"
_NO_MODELS_MESSAGE = (
    "未在该文件夹中识别到可用的 Live2D 模型，请选择解压后的完整模型文件夹。"
)
_RESOURCE_SUFFIXES = frozenset(
    {
        ".json",
        ".moc3",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".motion3",
        ".exp3",
        ".cdi3",
        ".physics3",
        ".pose3",
    }
)


def _model_name(path: str | Path | None) -> str | None:
    if not path:
        return None
    name = Path(path).name
    if name.lower().endswith(_MODEL_SUFFIX):
        return name[: -len(_MODEL_SUFFIX)] or None
    return Path(name).stem or None


def _redacted_path(path: str | Path | None) -> str | None:
    if not path:
        return None
    return f"<external-model>/{Path(path).name}"


def _capabilities_dict(capabilities: ModelCapabilities) -> dict[str, Any]:
    return {
        "parameter_ids": list(capabilities.parameter_ids),
        "parameter_count": len(capabilities.parameter_specs),
        "parameter_source": capabilities.parameter_source,
        "motion_groups": list(capabilities.motion_groups),
        "expression_ids": list(capabilities.expression_ids),
        "motion_files": list(capabilities.motion_files),
        "expression_files": list(capabilities.expression_files),
        "physics": capabilities.physics,
        "texture_count": capabilities.texture_count,
        "dependency_count": len(capabilities.dependencies),
        "missing_dependencies": list(capabilities.missing_dependencies),
    }


def _empty_capabilities() -> dict[str, Any]:
    return _capabilities_dict(ModelCapabilities())


class Live2DModelRegistry:
    """Own the config binding; imported models are copied into managed storage."""

    def __init__(
        self,
        config,
        *,
        loader: Live2DModelLoader | None = None,
        on_config_changed: Callable[[], None] | None = None,
        models_root: Path | None = None,
    ) -> None:
        self._config = config
        self._loader = loader or Live2DModelLoader()
        self._on_config_changed = on_config_changed
        self._runtime_status = "stopped"
        if models_root is None:
            from .model_storage import LIVE2D_MODELS_ROOT

            models_root = LIVE2D_MODELS_ROOT
        self._models_root = Path(models_root)

    def snapshot(self) -> dict[str, Any]:
        raw_path = str(self._config.get(LIVE2D_MODEL_PATH_KEY, "") or "").strip()
        if not raw_path:
            return self._snapshot(
                configured=False,
                model_name=None,
                model_path=None,
                status="unconfigured",
                reason="model_not_configured",
                capabilities=_empty_capabilities(),
                error=None,
            )

        result = self._loader.inspect(raw_path)
        configured_name = str(self._config.get(LIVE2D_MODEL_NAME_KEY, "") or "").strip() or None
        snapshot = self._snapshot_from_result(
            result,
            configured=True,
            fallback_path=raw_path,
            model_name=configured_name or _model_name(raw_path),
        )
        snapshot["model_id"] = str(self._config.get(LIVE2D_MODEL_ID_KEY, "") or "").strip() or None
        snapshot["model_entry"] = str(self._config.get(LIVE2D_MODEL_ENTRY_KEY, "") or "").strip() or None
        return snapshot

    def list_models(self) -> list[dict[str, Any]]:
        """Return imported model options without exposing local filesystem paths."""

        records = self._model_records()
        name_counts: dict[str, int] = {}
        for record in records:
            name = str(record["name"] or "未命名模型")
            name_counts[name] = name_counts.get(name, 0) + 1

        options: list[dict[str, Any]] = []
        for record in records:
            model_id = str(record["id"])
            name = str(record["name"] or "未命名模型")
            label = name if name_counts[name] == 1 else f"{name}（{model_id}）"
            result = record["result"]
            options.append(
                {
                    "id": model_id,
                    "label": label,
                    "model_name": name,
                    "status": result.status,
                    "ready": result.ok,
                }
            )
        return options

    def select_model(self, model_id: str) -> dict[str, Any]:
        """Select one imported model, or clear the active selection for an empty ID."""

        normalized_id = str(model_id or "").strip()
        if not normalized_id:
            self._clear_active_model()
            self._runtime_status = "stopped"
            self._notify_config_changed()
            result = self.snapshot()
            result["reason"] = "cleared"
            return result

        selected = next(
            (record for record in self._model_records() if record["id"] == normalized_id),
            None,
        )
        if selected is None:
            raise ValueError("live2d_model_not_found")
        result = selected["result"]
        if not result.ok:
            raise ValueError(result.reason or "live2d_model_not_ready")

        self._persist_managed_model(
            model_id=normalized_id,
            model_name=str(selected["name"]),
            model_entry=str(selected["entry"]),
            model_path=str(selected["path"]),
        )
        self._runtime_status = "stopped"
        self._notify_config_changed()
        snapshot = self.snapshot()
        snapshot["reason"] = "model_selected"
        return snapshot

    def _model_records(self) -> list[dict[str, Any]]:
        records: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for item in self._load_model_catalog():
            model_id = item["id"]
            model_path = resolve_managed_model_path(
                model_id,
                item["entry"],
                root=self._models_root,
            )
            if not model_path.is_file():
                continue
            records.append(
                self._build_model_record(
                    model_id=model_id,
                    model_name=item["name"],
                    model_entry=item["entry"],
                    model_path=model_path,
                )
            )
            seen_ids.add(model_id)

        root = self._models_root.expanduser().resolve()
        if root.is_dir():
            for model_root in sorted(root.iterdir(), key=lambda path: path.name.casefold()):
                if not model_root.is_dir() or model_root.name in seen_ids:
                    continue
                discovered = discover_models_in_folder(model_root)
                if not discovered:
                    continue
                model_path = discovered[0].model_path.resolve()
                entry = model_path.relative_to(model_root.resolve()).as_posix()
                records.append(
                    self._build_model_record(
                        model_id=model_root.name,
                        model_name=discovered[0].name,
                        model_entry=entry,
                        model_path=model_path,
                    )
                )

        return records

    def _build_model_record(
        self,
        *,
        model_id: str,
        model_name: str,
        model_entry: str,
        model_path: Path,
    ) -> dict[str, Any]:
        result = self._loader.inspect(model_path)
        return {
            "id": model_id,
            "name": model_name.strip() or _model_name(model_path) or "未命名模型",
            "entry": model_entry,
            "path": model_path,
            "result": result,
        }

    def _load_model_catalog(self) -> list[dict[str, str]]:
        raw = str(self._config.get(LIVE2D_MODEL_CATALOG_KEY, "[]") or "[]")
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return []
        if not isinstance(decoded, list):
            return []

        catalog: list[dict[str, str]] = []
        seen_ids: set[str] = set()
        for item in decoded:
            if not isinstance(item, Mapping):
                continue
            model_id = str(item.get("id") or "").strip()
            model_entry = str(item.get("entry") or "").strip()
            if not model_id or not model_entry or model_id in seen_ids:
                continue
            try:
                resolve_managed_model_path(
                    model_id,
                    model_entry,
                    root=self._models_root,
                )
            except ValueError:
                continue
            catalog.append(
                {
                    "id": model_id,
                    "name": str(item.get("name") or "").strip(),
                    "entry": model_entry,
                }
            )
            seen_ids.add(model_id)
        return catalog

    def start_model(self) -> dict[str, Any]:
        snapshot = self.snapshot()
        if not snapshot["configured"] or snapshot["status"] != "ready":
            raise ValueError("model_not_ready")
        self._runtime_status = "running"
        snapshot["runtime_status"] = self._runtime_status
        snapshot["model_url"] = _MODEL_RESOURCE_URL
        return snapshot

    def stop_model(self) -> dict[str, Any]:
        self._runtime_status = "stopped"
        snapshot = self.snapshot()
        snapshot["runtime_status"] = self._runtime_status
        return snapshot

    def read_resource(self, resource_path: str) -> tuple[bytes, str]:
        """Read one model resource without exposing the configured absolute path."""

        raw_model = str(self._config.get(LIVE2D_MODEL_PATH_KEY, "") or "").strip()
        model_path, reason = self._loader.validate_path(raw_model)
        if model_path is None:
            raise FileNotFoundError(reason or "model_not_configured")

        normalized = str(resource_path or "").replace("\\", "/")
        parts = normalized.split("/")
        if not normalized or normalized.startswith("/") or any(part in {"", ".", ".."} for part in parts):
            raise PermissionError("invalid_model_resource_path")
        if normalized == "model.json":
            return self._browser_model_json(model_path), "application/json"

        candidate = (model_path.parent / Path(*parts)).resolve()
        root = model_path.parent.resolve()
        if candidate != root and root not in candidate.parents:
            raise PermissionError("model_resource_outside_root")
        if candidate.suffix.lower() not in _RESOURCE_SUFFIXES or not candidate.is_file():
            raise FileNotFoundError("model_resource_not_found")
        return candidate.read_bytes(), mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"

    def _browser_model_json(self, model_path: Path) -> bytes:
        try:
            document = json.loads(model_path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise FileNotFoundError("model_json_invalid") from exc
        if not isinstance(document, Mapping):
            raise FileNotFoundError("model_json_invalid")

        browser_document = copy.deepcopy(document)
        references = browser_document.setdefault("FileReferences", {})
        if not isinstance(references, dict):
            raise FileNotFoundError("model_references_invalid")

        motion_files = self._discover_relative_files(model_path.parent, ".motion3.json")
        motions = references.get("Motions")
        if isinstance(motions, dict):
            motion_groups = motions
        elif isinstance(motions, list):
            motion_groups = {"动作": motions}
        else:
            motion_groups = {"动作": []}
        motion_group = motion_groups.setdefault("动作", [])
        if not isinstance(motion_group, list):
            motion_group = []
            motion_groups["动作"] = motion_group
        existing_motion_files = {
            item.get("File") or item.get("file")
            for group in motion_groups.values()
            if isinstance(group, list)
            for item in group
            if isinstance(item, Mapping)
        }
        for relative in motion_files:
            if relative not in existing_motion_files:
                motion_group.append({"File": relative})
        references["Motions"] = motion_groups

        expression_files = self._discover_relative_files(model_path.parent, ".exp3.json")
        expressions = references.get("Expressions")
        if isinstance(expressions, dict):
            expression_entries = list(expressions.values())
        elif isinstance(expressions, list):
            expression_entries = expressions
        else:
            expression_entries = []
        existing_expression_files = {
            item.get("File") or item.get("file")
            for item in expression_entries
            if isinstance(item, Mapping)
        }
        for relative in expression_files:
            if relative not in existing_expression_files:
                expression_entries.append(
                    {
                        "Name": self._resource_stem(relative, ".exp3.json"),
                        "File": relative,
                    }
                )
        references["Expressions"] = expression_entries
        return json.dumps(browser_document, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    @staticmethod
    def _discover_relative_files(root: Path, suffix: str) -> tuple[str, ...]:
        return tuple(
            sorted(
                path.relative_to(root).as_posix()
                for path in root.rglob(f"*{suffix}")
                if path.is_file()
            )
        )

    @staticmethod
    def _resource_stem(relative: str, suffix: str) -> str:
        name = Path(relative).name
        return name[: -len(suffix)] or name

    def import_model_via_dialog(self) -> dict[str, Any]:
        from PyQt6.QtWidgets import QFileDialog

        current = str(self._config.get(LIVE2D_MODEL_PATH_KEY, "") or "").strip()
        start_dir = str(Path(current).parent) if current else str(Path.home())
        selected_dir = QFileDialog.getExistingDirectory(
            None,
            "选择 Live2D 模型文件夹",
            start_dir,
            QFileDialog.Option.ShowDirsOnly,
        )
        if not selected_dir:
            result = self.snapshot()
            result["cancelled"] = True
            result["reason"] = "cancelled"
            return result

        discovered = discover_models_in_folder(Path(selected_dir))
        if not discovered:
            return self._snapshot(
                configured=False,
                model_name=None,
                model_path=None,
                status="invalid",
                reason="model_not_found_in_folder",
                capabilities=_empty_capabilities(),
                error=_NO_MODELS_MESSAGE,
            )

        if len(discovered) == 1:
            return self._import_discovered_model(discovered[0])

        return self._import_discovered_model_via_selection(discovered)

    def import_model_file_via_dialog(self) -> dict[str, Any]:
        from PyQt6.QtWidgets import QFileDialog

        current = str(self._config.get(LIVE2D_MODEL_PATH_KEY, "") or "").strip()
        start_dir = str(Path(current).parent) if current else str(Path.home())
        selected, _selected_filter = QFileDialog.getOpenFileName(
            None,
            "选择 Live2D 模型文件",
            start_dir,
            "Live2D 模型 (*.model3.json)",
        )
        if not selected:
            result = self.snapshot()
            result["cancelled"] = True
            result["reason"] = "cancelled"
            return result

        model_path = Path(selected).resolve()
        discovered = DiscoveredModel(
            name=_model_name(model_path) or "未命名模型",
            model_path=model_path,
            model_dir=model_path.parent,
        )
        return self._import_discovered_model(discovered)

    def _import_discovered_model_via_selection(
        self,
        discovered: list[DiscoveredModel],
    ) -> dict[str, Any]:
        from PyQt6.QtWidgets import QInputDialog

        labels = [model_selection_label(model, discovered) for model in discovered]
        selected_label, accepted = QInputDialog.getItem(
            None,
            "选择要导入的模型",
            "识别到多个 Live2D 模型，请选择一个：",
            labels,
            0,
            False,
        )
        if not accepted or not selected_label:
            result = self.snapshot()
            result["cancelled"] = True
            result["reason"] = "cancelled"
            return result

        index = labels.index(str(selected_label))
        return self._import_discovered_model(discovered[index])

    def _import_discovered_model(self, discovered: DiscoveredModel) -> dict[str, Any]:
        loaded = self._loader.inspect(discovered.model_path)
        if not loaded.ok:
            return self._snapshot_from_result(
                loaded,
                configured=False,
                fallback_path=discovered.model_path,
                model_name=discovered.name,
            )

        try:
            managed_path = self._copy_to_managed_storage(discovered)
        except OSError as exc:
            return self._snapshot(
                configured=False,
                model_name=discovered.name,
                model_path=_redacted_path(discovered.model_path),
                status="blocked",
                reason="model_copy_failed",
                capabilities=_capabilities_dict(loaded.capabilities),
                error=f"模型复制失败：{exc}",
            )

        self._persist_managed_model(
            model_id=managed_path["model_id"],
            model_name=discovered.name,
            model_entry=managed_path["model_entry"],
            model_path=managed_path["model_path"],
        )
        self._runtime_status = "stopped"
        self._notify_config_changed()
        persisted = self._loader.inspect(managed_path["model_path"])
        return self._snapshot_from_result(
            persisted,
            configured=True,
            fallback_path=managed_path["model_path"],
            model_name=discovered.name,
        )

    def _copy_to_managed_storage(self, discovered: DiscoveredModel) -> dict[str, str]:
        model_id = allocate_model_id(discovered.name, self._models_root)
        destination = copy_model_directory(
            discovered.model_dir,
            model_id=model_id,
            root=self._models_root,
        )
        model_path = (destination / discovered.entry_relative).resolve()
        return {
            "model_id": model_id,
            "model_entry": discovered.entry_relative,
            "model_path": str(model_path),
        }

    def _persist_managed_model(
        self,
        *,
        model_id: str,
        model_name: str,
        model_entry: str,
        model_path: str,
    ) -> None:
        replacement = {
            "id": model_id,
            "name": model_name,
            "entry": model_entry,
        }
        catalog: list[dict[str, str]] = []
        replaced = False
        for item in self._load_model_catalog():
            if item["id"] == model_id:
                catalog.append(replacement)
                replaced = True
            else:
                catalog.append(item)
        if not replaced:
            catalog.append(replacement)
        values = {
            LIVE2D_MODEL_ID_KEY: model_id,
            LIVE2D_MODEL_NAME_KEY: model_name,
            LIVE2D_MODEL_ENTRY_KEY: model_entry,
            LIVE2D_MODEL_PATH_KEY: model_path,
            LIVE2D_MODEL_CATALOG_KEY: json.dumps(
                catalog,
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        }
        setter = getattr(self._config, "set_batch", None)
        if callable(setter):
            setter(values)
        else:
            for key, value in values.items():
                self._config.set(key, value)

    def _clear_active_model(self) -> None:
        self._config.set(LIVE2D_MODEL_PATH_KEY, "")
        self._config.set(LIVE2D_MODEL_ID_KEY, "")
        self._config.set(LIVE2D_MODEL_NAME_KEY, "")
        self._config.set(LIVE2D_MODEL_ENTRY_KEY, "")

    def clear_model(self) -> dict[str, Any]:
        self._clear_active_model()
        self._runtime_status = "stopped"
        self._notify_config_changed()
        result = self.snapshot()
        result["reason"] = "cleared"
        return result

    def _snapshot_from_result(
        self,
        result: ModelLoadResult,
        *,
        configured: bool,
        fallback_path: str | Path | None,
        model_name: str | None = None,
    ) -> dict[str, Any]:
        resolved_name = model_name or _model_name(fallback_path)
        snapshot = self._snapshot(
            configured=configured,
            model_name=resolved_name,
            model_path=result.model_path or _redacted_path(fallback_path),
            status=result.status,
            reason=result.reason,
            capabilities=_capabilities_dict(result.capabilities),
            error=result.error,
        )
        if configured:
            snapshot["model_id"] = str(self._config.get(LIVE2D_MODEL_ID_KEY, "") or "").strip() or None
            snapshot["model_entry"] = str(self._config.get(LIVE2D_MODEL_ENTRY_KEY, "") or "").strip() or None
        return snapshot

    def _snapshot(
        self,
        *,
        configured: bool,
        model_name: str | None,
        model_path: str | None,
        status: str,
        reason: str | None,
        capabilities: dict[str, Any],
        error: str | None,
    ) -> dict[str, Any]:
        return {
            "configured": configured,
            "model_name": model_name,
            "model_path": model_path,
            "status": status,
            "reason": reason,
            "error": error,
            "capabilities": capabilities,
            "cancelled": False,
            "runtime_status": self._runtime_status,
            "model_url": _MODEL_RESOURCE_URL if configured and status == "ready" else None,
            "model_id": None,
            "model_entry": None,
            "models": self.list_models(),
        }

    def _notify_config_changed(self) -> None:
        if self._on_config_changed is not None:
            self._on_config_changed()


__all__ = [
    "LIVE2D_MODEL_CATALOG_KEY",
    "LIVE2D_MODEL_ENTRY_KEY",
    "LIVE2D_MODEL_ID_KEY",
    "LIVE2D_MODEL_NAME_KEY",
    "LIVE2D_MODEL_PATH_KEY",
    "Live2DModelRegistry",
]
