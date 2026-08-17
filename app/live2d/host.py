"""Main-thread-only facade for the isolated Live2D runtime candidate."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .model_loader import Live2DModelLoader, ModelCapabilities
from .parameters import Live2DParameterController, ParameterUpdate
from .renderer import Live2DRenderer


@dataclass(frozen=True)
class HostState:
    phase: str = "idle"
    visible: bool = False
    model_path: str | None = None
    error: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class HostResult:
    ok: bool
    status: str
    state: HostState
    reason: str | None = None


class Live2DHostFacade:
    """Public port for DanmuApp/Web integration after the 001 gate is passed.

    The owner thread is captured at construction. Calls from HTTP/worker threads
    must use the injected ``main_thread_invoker`` (for example the existing
    WebConsoleBridge); without it they fail before touching the renderer.
    """

    def __init__(
        self,
        loader: Live2DModelLoader,
        renderer_factory: Callable[[], Live2DRenderer],
        *,
        main_thread_invoker: Callable[[Callable[[], Any]], Any] | None = None,
    ) -> None:
        self._loader = loader
        self._renderer_factory = renderer_factory
        self._main_thread_invoker = main_thread_invoker
        self._owner_thread_id = threading.get_ident()
        self._renderer: Live2DRenderer | None = None
        self._controller: Live2DParameterController | None = None
        self._capabilities = ModelCapabilities()
        self._state = HostState()

    @property
    def state(self) -> HostState:
        return self._state

    def start(self, model_path: str | Path) -> HostResult:
        return self._dispatch(lambda: self._start_on_main(model_path))

    def stop(self) -> HostResult:
        return self._dispatch(self._stop_on_main)

    def show(self) -> HostResult:
        return self._dispatch(self._show_on_main)

    def hide(self) -> HostResult:
        return self._dispatch(self._hide_on_main)

    def close(self) -> HostResult:
        return self._dispatch(self._close_on_main)

    quit = close

    def handle_window_closed(self) -> HostResult:
        """Called by the injected window after it closes independently."""

        return self._dispatch(self._window_closed_on_main)

    def set_parameter(self, parameter_id: str, value: float) -> ParameterUpdate:
        return self._dispatch(
            lambda: self._set_parameter_on_main(parameter_id, value),
            on_thread_violation=lambda: ParameterUpdate(
                parameter_id, "unavailable", reason="thread_violation"
            ),
        )

    def animate_parameter(
        self,
        parameter_id: str,
        target: float,
        duration_sec: float,
        *,
        recover: bool = True,
    ) -> ParameterUpdate:
        return self._dispatch(
            lambda: self._animate_parameter_on_main(
                parameter_id, target, duration_sec, recover=recover
            ),
            on_thread_violation=lambda: ParameterUpdate(
                parameter_id, "unavailable", reason="thread_violation"
            ),
        )

    def tick_parameters(self, now: float | None = None) -> tuple[ParameterUpdate, ...]:
        return self._dispatch(
            lambda: self._tick_parameters_on_main(now),
            on_thread_violation=lambda: (),
        )

    def _dispatch(
        self,
        operation: Callable[[], Any],
        *,
        on_thread_violation: Callable[[], Any] | None = None,
    ) -> Any:
        if threading.get_ident() == self._owner_thread_id:
            return operation()
        if self._main_thread_invoker is None:
            if on_thread_violation is not None:
                return on_thread_violation()
            return self._thread_violation_result()
        return self._main_thread_invoker(operation)

    def _thread_violation_result(self) -> HostResult:
        return HostResult(False, "thread_violation", self._state, "thread_violation")

    def _start_on_main(self, model_path: str | Path) -> HostResult:
        if self._renderer is not None and self._state.phase == "running":
            return HostResult(True, "already_running", self._state)
        loaded = self._loader.load(model_path)
        if not loaded.ok:
            self._state = HostState(
                "failed", False, loaded.model_path, loaded.error, loaded.reason
            )
            return HostResult(False, "load_failed", self._state, loaded.reason)
        path, path_reason = self._loader.validate_path(model_path)
        if path is None:
            self._state = HostState("failed", False, loaded.model_path, "model path invalid", path_reason)
            return HostResult(False, "load_failed", self._state, path_reason)
        renderer = self._renderer_factory()
        if not renderer.load_and_start(path, loaded.capabilities):
            error = renderer.state.error or "renderer failed to start"
            self._state = HostState("failed", False, loaded.model_path, error, "renderer_load_failed")
            renderer.close()
            return HostResult(False, "renderer_failed", self._state, "renderer_load_failed")
        self._renderer = renderer
        self._capabilities = loaded.capabilities
        sink = renderer.parameter_sink()
        self._controller = (
            Live2DParameterController(loaded.capabilities.parameter_specs, sink)
            if sink is not None
            else None
        )
        renderer.set_window_closed_handler(self._on_renderer_window_closed)
        self._state = HostState("running", False, loaded.model_path)
        return HostResult(True, "started", self._state)

    def _stop_on_main(self) -> HostResult:
        if self._renderer is None:
            if self._state.phase == "closed":
                return HostResult(True, "already_stopped", self._state)
            self._state = HostState("stopped", False, self._state.model_path)
            return HostResult(True, "already_stopped", self._state)
        self._renderer.close()
        self._renderer = None
        self._controller = None
        self._state = HostState("stopped", False, self._state.model_path)
        return HostResult(True, "stopped", self._state)

    def _show_on_main(self) -> HostResult:
        if self._renderer is None:
            return HostResult(False, "not_loaded", self._state, "not_loaded")
        if self._state.visible:
            return HostResult(True, "already_visible", self._state)
        if not self._renderer.show():
            return HostResult(False, "show_failed", self._state, "renderer_not_running")
        self._state = HostState("running", True, self._state.model_path)
        return HostResult(True, "shown", self._state)

    def _hide_on_main(self) -> HostResult:
        if self._renderer is None:
            return HostResult(False, "not_loaded", self._state, "not_loaded")
        if not self._state.visible:
            return HostResult(True, "already_hidden", self._state)
        if not self._renderer.hide():
            return HostResult(False, "hide_failed", self._state, "renderer_not_running")
        self._state = HostState("running", False, self._state.model_path)
        return HostResult(True, "hidden", self._state)

    def _close_on_main(self) -> HostResult:
        result = self._stop_on_main()
        self._state = HostState("closed", False, self._state.model_path)
        return HostResult(True, "closed" if result.status != "already_stopped" else "already_closed", self._state)

    def _window_closed_on_main(self) -> HostResult:
        if self._renderer is not None:
            self._renderer.close()
            self._renderer = None
        self._controller = None
        self._state = HostState("closed", False, self._state.model_path, reason="window_closed")
        return HostResult(True, "window_closed", self._state, "window_closed")

    def _on_renderer_window_closed(self) -> None:
        self._window_closed_on_main()

    def _set_parameter_on_main(self, parameter_id: str, value: float) -> ParameterUpdate:
        if self._controller is None:
            return ParameterUpdate(parameter_id, "unavailable", reason="model_not_loaded")
        return self._controller.set_value(parameter_id, value)

    def _animate_parameter_on_main(
        self,
        parameter_id: str,
        target: float,
        duration_sec: float,
        *,
        recover: bool,
    ) -> ParameterUpdate:
        if self._controller is None:
            return ParameterUpdate(parameter_id, "unavailable", reason="model_not_loaded")
        return self._controller.animate(parameter_id, target, duration_sec, recover=recover)

    def _tick_parameters_on_main(self, now: float | None) -> tuple[ParameterUpdate, ...]:
        if self._controller is None:
            return ()
        return self._controller.tick(now)
