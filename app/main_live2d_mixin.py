"""DanmuApp façade for external Live2D model selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.live2d.model_registry import Live2DModelRegistry

if TYPE_CHECKING:
    from app.live2d.desktop_runtime import Live2DDesktopRuntime


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
        snapshot = self._get_live2d_model_registry().snapshot()
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is not None:
            runtime_snapshot = runtime.snapshot()
            snapshot["runtime_status"] = runtime_snapshot.get("runtime_status", "stopped")
            if runtime_snapshot.get("runtime_status") == "running":
                snapshot["desktop_visible"] = bool(runtime_snapshot.get("desktop_visible"))
                snapshot["capabilities"] = {
                    **dict(snapshot.get("capabilities") or {}),
                    **dict(runtime_snapshot.get("capabilities") or {}),
                }
            else:
                snapshot["desktop_visible"] = False
        return snapshot

    def _get_live2d_desktop_runtime(self) -> Live2DDesktopRuntime:
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is None:
            from app.live2d.desktop_runtime import Live2DDesktopRuntime

            runtime = Live2DDesktopRuntime()
            self.__dict__["_live2d_desktop_runtime"] = runtime
        return runtime

    def import_live2d_model_via_dialog(self) -> dict[str, object]:
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is not None:
            runtime.stop()
        return self._get_live2d_model_registry().import_model_via_dialog()

    def clear_live2d_model(self) -> dict[str, object]:
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is not None:
            runtime.stop()
        return self._get_live2d_model_registry().clear_model()

    def start_live2d_model(self) -> dict[str, object]:
        registry = self._get_live2d_model_registry()
        registry_snapshot = registry.start_model()
        model_path = str(self.config.get("live2d_model_path", "") or "").strip()
        try:
            runtime_snapshot = self._get_live2d_desktop_runtime().start(model_path)
        except Exception as exc:
            registry.stop_model()
            raise ValueError(f"desktop_runtime_failed:{_safe_live2d_error(exc)}") from exc
        ensure = getattr(self, "_ensure_virtual_host_runtime", None)
        if callable(ensure):
            ensure()
        virtual_host_runtime = self.__dict__.get("virtual_host_runtime")
        if virtual_host_runtime is not None:
            virtual_host_runtime.start()
        return {
            **registry_snapshot,
            **runtime_snapshot,
            "desktop_visible": bool(runtime_snapshot.get("desktop_visible")),
            "capabilities": {
                **dict(registry_snapshot.get("capabilities") or {}),
                **dict(runtime_snapshot.get("capabilities") or {}),
            },
        }

    def stop_live2d_model(self) -> dict[str, object]:
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is not None:
            runtime.stop()
        virtual_host_runtime = self.__dict__.get("virtual_host_runtime")
        if virtual_host_runtime is not None:
            virtual_host_runtime.stop()
        snapshot = self._get_live2d_model_registry().stop_model()
        snapshot["desktop_visible"] = False
        return snapshot

    def set_live2d_parameter(self, parameter_id: str, value: float) -> dict[str, object]:
        return {
            "ok": True,
            "kind": "parameter",
            **self._get_live2d_desktop_runtime().set_parameter(parameter_id, value),
        }

    def trigger_live2d_action(self, action: str) -> dict[str, object]:
        return {
            "ok": True,
            "kind": "action",
            **self._get_live2d_desktop_runtime().trigger_action(action),
        }

    def start_live2d_motion(self, file_name: str) -> dict[str, object]:
        return {
            "ok": True,
            "kind": "motion",
            **self._get_live2d_desktop_runtime().start_motion(file_name),
        }

    def set_live2d_expression(self, file_name: str) -> dict[str, object]:
        return {
            "ok": True,
            "kind": "expression",
            **self._get_live2d_desktop_runtime().set_expression(file_name),
        }

    def get_live2d_model_resource(self, resource_path: str) -> tuple[bytes, str]:
        return self._get_live2d_model_registry().read_resource(resource_path)

    def get_virtual_host_model_config(self) -> dict[str, object]:
        from app.virtual_host.model_config import (
            export_virtual_host_model_config,
            sanitize_virtual_host_model_config,
        )

        sanitize_virtual_host_model_config(self.config, persist=True)
        return export_virtual_host_model_config(self.config)

    def apply_virtual_host_model_config(self, patch: dict) -> dict[str, object]:
        from app.virtual_host.model_config import apply_virtual_host_model_config

        result = apply_virtual_host_model_config(self.config, patch)
        runtime = self.__dict__.get("virtual_host_runtime")
        if runtime is not None:
            runtime.refresh_model_bindings()
        self.config_changed.emit()
        return result


def _safe_live2d_error(exc: Exception) -> str:
    text = str(exc).strip().replace("\n", " ")
    return text[:240] if text else exc.__class__.__name__
