"""DanmuApp façade for external Live2D model selection."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.live2d.model_registry import LIVE2D_MODEL_ID_KEY, Live2DModelRegistry

if TYPE_CHECKING:
    from app.live2d.desktop_runtime import Live2DDesktopRuntime


class DanmuAppLive2DMixin:
    def _live2d_click_through_enabled(self) -> bool:
        return str(self.config.get("live2d_click_through", "0") or "0").strip() == "1"

    def _sync_live2d_click_through(self) -> None:
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is None:
            return
        runtime.set_click_through(self._live2d_click_through_enabled())

    def _get_live2d_model_registry(self) -> Live2DModelRegistry:
        registry = self.__dict__.get("_live2d_registry")
        if registry is None:
            registry = Live2DModelRegistry(
                self.config,
                on_config_changed=self.config_changed.emit,
            )
            self.__dict__["_live2d_registry"] = registry
        return registry

    def _current_live2d_model_id(self) -> str:
        return str(self.config.get(LIVE2D_MODEL_ID_KEY, "") or "").strip()

    def _live2d_display_scale_percent(self) -> int:
        from app.live2d.display_scale import get_model_display_scale_percent

        return get_model_display_scale_percent(self.config, self._current_live2d_model_id())

    def _sync_live2d_display_scale(self) -> None:
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is None:
            return
        runtime.set_display_scale_percent(self._live2d_display_scale_percent())

    def _attach_live2d_display_scale(self, snapshot: dict[str, object]) -> dict[str, object]:
        from app.live2d.display_scale import export_display_scale_settings

        return {
            **snapshot,
            **export_display_scale_settings(self.config, self._current_live2d_model_id()),
        }

    def get_live2d_model_snapshot(self) -> dict[str, object]:
        snapshot = self._attach_live2d_display_scale(self._get_live2d_model_registry().snapshot())
        snapshot["click_through"] = self._live2d_click_through_enabled()
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is not None:
            runtime_snapshot = runtime.snapshot()
            snapshot["runtime_status"] = runtime_snapshot.get("runtime_status", "stopped")
            snapshot["click_through"] = bool(runtime_snapshot.get("click_through"))
            if runtime_snapshot.get("runtime_status") == "running":
                snapshot["desktop_visible"] = bool(runtime_snapshot.get("desktop_visible"))
                snapshot["capabilities"] = {
                    **dict(snapshot.get("capabilities") or {}),
                    **dict(runtime_snapshot.get("capabilities") or {}),
                }
            else:
                snapshot["desktop_visible"] = False
        return snapshot

    def apply_live2d_settings_patch(self, patch: dict) -> dict[str, object]:
        if not isinstance(patch, dict):
            raise ValueError("invalid_payload")
        items: dict[str, str] = {}
        if "click_through" in patch and patch["click_through"] is not None:
            enabled = bool(patch["click_through"])
            items["live2d_click_through"] = "1" if enabled else "0"
        if "display_scale_percent" in patch and patch["display_scale_percent"] is not None:
            from app.live2d.display_scale import set_model_display_scale_percent

            model_id = self._current_live2d_model_id()
            if not model_id:
                raise ValueError("live2d_model_not_configured")
            set_model_display_scale_percent(
                self.config,
                model_id,
                patch["display_scale_percent"],
            )
            self._sync_live2d_display_scale()
        if items:
            self.config.set_batch(items)
            self._sync_live2d_click_through()
            self.config_changed.emit()
        elif "display_scale_percent" in patch and patch["display_scale_percent"] is not None:
            self.config_changed.emit()
        return self.get_live2d_model_snapshot()

    def _get_live2d_desktop_runtime(self) -> Live2DDesktopRuntime:
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is None:
            from app.live2d.desktop_runtime import Live2DDesktopRuntime

            runtime = Live2DDesktopRuntime()
            self.__dict__["_live2d_desktop_runtime"] = runtime
        return runtime

    def import_live2d_model_via_dialog(self) -> dict[str, object]:
        virtual_host_runtime = self.__dict__.get("virtual_host_runtime")
        if virtual_host_runtime is not None:
            virtual_host_runtime.stop()
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is not None:
            runtime.stop()
        return self._get_live2d_model_registry().import_model_via_dialog()

    def import_live2d_model_file_via_dialog(self) -> dict[str, object]:
        virtual_host_runtime = self.__dict__.get("virtual_host_runtime")
        if virtual_host_runtime is not None:
            virtual_host_runtime.stop()
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is not None:
            runtime.stop()
        return self._get_live2d_model_registry().import_model_file_via_dialog()

    def open_live2d_models_folder(self) -> dict[str, object]:
        from app.live2d.model_storage import open_models_root_directory

        return open_models_root_directory()

    def select_live2d_model(self, model_id: str) -> dict[str, object]:
        virtual_host_runtime = self.__dict__.get("virtual_host_runtime")
        if virtual_host_runtime is not None:
            virtual_host_runtime.stop()
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is not None:
            runtime.stop()
        return self._get_live2d_model_registry().select_model(model_id)

    def clear_live2d_model(self) -> dict[str, object]:
        virtual_host_runtime = self.__dict__.get("virtual_host_runtime")
        if virtual_host_runtime is not None:
            virtual_host_runtime.stop()
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is not None:
            runtime.stop()
        return self._get_live2d_model_registry().clear_model()

    def start_live2d_model(self) -> dict[str, object]:
        registry = self._get_live2d_model_registry()
        registry_snapshot = registry.start_model()
        model_path = str(self.config.get("live2d_model_path", "") or "").strip()
        runtime = self._get_live2d_desktop_runtime()
        runtime.set_click_through(self._live2d_click_through_enabled())
        runtime.set_display_scale_percent(self._live2d_display_scale_percent())
        try:
            runtime_snapshot = runtime.start(model_path)
        except Exception as exc:
            registry.stop_model()
            raise ValueError(f"desktop_runtime_failed:{_safe_live2d_error(exc)}") from exc
        ensure = getattr(self, "_ensure_virtual_host_runtime", None)
        if callable(ensure):
            ensure()
        virtual_host_runtime = self.__dict__.get("virtual_host_runtime")
        if virtual_host_runtime is not None:
            attach = getattr(virtual_host_runtime, "attach_live2d_runtime", None)
            if callable(attach):
                attach(self._get_live2d_desktop_runtime())
            virtual_host_runtime.start()
        return self._attach_live2d_display_scale({
            **registry_snapshot,
            **runtime_snapshot,
            "desktop_visible": bool(runtime_snapshot.get("desktop_visible")),
            "click_through": bool(runtime_snapshot.get("click_through")),
            "capabilities": {
                **dict(registry_snapshot.get("capabilities") or {}),
                **dict(runtime_snapshot.get("capabilities") or {}),
            },
        })

    def stop_live2d_model(self) -> dict[str, object]:
        virtual_host_runtime = self.__dict__.get("virtual_host_runtime")
        if virtual_host_runtime is not None:
            virtual_host_runtime.stop()
        runtime = self.__dict__.get("_live2d_desktop_runtime")
        if runtime is not None:
            runtime.stop()
        snapshot = self._attach_live2d_display_scale(self._get_live2d_model_registry().stop_model())
        snapshot["desktop_visible"] = False
        snapshot["click_through"] = self._live2d_click_through_enabled()
        return snapshot

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

    def get_virtual_host_settings(self) -> dict[str, object]:
        from app.virtual_host.mode_config import (
            export_virtual_host_mode_settings,
            sanitize_virtual_host_mode_settings,
        )

        sanitize_virtual_host_mode_settings(self.config, persist=True)
        snapshot: dict[str, object] = dict(export_virtual_host_mode_settings(self.config))
        runtime = self.__dict__.get("virtual_host_runtime")
        if runtime is not None:
            snapshot["runtime_status"] = "running" if runtime.running else "stopped"
            snapshot["runtime_generation"] = runtime.runtime_generation
        return snapshot

    def apply_virtual_host_settings(self, patch: dict) -> dict[str, object]:
        from app.virtual_host.mode_config import apply_virtual_host_mode_settings

        apply_virtual_host_mode_settings(self.config, patch)
        runtime = self.__dict__.get("virtual_host_runtime")
        if runtime is not None:
            runtime.refresh_mode_settings()
        self.config_changed.emit()
        return self.get_virtual_host_settings()

    def get_virtual_host_voice_status(self) -> dict[str, object]:
        runtime = self.__dict__.get("virtual_host_runtime")
        from app.virtual_host.voice_status import export_voice_status

        return export_voice_status(runtime, self)

    def get_virtual_host_speech_logs(self) -> dict[str, object]:
        runtime = self.__dict__.get("virtual_host_runtime")
        return {"items": runtime.get_speech_logs() if runtime is not None else []}

    def start_virtual_host_voice(self) -> dict[str, object]:
        runtime = self.__dict__.get("virtual_host_runtime")
        if runtime is None:
            raise ValueError("runtime_unavailable")
        return runtime.start_voice_session()

    def stop_virtual_host_voice(self) -> dict[str, object]:
        runtime = self.__dict__.get("virtual_host_runtime")
        if runtime is None:
            raise ValueError("runtime_unavailable")
        return runtime.stop_voice_session()

    def cancel_virtual_host_voice(self) -> dict[str, object]:
        runtime = self.__dict__.get("virtual_host_runtime")
        if runtime is None:
            raise ValueError("runtime_unavailable")
        return runtime.cancel_voice_session()

    def get_virtual_host_persona_config(self) -> dict[str, object]:
        from app.virtual_host.persona_config import (
            export_virtual_host_persona_config,
            sanitize_virtual_host_persona_config,
        )

        sanitize_virtual_host_persona_config(self.config, persist=True)
        return export_virtual_host_persona_config(self.config)

    def apply_virtual_host_persona_config(
        self,
        patch: dict,
        *,
        reset: bool = False,
    ) -> dict[str, object]:
        from app.virtual_host.persona_config import apply_virtual_host_persona_config

        result = apply_virtual_host_persona_config(self.config, patch, reset=reset)
        self.config_changed.emit()
        return result


def _safe_live2d_error(exc: Exception) -> str:
    text = str(exc).strip().replace("\n", " ")
    return text[:240] if text else exc.__class__.__name__
