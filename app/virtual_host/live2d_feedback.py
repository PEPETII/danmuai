"""虚拟主播结果到独立 Live2D runtime 的安全反馈编排。"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.live2d.actions import (
    DEFAULT_EMOTION_MAP,
    DEFAULT_PARAMETER_ALIASES,
    DEFAULT_REACTION_MAP,
    Live2DActionAdapter,
)
from app.live2d.model_loader import ParameterSpec
from app.live2d.parameters import ParameterUpdate


class Live2DFeedbackRuntime(Protocol):
    """反馈层所需的最小 runtime 端口。"""

    def snapshot(self) -> Mapping[str, object]: ...

    def set_parameter(self, parameter_id: str, value: float) -> object: ...

    def set_expression(self, file_name: str) -> object: ...

    def reset_expression(self) -> object: ...

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
_GESTURE_IDLE_GROUPS = frozenset({"idle", "default", "待机", "daiji", "breath", "呼吸"})
_PARAMETER_FALLBACK_GESTURES = frozenset({"nod", "shake", "tilt", "blink", "breath"})
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


def _parse_semantic_mappings(
    capabilities: Mapping[object, object],
) -> tuple[dict[str, object], dict[str, object]]:
    raw = capabilities.get("semantic_mappings")
    emotions: dict[str, object] = {}
    gestures: dict[str, object] = {}
    if not isinstance(raw, Mapping):
        return emotions, gestures
    emotion_raw = raw.get("emotions") or raw.get("emotion")
    gesture_raw = raw.get("gestures") or raw.get("gesture")
    if isinstance(emotion_raw, Mapping):
        for key, value in emotion_raw.items():
            if isinstance(key, str) and key.strip():
                emotions[_normalized(key)] = value
    if isinstance(gesture_raw, Mapping):
        for key, value in gesture_raw.items():
            if isinstance(key, str) and key.strip():
                gestures[_normalized(key)] = value
    return emotions, gestures


def _safe_relative_path(value: object) -> str:
    normalized = str(value or "").replace("\\", "/").strip()
    parts = normalized.split("/")
    if not normalized or normalized.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        return ""
    return normalized


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
        self._emotion_semantic_mappings: dict[str, object] = {}
        self._gesture_semantic_mappings: dict[str, object] = {}
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
                self._emotion_semantic_mappings, self._gesture_semantic_mappings = (
                    _parse_semantic_mappings(capabilities)
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
        if self._runtime is not None:
            self._reset_transient_state()
            try:
                self._runtime.set_frame_callback(None)
            except Exception as exc:
                self.last_failure = f"clear_frame_callback_failed:{type(exc).__name__}"
        self._runtime = None
        self._adapter = None
        self._parameter_specs = ()
        self._expression_entries = ()
        self._motion_entries = ()
        self._emotion_semantic_mappings = {}
        self._gesture_semantic_mappings = {}
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
        self._safe_runtime_call("reset_expression")
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
            if normalized == _normalized(key) or normalized in {_normalized(item) for item in aliases}:
                return aliases
        return ()

    @staticmethod
    def _semantic_key(table: Mapping[str, tuple[str, ...]], name: object) -> str | None:
        normalized = _normalized(name)
        if not normalized:
            return None
        for key, aliases in table.items():
            if normalized == _normalized(key) or normalized in {_normalized(item) for item in aliases}:
                return key
        return None

    @staticmethod
    def _entry_names(entry: Mapping[str, str]) -> set[str]:
        names = {
            _normalized(entry.get("name")),
            _normalized(Path(entry.get("file", "")).stem),
        }
        file_stem = Path(entry.get("file", "")).stem
        if file_stem.endswith((".exp3", ".motion3")):
            names.add(_normalized(file_stem.rsplit(".", 1)[0]))
        return {name for name in names if name}

    def _find_entry(
        self,
        entries: Sequence[Mapping[str, str]],
        aliases: Sequence[str],
        *,
        exclude_idle_groups: bool = False,
    ) -> Mapping[str, str] | None:
        wanted = {_normalized(alias) for alias in aliases if _normalized(alias)}
        if not wanted:
            return None
        for entry in entries:
            if exclude_idle_groups and _normalized(entry.get("name")) in _GESTURE_IDLE_GROUPS:
                continue
            if self._entry_names(entry) & wanted:
                return entry
        return None

    def _find_entry_exact(
        self,
        entries: Sequence[Mapping[str, str]],
        name: object,
        *,
        exclude_idle_groups: bool = False,
    ) -> Mapping[str, str] | None:
        wanted = _normalized(name)
        if not wanted:
            return None
        for entry in entries:
            if exclude_idle_groups and _normalized(entry.get("name")) in _GESTURE_IDLE_GROUPS:
                continue
            if wanted in self._entry_names(entry):
                return entry
        return None

    def _find_entry_by_mapping(
        self,
        mapping: object,
        entries: Sequence[Mapping[str, str]],
        *,
        expression: bool,
        exclude_idle_groups: bool = False,
    ) -> Mapping[str, str] | None:
        if isinstance(mapping, str):
            return self._find_entry_exact(
                entries,
                mapping,
                exclude_idle_groups=exclude_idle_groups,
            )
        if not isinstance(mapping, Mapping):
            return None
        file_name = _mapping_value(mapping, "file", "File")
        if isinstance(file_name, str) and file_name.strip():
            relative = _safe_relative_path(file_name)
            if relative:
                for entry in entries:
                    if exclude_idle_groups and _normalized(entry.get("name")) in _GESTURE_IDLE_GROUPS:
                        continue
                    if entry.get("file") == relative:
                        return entry
        identifier = _mapping_value(mapping, "id", "Id", "name", "Name")
        if isinstance(identifier, str) and identifier.strip():
            found = self._find_entry_exact(
                entries,
                identifier,
                exclude_idle_groups=exclude_idle_groups,
            )
            if found is not None:
                return found
        if not expression:
            group = _mapping_value(mapping, "group", "Group")
            index = _mapping_value(mapping, "index", "Index")
            if isinstance(group, str) and group.strip():
                group_norm = _normalized(group)
                for entry in entries:
                    if exclude_idle_groups and _normalized(entry.get("name")) in _GESTURE_IDLE_GROUPS:
                        continue
                    if _normalized(entry.get("name")) != group_norm:
                        continue
                    if index is None:
                        return entry
                    try:
                        if int(entry.get("index", 0)) == int(index):
                            return entry
                    except (TypeError, ValueError):
                        continue
        return None

    def _resolve_semantic_mapping_entry(
        self,
        semantic_key: str,
        mappings: Mapping[str, object],
        entries: Sequence[Mapping[str, str]],
        *,
        expression: bool,
        exclude_idle_groups: bool = False,
    ) -> Mapping[str, str] | None:
        mapping = mappings.get(_normalized(semantic_key))
        if mapping is None:
            return None
        return self._find_entry_by_mapping(
            mapping,
            entries,
            expression=expression,
            exclude_idle_groups=exclude_idle_groups,
        )

    def _parameter_ids(self) -> frozenset[str]:
        return frozenset(spec.parameter_id for spec in self._parameter_specs)

    def _apply_parameter_emotion_fallback(self, semantic_key: str) -> FeedbackOutcome:
        adapter = self._adapter
        effects = DEFAULT_EMOTION_MAP.get(semantic_key)
        if adapter is None or effects is None:
            return FeedbackOutcome(False, "expression", "ignored", "emotion_not_found")
        available_ids = self._parameter_ids()
        resolved = [
            logical
            for logical in effects
            if any(
                candidate in available_ids
                for candidate in DEFAULT_PARAMETER_ALIASES.get(logical, ())
            )
        ]
        if not resolved:
            return FeedbackOutcome(False, "expression", "ignored", "emotion_parameters_missing")
        result = adapter.set_emotion(semantic_key, 0.5, 1.0)
        if not result.ok:
            return FeedbackOutcome(False, "expression", "ignored", result.reason or "emotion_fallback_failed")
        return FeedbackOutcome(True, "expression", "parameter_fallback", result.reason or "")

    def _apply_parameter_gesture_fallback(self, semantic_key: str) -> FeedbackOutcome:
        adapter = self._adapter
        if semantic_key not in _PARAMETER_FALLBACK_GESTURES:
            return FeedbackOutcome(False, "gesture", "ignored", "gesture_not_parameterizable")
        effects = DEFAULT_REACTION_MAP.get(semantic_key)
        if adapter is None or effects is None:
            return FeedbackOutcome(False, "gesture", "ignored", "gesture_not_found")
        available_ids = self._parameter_ids()
        resolved = [
            logical
            for logical in effects
            if any(
                candidate in available_ids
                for candidate in DEFAULT_PARAMETER_ALIASES.get(logical, ())
            )
        ]
        if not resolved:
            return FeedbackOutcome(False, "gesture", "ignored", "gesture_parameters_missing")
        result = adapter.play_reaction(semantic_key, 0.5, 1.0)
        if not result.ok:
            return FeedbackOutcome(False, "gesture", "ignored", result.reason or "gesture_fallback_failed")
        return FeedbackOutcome(True, "gesture", "parameter_fallback", result.reason or "")

    def _apply_expression(
        self,
        name: object,
        *,
        allow_exact_resource_match: bool = False,
    ) -> FeedbackOutcome:
        semantic_key = self._semantic_key(_EXPRESSION_ALIASES, name)
        entry: Mapping[str, str] | None = None
        if semantic_key is not None:
            entry = self._resolve_semantic_mapping_entry(
                semantic_key,
                self._emotion_semantic_mappings,
                self._expression_entries,
                expression=True,
            )
            if entry is None:
                aliases = self._aliases(_EXPRESSION_ALIASES, semantic_key)
                entry = self._find_entry(self._expression_entries, aliases)
        elif allow_exact_resource_match:
            entry = self._find_entry_exact(self._expression_entries, name)
        if entry is not None:
            outcome = self._safe_runtime_call("set_expression", entry["file"])
            status = "expression_applied" if outcome.ok else outcome.status
            return FeedbackOutcome(outcome.ok, "expression", status, outcome.reason or "")
        if semantic_key is not None:
            return self._apply_parameter_emotion_fallback(semantic_key)
        return FeedbackOutcome(False, "expression", "ignored", "expression_not_found")

    def _apply_gesture(self, name: object) -> FeedbackOutcome:
        semantic_key = self._semantic_key(_GESTURE_ALIASES, name)
        entry: Mapping[str, str] | None = None
        if semantic_key is not None:
            entry = self._resolve_semantic_mapping_entry(
                semantic_key,
                self._gesture_semantic_mappings,
                self._motion_entries,
                expression=False,
                exclude_idle_groups=True,
            )
            if entry is None:
                aliases = self._aliases(_GESTURE_ALIASES, semantic_key)
                entry = self._find_entry(
                    self._motion_entries,
                    aliases,
                    exclude_idle_groups=True,
                )
        else:
            entry = self._find_entry_exact(
                self._motion_entries,
                name,
                exclude_idle_groups=True,
            )
        if entry is not None:
            outcome = self._safe_runtime_call("start_motion", entry["file"])
            status = "motion_applied" if outcome.ok else outcome.status
            return FeedbackOutcome(outcome.ok, "gesture", status, outcome.reason or "")
        if semantic_key is not None:
            return self._apply_parameter_gesture_fallback(semantic_key)
        return FeedbackOutcome(False, "gesture", "ignored", "motion_not_found")

    def _apply_action(self, action: object) -> FeedbackOutcome:
        kind = _normalized(getattr(action, "kind", ""))
        name = getattr(action, "name", "")
        if kind not in _ALLOWED_KINDS:
            return FeedbackOutcome(False, kind or "action", "ignored", "action_not_allowed")
        if kind == "expression":
            return self._apply_expression(name, allow_exact_resource_match=True)
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
