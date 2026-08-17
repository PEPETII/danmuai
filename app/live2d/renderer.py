"""Injectable render lifecycle; the concrete SDK and Qt window remain outside business code."""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Protocol

from .model_loader import ModelCapabilities


class Live2DRenderBackend(Protocol):
    """Opaque backend contract for a Qt/OpenGL + Live2D implementation."""

    def create_model(self, model_path: Path, capabilities: ModelCapabilities) -> Any: ...

    def get_parameter_sink(self, model: Any) -> Any: ...

    def update(self, model: Any, delta_sec: float) -> None: ...

    def render(self, model: Any) -> None: ...

    def show(self) -> None: ...

    def hide(self) -> None: ...

    def close_window(self) -> None: ...

    def destroy_model(self, model: Any) -> None: ...

    def dispose(self) -> None: ...


@dataclass(frozen=True)
class RendererState:
    phase: str = "idle"
    visible: bool = False
    loaded: bool = False
    error: str | None = None


class _TimerPort(Protocol):
    def start(self, interval_ms: int) -> None: ...

    def stop(self) -> None: ...


class Live2DRenderer:
    """Owns the render tick and guarantees teardown order around an opaque backend."""

    def __init__(
        self,
        backend: Live2DRenderBackend,
        *,
        timer_factory: Callable[[Callable[[], None]], _TimerPort] | None = None,
        frame_interval_ms: int = 16,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if frame_interval_ms <= 0:
            raise ValueError("frame_interval_ms must be positive")
        self._backend = backend
        self._timer_factory = timer_factory or _qt_timer_factory
        self._frame_interval_ms = frame_interval_ms
        self._clock = clock or time.monotonic
        self._timer: _TimerPort | None = None
        self._model: Any | None = None
        self._last_tick: float | None = None
        self._state = RendererState()
        self._window_closed_handler: Callable[[], None] | None = None
        self._backend_disposed = False

    @property
    def state(self) -> RendererState:
        return self._state

    @property
    def model_loaded(self) -> bool:
        return self._model is not None

    def set_window_closed_handler(self, handler: Callable[[], None] | None) -> None:
        self._window_closed_handler = handler

    def load_and_start(self, model_path: Path, capabilities: ModelCapabilities) -> bool:
        if self._model is not None:
            return self._state.phase == "running"
        self._state = RendererState("loading", False, False, None)
        try:
            self._model = self._backend.create_model(model_path, capabilities)
            if self._model is None:
                raise RuntimeError("backend returned no model")
            self._timer = self._timer_factory(self.tick)
            self._last_tick = self._clock()
            self._timer.start(self._frame_interval_ms)
        except Exception as exc:
            self._stop_timer()
            if self._model is not None:
                self._destroy_model()
            self._dispose_backend()
            self._state = RendererState("failed", False, False, _safe_error(exc))
            return False
        self._state = RendererState("running", False, True, None)
        return True

    def parameter_sink(self) -> Any | None:
        if self._model is None:
            return None
        return self._backend.get_parameter_sink(self._model)

    def tick(self) -> None:
        if self._model is None or self._state.phase != "running":
            return
        now = self._clock()
        delta = 0.0 if self._last_tick is None else max(0.0, now - self._last_tick)
        self._last_tick = now
        self._backend.update(self._model, delta)
        self._backend.render(self._model)

    def show(self) -> bool:
        if self._model is None or self._state.phase in {"closed", "failed"}:
            return False
        self._backend.show()
        self._state = RendererState(self._state.phase, True, True, self._state.error)
        return True

    def hide(self) -> bool:
        if self._model is None or self._state.phase in {"closed", "failed"}:
            return False
        self._backend.hide()
        self._state = RendererState(self._state.phase, False, True, self._state.error)
        return True

    def close(self) -> None:
        if self._state.phase == "closed":
            return
        self._stop_timer()
        self._destroy_model()
        try:
            self._backend.close_window()
        finally:
            self._dispose_backend()
            self._state = RendererState("closed", False, False, None)

    def handle_window_closed(self) -> None:
        self.close()
        if self._window_closed_handler is not None:
            self._window_closed_handler()

    def _stop_timer(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def _destroy_model(self) -> None:
        if self._model is None:
            return
        model = self._model
        self._model = None
        try:
            self._backend.destroy_model(model)
        finally:
            self._last_tick = None

    def _dispose_backend(self) -> None:
        if self._backend_disposed:
            return
        self._backend_disposed = True
        try:
            self._backend.dispose()
        except Exception:
            pass


class QtOpenGLLive2DBackend:
    """Adapter for an injected Qt window and SDK object; no SDK is bundled here."""

    def __init__(self, sdk_adapter: Any, window: Any) -> None:
        self._sdk = sdk_adapter
        self._window = window

    def create_model(self, model_path: Path, capabilities: ModelCapabilities) -> Any:
        return self._sdk.load_model(model_path, capabilities)

    def get_parameter_sink(self, model: Any) -> Any:
        return self._sdk.parameter_sink(model)

    def update(self, model: Any, delta_sec: float) -> None:
        self._sdk.update(model, delta_sec)

    def render(self, model: Any) -> None:
        self._sdk.render(model)

    def show(self) -> None:
        self._window.show()

    def hide(self) -> None:
        self._window.hide()

    def close_window(self) -> None:
        self._window.close()

    def destroy_model(self, model: Any) -> None:
        self._sdk.destroy_model(model)

    def dispose(self) -> None:
        self._sdk.dispose()


def _qt_timer_factory(callback: Callable[[], None]) -> _TimerPort:
    from PyQt6.QtCore import QTimer

    timer = QTimer()
    timer.timeout.connect(callback)
    return timer


def _safe_error(exc: Exception) -> str:
    text = str(exc).strip()
    return text[:240] if text else exc.__class__.__name__
