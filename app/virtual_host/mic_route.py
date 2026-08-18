"""虚拟主播对话模式下的本机麦克风分流与 ASR 交付（无 Qt 依赖）。"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.mic_transcription import MicTranscriptionResult
from app.virtual_host.audio import AsrResult, VirtualHostAudioOrchestrator
from app.virtual_host.diagnostics import log_diagnostic
from app.virtual_host.playback import PlaybackQueue

if TYPE_CHECKING:
    from app.virtual_host.runtime_service import VirtualHostRuntimeService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MicAsrJob:
    turn_id: int
    pcm: bytes
    runtime_generation: int
    scene_generation: int
    started_at: float


class VirtualHostMicRoute:
    """将本机麦克风 utterance 送入语音契约并完成 ASR，再交由运行时触发 Chat。"""

    def __init__(
        self,
        runtime: "VirtualHostRuntimeService",
        *,
        schedule_asr_job: Callable[[MicAsrJob], None],
    ) -> None:
        self._runtime = runtime
        self._schedule_asr_job = schedule_asr_job
        self._active_turn_id = 0
        self._active_runtime_generation = 0
        self._active_scene_generation = 0
        self._asr_in_flight = False

    @property
    def asr_in_flight(self) -> bool:
        return self._asr_in_flight

    @property
    def active_turn_id(self) -> int:
        return self._active_turn_id

    def _audio(self) -> VirtualHostAudioOrchestrator:
        return self._runtime.audio

    def _playback(self) -> PlaybackQueue:
        return self._runtime.audio.playback

    def _route_active(self) -> bool:
        return self._runtime.running and self._runtime.dialogue_enabled

    def reset(self, *, reason: str = "mic_route_reset") -> None:
        if self._active_turn_id:
            self._audio().cancel_turn(self._active_turn_id, reason=reason)
        self._active_turn_id = 0
        self._asr_in_flight = False
        if self._playback().playback_suppressed:
            self._playback().release_playback_suppression()

    def on_speech_start(self) -> bool:
        if not self._route_active():
            return False
        app = self._runtime._app
        scene_generation = int(getattr(app, "_scene_generation", 0))
        runtime_generation = self._runtime.runtime_generation
        turn = self._audio().begin_mic_turn(
            scene_generation=scene_generation,
            runtime_generation=runtime_generation,
            source="user_mic",
        )
        self._active_turn_id = turn.turn_id
        self._active_runtime_generation = runtime_generation
        self._active_scene_generation = scene_generation
        self._playback().suppress_playback(reason="mic_capture")
        log_diagnostic(
            "mic_turn_start",
            runtime_generation=runtime_generation,
            turn_id=turn.turn_id,
            scene_generation=scene_generation,
            status="capturing",
        )
        return True

    def on_utterance_discarded(self) -> bool:
        if not self._active_turn_id:
            return False
        turn_id = self._active_turn_id
        self._audio().cancel_turn(turn_id, reason="utterance_discarded")
        self._active_turn_id = 0
        self._asr_in_flight = False
        self._playback().release_playback_suppression()
        log_diagnostic(
            "mic_turn_cancelled",
            runtime_generation=self._runtime.runtime_generation,
            turn_id=turn_id,
            reason="utterance_discarded",
        )
        return True

    def on_utterance_end(self, pcm: bytes) -> bool:
        if not self._route_active():
            return False
        if not self._active_turn_id:
            turn = self._audio().begin_mic_turn(
                scene_generation=self._active_scene_generation,
                runtime_generation=self._runtime.runtime_generation,
                source="user_mic",
            )
            self._active_turn_id = turn.turn_id
            self._active_runtime_generation = self._runtime.runtime_generation
        turn_id = self._active_turn_id
        runtime_generation = self._active_runtime_generation
        scene_generation = int(getattr(self._runtime._app, "_scene_generation", 0))
        self._audio().end_input(turn_id)
        self._playback().release_playback_suppression()
        if not pcm:
            self._audio().transcribe(
                turn_id,
                b"",
                current_scene_generation=scene_generation,
                current_runtime_generation=runtime_generation,
            )
            self._active_turn_id = 0
            log_diagnostic(
                "mic_asr_end",
                runtime_generation=runtime_generation,
                turn_id=turn_id,
                status="failed",
                error="empty_pcm",
                pcm_bytes=0,
            )
            return True
        if self._asr_in_flight:
            log_diagnostic(
                "mic_asr_skipped",
                runtime_generation=runtime_generation,
                turn_id=turn_id,
                reason="asr_in_flight",
            )
            return True
        started_at = time.monotonic()
        self._asr_in_flight = True
        log_diagnostic(
            "mic_asr_start",
            runtime_generation=runtime_generation,
            turn_id=turn_id,
            pcm_bytes=len(pcm),
            scene_generation=scene_generation,
        )
        self._schedule_asr_job(
            MicAsrJob(
                turn_id=turn_id,
                pcm=bytes(pcm),
                runtime_generation=runtime_generation,
                scene_generation=scene_generation,
                started_at=started_at,
            )
        )
        return True

    def on_asr_completed(
        self,
        turn_id: int,
        result: MicTranscriptionResult,
        runtime_generation: int,
    ) -> None:
        self._asr_in_flight = False
        if int(runtime_generation) != self._runtime.runtime_generation:
            if turn_id:
                self._audio().cancel_turn(turn_id, reason="runtime_generation_stale")
            if self._active_turn_id == turn_id:
                self._active_turn_id = 0
            log_diagnostic(
                "mic_asr_end",
                runtime_generation=runtime_generation,
                turn_id=turn_id,
                status="cancelled",
                error="runtime_generation_stale",
            )
            return
        if turn_id != self._active_turn_id:
            log_diagnostic(
                "mic_asr_end",
                runtime_generation=runtime_generation,
                turn_id=turn_id,
                status="ignored",
                error="stale_turn",
            )
            return
        scene_generation = int(getattr(self._runtime._app, "_scene_generation", 0))
        state = self._audio().get_turn(turn_id)
        if state.cancelled or state.status in {"completed", "failed", "cancelled"}:
            self._active_turn_id = 0
            return
        if not getattr(result, "ok", False):
            error = str(getattr(result, "error", "") or "transcription_failed")
            self._audio().apply_asr_result(
                turn_id,
                AsrResult("unavailable", reason=error),
                current_scene_generation=scene_generation,
                current_runtime_generation=runtime_generation,
            )
            self._active_turn_id = 0
            log_diagnostic(
                "mic_asr_end",
                runtime_generation=runtime_generation,
                turn_id=turn_id,
                status="failed",
                error=error,
                asr_latency_ms=round((time.monotonic() - state.input_started_at) * 1000, 1),
            )
            return
        text = str(getattr(result, "text", "") or "").strip()
        if not text:
            self._audio().apply_asr_result(
                turn_id,
                AsrResult("failed", reason="asr_empty_transcript"),
                current_scene_generation=scene_generation,
                current_runtime_generation=runtime_generation,
            )
            self._active_turn_id = 0
            log_diagnostic(
                "mic_asr_end",
                runtime_generation=runtime_generation,
                turn_id=turn_id,
                status="failed",
                error="asr_empty_transcript",
            )
            return
        summary = f"mic_transcript:{len(text)}chars"
        self._audio().apply_asr_result(
            turn_id,
            AsrResult("ok", text=text, safe_summary=summary),
            current_scene_generation=scene_generation,
            current_runtime_generation=runtime_generation,
        )
        self._active_turn_id = 0
        final = self._audio().get_turn(turn_id)
        log_diagnostic(
            "mic_asr_end",
            runtime_generation=runtime_generation,
            turn_id=turn_id,
            status=final.asr_status,
            transcript_chars=len(text),
            asr_latency_ms=round((time.monotonic() - final.input_started_at) * 1000, 1),
        )
        if final.status == "transcribed":
            self._runtime.on_mic_transcript_ready(turn_id)


def mic_route_enabled(
    *,
    running: bool,
    dialogue_enabled: bool,
    danmu_adapter_enabled: bool,
) -> bool:
    """mode config 后端状态为唯一分流依据。"""

    return running and dialogue_enabled and not danmu_adapter_enabled


__all__ = [
    "MicAsrJob",
    "VirtualHostMicRoute",
    "mic_route_enabled",
]
