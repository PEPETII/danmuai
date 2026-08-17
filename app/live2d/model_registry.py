"""Persistent selection and capability snapshot for external Live2D models."""

from __future__ import annotations

import copy
import json
import mimetypes
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable

from .model_loader import Live2DModelLoader, ModelCapabilities, ModelLoadResult

LIVE2D_MODEL_PATH_KEY = "live2d_model_path"
_MODEL_SUFFIX = ".model3.json"
_MODEL_RESOURCE_URL = "/api/live2d/resource/model.json"
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
    """Own the config binding; model resources remain at their original path."""

    def __init__(
        self,
        config,
        *,
        loader: Live2DModelLoader | None = None,
        on_config_changed: Callable[[], None] | None = None,
    ) -> None:
        self._config = config
        self._loader = loader or Live2DModelLoader()
        self._on_config_changed = on_config_changed
        self._runtime_status = "stopped"

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
        return self._snapshot_from_result(
            result,
            configured=True,
            fallback_path=raw_path,
        )

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
        selected, _selected_filter = QFileDialog.getOpenFileName(
            None,
            "选择 Live2D 模型",
            start_dir,
            "Live2D 模型 (*.model3.json)",
        )
        if not selected:
            result = self.snapshot()
            result["cancelled"] = True
            result["reason"] = "cancelled"
            return result

        loaded = self._loader.inspect(selected)
        if not loaded.ok:
            return self._snapshot_from_result(
                loaded,
                configured=False,
                fallback_path=selected,
            )

        self._config.set(LIVE2D_MODEL_PATH_KEY, str(Path(selected).resolve()))
        self._runtime_status = "stopped"
        self._notify_config_changed()
        return self._snapshot_from_result(
            loaded,
            configured=True,
            fallback_path=selected,
        )

    def clear_model(self) -> dict[str, Any]:
        self._config.set(LIVE2D_MODEL_PATH_KEY, "")
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
    ) -> dict[str, Any]:
        return self._snapshot(
            configured=configured,
            model_name=_model_name(fallback_path),
            model_path=result.model_path or _redacted_path(fallback_path),
            status=result.status,
            reason=result.reason,
            capabilities=_capabilities_dict(result.capabilities),
            error=result.error,
        )

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
        }

    def _notify_config_changed(self) -> None:
        if self._on_config_changed is not None:
            self._on_config_changed()


__all__ = ["LIVE2D_MODEL_PATH_KEY", "Live2DModelRegistry"]
