"""Facade for DanmuApp microphone mode lifecycle."""

from __future__ import annotations

from typing import Callable

from app.mic_buffer import clamp_mic_window_sec
from app.mic_capture import MicCaptureService


def mic_mode_enabled(config) -> bool:
    return config.get("mic_mode_enabled", "0") == "1"


def mic_window_sec_from_config(config) -> int:
    raw = config.get_int("mic_window_sec", 5)
    return clamp_mic_window_sec(raw)


class MicService:
    def __init__(self, *, log_fn: Callable[[str], None] | None = None) -> None:
        self._capture = MicCaptureService(log_fn=log_fn)
        self._log = log_fn or (lambda _msg: None)

    @staticmethod
    def is_available() -> bool:
        return MicCaptureService.is_available()

    def is_running(self) -> bool:
        return self._capture.is_running()

    def last_error(self) -> str:
        return self._capture.last_error

    def ensure_capture(self) -> bool:
        if self._capture.is_running():
            return True
        return self._capture.start()

    def clear_buffer(self) -> None:
        self._capture.clear_buffer()

    def sync(self, *, enabled: bool) -> None:
        if enabled:
            if not self._capture.is_running():
                self._capture.start()
        else:
            if self._capture.is_running():
                self._capture.stop()

    def stop(self) -> None:
        self._capture.stop()

    def snapshot_pcm(self, window_sec: int) -> bytes:
        return self._capture.snapshot_pcm(window_sec)

    def snapshot_pcm_ms(self, ms: int) -> bytes:
        return self._capture.snapshot_pcm_ms(ms)
