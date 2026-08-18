"""DanmuApp 麦克风链路 mixin。

职责边界：
- 保留 DanmuApp 作为 façade、主线程对象持有者与冻结字段所有者
- 只迁出麦克风链路、probe/config 辅助与 mic reply 处理
- 不迁出 _trigger_api_call / _on_ai_reply / _consume_reply_queue
"""

from __future__ import annotations

import sys
import time
from datetime import datetime

from PyQt6.QtCore import QThreadPool, QTimer

from app.main_helpers import MAX_MIC_IN_FLIGHT
from app.mic_encode import pcm_to_wav_data_uri
from app.mic_prompt import build_mic_insert_user_pt, mic_insert_reply_count
from app.mic_service import mic_mode_enabled
from app.mic_transcript_worker import MicTranscriptRunnable
from app.model_providers import (
    mic_audio_supported_for_mic_config,
    mic_audio_unsupported_message,
    resolve_mic_model_id,
)
from app.persona_contract import append_live_topic_to_system_pt, append_nickname_to_system_pt
from app.reply_parser import normalize_reply_batch, parse_ai_reply_payload
from app.screenshot_compress import (
    IMAGE_JPEG_QUALITY,
    IMAGE_MAX_WIDTH,
    compress_screenshot,
)
from app.translations import tr
from app.worker_pools import ai_worker_pool

MIC_POLL_MS = 600
MIC_POLL_PHASE_MS = 250


def _resolve_runtime_symbol(name: str, fallback):
    """兼容测试对 main 模块符号的 monkeypatch。"""
    module = sys.modules.get("main") or sys.modules.get("__main__")
    if module is None:
        return fallback
    return getattr(module, name, fallback)


