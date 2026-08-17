"""Pure parameter animation controller for the Live2D runtime boundary."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

from .model_loader import ParameterSpec


class ParameterSink(Protocol):
    def get_parameter_value(self, parameter_id: str) -> float: ...

    def set_parameter_value(self, parameter_id: str, value: float) -> None: ...


@dataclass(frozen=True)
class ParameterUpdate:
    parameter_id: str
    status: str
    value: float | None = None
    target: float | None = None
    clamped: bool = False
    reason: str | None = None


@dataclass
class _Animation:
    spec: ParameterSpec
    start: float
    target: float
    started_at: float
    duration_sec: float
    recover: bool


def clamp(value: float, spec: ParameterSpec) -> float:
    return min(spec.maximum, max(spec.minimum, value))


def interpolate(start: float, target: float, progress: float) -> float:
    bounded = min(1.0, max(0.0, progress))
    return start + (target - start) * bounded


class Live2DParameterController:
    """Maps semantic callers to discovered parameters without exposing a model object."""

    def __init__(
        self,
        specs: tuple[ParameterSpec, ...] | list[ParameterSpec],
        sink: ParameterSink,
        *,
        clock=time.monotonic,
    ) -> None:
        self._specs = {spec.parameter_id: spec for spec in specs}
        self._sink = sink
        self._clock = clock
        self._animations: dict[str, _Animation] = {}

    def set_value(self, parameter_id: str, value: float) -> ParameterUpdate:
        spec = self._specs.get(parameter_id)
        if spec is None:
            return ParameterUpdate(parameter_id, "unsupported", reason="parameter_not_found")
        bounded = clamp(float(value), spec)
        self._sink.set_parameter_value(parameter_id, bounded)
        self._animations.pop(parameter_id, None)
        return ParameterUpdate(
            parameter_id,
            "applied",
            value=bounded,
            target=bounded,
            clamped=bounded != float(value),
        )

    def animate(
        self,
        parameter_id: str,
        target: float,
        duration_sec: float,
        *,
        recover: bool = True,
        now: float | None = None,
    ) -> ParameterUpdate:
        spec = self._specs.get(parameter_id)
        if spec is None:
            return ParameterUpdate(parameter_id, "unsupported", reason="parameter_not_found")
        if duration_sec <= 0:
            return ParameterUpdate(parameter_id, "invalid", reason="duration_must_be_positive")
        requested_target = float(target)
        bounded_target = clamp(requested_target, spec)
        current = clamp(float(self._sink.get_parameter_value(parameter_id)), spec)
        self._animations[parameter_id] = _Animation(
            spec=spec,
            start=current,
            target=bounded_target,
            started_at=self._clock() if now is None else now,
            duration_sec=float(duration_sec),
            recover=recover,
        )
        return ParameterUpdate(
            parameter_id,
            "scheduled",
            value=current,
            target=bounded_target,
            clamped=bounded_target != requested_target,
        )

    def tick(self, now: float | None = None) -> tuple[ParameterUpdate, ...]:
        timestamp = self._clock() if now is None else now
        completed: list[ParameterUpdate] = []
        for parameter_id, animation in tuple(self._animations.items()):
            elapsed = max(0.0, timestamp - animation.started_at)
            if elapsed < animation.duration_sec:
                value = interpolate(animation.start, animation.target, elapsed / animation.duration_sec)
                self._sink.set_parameter_value(parameter_id, clamp(value, animation.spec))
                continue
            if not animation.recover:
                self._sink.set_parameter_value(parameter_id, animation.target)
                self._animations.pop(parameter_id, None)
                completed.append(ParameterUpdate(parameter_id, "completed", value=animation.target))
                continue
            recovery_elapsed = elapsed - animation.duration_sec
            if recovery_elapsed < animation.duration_sec:
                value = interpolate(animation.target, animation.spec.default, recovery_elapsed / animation.duration_sec)
                self._sink.set_parameter_value(parameter_id, clamp(value, animation.spec))
                continue
            recovery = clamp(animation.spec.default, animation.spec)
            self._sink.set_parameter_value(parameter_id, recovery)
            self._animations.pop(parameter_id, None)
            completed.append(ParameterUpdate(parameter_id, "recovered", value=recovery))
        return tuple(completed)

    def cancel(self, parameter_id: str, *, recover: bool = True) -> ParameterUpdate:
        animation = self._animations.pop(parameter_id, None)
        if animation is None:
            return ParameterUpdate(parameter_id, "idle", reason="no_animation")
        value = clamp(animation.spec.default, animation.spec) if recover else None
        if value is not None:
            self._sink.set_parameter_value(parameter_id, value)
        return ParameterUpdate(parameter_id, "cancelled", value=value)

    @property
    def active_parameter_ids(self) -> tuple[str, ...]:
        return tuple(self._animations)
