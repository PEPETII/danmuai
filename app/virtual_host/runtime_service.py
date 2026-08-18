"""虚拟主播运行时：独立视觉/TTS 绑定消费与场景上下文更新。"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from app.danmu_tts_playback import DanmuTtsPlayback
from app.mic_transcription import MicTranscriptionResult, transcribe_pcm
from app.screenshot_compress import compress_screenshot
from app.tts.types import TtsError
from app.tts_providers import get_tts_manager
from app.virtual_host.audio import (
    TtsBinding,
    TtsSynthesisOutcome,
    TtsSynthesizer,
    VirtualHostAudioOrchestrator,
    segment_text,
)
from app.virtual_host.chat import HostChatHttpResult, request_host_chat
from app.virtual_host.contracts import (
    BatchAcceptance,
    DanmuBatchCreated,
    HostTurn,
    HostTurnResult,
    SceneContext,
)
from app.virtual_host.diagnostics import log_diagnostic
from app.virtual_host.knowledge import KnowledgeContextAdapter
from app.virtual_host.live2d_feedback import Live2DFeedbackController
from app.virtual_host.mic_route import MicAsrJob, VirtualHostMicRoute, mic_route_enabled
from app.virtual_host.mode_config import export_virtual_host_mode_settings
from app.virtual_host.model_config import (
    resolve_virtual_host_tts_binding,
    resolve_virtual_host_vision_credentials,
    sanitize_virtual_host_model_config,
    virtual_host_vision_enabled,
)
from app.virtual_host.persona_config import load_virtual_host_persona_snapshot
from app.virtual_host.playback import PlaybackItem, PlaybackPriority, PlaybackQueue
from app.virtual_host.response_scheduler import (
    ResponseCandidateEvent,
    VirtualHostResponseScheduler,
    build_autonomous_input,
)
from app.virtual_host.session import VirtualHostSession
from app.virtual_host.vision import (
    SceneSummaryResult,
    _keywords_from_summary,
    request_scene_summary,
)
from app.virtual_host.voice_status import export_voice_status
from app.virtual_host_playback_adapter import DanmuTtsPlaybackAdapter
from app.worker_pools import ai_worker_pool

if TYPE_CHECKING:
    from main import DanmuApp

logger = logging.getLogger(__name__)

_USER_MIC_PLAYBACK_ECHO_COOLDOWN_SEC = 0.35
_MAX_SPEECH_LOG_ENTRIES = 200


def _monotonic_elapsed_since(captured_at: float) -> float:
    """Return elapsed seconds since a monotonic capture stamp (diagnostics only)."""

    return max(0.0, time.monotonic() - float(captured_at))

__all__ = [
    "ChatResponseCoordinator",
    "SceneVisionCoordinator",
    "TtsSynthesisCoordinator",
    "VirtualHostRuntimeService",
]


class ChatResponseCoordinator(QObject):
    """主线程 QObject；Chat worker 经 completed 信号回传结构化结果。"""

    completed = pyqtSignal(object, object, int, str)


class SceneVisionCoordinator(QObject):
    """主线程 QObject；场景视觉 worker 经 completed 信号回传结构化结果。"""

    completed = pyqtSignal(object, int, int, float, int, str)


class TtsSynthesisCoordinator(QObject):
    """主线程 QObject；TTS worker 经 completed 信号回传合成结果。"""

    completed = pyqtSignal(object, object)


class MicAsrCoordinator(QObject):
    """主线程 QObject；麦克风 ASR worker 经 completed 信号回传结构化结果。"""

    completed = pyqtSignal(int, object, int)  # turn_id, MicTranscriptionResult, runtime_generation


@dataclass(frozen=True)
class TtsSynthesisJob:
    session_id: str
    turn_id: int
    segment_index: int
    text: str
    runtime_generation: int
    binding: TtsBinding
    priority: int = PlaybackPriority.AUTO_SCENE
    source: str = "auto_reply"
    started_at: float = 0.0


@dataclass
class _SpokenTtsState:
    session_id: str
    turn_id: int
    segments: tuple[str, ...] = ()
    next_segment_index: int = 0
    runtime_generation: int = 0
    priority: int = PlaybackPriority.AUTO_SCENE
    source: str = "auto_reply"
    event_kind: str = ""
    event_at: float = 0.0
    tts_started_at: float = 0.0
    failed: bool = False


class _TtsSynthesisRunnable(QRunnable):
    def __init__(
        self,
        coordinator: TtsSynthesisCoordinator,
        *,
        job: TtsSynthesisJob,
        synthesizer: TtsSynthesizer,
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._job = job
        self._synthesizer = synthesizer
        self.setAutoDelete(True)

    def run(self) -> None:
        started_at = self._job.started_at or time.monotonic()
        try:
            outcome = self._synthesizer.synthesize(self._job.text, self._job.binding)
        except Exception as exc:
            logger.warning("virtual_host tts worker failed: %r", exc)
            outcome = TtsSynthesisOutcome("failed", reason=type(exc).__name__)
        log_diagnostic(
            "tts_segment_end",
            runtime_generation=self._job.runtime_generation,
            turn_id=self._job.turn_id,
            model_id=self._job.binding.model_id,
            status=outcome.status,
            error=outcome.reason,
            segment_index=self._job.segment_index,
            segment_chars=len(self._job.text),
            tts_latency_ms=round((time.monotonic() - started_at) * 1000, 1),
        )
        self._coordinator.completed.emit(self._job, outcome)


class _MicAsrRunnable(QRunnable):
    def __init__(
        self,
        coordinator: MicAsrCoordinator,
        *,
        job: MicAsrJob,
        config: Any,
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._job = job
        self._config = config
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = transcribe_pcm(self._config, self._job.pcm)
        except Exception as exc:
            logger.warning("virtual_host mic asr worker failed: %r", exc)
            result = MicTranscriptionResult(False, error=type(exc).__name__)
        self._coordinator.completed.emit(
            self._job.turn_id,
            result,
            self._job.runtime_generation,
        )


class _ChatResponseRunnable(QRunnable):
    def __init__(
        self,
        coordinator: ChatResponseCoordinator,
        *,
        prompt: object,
        resolved: tuple[str, str, str, str],
        host_turn: HostTurn,
        runtime_generation: int,
        chat_model_id: str,
        started_at: float | None = None,
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._prompt = prompt
        self._resolved = resolved
        self._host_turn = host_turn
        self._runtime_generation = int(runtime_generation)
        self._chat_model_id = str(chat_model_id)
        self._started_at = time.monotonic() if started_at is None else float(started_at)
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = request_host_chat(
                self._prompt,
                self._resolved,
                session_id=self._host_turn.session_id,
                turn_id=self._host_turn.turn_id,
            )
        except Exception as exc:
            logger.warning("virtual_host chat worker failed: %r", exc)
            result = HostChatHttpResult(ok=False, error=type(exc).__name__)
        log_diagnostic(
            "chat_end",
            runtime_generation=self._runtime_generation,
            turn_id=self._host_turn.turn_id,
            model_id=self._chat_model_id,
            status="ok" if result.ok else "failed",
            error=result.error,
            text_chars=len(result.result.text) if result.ok and result.result is not None else 0,
            chat_latency_ms=round((time.monotonic() - self._started_at) * 1000, 1),
        )
        self._coordinator.completed.emit(
            result,
            self._host_turn,
            self._runtime_generation,
            self._chat_model_id,
        )


class _SceneVisionRunnable(QRunnable):
    def __init__(
        self,
        coordinator: SceneVisionCoordinator,
        *,
        image_data_uri: str,
        resolved: tuple[str, str, str, str],
        screenshot_id: int,
        scene_generation: int,
        captured_at: float,
        runtime_generation: int,
        vision_model_id: str,
        started_at: float | None = None,
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._image_data_uri = image_data_uri
        self._resolved = resolved
        self._screenshot_id = int(screenshot_id)
        self._scene_generation = int(scene_generation)
        self._captured_at = float(captured_at)
        self._runtime_generation = int(runtime_generation)
        self._vision_model_id = str(vision_model_id)
        self._started_at = time.monotonic() if started_at is None else float(started_at)
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = request_scene_summary(self._image_data_uri, self._resolved)
        except Exception as exc:
            logger.warning("virtual_host scene vision worker failed: %r", exc)
            result = SceneSummaryResult(ok=False, error=type(exc).__name__)
        log_diagnostic(
            "scene_request_end",
            runtime_generation=self._runtime_generation,
            model_id=self._vision_model_id,
            status="ok" if result.ok else "failed",
            error=result.error,
            screenshot_id=self._screenshot_id,
            scene_generation=self._scene_generation,
            request_latency_ms=round((time.monotonic() - self._started_at) * 1000, 1),
        )
        self._coordinator.completed.emit(
            result,
            self._screenshot_id,
            self._scene_generation,
            self._captured_at,
            self._runtime_generation,
            self._vision_model_id,
        )


class VirtualHostRuntimeService:
    """挂载于 DanmuApp；Live2D 启动后消费虚拟主播模型配置。"""

    def __init__(self, app: "DanmuApp") -> None:
        self._app = app
        self._running = False
        self._vision_in_flight = False
        self._chat_in_flight = False
        self._runtime_generation = 0
        mode_settings = export_virtual_host_mode_settings(app.config)
        self._dialogue_enabled = bool(mode_settings["dialogue_enabled"])
        self._danmu_adapter_enabled = bool(mode_settings["danmu_adapter_enabled"])
        self._active_vision_model_id = ""
        self._last_spoke_at: float | None = None
        self.vision_request_count = 0
        self.chat_request_count = 0
        self.tts_synthesize_count = 0
        self._session = VirtualHostSession(
            persona_snapshot_loader=lambda: load_virtual_host_persona_snapshot(self._app.config),
        )
        self._response_scheduler = VirtualHostResponseScheduler()
        self._tts_binding: TtsBinding | None = None
        self._spoken_tts_states: dict[tuple[str, int], _SpokenTtsState] = {}
        self._speech_logs: deque[dict[str, object]] = deque(maxlen=_MAX_SPEECH_LOG_ENTRIES)
        self._chat_event_context: dict[tuple[str, int], tuple[str, float]] = {}
        self._pending_voice_chat: dict[int, int] = {}
        self._knowledge_adapter: KnowledgeContextAdapter | None = None
        self._playback_event_at: dict[tuple[str, int, int], tuple[str, float]] = {}
        self._playback_started_at: dict[tuple[str, int, int], float] = {}
        self._playback_model_ids: dict[tuple[str, int, int], str] = {}
        self._playback_echo_guard_until = 0.0
        self._voice_session_armed = False
        self._live2d_feedback = Live2DFeedbackController()
        coordinator_parent = app if isinstance(app, QObject) else None
        self._vision_coordinator = SceneVisionCoordinator(coordinator_parent)
        self._vision_coordinator.completed.connect(self._on_scene_vision_completed)
        self._chat_coordinator = ChatResponseCoordinator(coordinator_parent)
        self._chat_coordinator.completed.connect(self._on_chat_response_completed)
        self._tts_coordinator = TtsSynthesisCoordinator(coordinator_parent)
        self._tts_coordinator.completed.connect(self._on_tts_synthesis_completed)
        self._mic_asr_coordinator = MicAsrCoordinator(coordinator_parent)
        self._mic_asr_coordinator.completed.connect(self._on_mic_asr_completed)
        self._danmu_playback = DanmuTtsPlayback()
        if coordinator_parent is not None:
            self._danmu_playback.setParent(coordinator_parent)
        playback_adapter = DanmuTtsPlaybackAdapter(self._danmu_playback)
        self._audio = VirtualHostAudioOrchestrator(
            self._session,
            tts=self._build_tts_synthesizer(),
            playback=PlaybackQueue(playback_adapter),
        )
        self._audio.playback.add_listener(self._on_playback_event)
        self._mic_route = VirtualHostMicRoute(
            self,
            schedule_asr_job=self._schedule_mic_asr_job,
        )
        self.refresh_model_bindings(bump_generation_on_vision_change=False)

    @property
    def session(self) -> VirtualHostSession:
        return self._session

    @property
    def audio(self) -> VirtualHostAudioOrchestrator:
        return self._audio

    @property
    def running(self) -> bool:
        return self._running

    @property
    def vision_in_flight(self) -> bool:
        return self._vision_in_flight

    @property
    def chat_in_flight(self) -> bool:
        return self._chat_in_flight

    @property
    def response_scheduler(self) -> VirtualHostResponseScheduler:
        return self._response_scheduler

    @property
    def runtime_generation(self) -> int:
        return self._runtime_generation

    @property
    def dialogue_enabled(self) -> bool:
        return self._dialogue_enabled

    @property
    def danmu_adapter_enabled(self) -> bool:
        return self._danmu_adapter_enabled

    @property
    def voice_session_armed(self) -> bool:
        return self._voice_session_armed

    def get_speech_logs(self) -> list[dict[str, object]]:
        """Return the bounded, current-process log of accepted host speech."""

        return [dict(entry) for entry in self._speech_logs]

    def _record_speech_log(
        self,
        result: HostTurnResult,
        *,
        source: str,
        event_kind: str = "",
        timestamp: float | None = None,
    ) -> None:
        if not result.speak or not result.text:
            return
        self._speech_logs.append(
            {
                "id": f"{result.session_id}:{result.turn_id}",
                "timestamp": time.time() if timestamp is None else float(timestamp),
                "turn_id": int(result.turn_id),
                "source": str(source or "virtual_host"),
                "event_kind": str(event_kind or ""),
                "text": result.text,
            }
        )

    def _autonomous_response_enabled(self) -> bool:
        """弹幕适配模式开启且对话模式关闭时才允许自动批次/场景回应。"""

        return self._danmu_adapter_enabled and not self._dialogue_enabled

    @property
    def live2d_feedback(self) -> Live2DFeedbackController:
        return self._live2d_feedback

    def attach_live2d_runtime(self, runtime: object) -> None:
        """Bind the feedback layer to the current main-thread Live2D window."""

        self._live2d_feedback.bind_runtime(
            runtime,
            runtime_generation=self._runtime_generation,
        )
        if self._running:
            self._live2d_feedback.activate()

    def detach_live2d_runtime(self) -> None:
        self._live2d_feedback.unbind_runtime()

    def mount(self) -> None:
        self.refresh_mode_settings(bump_generation=False)
        self.refresh_model_bindings(bump_generation_on_vision_change=False)

    def refresh_mode_settings(self, *, bump_generation: bool = True) -> None:
        """主线程：读取持久化互斥模式，变更时递增 runtime_generation 失效在途结果。"""

        settings = export_virtual_host_mode_settings(self._app.config)
        dialogue = bool(settings["dialogue_enabled"])
        danmu_adapter = bool(settings["danmu_adapter_enabled"])
        previous = (self._dialogue_enabled, self._danmu_adapter_enabled)
        current = (dialogue, danmu_adapter)
        self._dialogue_enabled = dialogue
        self._danmu_adapter_enabled = danmu_adapter
        if previous != current:
            self._voice_session_armed = False
            self._mic_route.reset(reason="mode_changed")
        if bump_generation and previous != current:
            self._bump_runtime_generation()
            log_diagnostic(
                "mode_settings_refresh",
                runtime_generation=self._runtime_generation,
                model_id=self._active_vision_model_id,
                reason="mode_changed",
            )

    def start(self) -> None:
        self._running = True
        self._bump_runtime_generation()
        self._live2d_feedback.activate()
        self.refresh_model_bindings(bump_generation_on_vision_change=False)
        log_diagnostic(
            "runtime_start",
            runtime_generation=self._runtime_generation,
            model_id=self._active_vision_model_id,
        )

    def stop(self) -> None:
        self._running = False
        self._voice_session_armed = False
        self._mic_route.reset(reason="runtime_stop")
        self._live2d_feedback.deactivate()
        self._playback_echo_guard_until = 0.0
        self._bump_runtime_generation()
        log_diagnostic(
            "runtime_stop",
            runtime_generation=self._runtime_generation,
            model_id=self._active_vision_model_id,
        )

    def _bump_runtime_generation(self) -> int:
        self._runtime_generation += 1
        self._live2d_feedback.set_runtime_generation(self._runtime_generation)
        self._spoken_tts_states.clear()
        self._chat_event_context.clear()
        self._pending_voice_chat.clear()
        self._purge_stale_auto_playback()
        self._playback_event_at.clear()
        self._playback_started_at.clear()
        self._playback_model_ids.clear()
        self._playback_echo_guard_until = 0.0
        log_diagnostic(
            "runtime_generation_bump",
            runtime_generation=self._runtime_generation,
            model_id=self._active_vision_model_id,
        )
        return self._runtime_generation

    def _purge_stale_auto_playback(self) -> None:
        self._audio.playback.purge_stale_auto_runtime(
            self._runtime_generation,
            reason="runtime_generation_stale",
        )

    def _tts_binding_key(self, binding: TtsBinding | None) -> tuple[str, str, str]:
        if binding is None:
            return ("", "", "")
        return (
            str(binding.provider_id),
            str(binding.model_id),
            str(binding.voice_id),
        )

    def refresh_model_bindings(self, *, bump_generation_on_vision_change: bool = True) -> None:
        config = self._app.config
        sanitize_virtual_host_model_config(config, persist=True)
        previous_vision = self._active_vision_model_id
        previous_tts_key = self._tts_binding_key(self._tts_binding)
        resolved = resolve_virtual_host_vision_credentials(config)
        new_vision = resolved[2] if resolved is not None else ""
        if bump_generation_on_vision_change and previous_vision != new_vision:
            self._bump_runtime_generation()
        self._active_vision_model_id = new_vision
        try:
            binding = resolve_virtual_host_tts_binding(config, get_tts_manager())
        except TtsError as exc:
            # TTS is optional: typed TTS configuration/provider errors disable
            # only the binding. Unknown exceptions must still reach the caller.
            binding = None
            log_diagnostic(
                "tts_binding_unavailable",
                runtime_generation=self._runtime_generation,
                model_id="",
                status="unavailable",
                reason=type(exc).__name__,
                error=type(exc).__name__,
            )
        new_tts_key = self._tts_binding_key(binding)
        if self._tts_binding is not None and new_tts_key != previous_tts_key:
            self._bump_runtime_generation()
        self._tts_binding = binding
        self._audio.tts_binding = binding
        self._audio.tts = self._build_tts_synthesizer()
        self._spoken_tts_states.clear()
        self._purge_stale_auto_playback()

    def _build_worker_tts_synthesizer(self) -> TtsSynthesizer:
        """Worker 线程专用合成器；计数在主线程投递 job 时维护。"""
        return TtsSynthesizer(get_tts_manager())

    def _build_tts_synthesizer(self) -> TtsSynthesizer:
        return self._build_worker_tts_synthesizer()

    def on_danmu_batch_created(self, batch: DanmuBatchCreated) -> BatchAcceptance:
        """主链路弹幕批次入口；未 running 时拒绝，不触发 Chat/TTS。"""

        if not self._running:
            batch_id = batch.batch_id if isinstance(batch, DanmuBatchCreated) else ""
            log_diagnostic(
                "danmu_batch",
                runtime_generation=self._runtime_generation,
                model_id=self._active_vision_model_id,
                batch_id=batch_id,
                accepted=False,
                reason="runtime_stopped",
            )
            return BatchAcceptance(False, "invalid", batch_id)
        batch_id = batch.batch_id if isinstance(batch, DanmuBatchCreated) else ""
        if not self._autonomous_response_enabled():
            log_diagnostic(
                "danmu_batch",
                runtime_generation=self._runtime_generation,
                model_id=self._active_vision_model_id,
                batch_id=batch_id,
                accepted=False,
                reason="mode_disabled",
            )
            return BatchAcceptance(False, "mode_disabled", batch_id)
        scene_generation = int(getattr(self._app, "_scene_generation", 0))
        decision = self._session.ingest_danmu_batch(
            batch,
            current_scene_generation=scene_generation,
        )
        if decision.accepted:
            self._on_response_candidate(
                ResponseCandidateEvent(
                    kind="danmu_batch",
                    at=time.time(),
                    batch_id=decision.batch_id,
                    scene_generation=scene_generation,
                )
            )
        log_diagnostic(
            "danmu_batch",
            runtime_generation=self._runtime_generation,
            model_id=self._active_vision_model_id,
            batch_id=decision.batch_id,
            accepted=decision.accepted,
            reason=decision.reason,
            scene_generation=scene_generation,
        )
        return decision

    def mic_route_active(self) -> bool:
        return (
            self._voice_session_armed
            and mic_route_enabled(
                running=self._running,
                dialogue_enabled=self._dialogue_enabled,
                danmu_adapter_enabled=self._danmu_adapter_enabled,
            )
        )

    def get_voice_status(self) -> dict[str, object]:
        return export_voice_status(self, self._app)

    def start_voice_session(self) -> dict[str, object]:
        if not self._dialogue_enabled:
            raise ValueError("dialogue_mode_disabled")
        if self._danmu_adapter_enabled:
            raise ValueError("adapter_mode_active")
        if not self._running:
            raise ValueError("runtime_stopped")
        self._voice_session_armed = True
        log_diagnostic(
            "voice_session_start",
            runtime_generation=self._runtime_generation,
            status="armed",
        )
        return self.get_voice_status()

    def stop_voice_session(self) -> dict[str, object]:
        self._voice_session_armed = False
        if self._mic_route.active_turn_id:
            self._mic_route.on_utterance_discarded()
        log_diagnostic(
            "voice_session_stop",
            runtime_generation=self._runtime_generation,
            status="disarmed",
        )
        return self.get_voice_status()

    def cancel_voice_session(self) -> dict[str, object]:
        self._voice_session_armed = False
        for state in self._audio.turns:
            if state.source != "user_mic":
                continue
            if state.status in {"completed", "cancelled", "failed"}:
                continue
            self._audio.cancel_turn(state.turn_id, reason="user_cancelled")
        self._mic_route.reset(reason="user_cancelled")
        self._playback_echo_guard_until = 0.0
        log_diagnostic(
            "voice_session_cancel",
            runtime_generation=self._runtime_generation,
            status="cancelled",
        )
        return self.get_voice_status()

    def on_mic_speech_start(self) -> bool:
        if not self.mic_route_active():
            return False
        if self._user_mic_echo_guard_active():
            log_diagnostic(
                "mic_turn_skipped",
                runtime_generation=self._runtime_generation,
                reason="playback_echo_guard",
            )
            return False
        return self._mic_route.on_speech_start()

    def _user_mic_echo_guard_active(self) -> bool:
        """USER_MIC 播报与结束后短 cooldown 内抑制自回声新轮次。"""

        active = self._audio.playback.active_item
        if active is not None and (
            str(getattr(active, "source", "")) == "mic_reply"
            or int(active.priority) >= PlaybackPriority.USER_MIC
        ):
            return True
        return time.monotonic() < self._playback_echo_guard_until

    def on_mic_utterance_discarded(self) -> bool:
        if not self._mic_route.active_turn_id and not self._mic_route.asr_in_flight:
            return False
        return self._mic_route.on_utterance_discarded()

    def on_mic_utterance_end(self, pcm: bytes) -> bool:
        if not self.mic_route_active():
            return False
        return self._mic_route.on_utterance_end(pcm)

    def _schedule_mic_asr_job(self, job: MicAsrJob) -> None:
        runnable = _MicAsrRunnable(
            self._mic_asr_coordinator,
            job=job,
            config=self._app.config,
        )
        ai_worker_pool().start(runnable)

    def _on_mic_asr_completed(
        self,
        turn_id: int,
        result: MicTranscriptionResult,
        runtime_generation: int,
    ) -> None:
        self._mic_route.on_asr_completed(turn_id, result, runtime_generation)

    def _knowledge_context_adapter(self) -> KnowledgeContextAdapter:
        if self._knowledge_adapter is None:
            runtime = getattr(self._app, "knowledge_runtime", None)
            self._knowledge_adapter = KnowledgeContextAdapter(runtime)
        return self._knowledge_adapter

    def on_mic_transcript_ready(self, voice_turn_id: int) -> None:
        """主线程：ASR 成功后投递 voice chat worker，不阻塞麦克风回调。"""

        if not self._running or not self._dialogue_enabled:
            return
        scene_generation = int(getattr(self._app, "_scene_generation", 0))
        runtime_generation = self._runtime_generation
        try:
            state = self._audio.get_turn(voice_turn_id)
        except KeyError:
            return
        if state.status != "transcribed":
            return
        if self._chat_in_flight:
            self._audio.fail_chat(
                voice_turn_id,
                "chat_in_flight",
                current_scene_generation=scene_generation,
                current_runtime_generation=runtime_generation,
            )
            log_diagnostic(
                "voice_chat_skipped",
                runtime_generation=runtime_generation,
                turn_id=voice_turn_id,
                reason="chat_in_flight",
            )
            return
        prompt = self._audio.prepare_chat(
            voice_turn_id,
            current_scene_generation=scene_generation,
            current_runtime_generation=runtime_generation,
        )
        if prompt is None or state.host_turn is None:
            return
        host_turn = state.host_turn
        knowledge = self._knowledge_context_adapter().retrieve(
            turn_id=host_turn.turn_id,
            input_text=host_turn.input_text,
            scene_context=host_turn.scene_context,
            recent_batches=host_turn.recent_batches,
            mic_text=host_turn.mic_text,
        )
        prompt = self._session.compose_prompt(host_turn, knowledge=knowledge)
        state.prompt = prompt
        resolved = resolve_virtual_host_vision_credentials(self._app.config)
        if resolved is None:
            self._audio.fail_chat(
                voice_turn_id,
                "credentials_unavailable",
                current_scene_generation=scene_generation,
                current_runtime_generation=runtime_generation,
            )
            log_diagnostic(
                "voice_chat_end",
                runtime_generation=runtime_generation,
                turn_id=voice_turn_id,
                status="failed",
                error="credentials_unavailable",
            )
            return
        chat_model_id = resolved[2]
        started_at = time.monotonic()
        self._pending_voice_chat[host_turn.turn_id] = voice_turn_id
        self._chat_in_flight = True
        self.chat_request_count += 1
        log_diagnostic(
            "voice_chat_start",
            runtime_generation=runtime_generation,
            turn_id=voice_turn_id,
            session_turn_id=host_turn.turn_id,
            model_id=chat_model_id,
            scene_generation=scene_generation,
            transcript_chars=len(state.transcript),
            source="user_mic",
        )
        runnable = _ChatResponseRunnable(
            self._chat_coordinator,
            prompt=prompt,
            resolved=resolved,
            host_turn=host_turn,
            runtime_generation=runtime_generation,
            chat_model_id=chat_model_id,
            started_at=started_at,
        )
        ai_worker_pool().start(runnable)

    def _should_apply_voice_chat_result(
        self,
        *,
        voice_turn_id: int,
        host_turn: HostTurn,
        runtime_generation: int,
        request_chat_model_id: str,
    ) -> bool:
        if not self._running or not self._dialogue_enabled:
            return False
        if int(runtime_generation) != self._runtime_generation:
            return False
        if str(request_chat_model_id) != self._active_vision_model_id:
            return False
        try:
            state = self._audio.get_turn(voice_turn_id)
        except KeyError:
            return False
        if state.cancelled or state.status not in {"chatting", "chat_completed"}:
            return False
        if state.host_turn is None or state.host_turn.turn_id != host_turn.turn_id:
            return False
        return True

    def _complete_voice_chat(
        self,
        voice_turn_id: int,
        result: HostChatHttpResult | None,
        host_turn: HostTurn,
        runtime_generation: int,
        request_chat_model_id: str,
    ) -> None:
        scene_generation = int(getattr(self._app, "_scene_generation", 0))
        if not self._should_apply_voice_chat_result(
            voice_turn_id=voice_turn_id,
            host_turn=host_turn,
            runtime_generation=runtime_generation,
            request_chat_model_id=request_chat_model_id,
        ):
            log_diagnostic(
                "voice_chat_end",
                runtime_generation=self._runtime_generation,
                turn_id=voice_turn_id,
                session_turn_id=host_turn.turn_id,
                model_id=request_chat_model_id,
                status="stale",
            )
            return
        if result is None or not result.ok or result.result is None:
            error = str(result.error if result is not None else "missing_result")
            self._audio.fail_chat(
                voice_turn_id,
                error,
                current_scene_generation=scene_generation,
                current_runtime_generation=runtime_generation,
            )
            log_diagnostic(
                "voice_chat_end",
                runtime_generation=runtime_generation,
                turn_id=voice_turn_id,
                session_turn_id=host_turn.turn_id,
                model_id=request_chat_model_id,
                status="failed",
                error=error,
            )
            return
        try:
            state = self._audio.submit_chat_result(
                voice_turn_id,
                result.result,
                current_scene_generation=scene_generation,
                current_runtime_generation=runtime_generation,
            )
        except ValueError as exc:
            self._audio.fail_chat(
                voice_turn_id,
                f"chat_result_invalid:{type(exc).__name__}",
                current_scene_generation=scene_generation,
                current_runtime_generation=runtime_generation,
            )
            log_diagnostic(
                "voice_chat_end",
                runtime_generation=runtime_generation,
                turn_id=voice_turn_id,
                session_turn_id=host_turn.turn_id,
                model_id=request_chat_model_id,
                status="failed",
                error=type(exc).__name__,
            )
            return
        if state.status != "chat_completed" or state.host_result is None:
            return
        self._record_speech_log(
            state.host_result,
            source="user_mic",
            event_kind="user_mic",
        )
        log_diagnostic(
            "voice_chat_end",
            runtime_generation=runtime_generation,
            turn_id=voice_turn_id,
            session_turn_id=host_turn.turn_id,
            model_id=request_chat_model_id,
            status="ok",
            text_chars=len(state.host_result.text),
            source="user_mic",
        )
        self._live2d_feedback.apply_turn_result(
            state.host_result,
            runtime_generation=runtime_generation,
        )
        self._enqueue_spoken_tts(
            state.host_result,
            runtime_generation=runtime_generation,
            priority=PlaybackPriority.USER_MIC,
            source="mic_reply",
            event_kind="user_mic",
            event_at=time.time(),
        )

    def on_capture_completed(
        self,
        pixmap: Any,
        *,
        screenshot_id: int,
        scene_generation: int,
        captured_at: float | None = None,
    ) -> None:
        if not self._running or pixmap is None:
            log_diagnostic(
                "scene_request_skipped",
                runtime_generation=self._runtime_generation,
                model_id=self._active_vision_model_id,
                screenshot_id=screenshot_id,
                scene_generation=scene_generation,
                reason="runtime_stopped_or_empty_capture",
            )
            return
        if not virtual_host_vision_enabled(self._app.config):
            log_diagnostic(
                "scene_request_skipped",
                runtime_generation=self._runtime_generation,
                model_id=self._active_vision_model_id,
                screenshot_id=screenshot_id,
                scene_generation=scene_generation,
                reason="model_disabled",
            )
            return
        if self._vision_in_flight:
            log_diagnostic(
                "scene_request_skipped",
                runtime_generation=self._runtime_generation,
                model_id=self._active_vision_model_id,
                screenshot_id=screenshot_id,
                scene_generation=scene_generation,
                reason="vision_in_flight",
            )
            return
        resolved = resolve_virtual_host_vision_credentials(self._app.config)
        if resolved is None:
            log_diagnostic(
                "scene_request_skipped",
                runtime_generation=self._runtime_generation,
                model_id=self._active_vision_model_id,
                screenshot_id=screenshot_id,
                scene_generation=scene_generation,
                reason="credentials_unavailable",
            )
            return
        try:
            image_data_uri = compress_screenshot(pixmap)
        except Exception as exc:
            logger.debug("virtual_host scene compress skipped: %r", exc)
            log_diagnostic(
                "scene_request_skipped",
                runtime_generation=self._runtime_generation,
                model_id=resolved[2],
                screenshot_id=screenshot_id,
                scene_generation=scene_generation,
                reason="compress_failed",
                error=type(exc).__name__,
            )
            return
        runtime_generation = self._runtime_generation
        vision_model_id = resolved[2]
        captured_at_value = captured_at if captured_at is not None else time.monotonic()
        started_at = time.monotonic()
        self._vision_in_flight = True
        self.vision_request_count += 1
        log_diagnostic(
            "scene_request_start",
            runtime_generation=runtime_generation,
            model_id=vision_model_id,
            screenshot_id=screenshot_id,
            scene_generation=scene_generation,
        )
        runnable = _SceneVisionRunnable(
            self._vision_coordinator,
            image_data_uri=image_data_uri,
            resolved=resolved,
            screenshot_id=screenshot_id,
            scene_generation=scene_generation,
            captured_at=captured_at_value,
            runtime_generation=runtime_generation,
            vision_model_id=vision_model_id,
            started_at=started_at,
        )
        ai_worker_pool().start(runnable)

    def update_scene_from_image_data_uri(
        self,
        image_data_uri: str,
        *,
        screenshot_id: int,
        scene_generation: int,
        captured_at: float | None = None,
    ) -> SceneSummaryResult | None:
        """同步场景更新；未配置视觉模型时返回 ``None`` 且不发 HTTP。"""

        if not self._running:
            return None
        resolved = resolve_virtual_host_vision_credentials(self._app.config)
        if resolved is None:
            return None
        runtime_generation = self._runtime_generation
        vision_model_id = resolved[2]
        started_at = time.monotonic()
        self.vision_request_count += 1
        log_diagnostic(
            "scene_request_start",
            runtime_generation=runtime_generation,
            model_id=vision_model_id,
            screenshot_id=screenshot_id,
            scene_generation=scene_generation,
        )
        result = request_scene_summary(image_data_uri, resolved)
        log_diagnostic(
            "scene_request_end",
            runtime_generation=runtime_generation,
            model_id=vision_model_id,
            status="ok" if result.ok else "failed",
            error=result.error,
            screenshot_id=screenshot_id,
            scene_generation=scene_generation,
            request_latency_ms=round((time.monotonic() - started_at) * 1000, 1),
        )
        if result.ok and self._should_apply_scene_vision_result(
            runtime_generation=runtime_generation,
            request_vision_model_id=vision_model_id,
        ):
            self._apply_scene_summary(
                result,
                screenshot_id=screenshot_id,
                scene_generation=scene_generation,
                captured_at=captured_at,
            )
        return result

    def _on_scene_vision_completed(
        self,
        result: SceneSummaryResult | None,
        screenshot_id: int,
        scene_generation: int,
        captured_at: float,
        runtime_generation: int,
        request_vision_model_id: str,
    ) -> None:
        self._complete_scene_vision(
            result,
            screenshot_id=screenshot_id,
            scene_generation=scene_generation,
            captured_at=captured_at,
            runtime_generation=runtime_generation,
            request_vision_model_id=request_vision_model_id,
        )

    def _should_apply_scene_vision_result(
        self,
        *,
        runtime_generation: int,
        request_vision_model_id: str,
    ) -> bool:
        if not self._running:
            return False
        if int(runtime_generation) != self._runtime_generation:
            return False
        if str(request_vision_model_id) != self._active_vision_model_id:
            return False
        return True

    def _complete_scene_vision(
        self,
        result: SceneSummaryResult | None,
        *,
        screenshot_id: int,
        scene_generation: int,
        captured_at: float,
        runtime_generation: int,
        request_vision_model_id: str,
    ) -> None:
        self._vision_in_flight = False
        if not self._should_apply_scene_vision_result(
            runtime_generation=runtime_generation,
            request_vision_model_id=request_vision_model_id,
        ):
            log_diagnostic(
                "scene_end",
                runtime_generation=self._runtime_generation,
                model_id=request_vision_model_id,
                status="stale",
                applied=False,
                screenshot_id=screenshot_id,
                scene_generation=scene_generation,
                scene_latency_ms=round(_monotonic_elapsed_since(captured_at) * 1000, 1),
            )
            return
        if result is None or not result.ok:
            log_diagnostic(
                "scene_end",
                runtime_generation=runtime_generation,
                model_id=request_vision_model_id,
                status="failed" if result is None else result.error or "failed",
                applied=False,
                screenshot_id=screenshot_id,
                scene_generation=scene_generation,
                scene_latency_ms=round(_monotonic_elapsed_since(captured_at) * 1000, 1),
            )
            return
        self._apply_scene_summary(
            result,
            screenshot_id=screenshot_id,
            scene_generation=scene_generation,
            captured_at=captured_at,
        )

    def _apply_scene_summary(
        self,
        result: SceneSummaryResult,
        *,
        screenshot_id: int,
        scene_generation: int,
        captured_at: float | None,
    ) -> None:
        wall_now = time.time()
        context = SceneContext(
            scene_generation=int(scene_generation),
            summary=result.text,
            keywords=_keywords_from_summary(result.text),
            screenshot_id=screenshot_id,
            updated_at=wall_now,
        )
        self._session.update_scene_context(context)
        latency_fields: dict[str, float] = {}
        if captured_at is not None:
            latency_fields["scene_latency_ms"] = round(
                _monotonic_elapsed_since(captured_at) * 1000,
                1,
            )
        log_diagnostic(
            "scene_end",
            runtime_generation=self._runtime_generation,
            model_id=result.model_id or self._active_vision_model_id,
            status="ok",
            applied=True,
            screenshot_id=screenshot_id,
            scene_generation=scene_generation,
            **latency_fields,
        )
        self._on_response_candidate(
            ResponseCandidateEvent(
                kind="scene_change",
                at=wall_now,
                scene_generation=int(scene_generation),
            )
        )

    def _on_response_candidate(self, event: ResponseCandidateEvent) -> None:
        if not self._running:
            return
        if not self._autonomous_response_enabled():
            log_diagnostic(
                "scheduler_decision",
                runtime_generation=self._runtime_generation,
                model_id=self._active_vision_model_id,
                decision="skip",
                reason="mode_disabled",
                event_kind=event.kind,
                batch_id=event.batch_id,
                scene_generation=event.scene_generation,
            )
            return
        decision = self._response_scheduler.evaluate(
            event,
            running=self._running,
            model_enabled=virtual_host_vision_enabled(self._app.config),
            chat_in_flight=self._chat_in_flight,
            last_spoke_at=self._last_spoke_at,
            session=self._session,
            now=event.at,
        )
        probability = min(1.0, max(0.0, float(decision.score)))
        log_diagnostic(
            "scheduler_decision",
            runtime_generation=self._runtime_generation,
            model_id=self._active_vision_model_id,
            decision="respond" if decision.should_respond else "skip",
            reason=decision.reason,
            relevance=round(float(decision.score), 4),
            probability=round(probability, 4),
            event_kind=event.kind,
            batch_id=event.batch_id,
            scene_generation=event.scene_generation,
        )
        if not decision.should_respond:
            return
        self._start_chat_request(now=event.at, event_kind=event.kind)

    def _start_chat_request(self, *, now: float | None = None, event_kind: str = "") -> None:
        if not self._running or self._chat_in_flight or not self._autonomous_response_enabled():
            return
        resolved = resolve_virtual_host_vision_credentials(self._app.config)
        if resolved is None:
            return
        current = time.time() if now is None else float(now)
        try:
            host_turn = self._session.start_turn(
                build_autonomous_input(self._session, now=current),
                now=current,
            )
            prompt = self._session.compose_prompt(host_turn, now=current)
        except Exception as exc:
            logger.debug("virtual_host chat prompt skipped: %r", exc)
            return
        runtime_generation = self._runtime_generation
        chat_model_id = resolved[2]
        started_at = time.monotonic()
        self._chat_in_flight = True
        self.chat_request_count += 1
        self._chat_event_context[
            self._spoken_turn_key(host_turn.session_id, host_turn.turn_id)
        ] = (str(event_kind), current)
        log_diagnostic(
            "chat_start",
            runtime_generation=runtime_generation,
            turn_id=host_turn.turn_id,
            model_id=chat_model_id,
            event_kind=event_kind,
        )
        runnable = _ChatResponseRunnable(
            self._chat_coordinator,
            prompt=prompt,
            resolved=resolved,
            host_turn=host_turn,
            runtime_generation=runtime_generation,
            chat_model_id=chat_model_id,
            started_at=started_at,
        )
        ai_worker_pool().start(runnable)

    def _should_apply_chat_result(
        self,
        *,
        runtime_generation: int,
        request_chat_model_id: str,
    ) -> bool:
        if not self._running:
            return False
        if int(runtime_generation) != self._runtime_generation:
            return False
        if str(request_chat_model_id) != self._active_vision_model_id:
            return False
        return True

    def _on_chat_response_completed(
        self,
        result: HostChatHttpResult | None,
        host_turn: HostTurn | None,
        runtime_generation: int,
        request_chat_model_id: str,
    ) -> None:
        self._chat_in_flight = False
        if host_turn is None:
            return
        voice_turn_id = self._pending_voice_chat.pop(host_turn.turn_id, 0)
        if voice_turn_id:
            self._complete_voice_chat(
                voice_turn_id,
                result,
                host_turn,
                runtime_generation,
                request_chat_model_id,
            )
            return
        if not self._should_apply_chat_result(
            runtime_generation=runtime_generation,
            request_chat_model_id=request_chat_model_id,
        ):
            return
        if result is None or not result.ok or result.result is None:
            return
        try:
            completed = self._session.complete_turn(host_turn, result.result)
        except ValueError as exc:
            logger.debug("virtual_host chat result rejected: %r", exc)
            return
        log_diagnostic(
            "chat_result_applied",
            runtime_generation=runtime_generation,
            turn_id=completed.turn_id,
            model_id=request_chat_model_id,
            status="accepted",
            text_chars=len(completed.text),
        )
        self._last_spoke_at = time.time()
        event_kind, event_at = self._chat_event_context.pop(
            self._spoken_turn_key(host_turn.session_id, host_turn.turn_id),
            ("", time.time()),
        )
        self._record_speech_log(
            completed,
            source="auto_reply",
            event_kind=event_kind,
        )
        self._live2d_feedback.apply_turn_result(
            completed,
            runtime_generation=runtime_generation,
        )
        self._enqueue_spoken_tts(
            completed,
            runtime_generation=runtime_generation,
            priority=PlaybackPriority.AUTO_SCENE,
            source="auto_reply",
            event_kind=event_kind,
            event_at=event_at,
        )

    def _spoken_turn_key(self, session_id: str, turn_id: int) -> tuple[str, int]:
        return str(session_id).strip(), int(turn_id)

    def _enqueue_spoken_tts(
        self,
        result: HostTurnResult,
        *,
        runtime_generation: int,
        priority: int = PlaybackPriority.AUTO_SCENE,
        source: str = "auto_reply",
        event_kind: str = "",
        event_at: float | None = None,
    ) -> None:
        if not result.speak or not result.text:
            log_diagnostic(
                "tts_skipped",
                runtime_generation=runtime_generation,
                turn_id=result.turn_id,
                model_id="",
                reason="silent_or_empty_result",
                text_chars=len(result.text),
            )
            return
        binding = self._tts_binding
        if binding is None:
            log_diagnostic(
                "tts_skipped",
                runtime_generation=runtime_generation,
                turn_id=result.turn_id,
                model_id="",
                reason="model_disabled",
                text_chars=len(result.text),
            )
            return
        segments = segment_text(result.text, max_chars=self._audio._max_segment_chars)
        if not segments:
            return
        key = self._spoken_turn_key(result.session_id, result.turn_id)
        self._spoken_tts_states[key] = _SpokenTtsState(
            session_id=result.session_id,
            turn_id=result.turn_id,
            segments=segments,
            runtime_generation=int(runtime_generation),
            priority=int(priority),
            source=str(source),
            event_kind=str(event_kind),
            event_at=time.time() if event_at is None else float(event_at),
            tts_started_at=time.monotonic(),
        )
        log_diagnostic(
            "tts_start",
            runtime_generation=runtime_generation,
            turn_id=result.turn_id,
            model_id=binding.model_id,
            status="started",
            segment_count=len(segments),
            text_chars=len(result.text),
        )
        self._start_next_tts_segment(key)

    def _start_next_tts_segment(self, key: tuple[str, int]) -> None:
        state = self._spoken_tts_states.get(key)
        if state is None or state.failed:
            return
        if state.next_segment_index >= len(state.segments):
            self._spoken_tts_states.pop(key, None)
            return
        binding = self._tts_binding
        if binding is None:
            self._spoken_tts_states.pop(key, None)
            return
        index = state.next_segment_index
        started_at = time.monotonic()
        self.tts_synthesize_count += 1
        log_diagnostic(
            "tts_segment_start",
            runtime_generation=state.runtime_generation,
            turn_id=state.turn_id,
            model_id=binding.model_id,
            status="started",
            segment_index=index,
            segment_count=len(state.segments),
            segment_chars=len(state.segments[index]),
        )
        job = TtsSynthesisJob(
            session_id=state.session_id,
            turn_id=state.turn_id,
            segment_index=index,
            text=state.segments[index],
            runtime_generation=state.runtime_generation,
            binding=binding,
            priority=state.priority,
            source=state.source,
            started_at=started_at,
        )
        runnable = _TtsSynthesisRunnable(
            self._tts_coordinator,
            job=job,
            synthesizer=self._build_worker_tts_synthesizer(),
        )
        ai_worker_pool().start(runnable)

    def _should_apply_tts_result(self, job: TtsSynthesisJob) -> bool:
        if not self._running:
            return False
        if int(job.runtime_generation) != self._runtime_generation:
            return False
        if job.session_id != self._session.session_id:
            return False
        key = self._spoken_turn_key(job.session_id, job.turn_id)
        state = self._spoken_tts_states.get(key)
        if state is None or state.failed:
            return False
        if state.runtime_generation != int(job.runtime_generation):
            return False
        if job.segment_index != state.next_segment_index:
            return False
        return True

    def _on_tts_synthesis_completed(
        self,
        job: TtsSynthesisJob | None,
        outcome: TtsSynthesisOutcome | None,
    ) -> None:
        if job is None:
            return
        key = self._spoken_turn_key(job.session_id, job.turn_id)
        state = self._spoken_tts_states.get(key)
        if not self._should_apply_tts_result(job):
            if state is not None and int(job.runtime_generation) != self._runtime_generation:
                self._spoken_tts_states.pop(key, None)
                self._audio.playback.cancel_turn(job.session_id, job.turn_id, reason="runtime_generation_stale")
            return
        if state is None:
            return
        if outcome is None or outcome.status != "ok" or not outcome.audio_bytes:
            log_diagnostic(
                "tts_end",
                runtime_generation=job.runtime_generation,
                turn_id=job.turn_id,
                model_id=job.binding.model_id,
                status="failed",
                error=outcome.reason if outcome is not None else "missing_outcome",
                segment_count=len(state.segments),
                tts_latency_ms=round((time.monotonic() - state.tts_started_at) * 1000, 1),
            )
            state.failed = True
            self._spoken_tts_states.pop(key, None)
            self._audio.playback.cancel_turn(job.session_id, job.turn_id, reason="tts_failed")
            return
        playback_key = (job.session_id, job.turn_id, job.segment_index)
        self._playback_event_at[playback_key] = (state.event_kind, state.event_at)
        self._playback_model_ids[playback_key] = job.binding.model_id
        playback_result = self._audio.playback.enqueue(
            PlaybackItem(
                session_id=job.session_id,
                turn_id=job.turn_id,
                segment_index=job.segment_index,
                audio_bytes=outcome.audio_bytes,
                priority=job.priority,
                source=job.source,
                runtime_generation=job.runtime_generation,
            )
        )
        if playback_result.status in {"unavailable", "rejected"}:
            self._playback_event_at.pop(playback_key, None)
            self._playback_model_ids.pop(playback_key, None)
            state.failed = True
            self._spoken_tts_states.pop(key, None)
            return
        state.next_segment_index += 1
        if state.next_segment_index >= len(state.segments):
            log_diagnostic(
                "tts_end",
                runtime_generation=state.runtime_generation,
                turn_id=state.turn_id,
                model_id=job.binding.model_id,
                status="completed",
                segment_count=len(state.segments),
                tts_latency_ms=round((time.monotonic() - state.tts_started_at) * 1000, 1),
            )
            self._spoken_tts_states.pop(key, None)
            return
        self._start_next_tts_segment(key)

    def _on_playback_event(self, event) -> None:
        self._live2d_feedback.handle_playback_event(event)
        item = event.item
        key = (item.session_id, item.turn_id, item.segment_index)
        model_id = self._playback_model_ids.get(key, "")
        if (
            event.kind == "end"
            and event.reason == "completed"
            and (
                str(getattr(item, "source", "")) == "mic_reply"
                or int(item.priority) >= PlaybackPriority.USER_MIC
            )
        ):
            self._playback_echo_guard_until = (
                time.monotonic() + _USER_MIC_PLAYBACK_ECHO_COOLDOWN_SEC
            )
        if event.kind == "start":
            self._playback_started_at[key] = time.monotonic()
            event_context = self._playback_event_at.get(key)
            event_to_playback_latency_ms = None
            event_kind = ""
            if event_context is not None:
                event_kind, event_at = event_context
                event_to_playback_latency_ms = round(
                    max(0.0, time.time() - event_at) * 1000,
                    1,
                )
            log_diagnostic(
                "playback_start",
                runtime_generation=self._runtime_generation,
                turn_id=item.turn_id,
                model_id=model_id,
                status="started",
                event_kind=event_kind,
                segment_index=item.segment_index,
                source=item.source,
                priority=item.priority,
                event_to_playback_latency_ms=event_to_playback_latency_ms,
            )
            return
        if event.kind != "end":
            return
        started_at = self._playback_started_at.pop(key, None)
        log_diagnostic(
            "playback_end",
            runtime_generation=self._runtime_generation,
            turn_id=item.turn_id,
            model_id=model_id,
            status="completed" if event.reason == "completed" else "failed",
            reason=event.reason,
            segment_index=item.segment_index,
            source=item.source,
            playback_duration_ms=(
                round((time.monotonic() - started_at) * 1000, 1)
                if started_at is not None
                else None
            ),
        )
        self._playback_event_at.pop(key, None)
        self._playback_model_ids.pop(key, None)
