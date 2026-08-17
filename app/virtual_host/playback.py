"""纯状态的虚拟主播音频播放队列。

本模块只协调已经合成的音频字节和一个可注入的播放器，不导入 Qt、
sounddevice 或 Live2D。真实桌面播放应由调用方提供 ``AudioPlayer`` 适配器；
没有适配器时，队列返回结构化 ``unavailable``，不会伪造播放成功。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum
from typing import Literal, Protocol


class PlaybackPriority(IntEnum):
    """越大越优先；用户麦克风语音必须高于自动语音。"""

    IDLE = 10
    AUTO_SCENE = 50
    USER_MIC = 100


PlaybackEventKind = Literal["start", "pause", "interrupted", "end"]
PlaybackStatus = Literal["queued", "started", "completed", "rejected", "unavailable"]


class AudioPlayer(Protocol):
    """不绑定具体音频设备的最小播放器协议。

    ``play`` 应在音频自然结束时调用一次 ``on_complete``。返回 False 表示
    播放器明确拒绝本次播放；返回 None 或其它句柄表示已接受。
    """

    def play(self, audio_bytes: bytes, on_complete: Callable[[], None]) -> object:
        ...

    def stop(self) -> object:
        ...

    def pause(self) -> object:
        ...


@dataclass(frozen=True)
class PlaybackItem:
    """与一个语音轮次和 TTS 分段绑定的音频。"""

    session_id: str
    turn_id: int
    segment_index: int
    audio_bytes: bytes
    priority: int = PlaybackPriority.AUTO_SCENE
    source: str = "virtual_host"
    runtime_generation: int = 0
    item_id: str = ""

    def __post_init__(self) -> None:
        session_id = str(self.session_id or "").strip()
        if not session_id:
            raise ValueError("session_id must not be empty")
        if not self.audio_bytes:
            raise ValueError("audio_bytes must not be empty")
        object.__setattr__(self, "session_id", session_id)
        object.__setattr__(self, "turn_id", int(self.turn_id))
        object.__setattr__(self, "segment_index", int(self.segment_index))
        object.__setattr__(self, "audio_bytes", bytes(self.audio_bytes))
        object.__setattr__(self, "priority", int(self.priority))
        object.__setattr__(self, "source", str(self.source or "virtual_host"))
        object.__setattr__(self, "runtime_generation", int(self.runtime_generation))
        object.__setattr__(self, "item_id", str(self.item_id or uuid.uuid4().hex))


@dataclass(frozen=True)
class PlaybackEvent:
    kind: PlaybackEventKind
    item: PlaybackItem
    reason: str = ""


@dataclass(frozen=True)
class PlaybackResult:
    status: PlaybackStatus
    item_id: str = ""
    reason: str = ""


class PlaybackQueue:
    """可取消、可打断且能拒绝迟到音频的纯队列状态机。"""

    def __init__(
        self,
        player: AudioPlayer | None = None,
        *,
        on_event: Callable[[PlaybackEvent], None] | None = None,
    ) -> None:
        self._player = player
        self._listeners: list[Callable[[PlaybackEvent], None]] = []
        if on_event is not None:
            self._listeners.append(on_event)
        self._pending: list[tuple[int, int, PlaybackItem]] = []
        self._sequence = 0
        self._active: PlaybackItem | None = None
        self._cancelled_turns: set[tuple[str, int]] = set()

    @property
    def active_item(self) -> PlaybackItem | None:
        return self._active

    @property
    def queued_items(self) -> tuple[PlaybackItem, ...]:
        return tuple(item for _priority, _sequence, item in self._pending)

    def add_listener(self, listener: Callable[[PlaybackEvent], None]) -> None:
        self._listeners.append(listener)

    def _emit(self, event: PlaybackEvent) -> None:
        for listener in tuple(self._listeners):
            try:
                listener(event)
            except Exception:
                # 事件订阅者属于下游口型/诊断层，不能破坏播放状态机。
                continue

    @staticmethod
    def _turn_key(item: PlaybackItem) -> tuple[str, int]:
        return item.session_id, item.turn_id

    def _is_cancelled(self, item: PlaybackItem) -> bool:
        return self._turn_key(item) in self._cancelled_turns

    def has_pending_for_turn(self, session_id: str, turn_id: int) -> bool:
        key = (str(session_id).strip(), int(turn_id))
        return (self._active is not None and self._turn_key(self._active) == key) or any(
            self._turn_key(item) == key for _priority, _sequence, item in self._pending
        )

    def enqueue(
        self,
        item: PlaybackItem,
        *,
        policy: Literal["queue", "interrupt", "replace"] = "queue",
    ) -> PlaybackResult:
        """加入队列；用户高优先级项目自动打断较低优先级当前播放。"""

        if not isinstance(item, PlaybackItem):
            raise TypeError("item must be PlaybackItem")
        if not item.audio_bytes:
            return PlaybackResult("rejected", item.item_id, "empty_audio")
        if self._is_cancelled(item):
            return PlaybackResult("rejected", item.item_id, "cancelled_turn")
        if policy not in {"queue", "interrupt", "replace"}:
            raise ValueError("unsupported playback policy")
        if policy == "replace":
            self._remove_turn_items(item.session_id, item.turn_id)
            if self._active is not None and self._turn_key(self._active) == self._turn_key(item):
                self.interrupt(reason="replaced")
        elif policy == "interrupt":
            self.interrupt(reason="interrupted_by_new_item")
        elif self._active is not None and item.priority > self._active.priority:
            self.interrupt(reason="higher_priority")

        self._sequence += 1
        self._pending.append((-item.priority, self._sequence, item))
        self._pending.sort(key=lambda value: (value[0], value[1]))
        if self._player is None:
            self._remove_turn_items(item.session_id, item.turn_id)
            self._emit(PlaybackEvent("end", item, "audio_player_unavailable"))
            return PlaybackResult("unavailable", item.item_id, "audio_player_unavailable")
        self._start_next()
        return PlaybackResult("queued", item.item_id)

    def _remove_turn_items(self, session_id: str, turn_id: int) -> None:
        key = (str(session_id).strip(), int(turn_id))
        self._pending = [
            value for value in self._pending if self._turn_key(value[2]) != key
        ]

    def _start_next(self) -> PlaybackResult | None:
        if self._active is not None:
            return None
        while self._pending:
            _priority, _sequence, item = self._pending.pop(0)
            if self._is_cancelled(item):
                continue
            self._active = item
            if self._player is None:
                self._active = None
                self._emit(PlaybackEvent("end", item, "audio_player_unavailable"))
                continue
            self._emit(PlaybackEvent("start", item))
            try:
                accepted = self._player.play(
                    item.audio_bytes,
                    lambda item_id=item.item_id: self.complete(item_id=item_id),
                )
            except Exception as exc:
                self._active = None
                self._emit(PlaybackEvent("end", item, f"playback_failed:{type(exc).__name__}"))
                continue
            if accepted is False:
                self._active = None
                self._emit(PlaybackEvent("end", item, "audio_player_rejected"))
                continue
            return PlaybackResult("started", item.item_id)
        return None

    def complete(self, *, item_id: str | None = None) -> bool:
        """结束当前项目；迟到的旧播放器回调会被忽略。"""

        item = self._active
        if item is None or (item_id is not None and item.item_id != item_id):
            return False
        self._active = None
        self._emit(PlaybackEvent("end", item, "completed"))
        self._start_next()
        return True

    def pause(self) -> bool:
        item = self._active
        if item is None:
            return False
        try:
            pause = getattr(self._player, "pause", None)
            if callable(pause):
                pause()
        except Exception:
            return False
        self._emit(PlaybackEvent("pause", item))
        return True

    def interrupt(self, *, reason: str = "interrupted") -> bool:
        item = self._active
        if item is None:
            return False
        self._active = None
        try:
            stop = getattr(self._player, "stop", None)
            if callable(stop):
                stop()
        except Exception:
            pass
        self._emit(PlaybackEvent("interrupted", item, reason))
        self._emit(PlaybackEvent("end", item, reason))
        self._start_next()
        return True

    def cancel_turn(self, session_id: str, turn_id: int, *, reason: str = "cancelled") -> None:
        """取消一个轮次的排队和当前音频，之后迟到音频不能入队。"""

        key = (str(session_id).strip(), int(turn_id))
        self._cancelled_turns.add(key)
        self._pending = [
            value for value in self._pending if self._turn_key(value[2]) != key
        ]
        if self._active is not None and self._turn_key(self._active) == key:
            self.interrupt(reason=reason)

    def clear_cancelled_turn(self, session_id: str, turn_id: int) -> None:
        self._cancelled_turns.discard((str(session_id).strip(), int(turn_id)))

    @staticmethod
    def _is_stale_auto_runtime(item: PlaybackItem, current_runtime_generation: int) -> bool:
        return (
            int(item.priority) <= PlaybackPriority.AUTO_SCENE
            and int(item.runtime_generation) < int(current_runtime_generation)
        )

    def purge_stale_auto_runtime(
        self,
        current_runtime_generation: int,
        *,
        reason: str = "runtime_generation_stale",
    ) -> None:
        """移除旧 runtime 的 AUTO_SCENE 排队项并打断当前自动播报；保留 USER_MIC。"""

        self._pending = [
            value
            for value in self._pending
            if not self._is_stale_auto_runtime(value[2], current_runtime_generation)
        ]
        if self._active is not None and self._is_stale_auto_runtime(
            self._active,
            current_runtime_generation,
        ):
            self.interrupt(reason=reason)


__all__ = [
    "AudioPlayer",
    "PlaybackEvent",
    "PlaybackItem",
    "PlaybackPriority",
    "PlaybackQueue",
    "PlaybackResult",
]
