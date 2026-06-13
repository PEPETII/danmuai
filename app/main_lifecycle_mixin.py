"""DanmuApp 生命周期 / 启动编排 mixin。

职责边界：
- 保留 DanmuApp 作为启动顺序、运行态字段与公共 start/stop/quit façade 的持有者
- 迁出 __init__ 的启动编排辅助，以及 config_changed / ai_error / 生命周期方法
- 不迁出 _trigger_api_call / _on_ai_reply / _consume_reply_queue 三个主链路入口
"""

from __future__ import annotations

import sys
import time

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QMessageBox

from app.ai_client import AiWorker
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
from app.logger import SanitizedLogger
from app.main_launch import show_startup_notice_if_needed
from app.main_mic_mixin import MIC_POLL_MS
from app.mic_orchestrator import MicOrchestrator
from app.mic_service import MicService
from app.model_providers import resolve_active_model_id
from app.overlay import DanmuOverlay
from app.personae import PersonaManager
from app.reply_queue import AIReplyFIFOBuffer
from app.snipper import ScreenCapturer, resolve_screen_index
from app.templates import TemplateManager
from app.translations import Translator, tr
from app.tray import TrayManager


def _resolve_runtime_symbol(name: str, fallback):
    module = sys.modules.get("main") or sys.modules.get("__main__")
    if module is None:
        return fallback
    return getattr(module, name, fallback)


