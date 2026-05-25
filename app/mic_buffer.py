"""Thread-safe in-memory PCM ring buffer (no disk persistence)."""

from __future__ import annotations

import threading

DEFAULT_MIC_SAMPLE_RATE = 16_000
BYTES_PER_SAMPLE = 2  # int16 mono


def clamp_mic_window_sec(seconds: int, *, minimum: int = 1, maximum: int = 30) -> int:
    return max(minimum, min(maximum, int(seconds)))


class MicRingBuffer:
    """Rolling byte buffer keeping the most recent ``capacity_sec`` of PCM audio."""

    def __init__(self, *, sample_rate: int = DEFAULT_MIC_SAMPLE_RATE, capacity_sec: int = 10) -> None:
        self.sample_rate = sample_rate
        self._capacity_bytes = max(
            sample_rate * BYTES_PER_SAMPLE,
            sample_rate * BYTES_PER_SAMPLE * clamp_mic_window_sec(capacity_sec, maximum=120),
        )
        self._data = bytearray()
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            self._data.extend(chunk)
            overflow = len(self._data) - self._capacity_bytes
            if overflow > 0:
                del self._data[:overflow]

    def take_recent(self, window_sec: int) -> bytes:
        window = clamp_mic_window_sec(window_sec)
        want = min(len(self._data), window * self.sample_rate * BYTES_PER_SAMPLE)
        with self._lock:
            if want <= 0:
                return b""
            return bytes(self._data[-want:])

    def take_recent_ms(self, ms: int) -> bytes:
        ms = max(1, min(int(ms), 30_000))
        want = min(len(self._data), ms * self.sample_rate * BYTES_PER_SAMPLE // 1000)
        with self._lock:
            if want <= 0:
                return b""
            return bytes(self._data[-want:])

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    @property
    def filled_bytes(self) -> int:
        with self._lock:
            return len(self._data)
