"""Persistent selection and capability snapshot for external Live2D models."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from .model_loader import Live2DModelLoader, ModelCapabilities, ModelLoadResult

LIVE2D_MODEL_PATH_KEY = "live2d_model_path"
_MODEL_SUFFIX = ".model3.json"


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
        self._notify_config_changed()
        return self._snapshot_from_result(
            loaded,
            configured=True,
            fallback_path=selected,
        )

    def clear_model(self) -> dict[str, Any]:
        self._config.set(LIVE2D_MODEL_PATH_KEY, "")
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

    @staticmethod
    def _snapshot(
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
        }

    def _notify_config_changed(self) -> None:
        if self._on_config_changed is not None:
            self._on_config_changed()


__all__ = ["LIVE2D_MODEL_PATH_KEY", "Live2DModelRegistry"]