class DanmuAppLifecycleMixin:
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

        from app.pet.pet_command_service import PetCommandService
        from app.pet.pet_window import PetWindow

        self.pet_command_service = PetCommandService()
        self.pet_window = PetWindow(self)

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

    def _init_runtime_tracking_state(self) -> None:
        self._pending = False
        self._latest_displayed_round = 0
        self._scene_generation = 0
        self._inflight_scene_generation = 0
        self._latest_screenshot_id = 0
        self._latest_requested_screenshot_id = 0
        self._latest_queued_screenshot_id = 0
        self._latest_displayed_screenshot_id = 0
        self._mic_service = MicService(log_fn=lambda msg: self.logger.info(msg))
        self._mic_orchestrator = MicOrchestrator(
            mic_service=self._mic_service,
            on_utterance_end=self._on_mic_utterance_end,
            log_fn=lambda msg: self.logger.info(msg),
        )
        self._danmu_read_service = DanmuReadService(self)
        self.stats_state = StatsState()
        self._consecutive_failures = 0
        self._capture_fail_streak = 0
        self._capture_error_active = False
        self._failure_backoff_paused = False
        self._last_error_message = ""
        self.MAX_CONSECUTIVE_FAILURES = 5
        self._inflight_screenshot_id = 0
        self._inflight_started_at = 0.0
        self._live_status_timer = QTimer(self)
        self._live_status_timer.setInterval(500)
        self._live_status_timer.timeout.connect(self._publish_live_status)

        self._topmost_health_timer = QTimer(self)
        self._topmost_health_timer.setInterval(500)
        self._topmost_health_timer.timeout.connect(self._on_topmost_health_tick)

    def _init_startup_services(self, log_startup) -> None:
        self.tray.show()
        qt_app = QApplication.instance()
        if qt_app is not None:
            qt_app.processEvents()

        hotkey_started = time.perf_counter()
        try:
            self.hotkey.register()
        except Exception as exc:
            self.logger.error("热键注册失败: %r", exc)
            QMessageBox.warning(None, tr("app.error_title"), f"热键注册失败: {exc}")
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

        # PET-009：启动期一次性把 pet_enabled=1 + pet_visible=1 的桌宠显示出来。
        # config_changed 信号在 _start_web_console_stack 才连接，启动期收不到；
        # 因此这里直接复用 app.pet.pet_facade.sync_pet_window_visibility 主线程 façade，
        # 后续 web / ConfigService 修改仍由 _on_config_changed 路径兜底，不绕开既有边界。
        pet_window = self.__dict__.get("pet_window")
        if pet_window is not None:
            try:
                self._sync_pet_window_visibility()
            except Exception as exc:
                self.logger.debug(f"pet startup visibility sync skipped: {exc!r}")

    def _start_web_console_stack(self, log_startup) -> None:
        from app.web_console import attach_web_console, classify_web_console_startup
        from app.webview_shell import notify_web_console_failure

        try:
            self.web_server = attach_web_console(self)
        except Exception as exc:
            self.logger.error("Web 控制台启动失败: %r", exc)
            QMessageBox.critical(None, tr("app.error_title"), f"Web 控制台启动失败: {exc}")
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
        initial = "/#settings" if not self.config.get_api_key() else "/"
        if self.web_server.startup_ok:
            self.logger.info(f"Web 控制台: {self.web_server.base_url} （托盘可再次打开）")
        elif self.web_launch_mode == "browser":
            self.logger.warning(
                f"Web 控制台仍在启动: {self.web_server.base_url} "
                "（就绪前将先打开系统浏览器）"
            )
        else:
            self.logger.warning(
                f"Web 控制台仍在启动: {self.web_server.base_url} "
                "（就绪后将打开桌面壳，请勿仅用浏览器替代）"
            )

        show_startup_notice_if_needed(self.config, self.logger)
        if self.web_launch_mode == "browser":
            QTimer.singleShot(
                900,
                lambda: self._open_web_console_when_ready(initial, use_browser=True),
            )
        else:
            self.logger.info("桌面壳: pywebview（--web-browser 可改用系统浏览器）")
            if classify_web_console_startup(self.web_server) == "failed":
                notify_web_console_failure(self, "web_console.startup_failed")
                self.web_server._startup_failure_user_notified = True
            else:
                self._schedule_webview_attach(initial)

    def _on_config_changed(self) -> None:
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
        self._sync_pet_window_visibility()
        self._sync_mic_service()
        fp_overlay = self.__dict__.get("floating_panel_overlay")
        pet_window = self.__dict__.get("pet_window")
        if pet_window is not None:
            try:
                pet_window.apply_config()
            except Exception as exc:
                self.logger.warning(f"pet window apply_config failed: {exc!r}")
        if fp_overlay is None:
            return
        try:
            fp_overlay.apply_config()
        except Exception as exc:
            self.logger.warning(f"floating panel overlay apply_config failed: {exc!r}")

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
        meta = self._pop_request_meta(request_round, screenshot_id, scene_generation)
        source = meta.get("source") or "visual"
        is_mic = source == "mic"

        self._release_inflight_for_source(source)
        self._publish_live_status()

        if is_mic:
            self.logger.warning(
                f"mic insert api error: {msg} "
                f"[persona={persona_id}, round={request_round}, screenshot_id={screenshot_id}]"
            )
            self._consume_request_timing(request_round, screenshot_id, scene_generation)
            return

        self._get_request_timing_service().purge_stale(now=time.monotonic())
        self._consume_request_timing(request_round, screenshot_id, scene_generation)
        self._notify_pet_visual_error()
        self.logger.error(
            "%s [persona=%s, round=%s, screenshot_id=%s, scene_generation=%s, "
            "input_tokens=%s, output_tokens=%s]",
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
        self._set_error_status_safe(msg, is_error=True)

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
        self._set_error_status_safe(
            tr("app.failure_paused").format(
                count=self.MAX_CONSECUTIVE_FAILURES,
                message=msg,
            ),
            is_error=True,
        )

    def _update_stats(self, *, success: bool = True) -> None:
        if success:
            self._ensure_stats_state().add_danmu(1)
            self.lifetime_stats.add_danmu(1)
        self._maybe_log_dedup_profile()

    def start(self) -> None:
        if not self.config.get_api_key():
            msg = tr("app.api_key_missing_warning")
            self.logger.warning(msg)
            self._set_error_status_safe(msg, is_error=True)
            self.tray.show_api_key_missing_hint()
            if self.web_server:
                self._open_web_console("/#settings")
            return

        from app.model_selection import visual_api_endpoint_issue

        endpoint_issue = visual_api_endpoint_issue(self.config)
        if endpoint_issue:
            self.logger.warning(endpoint_issue)
            self._set_error_status_safe(endpoint_issue, is_error=True)
            if self.web_server:
                self._open_web_console("/#settings")
            return

        self.engine.start()
        self.engine.clear_dedup_window()
        self.ai_worker.reset_stopping()
        self.ai_in_flight = 0
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
        self._get_request_timing_service().reset_started()
        self._latest_queued_screenshot_id = 0
        self._latest_displayed_screenshot_id = 0
        self._latest_requested_screenshot_id = 0
        self._scene_generation = 0
        self._inflight_scene_generation = 0
        self._inflight_started_at = 0.0
        self._inflight_screenshot_id = 0
        self._get_request_scheduler().reset_trigger_time()
        self._mic_request_seq = 0
        self._mic_batch_id = 0
        self._pending_request_meta.clear()
        self.reply_buffer.set_max_items(self._queue_capacity())
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
        self._sync_pet_window_visibility()
        self._pool_topup_timer.start()
        self._start_meme_barrage_timers()
        self.tray.update_state(running=True)
        self.state_changed.emit(True)
        self._set_error_status_safe("", is_error=False)
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

    def stop(self) -> None:
        self._lifetime_flush_timer.stop()
        stats = self._ensure_stats_state()
        self.lifetime_stats.flush_pending()
        self._flush_session_runtime_to_lifetime()
        self.session_run_log.complete(
            ended_at=time.time(),
            input_tokens=stats.total_input_tokens,
            output_tokens=stats.total_output_tokens,
            danmu_count=stats.danmu_count,
        )
        self.screenshot_timer.stop()
        self._live_status_timer.stop()
        self._topmost_health_timer.stop()
        runtime = self._ensure_web_runtime_state()
        runtime.set_overlay_compat_warning("")
        runtime.set_screen_index_fallback_warning("")
        self._pending = False
        self.ai_worker.mark_stopping()
        self.ai_in_flight = 0
        self.mic_in_flight = 0
        self._local_fallback_active = False
        self._pending_request_meta.clear()
        self._mic_orchestrator.stop_detector()
        self._is_generating = False
        self._inflight_started_at = 0.0
        self._inflight_screenshot_id = 0
        self._current_batch = None
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
        self._scene_generation = 0
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
            except Exception as exc:
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

    def quit(self) -> None:
        self.logger.info(tr("app.quitting"))
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

        from PyQt6 import QtCore

        pool = QtCore.QThreadPool.globalInstance()
        pool_done = pool.waitForDone(2000)
        if not pool_done:
            self.logger.warning(
                "quit timed out waiting for AI worker thread pool "
                "active_threads=%s max_threads=%s",
                pool.activeThreadCount(),
                pool.maxThreadCount(),
            )

        # W-QUIT-TEARDOWN-001：先停 Web 控制台（含 meta 轮询），再关 config.db，
        # 避免 HTTP 线程在 conn.close() 后仍读 meme_barrage_library。
        self.stop_web_status_timer()
        server = getattr(self, "web_server", None)
        if server:
            server.stop()
            web_thread = getattr(server, "_thread", None)
            if web_thread is not None and web_thread.is_alive():
                web_thread.join(timeout=3.0)
                if web_thread.is_alive():
                    self.logger.warning(
                        "quit timed out waiting for Web console thread "
                        "startup_ok=%s bind_failed=%s",
                        getattr(server, "startup_ok", False),
                        bool(getattr(server, "_bind_failed", None) and server._bind_failed.is_set()),
                    )

        shell = getattr(self, "webview_shell", None)
        if shell:
            shell.destroy()

        self.history_writer.stop()
        self.ai_worker.close()
        self.config.close()
        self.overlay.hide()

        self.logger.info(tr("app.quit_done"))
        QApplication.quit()
