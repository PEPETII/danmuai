"""DanmuApp 生命周期 mixin：启动编排、config_changed、start/stop/quit façade。"""

from __future__ import annotations

import sys
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.ai_client import AiWorker
from app.application.application_stats_state import ApplicationStatsState
from app.application.config_service import scene_version_fingerprint
from app.application.request_scheduler import RequestScheduler
from app.application.request_timing_service import RequestTimingService
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.config_defaults import config_value_with_default
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine
from app.danmu_read_service import DanmuReadService
from app.history_writer import HistoryWriter
from app.hotkey import HotkeyManager
from app.lifetime_stats import LifetimeStats
from app.logger import SanitizedLogger, sanitize_sensitive_text
from app.main_helpers import TOPMOST_HEALTH_INTERVAL_MS
from app.main_launch import show_startup_notice_if_needed
from app.main_mic_mixin import MIC_POLL_MS
from app.mic_orchestrator import MicOrchestrator
from app.mic_service import MicService
from app.model_providers import resolve_active_model_id
from app.overlay import DanmuOverlay
from app.persona_manager import PersonaManager
from app.problems.classifier import problem_code_from_error_message
from app.reply_queue import AIReplyFIFOBuffer
from app.snipper import ScreenCapturer, resolve_screen_index
from app.templates import TemplateManager
from app.translations import Translator, tr
from app.tray import TrayManager

KNOWLEDGE_QUIT_DRAIN_DEADLINE_SEC = 2.0
KNOWLEDGE_QUIT_DRAIN_POLL_MS = 50


def _resolve_runtime_symbol(name: str, fallback):
    module = sys.modules.get("main") or sys.modules.get("__main__")
    if module is None:
        return fallback
    return getattr(module, name, fallback)


# P1-04：运行中重复 start() 的限频诊断间隔（秒）。时间戳字段仅 Qt 主线程读写。
START_GUARD_LOG_INTERVAL_SEC = 5.0

# P1-05：连续业务空解析（传输成功但无有效弹幕）触发“响应格式不可用”暂停的阈值。
# 复用视觉传输失败阈值量级（MAX_CONSECUTIVE_FAILURES 默认 5）：单次空响应不阻断，
# 达到阈值才停止截图调度，避免把偶发空响应升级为暂停。测试与诊断显式写出该值。
EMPTY_PARSE_FAILURE_THRESHOLD = 5

# P1-05：业务空解析暂停时上报的稳定 problem 码（与网络/连接错误文案区分）。
EMPTY_PARSE_PROBLEM_CODE = "AI-FORMAT-001"


def _stop_and_wait_for_web_console(server, logger, *, context: str) -> bool:
    """Stop Web first and return whether its bounded shutdown barrier completed."""
    if server is None:
        return True

    server.stop()
    web_thread = getattr(server, "_thread", None)
    shutdown_done = False
    wait_shutdown_complete = getattr(server, "wait_shutdown_complete", None)
    if callable(wait_shutdown_complete):
        shutdown_done = bool(wait_shutdown_complete())
    if not shutdown_done and web_thread is not None and web_thread.is_alive():
        web_thread.join(timeout=0.5)
        shutdown_done = not web_thread.is_alive()
    if not shutdown_done:
        if logger is not None:
            logger.warning(
                f"{context} timed out waiting for Web console shutdown "
                "startup_ok=%s bind_failed=%s shutdown_requested=%s shutdown_complete=%s",
                getattr(server, "startup_ok", False),
                bool(getattr(server, "_bind_failed", None) and server._bind_failed.is_set()),
                bool(
                    getattr(server, "_shutdown_requested", None)
                    and server._shutdown_requested.is_set()
                ),
                bool(
                    getattr(server, "_shutdown_complete", None)
                    and server._shutdown_complete.is_set()
                ),
            )
    bridge = getattr(server, "bridge", None)
    if bridge is not None:
        bridge.set_event_loop(None)
    server._loop = None
    return shutdown_done


