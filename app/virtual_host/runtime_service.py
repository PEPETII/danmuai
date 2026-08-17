"""虚拟主播运行时：独立视觉/TTS 绑定消费与场景上下文更新。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from app.danmu_tts_playback import DanmuTtsPlayback
from app.screenshot_compress import compress_screenshot
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
from app.virtual_host.model_config import (
    resolve_virtual_host_tts_binding,
    resolve_virtual_host_vision_credentials,
    sanitize_virtual_host_model_config,
    virtual_host_vision_enabled,
)
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
from app.virtual_host_playback_adapter import DanmuTtsPlaybackAdapter
from app.worker_pools import ai_worker_pool

if TYPE_CHECKING:
    from main import DanmuApp

logger = logging.getLogger(__name__)

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


@dataclass
class _SpokenTtsState:
    session_id: str
    turn_id: int
    segments: tuple[str, ...] = ()
    next_segment_index: int = 0
    runtime_generation: int = 0
    priority: int = PlaybackPriority.AUTO_SCENE
    source: str = "auto_reply"
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
        try:
            outcome = self._synthesizer.synthesize(self._job.text, self._job.binding)
        except Exception as exc:
            logger.warning("virtual_host tts worker failed: %r", exc)
            outcome = TtsSynthesisOutcome("failed", reason=type(exc).__name__)
        self._coordinator.completed.emit(self._job, outcome)


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
    ) -> None:
        super().__init__()
        self._coordinator = coordinator
        self._prompt = prompt
        self._resolved = resolved
        self._host_turn = host_turn
        self._runtime_generation = int(runtime_generation)
        self._chat_model_id = str(chat_model_id)
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
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = request_scene_summary(self._image_data_uri, self._resolved)
        except Exception as exc:
            logger.warning("virtual_host scene vision worker failed: %r", exc)
            result = SceneSummaryResult(ok=False, error=type(exc).__name__)
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
        self._active_vision_model_id = ""
        self._last_spoke_at: float | None = None
        self.vision_request_count = 0
        self.chat_request_count = 0
        self.tts_synthesize_count = 0
        self._session = VirtualHostSession(persona_manager=getattr(app, "personae", None))
        self._response_scheduler = VirtualHostResponseScheduler()
        self._tts_binding: TtsBinding | None = None
        self._spoken_tts_states: dict[tuple[str, int], _SpokenTtsState] = {}
        coordinator_parent = app if isinstance(app, QObject) else None
        self._vision_coordinator = SceneVisionCoordinator(coordinator_parent)
        self._vision_coordinator.completed.connect(self._on_scene_vision_completed)
        self._chat_coordinator = ChatResponseCoordinator(coordinator_parent)
        self._chat_coordinator.completed.connect(self._on_chat_response_completed)
        self._tts_coordinator = TtsSynthesisCoordinator(coordinator_parent)
        self._tts_coordinator.completed.connect(self._on_tts_synthesis_completed)
        self._danmu_playback = DanmuTtsPlayback()
        if coordinator_parent is not None:
            self._danmu_playback.setParent(coordinator_parent)
        playback_adapter = DanmuTtsPlaybackAdapter(self._danmu_playback)
        self._audio = VirtualHostAudioOrchestrator(
            self._session,
            tts=self._build_tts_synthesizer(),
            playback=PlaybackQueue(playback_adapter),
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

    def mount(self) -> None:
        self.refresh_model_bindings(bump_generation_on_vision_change=False)

    def start(self) -> None:
        self._running = True
        self._bump_runtime_generation()
        self.refresh_model_bindings(bump_generation_on_vision_change=False)

    def stop(self) -> None:
        self._running = False
        self._bump_runtime_generation()

    def _bump_runtime_generation(self) -> int:
        self._runtime_generation += 1
        self._spoken_tts_states.clear()
        self._purge_stale_auto_playback()
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
        binding = resolve_virtual_host_tts_binding(config, get_tts_manager())
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
            return BatchAcceptance(False, "invalid", batch_id)
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
        return decision

    def on_capture_completed(
        self,
        pixmap: Any,
        *,
        screenshot_id: int,
        scene_generation: int,
        captured_at: float | None = None,
    ) -> None:
        if not self._running or pixmap is None:
            return
        if not virtual_host_vision_enabled(self._app.config):
            return
        if self._vision_in_flight:
            return
        resolved = resolve_virtual_host_vision_credentials(self._app.config)
        if resolved is None:
            return
        try:
            image_data_uri = compress_screenshot(pixmap)
        except Exception as exc:
            logger.debug("virtual_host scene compress skipped: %r", exc)
            return
        runtime_generation = self._runtime_generation
        vision_model_id = resolved[2]
        self._vision_in_flight = True
        self.vision_request_count += 1
        runnable = _SceneVisionRunnable(
            self._vision_coordinator,
            image_data_uri=image_data_uri,
            resolved=resolved,
            screenshot_id=screenshot_id,
            scene_generation=scene_generation,
            captured_at=captured_at if captured_at is not None else time.time(),
            runtime_generation=runtime_generation,
            vision_model_id=vision_model_id,
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
        self.vision_request_count += 1
        result = request_scene_summary(image_data_uri, resolved)
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
            return
        if result is None or not result.ok:
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
        current = time.time() if captured_at is None else float(captured_at)
        context = SceneContext(
            scene_generation=int(scene_generation),
            summary=result.text,
            keywords=_keywords_from_summary(result.text),
            screenshot_id=screenshot_id,
            updated_at=current,
        )
        self._session.update_scene_context(context)
        self._on_response_candidate(
            ResponseCandidateEvent(
                kind="scene_change",
                at=current,
                scene_generation=int(scene_generation),
            )
        )

    def _on_response_candidate(self, event: ResponseCandidateEvent) -> None:
        if not self._running:
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
        if not decision.should_respond:
            return
        self._start_chat_request(now=event.at)

    def _start_chat_request(self, *, now: float | None = None) -> None:
        if not self._running or self._chat_in_flight:
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
        self._chat_in_flight = True
        self.chat_request_count += 1
        runnable = _ChatResponseRunnable(
            self._chat_coordinator,
            prompt=prompt,
            resolved=resolved,
            host_turn=host_turn,
            runtime_generation=runtime_generation,
            chat_model_id=chat_model_id,
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
        self._last_spoke_at = time.time()
        self._enqueue_spoken_tts(completed, runtime_generation=runtime_generation)

    def _spoken_turn_key(self, session_id: str, turn_id: int) -> tuple[str, int]:
        return str(session_id).strip(), int(turn_id)

    def _enqueue_spoken_tts(
        self,
        result: HostTurnResult,
        *,
        runtime_generation: int,
        priority: int = PlaybackPriority.AUTO_SCENE,
        source: str = "auto_reply",
    ) -> None:
        if not result.speak or not result.text:
            return
        binding = self._tts_binding
        if binding is None:
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
        self.tts_synthesize_count += 1
        job = TtsSynthesisJob(
            session_id=state.session_id,
            turn_id=state.turn_id,
            segment_index=index,
            text=state.segments[index],
            runtime_generation=state.runtime_generation,
            binding=binding,
            priority=state.priority,
            source=state.source,
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
            state.failed = True
            self._spoken_tts_states.pop(key, None)
            self._audio.playback.cancel_turn(job.session_id, job.turn_id, reason="tts_failed")
            return
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
            state.failed = True
            self._spoken_tts_states.pop(key, None)
            return
        state.next_segment_index += 1
        if state.next_segment_index >= len(state.segments):
            self._spoken_tts_states.pop(key, None)
            return
        self._start_next_tts_segment(key)
