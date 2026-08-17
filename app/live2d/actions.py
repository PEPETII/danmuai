"""Candidate-only semantic Live2D action adapter.

The adapter deliberately stops at the parameter-controller boundary.  Semantic
action payloads are allow-listed here, model parameter IDs are resolved against
the current ``ParameterSpec`` set, and the injected controller is only touched
from the owner thread (or through an injected dispatcher).
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from app.virtual_host.playback import PlaybackEvent, PlaybackQueue

from .model_loader import ModelCapabilities, ParameterSpec
from .parameters import Live2DParameterController, ParameterUpdate

ActionLayer = Literal["idle", "speech-lip-sync", "emotion", "one-shot"]

SUPPORTED_ACTIONS = frozenset({"set_emotion", "set_parameter", "play_reaction"})
MAX_ACTION_DURATION_SECONDS = 30.0
MIN_ACTION_DURATION_SECONDS = 0.05


# These are managed aliases, not a pass-through from model/user input.  An
# alias is usable only when one of its exact IDs exists in the current model's
# discovered ParameterSpec set.
DEFAULT_PARAMETER_ALIASES: dict[str, tuple[str, ...]] = {
    "mouth_open": ("ParamMouthOpenY", "MouthOpenY", "MouthOpen"),
    "mouth_form": ("ParamMouthForm", "MouthForm"),
    "angle_x": ("ParamAngleX", "AngleX"),
    "angle_y": ("ParamAngleY", "AngleY"),
    "angle_z": ("ParamAngleZ", "AngleZ"),
    "eye_open": ("ParamEyeLOpen", "ParamEyeROpen", "EyeOpen"),
    "eye_ball_x": ("ParamEyeBallX", "EyeBallX"),
    "eye_ball_y": ("ParamEyeBallY", "EyeBallY"),
    "brow_form": ("ParamBrowLY", "ParamBrowRY", "BrowForm"),
    "body_angle_x": ("ParamBodyAngleX", "BodyAngleX"),
    "body_angle_y": ("ParamBodyAngleY", "BodyAngleY"),
    "body_angle_z": ("ParamBodyAngleZ", "BodyAngleZ"),
}

DEFAULT_EMOTION_MAP: dict[str, dict[str, float]] = {
    "happy": {"mouth_form": 1.0},
    "sad": {"mouth_form": -1.0},
    "angry": {"brow_form": -1.0, "mouth_form": -0.5},
    "surprised": {"mouth_open": 1.0, "eye_open": 1.0},
    "nervous": {"angle_z": 0.5},
}

DEFAULT_REACTION_MAP: dict[str, dict[str, float]] = {
    "nod": {"angle_y": 1.0},
    "shake": {"angle_x": 1.0},
    "blink": {"eye_open": -1.0},
    "breath": {"body_angle_y": 1.0},
}


class ParameterControllerPort(Protocol):
    """The narrow controlled layer needed by this candidate adapter."""

    def set_value(self, parameter_id: str, value: float) -> ParameterUpdate: ...


@dataclass(frozen=True)
class ParameterBinding:
    """A managed logical name and its candidate model parameter ID."""

    logical_name: str
    parameter_id: str


@dataclass(frozen=True)
class ActionResult:
    """Structured action outcome; callers never receive an exception for bad input."""

    ok: bool
    status: str
    action: str
    action_id: str = ""
    logical_name: str = ""
    parameter_id: str = ""
    layer: str = ""
    clamped: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class IdleChannel:
    logical_name: str
    amplitude: float
    period_seconds: float
    phase: float = 0.0


@dataclass
class _LayerEntry:
    action_id: str
    logical_name: str
    parameter_id: str
    layer: ActionLayer
    target: float
    expires_at: float | None
    sequence: int


def _safe_number(value: object, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field}_must_be_number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field}_must_be_finite")
    return number


def _bounded(value: object, minimum: float, maximum: float, *, field: str) -> tuple[float, bool]:
    number = _safe_number(value, field=field)
    bounded = min(maximum, max(minimum, number))
    return bounded, bounded != number


def _normalize_name(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field}_must_be_string")
    name = " ".join(value.split())
    if not name or len(name) > 64:
        raise ValueError(f"{field}_invalid")
    return name


def _coerce_aliases(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        values: Iterable[object] = (value,)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, Mapping)):
        values = value
    else:
        return ()
    result: list[str] = []
    for item in values:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if item and item not in result:
            result.append(item)
    return tuple(result)


class Live2DActionAdapter:
    """Resolve semantic actions into layered, time-bounded parameter updates.

    ``tick`` is the only method that writes through the controller.  The
    adapter captures an owner thread at construction; callers from an HTTP/LLM
    thread must provide ``main_thread_invoker`` or the write is rejected before
    reaching the injected controller/sink.
    """

    _LAYER_PRIORITY: dict[ActionLayer, int] = {
        "idle": 0,
        "speech-lip-sync": 1,
        "emotion": 2,
        "one-shot": 3,
    }

    def __init__(
        self,
        controller: ParameterControllerPort | Live2DParameterController | None,
        specs: Iterable[ParameterSpec] | None = None,
        *,
        capabilities: ModelCapabilities | None = None,
        parameter_map: Mapping[str, str | Iterable[str] | ParameterBinding] | None = None,
        emotion_map: Mapping[str, Mapping[str, float]] | None = None,
        reaction_map: Mapping[str, Mapping[str, float]] | None = None,
        playback_queue: PlaybackQueue | None = None,
        main_thread_invoker: Callable[[Callable[[], Any]], Any] | None = None,
        clock: Callable[[], float] = time.monotonic,
        idle_tick_interval_seconds: float = 0.1,
        lip_release_seconds: float = 0.25,
    ) -> None:
        if capabilities is not None:
            if specs is not None:
                raise ValueError("specs and capabilities are mutually exclusive")
            specs = capabilities.parameter_specs
        if idle_tick_interval_seconds <= 0 or lip_release_seconds <= 0:
            raise ValueError("tick intervals must be positive")

        self._controller = controller
        self._specs = {spec.parameter_id: spec for spec in (specs or ())}
        self._parameter_map = self._build_parameter_map(parameter_map)
        self._emotion_map = self._build_action_map(emotion_map, DEFAULT_EMOTION_MAP)
        self._reaction_map = self._build_action_map(reaction_map, DEFAULT_REACTION_MAP)
        self._main_thread_invoker = main_thread_invoker
        self._owner_thread_id = threading.get_ident()
        self._clock = clock
        self._idle_tick_interval = float(idle_tick_interval_seconds)
        self._lip_release_seconds = float(lip_release_seconds)
        self._entries: dict[str, list[_LayerEntry]] = {}
        self._sequence = 0
        self._next_action_number = 1
        self._idle_channels: dict[str, IdleChannel] = {}
        self._idle_values: dict[str, float] = {}
        self._last_idle_tick: float | None = None
        self._last_output: dict[str, float] = {}
        self._speech_active = False
        self._speech_started_at: float | None = None
        self._speech_release_started_at: float | None = None
        self._speech_level_value: float | None = None
        self._attached_playback_queue: PlaybackQueue | None = None
        self.last_failure: str | None = None
        if playback_queue is not None:
            self.attach_playback_queue(playback_queue)

    @staticmethod
    def _build_parameter_map(
        overrides: Mapping[str, str | Iterable[str] | ParameterBinding] | None,
    ) -> dict[str, tuple[str, ...]]:
        result = dict(DEFAULT_PARAMETER_ALIASES)
        for raw_logical, raw_value in (overrides or {}).items():
            logical = _normalize_name(raw_logical, field="logical_name")
            if isinstance(raw_value, ParameterBinding):
                aliases = (raw_value.parameter_id.strip(),)
            else:
                aliases = _coerce_aliases(raw_value)
            if aliases:
                result[logical] = aliases
        return result

    @staticmethod
    def _build_action_map(
        overrides: Mapping[str, Mapping[str, float]] | None,
        defaults: Mapping[str, Mapping[str, float]],
    ) -> dict[str, dict[str, float]]:
        result = {name: dict(values) for name, values in defaults.items()}
        for raw_name, raw_values in (overrides or {}).items():
            name = _normalize_name(raw_name, field="action_name")
            if not isinstance(raw_values, Mapping):
                continue
            effects: dict[str, float] = {}
            for raw_logical, raw_scale in raw_values.items():
                try:
                    logical = _normalize_name(raw_logical, field="logical_name")
                    scale, _ = _bounded(raw_scale, -1.0, 1.0, field="scale")
                except (TypeError, ValueError):
                    continue
                effects[logical] = scale
            if effects:
                result[name] = effects
        return result

    @property
    def model_loaded(self) -> bool:
        return self._controller is not None

    @property
    def speech_lip_sync_active(self) -> bool:
        return self._speech_active

    @property
    def managed_parameter_ids(self) -> dict[str, str]:
        return {
            logical: binding.parameter_id
            for logical in self._parameter_map
            if (binding := self._resolve(logical)) is not None
        }

    def _new_action_id(self, prefix: str) -> str:
        action_id = f"{prefix}-{self._next_action_number}"
        self._next_action_number += 1
        return action_id

    def _resolve(self, logical_name: str) -> ParameterBinding | None:
        aliases = self._parameter_map.get(logical_name)
        if aliases is None:
            return None
        for parameter_id in aliases:
            if parameter_id in self._specs:
                return ParameterBinding(logical_name, parameter_id)
        return None

    def _unavailable(self, action: str) -> ActionResult | None:
        if self._controller is None:
            return ActionResult(False, "unavailable", action, reason="model_not_loaded")
        if not self._specs:
            return ActionResult(False, "unavailable", action, reason="parameter_specs_unavailable")
        return None

    def _duration(self, value: object) -> tuple[float, bool]:
        return _bounded(
            value,
            MIN_ACTION_DURATION_SECONDS,
            MAX_ACTION_DURATION_SECONDS,
            field="duration",
        )

    def _target_from_effect(self, spec: ParameterSpec, intensity: float, scale: float) -> float:
        if scale >= 0:
            return spec.default + (spec.maximum - spec.default) * intensity * scale
        return spec.default + (spec.minimum - spec.default) * intensity * abs(scale)

    def _clear_layer(self, layer: ActionLayer) -> None:
        for action_id in tuple(self._entries):
            entries = [entry for entry in self._entries[action_id] if entry.layer != layer]
            if entries:
                self._entries[action_id] = entries
            else:
                del self._entries[action_id]

    def _add_entry(
        self,
        *,
        action_id: str,
        logical_name: str,
        binding: ParameterBinding,
        layer: ActionLayer,
        target: float,
        expires_at: float | None,
    ) -> None:
        self._sequence += 1
        self._entries.setdefault(action_id, []).append(
            _LayerEntry(
                action_id,
                logical_name,
                binding.parameter_id,
                layer,
                target,
                expires_at,
                self._sequence,
            )
        )

    def set_emotion(
        self,
        name: object,
        intensity: object = 0.5,
        duration: object = 1.0,
    ) -> ActionResult:
        action = "set_emotion"
        try:
            emotion_name = _normalize_name(name, field="emotion_name")
            effects = self._emotion_map.get(emotion_name)
            if effects is None:
                return ActionResult(False, "unsupported", action, reason="emotion_not_allowed")
            unavailable = self._unavailable(action)
            if unavailable is not None:
                return unavailable
            bounded_intensity, intensity_clamped = _bounded(
                intensity, 0.0, 1.0, field="intensity"
            )
            bounded_duration, duration_clamped = self._duration(duration)
            resolved = [
                (logical, binding, self._specs[binding.parameter_id], scale)
                for logical, scale in effects.items()
                if (binding := self._resolve(logical)) is not None
            ]
            if not resolved:
                return ActionResult(False, "unsupported", action, reason="emotion_parameters_missing")
            action_id = self._new_action_id("emotion")
            self._clear_layer("emotion")
            expires_at = self._clock() + bounded_duration
            for logical, binding, spec, scale in resolved:
                self._add_entry(
                    action_id=action_id,
                    logical_name=logical,
                    binding=binding,
                    layer="emotion",
                    target=self._target_from_effect(spec, bounded_intensity, scale),
                    expires_at=expires_at,
                )
            return ActionResult(
                True,
                "scheduled",
                action,
                action_id,
                layer="emotion",
                clamped=intensity_clamped or duration_clamped,
                reason="partial_parameter_mapping" if len(resolved) != len(effects) else None,
            )
        except (TypeError, ValueError) as exc:
            return ActionResult(False, "rejected", action, reason=str(exc))
        except Exception as exc:
            return ActionResult(False, "rejected", action, reason=f"action_failed:{type(exc).__name__}")

    def set_parameter(
        self,
        logical_name: object,
        value: object,
        duration: object = 1.0,
        restore: object = True,
    ) -> ActionResult:
        action = "set_parameter"
        try:
            logical = _normalize_name(logical_name, field="logical_name")
            binding = self._resolve(logical)
            if binding is None:
                reason = "logical_name_not_allowed" if logical not in self._parameter_map else "parameter_not_found"
                return ActionResult(False, "unsupported", action, logical_name=logical, reason=reason)
            unavailable = self._unavailable(action)
            if unavailable is not None:
                return unavailable
            spec = self._specs[binding.parameter_id]
            bounded_value, value_clamped = _bounded(
                value, spec.minimum, spec.maximum, field="value"
            )
            bounded_duration, duration_clamped = self._duration(duration)
            if not isinstance(restore, bool):
                raise ValueError("restore_must_be_boolean")
            action_id = self._new_action_id("parameter")
            self._add_entry(
                action_id=action_id,
                logical_name=logical,
                binding=binding,
                layer="emotion",
                target=bounded_value,
                expires_at=self._clock() + bounded_duration if restore else None,
            )
            return ActionResult(
                True,
                "scheduled",
                action,
                action_id,
                logical,
                binding.parameter_id,
                "emotion",
                value_clamped or duration_clamped,
            )
        except (TypeError, ValueError) as exc:
            return ActionResult(False, "rejected", action, reason=str(exc))
        except Exception as exc:
            return ActionResult(False, "rejected", action, reason=f"action_failed:{type(exc).__name__}")

    def play_reaction(
        self,
        name: object,
        intensity: object = 0.5,
        duration: object = 1.0,
    ) -> ActionResult:
        action = "play_reaction"
        try:
            reaction_name = _normalize_name(name, field="reaction_name")
            effects = self._reaction_map.get(reaction_name)
            if effects is None:
                return ActionResult(False, "unsupported", action, reason="reaction_not_allowed")
            unavailable = self._unavailable(action)
            if unavailable is not None:
                return unavailable
            bounded_intensity, intensity_clamped = _bounded(
                intensity, 0.0, 1.0, field="intensity"
            )
            bounded_duration, duration_clamped = self._duration(duration)
            resolved = [
                (logical, binding, self._specs[binding.parameter_id], scale)
                for logical, scale in effects.items()
                if (binding := self._resolve(logical)) is not None
            ]
            if not resolved:
                return ActionResult(False, "unsupported", action, reason="reaction_parameters_missing")
            action_id = self._new_action_id("reaction")
            self._clear_layer("one-shot")
            expires_at = self._clock() + bounded_duration
            for logical, binding, spec, scale in resolved:
                self._add_entry(
                    action_id=action_id,
                    logical_name=logical,
                    binding=binding,
                    layer="one-shot",
                    target=self._target_from_effect(spec, bounded_intensity, scale),
                    expires_at=expires_at,
                )
            return ActionResult(
                True,
                "scheduled",
                action,
                action_id,
                layer="one-shot",
                clamped=intensity_clamped or duration_clamped,
                reason="partial_parameter_mapping" if len(resolved) != len(effects) else None,
            )
        except (TypeError, ValueError) as exc:
            return ActionResult(False, "rejected", action, reason=str(exc))
        except Exception as exc:
            return ActionResult(False, "rejected", action, reason=f"action_failed:{type(exc).__name__}")

    def dispatch(self, payload: object) -> ActionResult:
        """Validate a structured semantic action and route it to the adapter."""

        if not isinstance(payload, Mapping):
            return ActionResult(False, "rejected", "", reason="action_must_be_object")
        action_type = payload.get("type", payload.get("action"))
        if not isinstance(action_type, str) or action_type not in SUPPORTED_ACTIONS:
            return ActionResult(False, "unsupported", str(action_type or ""), reason="action_not_allowed")
        if action_type == "set_emotion":
            return self.set_emotion(payload.get("name"), payload.get("intensity", 0.5), payload.get("duration", 1.0))
        if action_type == "set_parameter":
            return self.set_parameter(
                payload.get("logical_name"),
                payload.get("value"),
                payload.get("duration", 1.0),
                payload.get("restore", True),
            )
        return self.play_reaction(payload.get("name"), payload.get("intensity", 0.5), payload.get("duration", 1.0))

    def cancel(self, action_id: object) -> ActionResult:
        """Cancel a scheduled semantic action without raising on stale IDs."""

        action = "cancel"
        try:
            normalized = _normalize_name(action_id, field="action_id")
        except (TypeError, ValueError) as exc:
            return ActionResult(False, "rejected", action, reason=str(exc))
        if normalized not in self._entries:
            reason = "model_not_loaded" if self._controller is None else "action_not_found"
            status = "unavailable" if self._controller is None else "rejected"
            return ActionResult(False, status, action, normalized, reason=reason)
        del self._entries[normalized]
        return ActionResult(True, "cancelled", action, normalized)

    def configure_idle(
        self,
        logical_name: object,
        amplitude: object = 0.1,
        period_seconds: object = 8.0,
        phase: object = 0.0,
    ) -> ActionResult:
        """Register a deterministic, low-frequency local idle channel."""

        action = "configure_idle"
        try:
            unavailable = self._unavailable(action)
            if unavailable is not None:
                return unavailable
            logical = _normalize_name(logical_name, field="logical_name")
            binding = self._resolve(logical)
            if binding is None:
                return ActionResult(False, "unsupported", action, logical_name=logical, reason="parameter_not_found")
            bounded_amplitude, clamped_amplitude = _bounded(amplitude, 0.0, 1.0, field="amplitude")
            bounded_period, clamped_period = _bounded(period_seconds, 1.0, 60.0, field="period")
            bounded_phase = _safe_number(phase, field="phase")
            self._idle_channels[logical] = IdleChannel(
                logical, bounded_amplitude, bounded_period, bounded_phase
            )
            return ActionResult(
                True,
                "configured",
                action,
                logical_name=logical,
                parameter_id=binding.parameter_id,
                layer="idle",
                clamped=clamped_amplitude or clamped_period,
            )
        except (TypeError, ValueError) as exc:
            return ActionResult(False, "rejected", action, reason=str(exc))

    def attach_playback_queue(self, queue: PlaybackQueue) -> None:
        if self._attached_playback_queue is queue:
            return
        queue.add_listener(self.handle_playback_event)
        self._attached_playback_queue = queue

    def handle_playback_event(self, event: PlaybackEvent) -> ActionResult:
        """Translate PlaybackQueue lifecycle events into speech-lip-sync state."""

        action = "speech_lip_sync"
        try:
            kind = event.kind
            now = self._clock()
            if kind == "start":
                self._speech_active = True
                self._speech_started_at = now
                self._speech_release_started_at = None
                return ActionResult(True, "speaking", action, layer="speech-lip-sync")
            if kind in {"pause", "interrupted", "end"}:
                if self._speech_active:
                    self._speech_active = False
                    self._speech_release_started_at = now
                return ActionResult(True, "releasing", action, layer="speech-lip-sync", reason=kind)
            return ActionResult(False, "unsupported", action, reason="playback_event_not_allowed")
        except Exception as exc:
            return ActionResult(False, "rejected", action, reason=f"playback_event_failed:{type(exc).__name__}")

    def _update_idle_values(self, now: float) -> None:
        if self._last_idle_tick is not None and now - self._last_idle_tick < self._idle_tick_interval:
            return
        self._last_idle_tick = now
        for logical, channel in self._idle_channels.items():
            binding = self._resolve(logical)
            if binding is None:
                continue
            spec = self._specs[binding.parameter_id]
            wave = math.sin((now / channel.period_seconds) * math.tau + channel.phase)
            offset = (spec.maximum - spec.minimum) * channel.amplitude * 0.5 * wave
            self._idle_values[binding.parameter_id] = min(
                spec.maximum, max(spec.minimum, spec.default + offset)
            )

    def _speech_value(self, spec: ParameterSpec, now: float) -> float | None:
        if self._speech_active and self._speech_started_at is not None:
            phase = (now - self._speech_started_at) * math.tau * 3.0
            level = 0.18 + 0.22 * (0.5 + 0.5 * math.sin(phase))
            value = spec.default + (spec.maximum - spec.default) * level
            self._speech_level_value = min(spec.maximum, max(spec.minimum, value))
            return self._speech_level_value
        if self._speech_release_started_at is not None and self._speech_level_value is not None:
            elapsed = now - self._speech_release_started_at
            factor = max(0.0, 1.0 - elapsed / self._lip_release_seconds)
            if factor <= 0:
                self._speech_release_started_at = None
                self._speech_level_value = None
                return None
            value = spec.default + (self._speech_level_value - spec.default) * factor
            return min(spec.maximum, max(spec.minimum, value))
        return None

    def _cleanup_expired(self, now: float) -> None:
        for action_id in tuple(self._entries):
            entries = [
                entry
                for entry in self._entries[action_id]
                if entry.expires_at is None or now < entry.expires_at
            ]
            if entries:
                self._entries[action_id] = entries
            else:
                del self._entries[action_id]

    def _desired_values(self, now: float) -> dict[str, float]:
        self._cleanup_expired(now)
        self._update_idle_values(now)
        desired = {
            parameter_id: self._idle_values.get(parameter_id, spec.default)
            for parameter_id, spec in self._specs.items()
        }

        speech_binding = self._resolve("mouth_open")
        if speech_binding is not None:
            speech_value = self._speech_value(self._specs[speech_binding.parameter_id], now)
            if speech_value is not None:
                desired[speech_binding.parameter_id] = speech_value

        candidates: dict[str, _LayerEntry] = {}
        for entries in self._entries.values():
            for entry in entries:
                current = candidates.get(entry.parameter_id)
                if current is None or (
                    self._LAYER_PRIORITY[entry.layer], entry.sequence
                ) > (self._LAYER_PRIORITY[current.layer], current.sequence):
                    candidates[entry.parameter_id] = entry
        for parameter_id, entry in candidates.items():
            desired[parameter_id] = entry.target
        return desired

    def _apply_value(self, parameter_id: str, value: float) -> ParameterUpdate:
        def operation() -> ParameterUpdate:
            if self._controller is None:
                return ParameterUpdate(parameter_id, "unavailable", reason="model_not_loaded")
            update = self._controller.set_value(parameter_id, value)
            if update.status == "applied":
                self._last_output[parameter_id] = update.value if update.value is not None else value
            return update

        if threading.get_ident() == self._owner_thread_id:
            try:
                return operation()
            except Exception as exc:
                self.last_failure = f"parameter_apply_failed:{type(exc).__name__}"
                return ParameterUpdate(parameter_id, "unavailable", reason=self.last_failure)
        if self._main_thread_invoker is None:
            self.last_failure = "thread_violation"
            return ParameterUpdate(parameter_id, "unavailable", reason=self.last_failure)
        try:
            return self._main_thread_invoker(operation)
        except Exception as exc:
            self.last_failure = f"main_thread_dispatch_failed:{type(exc).__name__}"
            return ParameterUpdate(parameter_id, "unavailable", reason=self.last_failure)

    def tick(self, now: float | None = None) -> tuple[ParameterUpdate, ...]:
        """Apply the current layer projection through the injected controller."""

        timestamp = self._clock() if now is None else float(now)
        if self._controller is None or not self._specs:
            return ()
        updates: list[ParameterUpdate] = []
        for parameter_id, value in self._desired_values(timestamp).items():
            previous = self._last_output.get(parameter_id)
            if previous is not None and math.isclose(previous, value, abs_tol=1e-6):
                continue
            updates.append(self._apply_value(parameter_id, value))
        return tuple(updates)


ParameterActionAdapter = Live2DActionAdapter


__all__ = [
    "ActionLayer",
    "ActionResult",
    "DEFAULT_EMOTION_MAP",
    "DEFAULT_PARAMETER_ALIASES",
    "DEFAULT_REACTION_MAP",
    "IdleChannel",
    "Live2DActionAdapter",
    "MIN_ACTION_DURATION_SECONDS",
    "MAX_ACTION_DURATION_SECONDS",
    "ParameterActionAdapter",
    "ParameterBinding",
    "ParameterControllerPort",
    "SUPPORTED_ACTIONS",
]
