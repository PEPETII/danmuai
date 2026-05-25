"""RMS-based utterance-end detection for mic insert mode (no VAD library)."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from app.mic_test import QUIET_RMS, pcm_metrics


class UtteranceState(str, Enum):
    IDLE = "idle"
    SPEAKING = "speaking"
    SILENCE_PENDING = "silence_pending"
    COOLDOWN = "cooldown"


@dataclass(frozen=True)
class MicUtteranceConfig:
    speech_rms: int = QUIET_RMS
    silence_ms: int = 400
    min_speech_ms: int = 300
    cooldown_sec: float = 4.0


def mic_utterance_config_from_store(config) -> MicUtteranceConfig:
    return MicUtteranceConfig(
        speech_rms=config.get_int("mic_speech_rms", QUIET_RMS),
        silence_ms=config.get_int("mic_silence_ms", 400),
        min_speech_ms=config.get_int("mic_min_speech_ms", 300),
        cooldown_sec=float(config.get_float("mic_cooldown_sec", 4.0)),
    )


def calibrate_noise_floor_rms(pcm: bytes) -> int:
    """Estimate ambient RMS from a short pre-roll buffer."""
    rms, _ = pcm_metrics(pcm)
    return max(0, rms)


class MicUtteranceDetector:
    """Poll recent PCM chunks; fire callback once per completed utterance."""

    def __init__(
        self,
        *,
        on_utterance_end: Callable[[], None],
        config: MicUtteranceConfig | None = None,
    ) -> None:
        self._on_utterance_end = on_utterance_end
        self._config = config or MicUtteranceConfig()
        self._state = UtteranceState.IDLE
        self._speech_started_at = 0.0
        self._silence_started_at = 0.0
        self._cooldown_until = 0.0
        self._noise_floor = 0
        self._peak_rms = 0

    @property
    def state(self) -> UtteranceState:
        return self._state

    def update_config(self, config: MicUtteranceConfig) -> None:
        self._config = config

    def reset(self) -> None:
        self._state = UtteranceState.IDLE
        self._speech_started_at = 0.0
        self._silence_started_at = 0.0
        self._cooldown_until = 0.0
        self._noise_floor = 0
        self._peak_rms = 0

    def set_noise_floor(self, floor_rms: int) -> None:
        self._noise_floor = max(0, int(floor_rms))

    def enter_threshold(self) -> int:
        return self._speech_enter_threshold()

    def _speech_enter_threshold(self) -> int:
        floor = self._noise_floor
        return max(
            self._config.speech_rms,
            floor + 120,
            int(floor * 1.6) + 60,
        )

    def _speech_exit_threshold(self) -> int:
        floor = self._noise_floor
        return max(80, floor + 40, int(self._peak_rms * 0.45))

    def poll(self, pcm_chunk: bytes, *, now: float | None = None) -> None:
        now = now if now is not None else time.monotonic()
        if self._state == UtteranceState.COOLDOWN:
            if now >= self._cooldown_until:
                self._state = UtteranceState.IDLE
                self._peak_rms = 0
            else:
                return

        rms, _ = pcm_metrics(pcm_chunk)
        enter_threshold = self._speech_enter_threshold()

        if self._state == UtteranceState.IDLE:
            if rms >= enter_threshold:
                self._state = UtteranceState.SPEAKING
                self._speech_started_at = now
                self._peak_rms = rms
            return

        exit_threshold = self._speech_exit_threshold()

        if self._state == UtteranceState.SPEAKING:
            self._peak_rms = max(self._peak_rms, rms)
            if rms >= exit_threshold:
                return
            self._state = UtteranceState.SILENCE_PENDING
            self._silence_started_at = now
            return

        if self._state == UtteranceState.SILENCE_PENDING:
            if rms >= enter_threshold:
                self._state = UtteranceState.SPEAKING
                self._peak_rms = max(self._peak_rms, rms)
                return
            if rms >= exit_threshold:
                return
            silence_ms = (now - self._silence_started_at) * 1000.0
            if silence_ms < self._config.silence_ms:
                return
            speech_ms = (self._silence_started_at - self._speech_started_at) * 1000.0
            if speech_ms >= self._config.min_speech_ms:
                self._fire(now)
            else:
                self._state = UtteranceState.IDLE
                self._peak_rms = 0

    def _fire(self, now: float) -> None:
        self._state = UtteranceState.COOLDOWN
        self._cooldown_until = now + self._config.cooldown_sec
        self._peak_rms = 0
        self._on_utterance_end()