class DanmuAppLifecycleMixin:
    # P1-05：业务空解析阈值（实例可覆盖；类属性确保最小测试实例也能解析）。
    EMPTY_PARSE_FAILURE_THRESHOLD = EMPTY_PARSE_FAILURE_THRESHOLD

    def _init_runtime_bridge_state(self, web_launch_mode: str) -> None:
        # FastAPI/uvicorn 在独立线程；Qt 对象修改必须回主线程。
        self.web_launch_mode = web_launch_mode
        self.web_server = None
        self.web_bridge = None
        self.webview_shell = None
        self.web_runtime_state = WebRuntimeState()
        self._region_selector = None
        self._region_selection_state = "idle"
        self._region_selection_screen_index = None

    def _init_core_subsystems(self, log_startup) -> None:
        config_started = time.perf_counter()
        self.config = ConfigStore()
        log_startup(
            "config_store.done",
            ms=(time.perf_counter() - config_started) * 1000.0,
        )
        Translator.set_language(
            Translator.resolve_language(
                config_value_with_default(self.config, "language")
            )
        )
        self.logger = SanitizedLogger()
        self.personae = PersonaManager(self.config)
        self.templates = TemplateManager(self.config)
        self.history_writer = HistoryWriter(self.config)
        self.capturer = ScreenCapturer(self.config)
        self.engine = DanmuEngine(self.config)
        self.overlay = DanmuOverlay(self.config, self.engine)
        self.engine.overlay = self.overlay

        qt_app = QApplication.instance()
        if qt_app is not None:
            qt_app.focusChanged.connect(self._on_app_focus_changed)

        self.web_runtime_state.set_overlay_cache(
            danmu_lines=self.config.get_int("danmu_lines", 0),
            layout_mode=self.config.get("layout_mode", "fullscreen"),
        )

        tray_started = time.perf_counter()
        self.tray = TrayManager(self)
        log_startup("tray.done", ms=(time.perf_counter() - tray_started) * 1000.0)
        self.hotkey = HotkeyManager(self)

        from app.floating_panel_engine import FloatingPanelEngine
        from app.floating_panel_overlay import FloatingPanelOverlay

        self.floating_panel_engine = FloatingPanelEngine(self.config)
        self.floating_panel_overlay = FloatingPanelOverlay(
            self.config, self.floating_panel_engine
        )

    def _init_request_pipeline_state(self) -> None:
        self.ai_worker = AiWorker(self.config)
        self.ai_worker.finished.connect(self._on_ai_reply)
        self.ai_worker.error.connect(self._on_ai_error)

        # W-MEDLOW-001（MS-001）：主线程启动期 eager 创建，_get_* 不再懒初始化。
        self._request_scheduler = RequestScheduler()
        self._request_timing_service = RequestTimingService()

        self.screenshot_round = 0
        self.screenshot_timer = QTimer()
        self.screenshot_timer.timeout.connect(self._on_screenshot_timer)

        self.ai_in_flight = 0
        self.mic_in_flight = 0
        self._local_fallback_active = False
        self._mic_request_seq = 0
        self._mic_batch_id = 0
        self._pending_request_meta = {}

        from app.runnable import CaptureCoordinator

        self._capture_coordinator = CaptureCoordinator(self)
        self._capture_coordinator.completed.connect(self._on_capture_completed)
        self._capture_coordinator.failed.connect(self._on_capture_failed)
        self._capture_in_flight = False
        self._capture_session_epoch = 0

        self._mic_poll_timer = QTimer(self)
        self._mic_poll_ms = MIC_POLL_MS
        self._mic_poll_timer.setInterval(self._mic_poll_ms)
        self._mic_poll_timer.setSingleShot(True)
        self._mic_poll_timer.timeout.connect(self._poll_mic_utterance)

        self._latest_screenshot = None
        self._latest_screenshot_time = 0.0
        self._is_generating = False
        self._batch_id = 0
        self._current_batch = None

        self.reply_buffer = AIReplyFIFOBuffer(max_items=8)
        self.reply_timer = QTimer(self)
        self.reply_timer.setInterval(800)
        self.reply_timer.setSingleShot(True)
        self.reply_timer.timeout.connect(self._consume_reply_queue)

        self._pool_topup_timer = QTimer(self)
        self._pool_topup_timer.setInterval(500)
        self._pool_topup_timer.timeout.connect(self._maybe_pool_topup)

        self._queue_low_watermark = 3
        self._queue_fallback_keep = 3
        self._reply_scene_count = 2
        self._reply_filler_count = 3
        self._queue_batch_size = 5
        self._init_meme_barrage_timers()

        # W-GENPIPELINE-EXTRACT：reply_timer / reply_buffer 所有权仍属 DanmuApp，
        # 回复消费与三路分发逻辑委托 GenerationPipeline（app/application/generation_pipeline.py）。
        # 必须在 reply_timer 创建之后实例化（服务方法内调 self._app.reply_timer.start()）。
        from app.application.generation_pipeline import GenerationPipeline

        self._generation_pipeline = GenerationPipeline(self)

    def _init_runtime_tracking_state(self) -> None:
        self._pending = False
        self._latest_displayed_round = 0
        self._scene_generation = 0
        self._inflight_scene_generation = 0
        self._scene_refresh_wanted = False
        self._pending_api_trigger_source = None
        self._latest_screenshot_id = 0
        self._latest_requested_screenshot_id = 0
        self._latest_queued_screenshot_id = 0
        self._latest_displayed_screenshot_id = 0
        self._mic_unsupported_error_active = False
        self._mic_capture_error_active = False
        self._active_mic_utterance_id = ""
        from app.mic_log_store import MicLogStore
        from app.mic_transcript_worker import MicTranscriptCoordinator

        self._mic_log_store = MicLogStore()
        self._mic_transcript_coordinator = MicTranscriptCoordinator(self)
        self._mic_transcript_coordinator.finished.connect(self._on_mic_transcript_finished)
        self._mic_service = MicService(log_fn=lambda msg: self.logger.info(msg))
        self._mic_orchestrator = MicOrchestrator(
            mic_service=self._mic_service,
            on_utterance_end=self._on_mic_utterance_end,
            on_speech_start=self._on_mic_speech_start,
            on_utterance_discarded=self._on_mic_utterance_discarded,
            log_fn=lambda msg: self.logger.info(msg),
            on_unsupported_model_fn=self._on_mic_model_unsupported,
            on_capture_failed_fn=self._on_mic_capture_failed,
            on_incomplete_credentials_fn=self._on_mic_incomplete_credentials,
        )
        self._danmu_read_service = DanmuReadService(self)
        self.stats_state = StatsState()
        self.application_stats_state = ApplicationStatsState(start_time=time.monotonic())
        self._consecutive_failures = 0
        self._capture_fail_streak = 0
        self._capture_error_active = False
        self._failure_backoff_paused = False
        self._last_error_message = ""
        self.MAX_CONSECUTIVE_FAILURES = 5
        # P1-05：连续业务空解析预算与暂停状态（Qt 主线程读写）。
        self._consecutive_empty_parses = 0
        self._empty_parse_paused = False
        self.EMPTY_PARSE_FAILURE_THRESHOLD = EMPTY_PARSE_FAILURE_THRESHOLD
        self._inflight_screenshot_id = 0
        self._inflight_started_at = 0.0
        from app.application.danmu_diagnostics import DanmuDiagnosticsRecorder

        self._danmu_diagnostics = DanmuDiagnosticsRecorder()
        self._live_status_timer = QTimer(self)
        self._live_status_timer.setInterval(500)
        self._live_status_timer.timeout.connect(self._publish_live_status)

        self._topmost_health_timer = QTimer(self)
        self._topmost_health_timer.setInterval(TOPMOST_HEALTH_INTERVAL_MS)
        self._topmost_health_timer.timeout.connect(self._on_topmost_health_tick)
        # WebView2 drag runs in its child process; the Qt main thread samples
        # the existing HWND so the final logical origin can be persisted.
        self._panel_position_timer = QTimer(self)
        self._panel_position_timer.setInterval(100)
        self._panel_position_timer.timeout.connect(self._on_panel_position_tick)
        self._panel_position_candidate = None
        self._panel_position_last_changed_at = 0.0
        self._panel_position_last_saved = None
        self._last_foreground_hwnd = 0
        self._topmost_health_tick = 0
        self._last_fullscreen_at_risk = False
        self._screen_recovery_bound = False
        self._bind_screen_recovery_signals()
        self._reset_scene_generation_baseline()

    def _reset_scene_generation_baseline(self) -> None:
        self._scene_generation = 0
        self._scene_version_fingerprint = scene_version_fingerprint(self.config)
        self._scene_refresh_wanted = False
        self._pending_api_trigger_source = None
        self._notify_virtual_host_scene_generation(reset=True)

    def get_scene_generation_snapshot(self) -> int:
        """Return the main-thread-owned scene generation for dependent runtimes."""

        return int(self._scene_generation)

    def _notify_virtual_host_scene_generation(self, *, reset: bool = False) -> None:
        runtime = self.__dict__.get("virtual_host_runtime")
        callback = getattr(runtime, "on_scene_generation_changed", None)
        if callable(callback):
            callback(self.get_scene_generation_snapshot(), reset=reset)

    def _maybe_bump_scene_generation_on_config(self) -> bool:
        fp = scene_version_fingerprint(self.config)
        prev = self.__dict__.get("_scene_version_fingerprint")
        if prev is None:
            self._scene_version_fingerprint = fp
            return False
        if fp == prev:
            return False
        self._scene_version_fingerprint = fp
        self._scene_generation = int(self.__dict__.get("_scene_generation", 0)) + 1
        self.logger.info(
            "scene_generation=%s reason=scene_config_changed",
            self._scene_generation,
        )
        self._notify_virtual_host_scene_generation()
        return True

    def _on_scene_generation_bumped(self) -> None:
        """W-THEME-LAG-QUEUE-PURGE-001 / REFRESH: purge stale ai/fallback queue, keep mic."""
        gen = self._scene_generation
        for event, count in (
            ("scene_queue_purged", self.reply_buffer.purge_stale_by_generation(gen)),
            ("scene_engine_purged", self.engine.drop_pending_below_generation(gen)),
        ):
            if count > 0:
                self.logger.info("%s scene_generation=%s dropped=%s", event, gen, count)
        self._scene_refresh_wanted = True
        QTimer.singleShot(0, self._try_scene_refresh)

    def _try_scene_refresh(self) -> None:
        """Run one capture tick for scene refresh when pipeline gates allow."""
        if not getattr(self, "_scene_refresh_wanted", False):
            return
        if not self.engine.running or self._failure_backoff_paused:
            return
        if self._has_visual_request_in_flight():
            return
        if self._capture_in_flight:
            return
        self._pending_api_trigger_source = "scene_refresh"
        self._on_normal_capture_tick()

    def _ensure_knowledge_runtime(self) -> bool:
        """确保知识包运行时在启动或重新启动后可用。"""
        runtime = self.__dict__.get("knowledge_runtime")
        mount_result = True
        try:
            if runtime is None:
                from app.knowledge.runtime_service import KnowledgeRuntimeService

                runtime = KnowledgeRuntimeService(self)
                self.knowledge_runtime = runtime
                mount_result = bool(getattr(runtime, "_mount_result", False))
            else:
                mount = getattr(runtime, "mount", None)
                if callable(mount):
                    mount_result = bool(mount())
        except Exception as exc:
            self.logger.warning(f"knowledge_runtime mount failed: {exc!r}")
            return False
        # ``_closing``：关闭进行中；``_closed``：整个应用已退出并终止该运行时。
        # 两种情况下都不得重新挂载，否则会造出第二套 DB / executor。
        if (
            not mount_result
            or bool(getattr(runtime, "_closing", False))
            or bool(getattr(runtime, "_closed", False))
        ):
            return False
        return all(
            getattr(runtime, attr, None) is not None
            for attr in ("repository", "import_orchestrator", "retriever")
        )

    def _ensure_virtual_host_runtime(self) -> bool:
        runtime = self.__dict__.get("virtual_host_runtime")
        try:
            if runtime is None:
                from app.virtual_host.runtime_service import VirtualHostRuntimeService

                runtime = VirtualHostRuntimeService(self)
                self.virtual_host_runtime = runtime
            else:
                mount = getattr(runtime, "mount", None)
                if callable(mount):
                    mount()
        except Exception as exc:
            self.logger.warning(f"virtual_host_runtime mount failed: {exc!r}")
            self.virtual_host_runtime = None
            return False
        return getattr(runtime, "session", None) is not None

    def _init_startup_services(self, log_startup) -> None:
        self.tray.show()
        qt_app = QApplication.instance()
        if qt_app is not None:
            qt_app.processEvents()

        # W-PERF-STARTUP-001：延迟执行非关键迁移，减少启动阻塞
        QTimer.singleShot(0, self.config.run_deferred_migrations)

        hotkey_started = time.perf_counter()
        try:
            self.hotkey.register()
        except Exception as exc:  # boundary: hotkey platform API
            self.logger.error(tr("app.hotkey_register_failed").format(error=exc))
            QMessageBox.warning(
                None,
                tr("app.error_title"),
                tr("app.hotkey_register_failed").format(error=exc),
            )
        log_startup(
            "hotkey.register.done",
            ms=(time.perf_counter() - hotkey_started) * 1000.0,
        )

        from app.session_run_log import SessionRunLog

        self.session_run_log = SessionRunLog(self.config)
        self.lifetime_stats = LifetimeStats(self.config)
        self._lifetime_flush_timer = QTimer(self)
        self._lifetime_flush_timer.setInterval(2000)
        self._lifetime_flush_timer.timeout.connect(self.lifetime_stats.flush_pending)

        # Phase B / Wave 7（B2）：挂载知识包运行时服务。
        # 异常隔离：装配失败时主链路调用 no-op；start() 会再次尝试恢复。
        self._ensure_knowledge_runtime()

        # 虚拟主播运行时：Live2D 启动后消费独立视觉/TTS 配置。
        self._ensure_virtual_host_runtime()

    def _start_web_console_stack(self, log_startup) -> None:
        from app.web_console import attach_web_console, classify_web_console_startup
        from app.webview_shell import notify_web_console_failure

        try:
            self.web_server = attach_web_console(self)
        except Exception as exc:  # boundary: web console startup fatal
            self.logger.error(tr("app.web_console_startup_failed").format(error=exc))
            raise

        from app.font_registry import FontRegistry

        font_registry_started = time.perf_counter()
        self.font_registry = FontRegistry(self.config)
        loaded_count = self.font_registry.load_all()
        log_startup(
            "font_registry.loaded",
            count=loaded_count,
            ms=(time.perf_counter() - font_registry_started) * 1000.0,
        )

        self.config_changed.connect(self._on_config_changed)
        from app.ai_client_requests import visual_credentials_ready

        initial = "/" if visual_credentials_ready(self.config) else "/#settings"
        if self.web_server.startup_ok:
            self.logger.info(
                tr("app.web_console_ready").format(url=self.web_server.base_url)
            )
        elif self.web_launch_mode == "browser":
            self.logger.warning(
                tr("app.web_console_starting_browser").format(url=self.web_server.base_url)
            )
        else:
            self.logger.warning(
                tr("app.web_console_starting_shell").format(url=self.web_server.base_url)
            )

        QTimer.singleShot(
            0, lambda: show_startup_notice_if_needed(self.config, self.logger)
        )
        try:
            tray = getattr(self, "tray", None)
        except RuntimeError as exc:
            message = str(exc)
            if not (
                message.startswith("super-class __init__() of type ")
                and message.endswith(" was never called")
            ):
                raise
            tray = None
        if tray is not None:
            QTimer.singleShot(1500, tray.schedule_startup_update_check)
        if self.web_launch_mode == "browser":
            QTimer.singleShot(
                900,
                lambda: self._open_web_console_when_ready(initial, use_browser=True),
            )
        else:
            self.logger.info(tr("app.desktop_shell_pywebview"))
            if classify_web_console_startup(self.web_server) == "failed":
                notify_web_console_failure(self, "web_console.startup_failed")
                self.web_server._startup_failure_user_notified = True
            else:
                self._schedule_webview_attach(initial)

    def _on_config_changed(self) -> None:
        if self._maybe_bump_scene_generation_on_config():
            self._on_scene_generation_bumped()
        self._sync_reply_batch_config()
        web_runtime_state = self._ensure_web_runtime_state()
        self.screenshot_timer.setInterval(self._normal_recognition_interval_ms())
        self.reply_buffer.set_max_items(self._queue_capacity())
        new_lines = self.config.get_int("danmu_lines", 0)
        lines_changed = new_lines != web_runtime_state.cached_danmu_lines
        if lines_changed:
            self.engine.reload_tracks(preserve_visible=True)
        new_layout = self.config.get("layout_mode", "fullscreen")
        layout_changed = new_layout != web_runtime_state.cached_layout_mode
        if layout_changed and self.engine.running and self._overlay_display_enabled():
            resolve_screen_index_fn = _resolve_runtime_symbol(
                "resolve_screen_index",
                resolve_screen_index,
            )
            self.overlay.show_for_screen(
                resolve_screen_index_fn(self.config),
                reload_tracks=True,
            )
        if lines_changed or layout_changed:
            web_runtime_state.set_overlay_cache(
                danmu_lines=new_lines,
                layout_mode=new_layout,
            )
        self.hotkey.set_keys(self.config.get("hotkey", "Ctrl+Shift+B"))
        if self.overlay.display_settings_dirty():
            self.overlay.apply_display_settings()
        self._sync_overlay_visibility()
        self._sync_floating_panel_visibility()
        self._sync_web_panel_click_through()
        self._sync_mic_service()
        fp_overlay = self.__dict__.get("floating_panel_overlay")
        # Keep an already-running WebView converged with config changes,
        # including replacement/clearing of the managed custom CSS text.
        push_panel_config = getattr(self, "_push_panel_config", None)
        if callable(push_panel_config):
            try:
                push_panel_config()
            except RuntimeError as exc:
                self.logger.debug(f"floating panel web config push skipped: {exc!r}")
        if fp_overlay is None:
            return
        try:
            fp_overlay.apply_config()
        except RuntimeError as exc:
            self.logger.warning(f"floating panel overlay apply_config failed: {exc!r}")

    def _handle_visual_ai_failure(
        self,
        msg: str,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
        *,
        diagnostic_reason: str = "",
        elapsed_ms: int | None = None,
        popped_meta: list[tuple[int, int, int]] | None = None,
        request_context: dict[str, object] | None = None,
    ) -> None:
        """Apply the shared visual-request failure contract.

        The caller must have consumed the request meta exactly once.  This
        keeps ordinary error callbacks and watchdog recovery on the same
        timing, failure-count, problem-reporting, and backoff path while late
        callbacks remain rejected by the meta guard in ``_on_ai_error``.
        """
        msg = sanitize_sensitive_text(str(msg or ""))
        self._release_inflight_for_source("visual")
        self._publish_live_status()

        timing_service = self._get_request_timing_service()
        self._consume_request_timing(request_round, screenshot_id, scene_generation)
        purged_timing = timing_service.purge_stale(now=time.monotonic())
        if diagnostic_reason:
            self.logger.error(
                "视觉请求 in-flight 强制恢复: %s [persona=%s, round=%s, "
                "screenshot_id=%s, scene_generation=%s, input_tokens=%s, "
                "output_tokens=%s] elapsed_ms=%s popped_meta=%s "
                "purged_timing=%s reason=%s",
                msg,
                persona_id,
                request_round,
                screenshot_id,
                scene_generation,
                input_tokens,
                output_tokens,
                elapsed_ms,
                popped_meta or [],
                purged_timing,
                diagnostic_reason,
            )
        else:
            self.logger.error(
                "%s [persona=%s, round=%s, screenshot_id=%s, "
                "scene_generation=%s, input_tokens=%s, output_tokens=%s]",
                msg,
                persona_id,
                request_round,
                screenshot_id,
                scene_generation,
                input_tokens,
                output_tokens,
            )

        self._consecutive_failures += 1
        self._capture_error_active = False
        self._last_error_message = msg
        self._record_undisplayed("ai_request_failure", persona_id=persona_id)
        lower_msg = msg.lower()
        is_fatal = (
            "401" in msg
            or "402" in msg
            or "403" in msg
            or "api key" in lower_msg
            or "not configured" in lower_msg
            or "未配置" in msg
            or "余额" in msg
            or "balance" in lower_msg
            or "欠费" in msg
        )
        classification = problem_code_from_error_message(msg)
        context = {
            "model_id": resolve_active_model_id(self.config),
            **(classification.context or {}),
        }
        if request_context:
            context.update(
                {
                    key: request_context[key]
                    for key in (
                        "profile_id",
                        "model_id",
                        "provider_id",
                        "api_family",
                        "endpoint_host",
                        "max_tokens",
                        "temperature",
                        "thinking",
                    )
                    if key in request_context
                }
            )
        if diagnostic_reason:
            context["reason"] = diagnostic_reason
        self.report_problem(
            classification.code,
            technical_detail=classification.technical_detail or msg,
            context=context,
        )

        if is_fatal:
            self.logger.warning(tr("app.fatal_error_pause").format(message=msg))
            self._failure_backoff_paused = True
            self.screenshot_timer.stop()
            return

        if self._consecutive_failures < self.MAX_CONSECUTIVE_FAILURES:
            return

        self.logger.warning(
            tr("app.failure_paused").format(
                count=self._consecutive_failures,
                message=msg,
            )
        )
        self._failure_backoff_paused = True
        self.screenshot_timer.stop()
        paused_msg = tr("app.failure_paused").format(
            count=self.MAX_CONSECUTIVE_FAILURES,
            message=msg,
        )
        self.report_problem(
            "INTERNAL-001",
            technical_detail=paused_msg,
            force_new_event=True,
        )

    def _handle_visual_empty_parse_failure(
        self,
        *,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        scene_generation: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        """post-transport 业务空失败入口（P1-05）。

        与 ``_handle_visual_ai_failure`` 的区别：调用本方法时视觉请求的 in-flight
        slot、request meta、timing 均已在 ``_on_ai_reply`` 释放一次，token 也已统计
        一次；因此这里**不得**再次 ``_release_inflight_for_source`` /
        ``_consume_request_timing`` / 计 token，也不累计传输失败 ``_consecutive_failures``，
        更不误报连接/网络错误。只累计独立业务空计数，达阈值后停止截图调度并上报
        “响应格式不可用”（``EMPTY_PARSE_PROBLEM_CODE``）。

        调用线程：Qt 主线程。空结果不伪造成功、不放宽 parser/normalize 校验。
        """
        count = int(self.__dict__.get("_consecutive_empty_parses", 0)) + 1
        self._consecutive_empty_parses = count
        threshold = int(
            getattr(self, "EMPTY_PARSE_FAILURE_THRESHOLD", EMPTY_PARSE_FAILURE_THRESHOLD)
        )
        self.logger.warning(
            "视觉空解析业务失败: request_round=%s screenshot_id=%s scene_generation=%s "
            "persona=%s input_tokens=%s output_tokens=%s count=%s threshold=%s "
            "reason=empty_parse",
            request_round,
            screenshot_id,
            scene_generation,
            persona_id,
            input_tokens,
            output_tokens,
            count,
            threshold,
        )
        if count < threshold:
            return
        if self.__dict__.get("_empty_parse_paused", False):
            return
        self._empty_parse_paused = True
        # 复用既有退避暂停位：screenshot_timer 停止后主链路门禁
        # （_schedule_capture / _on_capture_completed / _try_scene_refresh）不再发请求。
        self._failure_backoff_paused = True
        self.screenshot_timer.stop()
        paused_msg = tr("app.response_format_unavailable").format(
            count=count,
            threshold=threshold,
        )
        self.report_problem(
            EMPTY_PARSE_PROBLEM_CODE,
            technical_detail=paused_msg,
            context={
                "reason": "empty_parse",
                "empty_parse_count": count,
                "empty_parse_threshold": threshold,
                "persona_id": persona_id,
            },
        )
        self.logger.warning(paused_msg)

    def _reset_empty_parse_backoff_if_needed(self) -> None:
        """有效规范化结果入队后清零业务空计数并解除业务暂停（P1-05，Qt 主线程）。"""
        had_state = (
            int(self.__dict__.get("_consecutive_empty_parses", 0)) > 0
            or bool(self.__dict__.get("_empty_parse_paused", False))
        )
        if not had_state:
            return
        self._consecutive_empty_parses = 0
        self._empty_parse_paused = False
        active = self.get_active_problem() if hasattr(self, "get_active_problem") else None
        if active and str(active.get("code", "")) == EMPTY_PARSE_PROBLEM_CODE:
            self.clear_problem(code=EMPTY_PARSE_PROBLEM_CODE)
        # 仅当没有其它业务暂停来源（传输失败退避）时才由业务空恢复解除暂停。
        if self._failure_backoff_paused and int(
            self.__dict__.get("_consecutive_failures", 0)
        ) <= 0:
            self._failure_backoff_paused = False
        if (
            self.engine.running
            and not self._failure_backoff_paused
            and not self.screenshot_timer.isActive()
        ):
            self.screenshot_timer.start()

    def _on_ai_error(
        self,
        msg: str,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        if self._discard_stale_mic_callback_if_needed(
            request_round,
            screenshot_id,
            scene_generation,
            kind="error",
        ):
            return
        meta = self._pop_request_meta(request_round, screenshot_id, scene_generation)
        if not meta:
            self.logger.warning(
                "stale_error_dropped: request_round=%s screenshot_id=%s scene_generation=%s",
                request_round, screenshot_id, scene_generation,
            )
            return
        msg = sanitize_sensitive_text(str(msg or ""))
        source = meta.get("source") or "visual"
        is_mic = source == "mic"

        if is_mic:
            self._release_inflight_for_source(source)
            self._publish_live_status()
            self.logger.warning(
                f"mic insert api error: {msg} "
                f"[persona={persona_id}, round={request_round}, screenshot_id={screenshot_id}]"
            )
            self._consume_request_timing(request_round, screenshot_id, scene_generation)
            return

        if self._drop_stale_visual_error_if_needed(
            source=source,
            request_round=request_round,
            screenshot_id=screenshot_id,
            scene_generation=scene_generation,
        ):
            return

        self._handle_visual_ai_failure(
            msg,
            persona_id,
            request_round,
            screenshot_id,
            captured_at,
            scene_generation,
            input_tokens,
            output_tokens,
            request_context=meta.get("request_context"),
        )

    def _update_stats(self, *, success: bool = True, count: int = 1) -> None:
        if success:
            safe_count = max(1, int(count))
            self._ensure_stats_state().add_danmu(safe_count)
            self._ensure_application_stats_state().add_danmu(safe_count)
            self.lifetime_stats.add_danmu(safe_count)
        self._maybe_log_dedup_profile()

    def _visual_session_active(self) -> bool:
        """P1-04 权威运行态：视觉会话（弹幕引擎）当前是否已在运行。

        仅由 Qt 主线程读取（``start``/``toggle``/测试）；``engine.running`` 也只由
        主线程的 ``engine.start()``/``engine.stop()`` 写入，因此这里不存在需要额外
        同步原语的跨线程读写。``start()`` 只有在它返回 False 时才允许执行会话
        初始化，重复 ``start()`` 因此成为无副作用 no-op。
        """
        engine = self.__dict__.get("engine")
        return bool(engine is not None and getattr(engine, "running", False))

    def _note_duplicate_start(self) -> None:
        """运行中重复 ``start()`` 的限频诊断（Qt 主线程）。

        托盘/热键/Web 重复点击会连续触发 ``start()``；按
        ``START_GUARD_LOG_INTERVAL_SEC`` 限频，避免刷屏。``_duplicate_start_log_at``
        仅主线程读写，进程内有效。
        """
        now = time.monotonic()
        last = self.__dict__.get("_duplicate_start_log_at") or 0.0
        if now - last < START_GUARD_LOG_INTERVAL_SEC:
            return
        self._duplicate_start_log_at = now
        self.logger.info("start_ignored reason=already_running")

    def start(self) -> None:
        from app.ai_client_requests import format_credential_error, visual_credentials_ready

        # P1-04（主链路生命周期幂等）：引擎已在运行时，重复 start 必须在任何
        # 运行态重置和新 capture 之前无副作用返回。该门禁是 start() 的第一项
        # 业务动作，早于知识运行时重试、凭据提示、session epoch 递增、
        # engine.start()、统计/定时器变更、_pending_request_meta.clear() 与
        # _on_normal_capture_tick()，因此在途请求、request meta、session epoch、
        # 统计和定时器全部保持不变。需要重启的调用者必须显式 stop() 后再 start()。
        if self._visual_session_active():
            self._note_duplicate_start()
            return

        # 运行时通常已在应用启动时挂载；若启动阶段曾降级，则在这里用
        # 同一个对象重试挂载。返回值必须参与判定：知识库不可用时只记录
        # 结构化诊断，不阻断弹幕主链路（知识故障不得影响弹幕生成）。
        if not self._ensure_knowledge_runtime():
            self.logger.warning(
                "knowledge runtime unavailable at start; "
                "reason=knowledge_disabled danmu pipeline continues"
            )

        if not visual_credentials_ready(self.config):
            msg = format_credential_error(self.config)
            self.logger.warning(msg)
            self.report_problem("CONFIG-001", technical_detail=msg)
            self.tray.show_api_key_missing_hint()
            if self.web_server:
                self._open_web_console("/#settings")
            self.tray.update_state(running=False)
            return

        from app.model_selection import visual_api_endpoint_issue

        endpoint_issue = visual_api_endpoint_issue(self.config)
        if endpoint_issue:
            self.logger.warning(endpoint_issue)
            self.report_problem("CONFIG-001", technical_detail=endpoint_issue)
            if self.web_server:
                self._open_web_console("/#settings")
            self.tray.update_state(running=False)
            return

        self._capture_session_epoch = getattr(self, "_capture_session_epoch", 0) + 1
        self.engine.start()
        self.engine.clear_dedup_window()
        recorder = self.__dict__.get("_danmu_diagnostics")
        if recorder is not None:
            recorder.reset()
        self.ai_worker.reset_stopping()
        self.ai_in_flight = 0
        self._capture_in_flight = False
        self._is_generating = False
        self._local_fallback_active = False
        self._batch_id = 0
        self._current_batch = None
        self._latest_screenshot = None
        self._latest_screenshot_time = 0.0
        self._ensure_stats_state().reset_session(start_time=time.monotonic())
        self.session_run_log.begin(
            started_at=time.time(),
            model=resolve_active_model_id(self.config),
        )
        self._consecutive_failures = 0
        self._failure_backoff_paused = False
        self._last_error_message = ""
        # P1-05：新会话重置业务空解析预算与暂停（run 级清理）。
        self._consecutive_empty_parses = 0
        self._empty_parse_paused = False
        self.EMPTY_PARSE_FAILURE_THRESHOLD = EMPTY_PARSE_FAILURE_THRESHOLD
        self._get_request_timing_service().reset_started()
        self._latest_queued_screenshot_id = 0
        self._latest_displayed_screenshot_id = 0
        self._latest_requested_screenshot_id = 0
        self._reset_scene_generation_baseline()
        self._inflight_scene_generation = 0
        self._inflight_started_at = 0.0
        self._inflight_screenshot_id = 0
        self._get_request_scheduler().reset_trigger_time()
        self._mic_request_seq = 0
        self._mic_batch_id = 0
        self._pending_request_meta.clear()
        self._last_request_context_public = {}
        self.reply_buffer.set_max_items(self._queue_capacity())
        self.reply_buffer.reset_metrics()
        self.screenshot_timer.stop()
        self.screenshot_timer.setInterval(self._normal_recognition_interval_ms())
        self.screenshot_timer.start()
        self._live_status_timer.start()
        self._lifetime_flush_timer.start()
        self._on_normal_capture_tick()
        self.logger.debug(
            f"[DEBUG] Normal mode: screenshot={self._normal_recognition_interval_ms()}ms"
        )
        if not self.reply_buffer.is_empty() and not self.reply_timer.isActive():
            self.reply_timer.start(200)
        if self.config.get("eviction_mode", "natural") == "accelerate":
            self.engine.trigger_acceleration(60)
        self._sync_overlay_visibility()
        self._sync_floating_panel_visibility()
        self._topmost_health_timer.start()
        self._reassert_active_overlay_topmost()
        self._pool_topup_timer.start()
        self._start_meme_barrage_timers()
        self.tray.update_state(running=True)
        self.state_changed.emit(True)
        self.clear_problem()
        self.logger.info(tr("app.started"))
        self._sync_mic_service()

        read_svc = self.__dict__.get("_danmu_read_service")
        if read_svc is not None:
            read_svc.on_engine_started()

    def _flush_session_runtime_to_lifetime(self) -> None:
        stats_state = self._ensure_stats_state()
        if stats_state.start_time <= 0:
            return
        session_sec = stats_state.runtime_sec()
        if self.lifetime_stats.flush_runtime(session_sec):
            stats_state.clear_runtime()

    def _flush_lifetime_stats_on_stop(self) -> bool:
        """Persist lifetime counters during stop; return False when persistence fails."""
        try:
            self.lifetime_stats.flush_pending()
            self._flush_session_runtime_to_lifetime()
            return True
        except Exception as exc:
            self.logger.warning(
                "lifetime stats flush failed during stop: %s",
                sanitize_sensitive_text(repr(exc)),
            )
            return False

    def stop(self) -> None:
        self._lifetime_flush_timer.stop()
        stats = self._ensure_stats_state()
        lifetime_flush_ok = self._flush_lifetime_stats_on_stop()
        if lifetime_flush_ok:
            self.session_run_log.complete(
                ended_at=time.time(),
                input_tokens=stats.total_input_tokens,
                output_tokens=stats.total_output_tokens,
                danmu_count=stats.danmu_count,
            )
        else:
            self.logger.warning(
                "session run log skipped: lifetime stats flush failed during stop"
            )
        self.screenshot_timer.stop()
        self._live_status_timer.stop()
        self._topmost_health_timer.stop()
        self._panel_position_timer.stop()
        self._last_foreground_hwnd = 0
        self._topmost_health_tick = 0
        self._last_fullscreen_at_risk = False
        runtime = self._ensure_web_runtime_state()
        runtime.set_overlay_compat_warning("")
        runtime.set_screen_index_fallback_warning("")
        self._pending = False
        self._capture_session_epoch = getattr(self, "_capture_session_epoch", 0) + 1
        self.ai_worker.mark_stopping()
        self.ai_in_flight = 0
        self.mic_in_flight = 0
        # 与 ai_in_flight 对称：截图 worker stopping 早退或迟到信号前主线程必释放
        #（W-AUDIT-0714-CAPTURE-STOP-001 / BUG-005）
        self._capture_in_flight = False
        self._local_fallback_active = False
        self._pending_request_meta.clear()
        self._last_request_context_public = {}
        self._mic_orchestrator.stop_detector()
        self._mic_poll_timer.stop()
        self._is_generating = False
        self._inflight_started_at = 0.0
        self._inflight_screenshot_id = 0
        self._current_batch = None
        # P1-05：停止会话时清理业务空解析预算与暂停状态。
        self._consecutive_empty_parses = 0
        self._empty_parse_paused = False
        self.reply_timer.stop()
        self._pool_topup_timer.stop()
        stop_meme_timers = self.__dict__.get("_stop_meme_barrage_timers")
        if callable(stop_meme_timers):
            stop_meme_timers()
        self.reply_buffer.clear()
        self._get_request_timing_service().reset_started()
        self._latest_requested_screenshot_id = 0
        self._latest_queued_screenshot_id = 0
        self._latest_displayed_screenshot_id = 0
        self._reset_scene_generation_baseline()
        self._inflight_scene_generation = 0
        self.engine.stop()

        read_svc = self.__dict__.get("_danmu_read_service")
        if read_svc is not None:
            read_svc.on_engine_stopped()
        self._sync_mic_service()
        self.overlay.stop_render_loop()
        self.overlay.hide()

        fp_overlay = self.__dict__.get("floating_panel_overlay")
        fp_engine = self.__dict__.get("floating_panel_engine")
        if fp_overlay is not None:
            try:
                fp_overlay.reset_session_state()
            except RuntimeError as exc:
                self.logger.debug(f"floating panel stop cleanup skipped: {exc!r}")
        if fp_engine is not None:
            fp_engine.stop()

        self.tray.update_state(running=False)
        self.state_changed.emit(False)
        self.logger.info(tr("app.stopped"))

    def toggle(self) -> None:
        if self.engine.running:
            self.stop()
            return
        self.start()

    def release_startup_failure(self) -> None:
        """Release resources started during __init__ when construction aborts."""
        hotkey = getattr(self, "hotkey", None)
        if hotkey is not None:
            hotkey.unregister()

        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.hide()

        for attr in (
            "_lifetime_flush_timer",
            "_live_status_timer",
            "_topmost_health_timer",
            "screenshot_timer",
            "reply_timer",
            "_mic_poll_timer",
            "_pool_topup_timer",
        ):
            timer = getattr(self, attr, None)
            if timer is not None:
                timer.stop()

        overlay = getattr(self, "overlay", None)
        if overlay is not None:
            overlay.hide()

        server = getattr(self, "web_server", None)
        web_shutdown_done = True
        if server is not None:
            web_shutdown_done = _stop_and_wait_for_web_console(
                server,
                getattr(self, "logger", None),
                context="startup failure cleanup",
            )

        history_writer = getattr(self, "history_writer", None)
        if history_writer is not None:
            history_writer.stop()

        ai_worker = getattr(self, "ai_worker", None)
        if ai_worker is not None:
            ai_worker.close()

        knowledge_runtime = self.__dict__.get("knowledge_runtime")
        if knowledge_runtime is not None:
            try:
                knowledge_runtime.close(wait=True)
            except Exception as exc:
                logger = getattr(self, "logger", None)
                if logger is not None:
                    logger.warning(f"knowledge_runtime close failed: {exc!r}")

        config = getattr(self, "config", None)
        if config is not None:
            if web_shutdown_done:
                config.close()
            else:
                logger = getattr(self, "logger", None)
                if logger is not None:
                    logger.error(
                        "startup failure cleanup deferred config close: Web console still running"
                    )

    def _begin_knowledge_quit_shutdown(self) -> None:
        """Start the non-blocking knowledge/route drain owned by quit()."""
        self._knowledge_quit_deadline_at = (
            time.monotonic() + KNOWLEDGE_QUIT_DRAIN_DEADLINE_SEC
        )
        runtime = self.__dict__.get("knowledge_runtime")
        if runtime is not None:
            runtime.begin_shutdown(
                deadline_at=self._knowledge_quit_deadline_at,
                observe_async=False,
            )
        else:
            from app.web_api.knowledge_routes import (
                begin_shutdown_knowledge_route_executor,
            )

            begin_shutdown_knowledge_route_executor()

    def _knowledge_quit_state(self) -> str:
        runtime = self.__dict__.get("knowledge_runtime")
        if runtime is not None:
            return runtime.poll_shutdown(now=time.monotonic())
        from app.web_api.knowledge_routes import (
            close_knowledge_route_executor_if_drained,
            knowledge_route_executor_is_drained,
        )

        if knowledge_route_executor_is_drained():
            return "closed" if close_knowledge_route_executor_if_drained() else "draining"
        deadline_at = getattr(self, "_knowledge_quit_deadline_at", None)
        if deadline_at is not None and time.monotonic() >= deadline_at:
            return "timeout"
        return "draining"

    def _ensure_knowledge_quit_timer(self) -> None:
        timer = self.__dict__.get("_knowledge_quit_timer")
        if timer is None:
            try:
                timer = QTimer(self)
            except TypeError:
                timer = QTimer()
            timer.setInterval(KNOWLEDGE_QUIT_DRAIN_POLL_MS)
            timer.timeout.connect(DanmuAppLifecycleMixin._poll_knowledge_quit)
            self._knowledge_quit_timer = timer
        timer.start()

    def _poll_knowledge_quit(self) -> None:
        if getattr(self, "_quit_finalized", False):
            timer = self.__dict__.get("_knowledge_quit_timer")
            if timer is not None:
                timer.stop()
            return
        state = DanmuAppLifecycleMixin._knowledge_quit_state(self)
        if state == "closed":
            timer = self.__dict__.get("_knowledge_quit_timer")
            if timer is not None:
                timer.stop()
            DanmuAppLifecycleMixin._finish_quit_after_knowledge_shutdown(self)
            return
        if state == "timeout" and not getattr(self, "_knowledge_quit_timeout_reported", False):
            self._knowledge_quit_timeout_reported = True
            self.logger.error(
                "knowledge shutdown timed out; DB remains open until workers drain"
            )
            progress = self.__dict__.get("_quit_progress")
            if progress is not None:
                progress.close()
        DanmuAppLifecycleMixin._ensure_knowledge_quit_timer(self)

    def _finish_quit_after_knowledge_shutdown(self) -> None:
        if getattr(self, "_quit_finalized", False):
            return
        self._quit_finalized = True
        workers_drained = getattr(self, "_quit_workers_drained", False)
        web_shutdown_done = getattr(self, "_quit_web_shutdown_done", False)
        progress = self.__dict__.get("_quit_progress")
        try:
            shell = getattr(self, "webview_shell", None)
            if shell:
                shell.destroy()

            self.history_writer.stop()
            if workers_drained:
                self.ai_worker.close()
            else:
                self.logger.error(
                    "quit deferred AI worker close: worker pool timeout leaves shared worker in use"
                )
            if workers_drained and web_shutdown_done:
                self.config.close()
            else:
                self.logger.error(
                    "quit deferred config close: Web/worker shutdown barrier incomplete"
                )

            virtual_host_runtime = self.__dict__.get("virtual_host_runtime")
            if virtual_host_runtime is not None:
                try:
                    virtual_host_runtime.stop()
                except Exception as exc:
                    self.logger.warning(f"virtual host runtime close on quit failed: {exc!r}")

            live2d_runtime = self.__dict__.get("_live2d_desktop_runtime")
            if live2d_runtime is not None:
                try:
                    live2d_runtime.stop()
                except Exception as exc:
                    self.logger.warning(f"Live2D desktop runtime close on quit failed: {exc!r}")

            self.overlay.hide()
            self.logger.info(tr("app.quit_done"))
        finally:
            if progress is not None:
                progress.close()
            QApplication.quit()

    def quit(self) -> None:
        """Begin bounded, event-loop-observed teardown; repeated calls are no-ops."""
        if getattr(self, "_quit_in_progress", False):
            DanmuAppLifecycleMixin._poll_knowledge_quit(self)
            return
        self._quit_in_progress = True
        self._quit_finalized = False
        self._knowledge_quit_timeout_reported = False
        self.logger.info(tr("app.quitting"))

        from PyQt6.QtCore import Qt
        from PyQt6.QtWidgets import QProgressDialog

        progress = QProgressDialog(tr("app.quitting"), None, 0, 0, None)
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setCancelButton(None)
        progress.setMinimumDuration(0)
        progress.setWindowTitle("DanmuAI")
        progress.show()
        self._quit_progress = progress
        QApplication.processEvents()

        self.stop()
        self._mic_service.stop()
        self._pool_topup_timer.stop()
        stop_meme_timers = self.__dict__.get("_stop_meme_barrage_timers")
        if callable(stop_meme_timers):
            stop_meme_timers()

        read_svc = self.__dict__.get("_danmu_read_service")
        if read_svc is not None:
            read_svc.shutdown()

        self.hotkey.unregister()
        self.tray.hide()

        from app.worker_pools import wait_all_worker_pools_done, worker_pool_for_label

        pool_wait_labels = {
            "capture": "capture worker thread pool",
            "ai": "ai worker thread pool",
            "meme_ai": "meme ai worker thread pool",
            "meme_fetch": "meme fetch thread pool",
            "global": "AI worker thread pool",
        }
        pool_results = wait_all_worker_pools_done(2000)
        for label, done in pool_results.items():
            if done:
                continue
            pool = worker_pool_for_label(label)
            self.logger.warning(
                "quit timed out waiting for %s active_threads=%s max_threads=%s",
                pool_wait_labels.get(label, label),
                pool.activeThreadCount() if pool is not None else "?",
                pool.maxThreadCount() if pool is not None else "?",
            )

        self._quit_workers_drained = all(pool_results.values())
        close_meme_client = self.__dict__.get("close_meme_barrage_client")
        if callable(close_meme_client):
            if self._quit_workers_drained:
                close_meme_client()
            else:
                self.logger.error(
                    "quit deferred Meme client close: worker pool timeout may leave "
                    "MemeFetchRunnable in flight"
                )

        self.stop_web_status_timer()
        server = getattr(self, "web_server", None)
        self._quit_web_shutdown_done = _stop_and_wait_for_web_console(
            server,
            self.logger,
            context="quit",
        )

        try:
            DanmuAppLifecycleMixin._begin_knowledge_quit_shutdown(self)
        except Exception as exc:
            self.logger.error("knowledge shutdown could not start: %r", exc)
            self._knowledge_quit_timeout_reported = True
        DanmuAppLifecycleMixin._poll_knowledge_quit(self)