class DanmuAppMicMixin:
    def _mic_audio_supported(self) -> bool:
        resolver = _resolve_runtime_symbol(
            "mic_audio_supported_for_mic_config",
            mic_audio_supported_for_mic_config,
        )
        return resolver(self.config)

    def _mic_credentials_ready(self) -> bool:
        from app.ai_client_requests import resolve_mic_request_credentials

        return resolve_mic_request_credentials(self.config) is not None

    def _sync_mic_service(self) -> None:
        """按配置与运行状态启停 MicService / 端点检测器。"""
        self._mic_orchestrator.sync(
            engine_running=self.engine.running,
            config=self.config,
            mic_audio_supported_fn=self._mic_audio_supported,
            resolve_active_model_id_fn=lambda: resolve_mic_model_id(self.config),
            mic_credentials_ready_fn=self._mic_credentials_ready,
        )
        if self.engine.running and self._mic_orchestrator.detector is not None:
            if self._mic_unsupported_error_active or self._mic_capture_error_active:
                self._mic_unsupported_error_active = False
                self._mic_capture_error_active = False
                self.set_web_error_status("", is_error=False)
            self._mic_poll_timer.stop()
            self._mic_poll_timer.start(MIC_POLL_PHASE_MS)
            QTimer.singleShot(1500, self._calibrate_mic_noise_floor)
        else:
            self._mic_poll_timer.stop()

    def _on_mic_model_unsupported(self, model_id: str) -> None:
        """BUG-014: mic 模型不支持时，把错误推到 Web 状态栏。"""
        self._mic_unsupported_error_active = True
        self._mic_capture_error_active = False
        self.set_web_error_status(
            mic_audio_unsupported_message(model_id),
            is_error=True,
        )

    def _on_mic_capture_failed(self, error: str) -> None:
        """采集启动失败时展示可操作错误（权限/驱动/设备等）。"""
        self._mic_capture_error_active = True
        self._mic_unsupported_error_active = False
        self.set_web_error_status(
            f"麦克风采集未启动：{error}",
            is_error=True,
        )

    def _on_mic_incomplete_credentials(self) -> None:
        """麦克风凭证不完整时展示配置指引。"""
        from app.ai_client_requests import format_mic_credential_error

        self._mic_capture_error_active = False
        self._mic_unsupported_error_active = False
        self.set_web_error_status(
            format_mic_credential_error(self.config),
            is_error=True,
        )

    def _calibrate_mic_noise_floor(self) -> None:
        self._mic_orchestrator.calibrate_noise_floor(
            engine_running=self.engine.running,
            config=self.config,
        )

    def _poll_mic_utterance(self) -> None:
        try:
            self._mic_orchestrator.poll(
                engine_running=self.engine.running,
                config=self.config,
            )
        finally:
            if self._mic_orchestrator.should_schedule_next_poll(
                engine_running=self.engine.running,
                config=self.config,
            ):
                self._mic_poll_timer.start(self._mic_poll_ms)

    def _on_mic_speech_start(self) -> None:
        if not mic_mode_enabled(self.config) or not self.engine.running:
            return
        runtime = self.__dict__.get("virtual_host_runtime")
        if runtime is not None and runtime.on_mic_speech_start():
            import uuid

            self._active_mic_utterance_id = str(uuid.uuid4())
            self._mic_log_store.begin_partial(utterance_id=self._active_mic_utterance_id)
            return
        import uuid

        self._active_mic_utterance_id = str(uuid.uuid4())
        self._mic_log_store.begin_partial(utterance_id=self._active_mic_utterance_id)

    def _on_mic_utterance_discarded(self) -> None:
        runtime = self.__dict__.get("virtual_host_runtime")
        if runtime is not None:
            runtime.on_mic_utterance_discarded()
        if not self._active_mic_utterance_id:
            return
        self._mic_log_store.discard(self._active_mic_utterance_id)
        self._active_mic_utterance_id = ""

    def _schedule_mic_transcription_log(self, utterance_id: str, pcm: bytes) -> None:
        if not utterance_id or not pcm:
            return
        runnable = MicTranscriptRunnable(
            config=self.config,
            pcm=pcm,
            utterance_id=utterance_id,
            coordinator=self._mic_transcript_coordinator,
        )
        QThreadPool.globalInstance().start(runnable)

    def _on_mic_transcript_finished(self, utterance_id: str, result) -> None:
        if not utterance_id:
            return
        if getattr(result, "ok", False):
            self._mic_log_store.finalize(
                utterance_id,
                text=getattr(result, "text", "") or "",
                status="success",
            )
        else:
            self._mic_log_store.finalize(
                utterance_id,
                text="",
                status="failed",
                error=getattr(result, "error", "") or "transcription_failed",
            )
        if utterance_id == self._active_mic_utterance_id:
            self._active_mic_utterance_id = ""

    def _on_mic_utterance_end(self) -> None:
        if not mic_mode_enabled(self.config) or not self.engine.running:
            return
        if self._has_mic_request_in_flight():
            self.logger.info("mic insert skipped: request already in flight")
            return
        if not self._mic_audio_supported():
            return
        pcm = self._mic_orchestrator.snapshot_pcm_for_utterance(self.config)
        runtime = self.__dict__.get("virtual_host_runtime")
        routed = (
            runtime is not None
            and pcm is not None
            and runtime.on_mic_utterance_end(pcm)
        )
        if pcm is None:
            if self._active_mic_utterance_id:
                self._mic_log_store.finalize(
                    self._active_mic_utterance_id,
                    text="",
                    status="failed",
                    error="empty_buffer",
                )
                self._active_mic_utterance_id = ""
            return
        utterance_id = self._active_mic_utterance_id
        if not utterance_id:
            import uuid

            utterance_id = str(uuid.uuid4())
            self._mic_log_store.begin_partial(utterance_id=utterance_id)
        self._schedule_mic_transcription_log(utterance_id, pcm)
        rms, _ = self._mic_orchestrator.pcm_metrics(pcm)
        self.logger.info(f"mic utterance end: pcm_bytes={len(pcm)} rms={rms}")
        if routed:
            return
        self._trigger_mic_api_call(pcm)

    def _has_mic_request_in_flight(self) -> bool:
        return self.mic_in_flight >= MAX_MIC_IN_FLIGHT

    def _trigger_mic_api_call(self, pcm: bytes) -> None:
        """语音段结束时插入一发 AI。"""
        if not mic_mode_enabled(self.config) or not self.engine.running:
            return
        if self._has_mic_request_in_flight():
            return
        if not self._mic_audio_supported():
            model_id = resolve_mic_model_id(self.config)
            self.logger.warning(
                tr("mic.warn_unsupported_model").format(model=model_id or "?")
            )
            return
        if self._latest_screenshot is None:
            self.logger.debug("mic insert skipped: no_screenshot")
            return
        if not pcm or pcm_to_wav_data_uri(pcm) is None:
            self.logger.debug(tr("mic.warn_empty_buffer"))
            return

        self._mic_request_seq += 1
        request_round = -self._mic_request_seq
        screenshot_id = self._latest_screenshot_id
        captured_at = time.monotonic()
        scene_generation = self._scene_generation
        pixmap = self._latest_screenshot

        persona = self.personae.pick_random()
        system_pt, user_pt = self.personae.get_prompt(persona)
        system_pt = append_nickname_to_system_pt(system_pt, self.config)
        system_pt = append_live_topic_to_system_pt(system_pt, self.config)
        # Phase B / Wave 7（B2）：知识包检索注入到 system_pt 末尾。
        # 异常隔离：knowledge_runtime 未挂载或检索失败 → 原样返回 system_pt。
        system_pt = self._inject_knowledge_prompt(
            system_pt,
            request_round=request_round,
            screenshot_id=screenshot_id,
        )
        now = datetime.now().strftime("%H:%M:%S")
        user_pt = user_pt.replace("{current_time}", now)
        user_pt = user_pt.replace("{round}", str(self.screenshot_round))
        user_pt = build_mic_insert_user_pt(user_pt, self.config)

        self.mic_in_flight += 1
        mic_request_id = self._reply_request_id(
            request_round,
            screenshot_id,
            scene_generation,
        )
        self._get_request_timing_service().mark_started(
            request_id=mic_request_id,
            now=time.monotonic(),
        )
        self._register_request_meta(request_round, screenshot_id, scene_generation, "mic")
        self.logger.info(
            f"mic insert api triggered seq={self._mic_request_seq} "
            f"screenshot_id={screenshot_id} pcm_bytes={len(pcm)}"
        )

        from app.runnable import AiRunnable

        image_max_width = self.config.get_int("image_max_width", IMAGE_MAX_WIDTH)
        image_quality = self.config.get_int("image_quality", IMAGE_JPEG_QUALITY)
        runnable = AiRunnable(
            self.ai_worker,
            pixmap,
            system_pt,
            user_pt,
            persona,
            request_round,
            screenshot_id,
            captured_at,
            scene_generation,
            lambda p: compress_screenshot(p, image_max_width, image_quality),
            image_quality=image_quality,
            mic_pcm=pcm,
            mic_attach_audio=True,
        )
        ai_worker_pool().start(runnable)

    def _handle_mic_ai_reply(
        self,
        text: str,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
    ) -> None:
        raw_items = parse_ai_reply_payload(text)
        reply_count = mic_insert_reply_count(self.config)
        normalized_items = normalize_reply_batch(
            raw_items,
            scene_count=reply_count,
            filler_count=0,
            config=self.config,
        )
        if not normalized_items:
            self.logger.debug("mic insert reply empty after parse")
            return

        self._enqueue_reply_batch(
            persona_id,
            request_round,
            screenshot_id,
            captured_at,
            scene_generation,
            normalized_items,
            from_mic_insert=True,
        )
        self._publish_live_status()
        if not self.reply_timer.isActive():
            self._consume_reply_queue()
        else:
            self.reply_timer.stop()
            self._consume_reply_queue()

    def list_mic_logs(self, since_ts: float = 0.0) -> list[dict]:
        store = getattr(self, "_mic_log_store", None)
        if store is None:
            return []
        return store.list_recent(since_ts)

    def clear_mic_logs(self) -> None:
        store = getattr(self, "_mic_log_store", None)
        if store is not None:
            store.clear()

    def apply_danmu_read_config(self, patch: dict) -> dict:
        """读弹幕配置（Web PUT /api/danmu-read/config）；须在主线程调用。"""
        return self._danmu_read_service.apply_config(patch)

    def run_danmu_read_probe(
        self,
        api_key_override: str | None = None,
        *,
        provider_override: str | None = None,
        endpoint_override: str | None = None,
        model_id_override: str | None = None,
        voice_override: str | None = None,
        style_prompt_override: str | None = None,
        credentials_override: dict[str, str] | None = None,
    ) -> dict:
        """TTS 试听；须在主线程调用。"""
        return self._danmu_read_service.run_probe(
            api_key_override=api_key_override,
            provider_override=provider_override,
            endpoint_override=endpoint_override,
            model_id_override=model_id_override,
            voice_override=voice_override,
            style_prompt_override=style_prompt_override,
            credentials_override=credentials_override,
        )
