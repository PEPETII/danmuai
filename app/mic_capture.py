"""Microphone capture via sounddevice (background thread, memory-only).

线程模型：
- ``MicCaptureService.start()`` 在调用线程（主线程）创建 ``sounddevice.InputStream`` 并
  由 ``sounddevice`` 内部回调线程持续写入 ``MicRingBuffer``。
- ``try_snapshot_pcm_ms`` / ``snapshot_pcm`` 在任意线程读取缓冲；``MicRingBuffer`` 内部
  ``threading.Lock`` 保护读写。
- 关闭麦克风/切模式时 ``stop()`` 显式关闭 stream，避免 callback 句柄泄漏。

约束：音频仅驻留内存，**不**写磁盘；超过 ``capacity_sec``（默认 10s）的旧 PCM 自动滚出。
``try_snapshot_pcm_ms`` 在 stream 未启动时返回 None，调用方需自己判定。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Callable

from app.mic_buffer import (
    BYTES_PER_SAMPLE,
    DEFAULT_MIC_SAMPLE_RATE,
    MicRingBuffer,
    clamp_mic_window_sec,
)

try:
    import numpy as np
    import sounddevice as sd

    _HAS_SOUNDDEVICE = True
except ImportError:  # pragma: no cover - optional dependency
    _HAS_SOUNDDEVICE = False
    np = None  # type: ignore
    sd = None  # type: ignore


@dataclass(frozen=True)
class MicInputDeviceInfo:
    id: int
    name: str
    is_default: bool
    max_input_channels: int


def default_input_device_id() -> int | None:
    """PortAudio default input index (matches Windows「默认录音设备」when configured)."""
    if not _HAS_SOUNDDEVICE:
        return None
    try:
        dev_id = sd.default.device[0]
        if dev_id is None:
            return None
        dev_id = int(dev_id)
        return dev_id if dev_id >= 0 else None
    except Exception:
        return None


def default_input_device_label(device_id: int | None = None) -> str:
    if not _HAS_SOUNDDEVICE:
        return ""
    try:
        dev_id = default_input_device_id() if device_id is None else device_id
        if dev_id is None:
            return ""
        return str(sd.query_devices(dev_id).get("name", ""))
    except Exception:
        return ""


def list_input_devices() -> list[MicInputDeviceInfo]:
    """Enumerate PortAudio input devices for the Web settings picker."""
    if not _HAS_SOUNDDEVICE:
        return []
    default_id = default_input_device_id()
    try:
        devices = sd.query_devices()
    except Exception:
        return []
    items: list[MicInputDeviceInfo] = []
    for index, device in enumerate(devices):
        try:
            max_input = int(device.get("max_input_channels", 0) or 0)
        except Exception:
            max_input = 0
        if max_input <= 0:
            continue
        items.append(
            MicInputDeviceInfo(
                id=int(index),
                name=str(device.get("name", "") or f"Input {index}"),
                is_default=int(index) == default_id,
                max_input_channels=max_input,
            )
        )
    return items


def resolve_preferred_input_device_id(raw_value) -> int | None:
    text = str(raw_value or "").strip()
    if not text:
        return None
    try:
        value = int(text)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


def input_device_exists(device_id: int | None) -> bool:
    if not _HAS_SOUNDDEVICE or device_id is None:
        return False
    try:
        info = sd.query_devices(int(device_id))
    except Exception:
        return False
    try:
        max_input = int(info.get("max_input_channels", 0) or 0)
    except Exception:
        max_input = 0
    return max_input > 0


class MicCaptureService:
    """Capture PCM into a ring buffer; never writes audio to disk."""

    def __init__(
        self,
        *,
        sample_rate: int = DEFAULT_MIC_SAMPLE_RATE,
        buffer_capacity_sec: int = 12,
        log_fn: Callable[[str], None] | None = None,
    ) -> None:
        self.sample_rate = sample_rate
        self._buffer = MicRingBuffer(sample_rate=sample_rate, capacity_sec=buffer_capacity_sec)
        self._log = log_fn or (lambda _msg: None)
        self._stream = None
        self._lock = threading.Lock()
        self._running = False
        self._last_error = ""
        self._active_device_id: int | None = None
        self._requested_device_id: int | None = None
        self._requested_follow_default = True
        self._fallback_to_default = False
        self._active_device_label = ""
        self._last_start_reason = ""

    @staticmethod
    def is_available() -> bool:
        return _HAS_SOUNDDEVICE

    @property
    def last_error(self) -> str:
        return self._last_error

    @property
    def active_device_id(self) -> int | None:
        return self._active_device_id

    @property
    def active_device_label(self) -> str:
        return self._active_device_label

    @property
    def requested_device_id(self) -> int | None:
        return self._requested_device_id

    @property
    def fallback_to_default(self) -> bool:
        return self._fallback_to_default

    @property
    def last_start_reason(self) -> str:
        return self._last_start_reason

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self, *, preferred_device_id: int | None = None) -> bool:
        follow_default = preferred_device_id is None
        desired_id = default_input_device_id() if follow_default else preferred_device_id
        fallback_to_default = False
        start_reason = ""
        if not follow_default and not input_device_exists(desired_id):
            fallback_id = default_input_device_id()
            fallback_to_default = True
            start_reason = "preferred_device_unavailable"
            desired_id = fallback_id
        with self._lock:
            if self._running:
                if (
                    desired_id == self._active_device_id
                    and follow_default == self._requested_follow_default
                    and preferred_device_id == self._requested_device_id
                ):
                    return True
                stream = self._stream
                self._stream = None
                self._running = False
                self._active_device_id = None
                self._active_device_label = ""
            else:
                stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            if follow_default:
                self._log("mic capture restarted: system default input device changed")
            else:
                self._log("mic capture restarted: selected input device changed")
        with self._lock:
            if not _HAS_SOUNDDEVICE:
                self._last_error = "sounddevice not installed"
                self._log("mic capture unavailable: sounddevice not installed")
                return False
            try:
                stream_kwargs: dict = {
                    "samplerate": self.sample_rate,
                    "channels": 1,
                    "dtype": "int16",
                    "callback": self._on_audio,
                }
                if desired_id is not None:
                    stream_kwargs["device"] = desired_id
                self._stream = sd.InputStream(**stream_kwargs)
                self._stream.start()
                self._running = True
                self._active_device_id = desired_id
                self._requested_device_id = preferred_device_id
                self._requested_follow_default = follow_default
                self._fallback_to_default = fallback_to_default
                self._last_start_reason = start_reason
                self._last_error = ""
                device = default_input_device_label(desired_id)
                self._active_device_label = device
                if device:
                    if fallback_to_default:
                        self._log(
                            "mic capture started with default input fallback "
                            f"(preferred={preferred_device_id}, input={device})"
                        )
                    else:
                        self._log(f"mic capture started (input={device})")
                else:
                    self._log("mic capture started")
                return True
            except Exception as exc:  # pragma: no cover - hardware dependent
                self._last_error = str(exc)
                self._stream = None
                self._running = False
                self._active_device_id = None
                self._active_device_label = ""
                self._requested_device_id = preferred_device_id
                self._requested_follow_default = follow_default
                self._fallback_to_default = fallback_to_default
                self._last_start_reason = start_reason
                self._log(f"mic capture failed: {exc}")
                return False

    def stop(self) -> None:
        with self._lock:
            was_running = self._running
            stream = self._stream
            self._stream = None
            self._running = False
            self._active_device_id = None
            self._active_device_label = ""
        if not was_running:
            return
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        self._buffer.clear()
        self._log("mic capture stopped")

    def clear_buffer(self) -> None:
        self._buffer.clear()

    def snapshot_pcm(self, window_sec: int) -> bytes:
        return self._buffer.take_recent(clamp_mic_window_sec(window_sec))

    def snapshot_pcm_ms(self, ms: int) -> bytes:
        return self._buffer.take_recent_ms(ms)

    def try_snapshot_pcm_ms(self, ms: int) -> bytes | None:
        """Non-blocking PCM snapshot for utterance poll; None if ring buffer lock is busy."""
        return self._buffer.try_take_recent_ms(ms)

    def _on_audio(self, indata, frames, time_info, status) -> None:  # pragma: no cover
        if status:
            self._last_error = str(status)
        self._buffer.append(indata.tobytes())
