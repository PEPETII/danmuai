"""虚拟主播运行时：独立视觉/TTS 绑定消费与场景上下文更新。"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QObject, QRunnable, pyqtSignal

from app.screenshot_compress import compress_screenshot
from app.tts_providers import get_tts_manager
from app.virtual_host.audio import (
    TtsBinding,
    TtsSynthesisOutcome,
    TtsSynthesizer,
    VirtualHostAudioOrchestrator,
)
from app.virtual_host.contracts import SceneContext
from app.virtual_host.model_config import (
    resolve_virtual_host_tts_binding,
    resolve_virtual_host_vision_credentials,
    sanitize_virtual_host_model_config,
    virtual_host_vision_enabled,
)
from app.virtual_host.session import VirtualHostSession
from app.virtual_host.vision import (
    SceneSummaryResult,
    _keywords_from_summary,
    request_scene_summary,
)
from app.worker_pools import ai_worker_pool

if TYPE_CHECKING:
    from main import DanmuApp

logger = logging.getLogger(__name__)

__all__ = ["SceneVisionCoordinator", "VirtualHostRuntimeService"]


class SceneVisionCoordinator(QObject):
    """主线程 QObject；场景视觉 worker 经 completed 信号回传结构化结果。"""

    completed = pyqtSignal(object, int, int, float, int, str)


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
        self._runtime_generation = 0
        self._active_vision_model_id = ""
        self.vision_request_count = 0
        self.tts_synthesize_count = 0
        self._session = VirtualHostSession(persona_manager=getattr(app, "personae", None))
        self._tts_binding: TtsBinding | None = None
        coordinator_parent = app if isinstance(app, QObject) else None
        self._vision_coordinator = SceneVisionCoordinator(coordinator_parent)
        self._vision_coordinator.completed.connect(self._on_scene_vision_completed)
        self._audio = VirtualHostAudioOrchestrator(
            self._session,
            tts=self._build_tts_synthesizer(),
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
        return self._runtime_generation

    def refresh_model_bindings(self, *, bump_generation_on_vision_change: bool = True) -> None:
        config = self._app.config
        sanitize_virtual_host_model_config(config, persist=True)
        previous_vision = self._active_vision_model_id
        resolved = resolve_virtual_host_vision_credentials(config)
        new_vision = resolved[2] if resolved is not None else ""
        if bump_generation_on_vision_change and previous_vision != new_vision:
            self._bump_runtime_generation()
        self._active_vision_model_id = new_vision
        binding = resolve_virtual_host_tts_binding(config, get_tts_manager())
        self._tts_binding = binding
        self._audio.tts_binding = binding
        self._audio.tts = self._build_tts_synthesizer()

    def _build_tts_synthesizer(self) -> TtsSynthesizer:
        service = self
        manager = get_tts_manager()

        def _counting_synthesize(text: str, binding: TtsBinding) -> TtsSynthesisOutcome:
            service.tts_synthesize_count += 1
            synthesizer = TtsSynthesizer(manager)
            return synthesizer.synthesize(text, binding)

        return TtsSynthesizer(manager, synthesize_fn=_counting_synthesize)

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
