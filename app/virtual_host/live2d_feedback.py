"""虚拟主播结果到独立 Live2D runtime 的安全反馈编排。"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.live2d.actions import Live2DActionAdapter
from app.live2d.model_loader import ParameterSpec
from app.live2d.parameters import ParameterUpdate


class Live2DFeedbackRuntime(Protocol):
    """反馈层所需的最小 runtime 端口。"""

    def snapshot(self) -> Mapping[str, object]: ...

    def set_parameter(self, parameter_id: str, value: float) -> object: ...

    def set_expression(self, file_name: str) -> object: ...

    def start_motion(self, file_name: str) -> object: ...

    def restore_idle(self) -> object: ...

    def set_frame_callback(self, callback: Callable[[], object] | None) -> object: ...


@dataclass(frozen=True)
class FeedbackOutcome:
    """单次反馈的结构化结果；失败不会从控制器向外抛出。"""

    ok: bool
    kind: str
    status: str
    reason: str = ""


_EXPRESSION_ALIASES: dict[str, tuple[str, ...]] = {
    "neutral": ("neutral", "default", "normal", "中性", "平静"),
    "happy": ("happy", "开心", "smile", "微笑", "joy", "joyful", "glad", "高兴", "喜悦"),
    "sad": ("sad", "悲伤", "难过", "哭", "sorrow", "cry", "tears"),
    "angry": ("angry", "生气", "愤怒", "rage", "mad"),
    "surprised": ("surprised", "surprise", "惊讶", "shock", "astonished"),
    "nervous": ("nervous", "紧张", "anxious", "焦虑"),
    "smile": ("smile", "微笑"),
    "wink": ("wink", "眨眼"),
    "blink": ("blink", "眨眼"),
}
_GESTURE_ALIASES: dict[str, tuple[str, ...]] = {
    "nod": ("nod", "点头"),
    "shake": ("shake", "摇头"),
    "wave": ("wave", "挥手"),
    "tilt": ("tilt", "歪头"),
    "breath": ("breath", "呼吸"),
    "blink": ("blink", "眨眼"),
}
_LOOK_AT_VALUES: dict[str, tuple[str, float]] = {
    "left": ("eye_ball_x", -1.0),
    "左": ("eye_ball_x", -1.0),
    "right": ("eye_ball_x", 1.0),
    "右": ("eye_ball_x", 1.0),
    "center": ("eye_ball_x", 0.0),
    "middle": ("eye_ball_x", 0.0),
    "中": ("eye_ball_x", 0.0),
    "up": ("eye_ball_y", 1.0),
    "上": ("eye_ball_y", 1.0),
    "down": ("eye_ball_y", -1.0),
    "下": ("eye_ball_y", -1.0),
}
_IDLE_NAMES = frozenset({"idle", "default", "待机", "breath", "呼吸"})
_ALLOWED_KINDS = frozenset({"expression", "gesture", "look_at", "idle"})


def _normalized(value: object) -> str:
    return " ".join(value.split()).casefold() if isinstance(value, str) else ""


def _finite_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mapping_value(item: Mapping[object, object], *keys: str) -> object:
    for key in keys:
        if key in item:
            return item[key]
    return None


def _parse_parameter_specs(capabilities: Mapping[object, object]) -> tuple[ParameterSpec, ...]:
    raw_specs = capabilities.get("parameter_specs")
    if not isinstance(raw_specs, Sequence) or isinstance(raw_specs, (str, bytes, bytearray)):
        return ()
    parsed: list[ParameterSpec] = []
    seen: set[str] = set()
    for raw in raw_specs:
        if isinstance(raw, ParameterSpec):
            spec = raw
        elif isinstance(raw, Mapping):
            parameter_id = _mapping_value(raw, "parameter_id", "id", "Id")
            minimum = _finite_float(_mapping_value(raw, "minimum", "min", "Min"))
            maximum = _finite_float(_mapping_value(raw, "maximum", "max", "Max"))
            default = _finite_float(_mapping_value(raw, "default", "Default"))
            current = _finite_float(_mapping_value(raw, "current", "value", "Value"))
            if not isinstance(parameter_id, str) or not parameter_id.strip():
                continue
            if minimum is None or maximum is None or default is None:
                continue
            if current is None:
                current = default
            try:
                spec = ParameterSpec(
                    parameter_id=parameter_id.strip(),
                    minimum=minimum,
                    maximum=maximum,
                    default=default,
                    current=current,
                )
            except (TypeError, ValueError):
                continue
        else:
            continue
        if spec.parameter_id in seen:
            continue
        seen.add(spec.parameter_id)
        parsed.append(spec)
    return tuple(parsed)


def _parse_entries(value: object, *, expression: bool) -> tuple[dict[str, str], ...]:
    if isinstance(value, Mapping):
        values: list[object] = list(value.values())
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        values = list(value)
    else:
        return ()

    entries: list[dict[str, str]] = []
    for raw in values:
        if not isinstance(raw, Mapping):
            continue
        file_name = _mapping_value(raw, "file", "File")
        if not isinstance(file_name, str) or not file_name.strip():
            continue
        file_name = file_name.strip().replace("\\", "/")
        path = Path(file_name)
        if path.is_absolute() or ".." in path.parts or not file_name:
            continue
        if expression:
            entry_name = _mapping_value(raw, "id", "name", "Name")
            if not isinstance(entry_name, str) or not entry_name.strip():
                entry_name = path.stem
            entries.append({"name": entry_name.strip(), "file": file_name})
        else:
            group = _mapping_value(raw, "group", "Group", "name", "Name")
            if not isinstance(group, str) or not group.strip():
                continue
            entries.append({"name": group.strip(), "file": file_name})
    return tuple(entries)


class _RuntimeParameterPort:
    def __init__(self, runtime: Live2DFeedbackRuntime) -> None:
        self.runtime = runtime

    def set_value(self, parameter_id: str, value: float) -> ParameterUpdate:
        try:
            result = self.runtime.set_parameter(parameter_id, value)
            applied_value = value
            if isinstance(result, Mapping):
                parsed_value = _finite_float(result.get("value"))
                if parsed_value is not None:
                    applied_value = parsed_value
            return ParameterUpdate(parameter_id, "applied", value=applied_value, target=applied_value)
        except Exception as exc:  # runtime failure is isolated from the frame callback
            return ParameterUpdate(
                parameter_id,
                "unavailable",
                reason=f"runtime_parameter_failed:{type(exc).__name__}",
            )


class Live2DFeedbackController:
    """消费主播反馈，不拥有播放队列、模型对象或独立调度器。"""

    def __init__(self) -> None:
        self._runtime: Live2DFeedbackRuntime | None = None
        self._runtime_generation = 0
        self._adapter: Live2DActionAdapter | None = None
        self._parameter_specs: tuple[ParameterSpec, ...] = ()
        self._expression_entries: tuple[dict[str, str], ...] = ()
        self._motion_entries: tuple[dict[str, str], ...] = ()
        self._active = False
        self._active_item_id: str | None = None
        self._active_playback_generation: int | None = None
        self._current_session_id = ""
        self._current_turn_id: int | None = None
        self.last_failure: str | None = None

    @property
    def runtime_generation(self) -> int:
        return self._runtime_generation

    @property
    def active(self) -> bool:
        return self._active

    @property
    def speech_lip_sync_active(self) -> bool:
        return bool(self._adapter and self._adapter.speech_lip_sync_active)

    def _build_adapter(self) -> None:
        runtime = self._runtime
        if runtime is None:
            self._adapter = None
            return
        self._adapter = Live2DActionAdapter(
            _RuntimeParameterPort(runtime),
            self._parameter_specs,
        )

    def _safe_runtime_call(self, method: str, *args: object) -> FeedbackOutcome:
        runtime = self._runtime
        if runtime is None:
            return FeedbackOutcome(False, method, "unavailable", "runtime_unbound")
        try:
            getattr(runtime, method)(*args)
        except Exception as exc:
            self.last_failure = f"{method}_failed:{type(exc).__name__}"
            return FeedbackOutcome(False, method, "failed", self.last_failure)
        return FeedbackOutcome(True, method, "applied")

    def bind_runtime(self, runtime: Live2DFeedbackRuntime, runtime_generation: int) -> None:
        self.unbind_runtime()
        self._runtime = runtime
        self._runtime_generation = int(runtime_generation)
        self._parameter_specs = ()
        self._expression_entries = ()
        self._motion_entries = ()
        try:
            snapshot = runtime.snapshot()
            capabilities = snapshot.get("capabilities", {}) if isinstance(snapshot, Mapping) else {}
            if isinstance(capabilities, Mapping):
                self._parameter_specs = _parse_parameter_specs(capabilities)
                self._expression_entries = _parse_entries(
                    capabilities.get("expression_entries"), expression=True
                )
                self._motion_entries = _parse_entries(
                    capabilities.get("motion_entries"), expression=False
                )
        except Exception as exc:
            self.last_failure = f"snapshot_failed:{type(exc).__name__}"
        self._build_adapter()
        self._active = False
        try:
            runtime.set_frame_callback(self.tick)
        except Exception as exc:
            self.last_failure = f"set_frame_callback_failed:{type(exc).__name__}"

    def unbind_runtime(self) -> None:
        runtime = self._runtime
        if runtime is not None:
            try:
                runtime.set_frame_callback(None)
            except Exception as exc:
                self.last_failure = f"clear_frame_callback_failed:{type(exc).__name__}"
        self._runtime = None
        self._adapter = None
        self._parameter_specs = ()
        self._expression_entries = ()
        self._motion_entries = ()
        self._active = False
        self._active_item_id = None
        self._active_playback_generation = None

    def _reset_transient_state(self) -> None:
        adapter = self._adapter
        if adapter is not None:
            try:
                adapter.reset()
            except Exception as exc:
                self.last_failure = f"reset_failed:{type(exc).__name__}"
        self._safe_runtime_call("restore_idle")
        self._active_item_id = None
        self._active_playback_generation = None
        self._current_session_id = ""
        self._current_turn_id = None
        self._build_adapter()

    def activate(self) -> None:
        self._active = self._runtime is not None

    def deactivate(self) -> None:
        self._active = False
        self._reset_transient_state()

    def set_runtime_generation(self, runtime_generation: int) -> None:
        generation = int(runtime_generation)
        if generation == self._runtime_generation:
            return
        self._runtime_generation = generation
        self._reset_transient_state()

    @staticmethod
    def _aliases(table: Mapping[str, tuple[str, ...]], name: object) -> tuple[str, ...]:
        normalized = _normalized(name)
        for key, aliases in table.items():
            if normalized == key or normalized in {_normalized(item) for item in aliases}:
                return aliases
        return ()

    @staticmethod
    def _find_entry(
        entries: Sequence[Mapping[str, str]], aliases: Sequence[str]
    ) -> Mapping[str, str] | None:
        wanted = {_normalized(alias) for alias in aliases}
        for entry in entries:
            names = {
                _normalized(entry.get("name")),
                _normalized(Path(entry.get("file", "")).stem),
            }
            file_stem = Path(entry.get("file", "")).stem
            if file_stem.endswith((".exp3", ".motion3")):
                names.add(_normalized(file_stem.rsplit(".", 1)[0]))
            if names & wanted:
                return entry
        return None

    def _apply_expression(self, name: object) -> FeedbackOutcome:
        aliases = self._aliases(_EXPRESSION_ALIASES, name)
        entry = self._find_entry(self._expression_entries, aliases) if aliases else None
        if entry is None:
            return FeedbackOutcome(False, "expression", "ignored", "expression_not_found")
        return self._safe_runtime_call("set_expression", entry["file"])

    def _apply_gesture(self, name: object) -> FeedbackOutcome:
        aliases = self._aliases(_GESTURE_ALIASES, name)
        entry = self._find_entry(self._motion_entries, aliases) if aliases else None
        if entry is None:
            return FeedbackOutcome(False, "gesture", "ignored", "motion_not_found")
        return self._safe_runtime_call("start_motion", entry["file"])

    def _apply_action(self, action: object) -> FeedbackOutcome:
        kind = _normalized(getattr(action, "kind", ""))
        name = getattr(action, "name", "")
        if kind not in _ALLOWED_KINDS:
            return FeedbackOutcome(False, kind or "action", "ignored", "action_not_allowed")
        if kind == "expression":
            return self._apply_expression(name)
        if kind == "gesture":
            return self._apply_gesture(name)
        if kind == "idle":
            if name and _normalized(name) not in _IDLE_NAMES:
                return FeedbackOutcome(False, "idle", "ignored", "idle_not_allowed")
            adapter = self._adapter
            if adapter is not None:
                try:
                    adapter.reset()
                except Exception as exc:
                    self.last_failure = f"idle_reset_failed:{type(exc).__name__}"
            return self._safe_runtime_call("restore_idle")
        lookup = _LOOK_AT_VALUES.get(_normalized(name))
        adapter = self._adapter
        if lookup is None or adapter is None:
            return FeedbackOutcome(False, "look_at", "ignored", "look_at_not_allowed")
        logical_name, value = lookup
        result = adapter.set_parameter(
            logical_name,
            value,
            getattr(action, "duration_seconds", 1.0),
            True,
        )
        return FeedbackOutcome(result.ok, "look_at", result.status, result.reason or "")

    def apply_turn_result(self, result: object, runtime_generation: int) -> tuple[FeedbackOutcome, ...]:
        if not self._active or int(runtime_generation) != self._runtime_generation:
            return ()
        outcomes: list[FeedbackOutcome] = []
        try:
            session_id = str(getattr(result, "session_id", "") or "").strip()
            if session_id:
                self._current_session_id = session_id
            try:
                self._current_turn_id = int(getattr(result, "turn_id"))
            except (TypeError, ValueError):
                self._current_turn_id = None
            emotion = getattr(result, "emotion", None)
            if emotion is not None:
                emotion_result = self._apply_expression(getattr(emotion, "name", ""))
                outcomes.append(
                    FeedbackOutcome(
                        emotion_result.ok,
                        "emotion",
                        emotion_result.status,
                        emotion_result.reason or "",
                    )
                )
            actions = getattr(result, "actions", ())
            if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes, bytearray)):
                return tuple(outcomes)
            for action in actions:
                outcomes.append(self._apply_action(action))
        except Exception as exc:
            self.last_failure = f"turn_result_failed:{type(exc).__name__}"
            outcomes.append(FeedbackOutcome(False, "turn", "failed", self.last_failure))
        return tuple(outcomes)

    def handle_playback_event(self, event: object) -> FeedbackOutcome:
        kind = _normalized(getattr(event, "kind", ""))
        if kind not in {"start", "end", "interrupted", "pause"}:
            return FeedbackOutcome(False, "playback", "ignored", "playback_event_not_allowed")
        if not self._active or self._adapter is None:
            return FeedbackOutcome(False, "playback", "ignored", "controller_inactive")
        item = getattr(event, "item", None)
        item_id = str(getattr(item, "item_id", "") or "").strip()
        try:
            generation = int(getattr(item, "runtime_generation"))
        except (TypeError, ValueError):
            return FeedbackOutcome(False, "playback", "ignored", "runtime_generation_invalid")
        if not item_id or generation != self._runtime_generation:
            return FeedbackOutcome(False, "playback", "ignored", "stale_playback")
        session_id = str(getattr(item, "session_id", "") or "").strip()
        if self._current_session_id and session_id != self._current_session_id:
            return FeedbackOutcome(False, "playback", "ignored", "stale_playback")
        try:
            turn_id = int(getattr(item, "turn_id"))
        except (TypeError, ValueError):
            return FeedbackOutcome(False, "playback", "ignored", "turn_id_invalid")
        if self._current_turn_id is not None and turn_id != self._current_turn_id:
            return FeedbackOutcome(False, "playback", "ignored", "stale_playback")
        if kind == "start":
            self._active_item_id = item_id
            self._active_playback_generation = generation
        elif item_id != self._active_item_id or generation != self._active_playback_generation:
            return FeedbackOutcome(False, "playback", "ignored", "stale_playback")
        try:
            result = self._adapter.handle_playback_event(event)
            if kind != "start":
                self._active_item_id = None
                self._active_playback_generation = None
            return FeedbackOutcome(result.ok, "playback", result.status, result.reason or "")
        except Exception as exc:
            self.last_failure = f"playback_event_failed:{type(exc).__name__}"
            return FeedbackOutcome(False, "playback", "failed", self.last_failure)

    def tick(self) -> tuple[ParameterUpdate, ...]:
        if not self._active or self._adapter is None:
            return ()
        try:
            return self._adapter.tick()
        except Exception as exc:
            self.last_failure = f"tick_failed:{type(exc).__name__}"
            return ()


__all__ = ["FeedbackOutcome", "Live2DFeedbackController", "Live2DFeedbackRuntime"]
