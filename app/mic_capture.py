"""Microphone capture via sounddevice (background thread, memory-only)."""

from __future__ import annotations

import threading
from typing import Callable

from app.mic_buffer import DEFAULT_MIC_SAMPLE_RATE, MicRingBuffer, clamp_mic_window_sec

try:
    import numpy as np
    import sounddevice as sd

    _HAS_SOUNDDEVICE = True
except ImportError:  # pragma: no cover - optional dependency
    _HAS_SOUNDDEVICE = False
    np = None  # type: ignore
    sd = None  # type: ignore


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

    @staticmethod
    def is_available() -> bool:
        return _HAS_SOUNDDEVICE

    @property
    def last_error(self) -> str:
        return self._last_error

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def start(self) -> bool:
        desired_id = default_input_device_id()
        with self._lock:
            if self._running:
                if desired_id == self._active_device_id:
                    return True
                stream = self._stream
                self._stream = None
                self._running = False
                self._active_device_id = None
            else:
                stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
            self._log("mic capture restarted: system default input device changed")
        with self._lock:
            if not _HAS_SOUNDDEVICE:
                self._last_error = "sounddevice_unavailable"
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
                self._last_error = ""
                device = default_input_device_label(desired_id)
                if device:
                    self._log(f"mic capture started (input={device})")
                else:
                    self._log("mic capture started")
                return True
            except Exception as exc:  # pragma: no cover - hardware dependent
                self._last_error = str(exc)
                self._stream = None
                self._running = False
                self._active_device_id = None
                self._log(f"mic capture failed: {exc}")
                return False

    def stop(self) -> None:
        with self._lock:
            was_running = self._running
            stream = self._stream
            self._stream = None
            self._running = False
            self._active_device_id = None
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

    def _on_audio(self, indata, frames, time_info, status) -> None:  # pragma: no cover
        if status:
            self._last_error = str(status)
        self._buffer.append(indata.tobytes())
