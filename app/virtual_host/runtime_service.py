"""虚拟主播运行时：独立视觉/TTS 绑定消费与场景上下文更新。"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from PyQt6.QtCore import QRunnable, QTimer

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

__all__ = ["VirtualHostRuntimeService"]


class _SceneVisionRunnable(QRunnable):
    def __init__(
        self,
        service: "VirtualHostRuntimeService",
        *,
        image_data_uri: str,
        screenshot_id: int,
        scene_generation: int,
        captured_at: float,
    ) -> None:
        super().__init__()
        self._service = service
        self._image_data_uri = image_data_uri
        self._screenshot_id = int(screenshot_id)
        self._scene_generation = int(scene_generation)
        self._captured_at = float(captured_at)
        self.setAutoDelete(True)

    def run(self) -> None:
        try:
            result = self._service._run_scene_vision_request(self._image_data_uri)
        except Exception as exc:
            logger.warning("virtual_host scene vision worker failed: %r", exc)
            result = SceneSummaryResult(ok=False, error=type(exc).__name__)
        QTimer.singleShot(
            0,
            lambda: self._service._complete_scene_vision(
                result,
                screenshot_id=self._screenshot_id,
                scene_generation=self._scene_generation,
                captured_at=self._captured_at,
            ),
        )


class VirtualHostRuntimeService:
    """挂载于 DanmuApp；Live2D 启动后消费虚拟主播模型配置。"""

    def __init__(self, app: "DanmuApp") -> None:
        self._app = app
        self._running = False
        self._vision_in_flight = False
        self.vision_request_count = 0
        self.tts_synthesize_count = 0
        self._session = VirtualHostSession(persona_manager=getattr(app, "personae", None))
        self._tts_binding: TtsBinding | None = None
        self._audio = VirtualHostAudioOrchestrator(
            self._session,
            tts=self._build_tts_synthesizer(),
        )
        self.refresh_model_bindings()

    @property
    def session(self) -> VirtualHostSession:
        return self._session

    @property
    def audio(self) -> VirtualHostAudioOrchestrator:
        return self._audio

    @property
    def running(self) -> bool:
        return self._running

    def mount(self) -> None:
        self.refresh_model_bindings()

    def start(self) -> None:
        self._running = True
        self.refresh_model_bindings()

    def stop(self) -> None:
        self._running = False
        self._vision_in_flight = False

    def refresh_model_bindings(self) -> None:
        config = self._app.config
        sanitize_virtual_host_model_config(config, persist=True)
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
        try:
            image_data_uri = compress_screenshot(pixmap)
        except Exception as exc:
            logger.debug("virtual_host scene compress skipped: %r", exc)
            return
        self._vision_in_flight = True
        runnable = _SceneVisionRunnable(
            self,
            image_data_uri=image_data_uri,
            screenshot_id=screenshot_id,
            scene_generation=scene_generation,
            captured_at=captured_at if captured_at is not None else time.time(),
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

        resolved = resolve_virtual_host_vision_credentials(self._app.config)
        if resolved is None:
            return None
        self.vision_request_count += 1
        result = request_scene_summary(image_data_uri, resolved)
        if result.ok:
            self._apply_scene_summary(
                result,
                screenshot_id=screenshot_id,
                scene_generation=scene_generation,
                captured_at=captured_at,
            )
        return result

    def _run_scene_vision_request(self, image_data_uri: str) -> SceneSummaryResult | None:
        resolved = resolve_virtual_host_vision_credentials(self._app.config)
        if resolved is None:
            return None
        self.vision_request_count += 1
        return request_scene_summary(image_data_uri, resolved)

    def _complete_scene_vision(
        self,
        result: SceneSummaryResult | None,
        *,
        screenshot_id: int,
        scene_generation: int,
        captured_at: float,
    ) -> None:
        self._vision_in_flight = False
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
