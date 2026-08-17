"""DanmuApp façade for external Live2D model selection."""

from __future__ import annotations

from app.live2d.model_registry import Live2DModelRegistry


class DanmuAppLive2DMixin:
    def _get_live2d_model_registry(self) -> Live2DModelRegistry:
        registry = self.__dict__.get("_live2d_registry")
        if registry is None:
            registry = Live2DModelRegistry(
                self.config,
                on_config_changed=self.config_changed.emit,
            )
            self.__dict__["_live2d_registry"] = registry
        return registry

    def get_live2d_model_snapshot(self) -> dict[str, object]:
        return self._get_live2d_model_registry().snapshot()

    def import_live2d_model_via_dialog(self) -> dict[str, object]:
        return self._get_live2d_model_registry().import_model_via_dialog()

    def clear_live2d_model(self) -> dict[str, object]:
        return self._get_live2d_model_registry().clear_model()
