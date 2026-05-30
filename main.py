"""DanmuAI 应用入口与单例状态机（DanmuApp）。

职责边界（bootstrap / lifecycle / façade）：
- 截图定时、视觉/麦克风双轨 AI 调度、回复队列消费、场景代际淘汰、失败退避
- 与 DanmuOverlay / DanmuEngine 协同上屏；Web 控制台经 bridge 信号回主线程改配置
- 运行态对外展示委托 StatusSnapshotBuilder / DiagnosticSnapshotBuilder，勿在 Web 层拼私有字段

主链路（普通模式，详见 docs/MAIN_PIPELINE.md）：
  screenshot_timer → _on_normal_capture_tick → _capture_screenshot → _trigger_api_call
  → AiRunnable(QThreadPool) → _on_ai_reply → _enqueue_reply_batch → _consume_reply_queue
  → DanmuEngine.add_text → Overlay 绘制

关键设计：
- screenshot_id：每帧截图递增，用于「更新帧优于在途回复」的 supersede 判定
- scene_generation：场景切换递增，用于丢弃旧场景弹幕与 AIReplyFIFOBuffer 代际淘汰
- MAX_IN_FLIGHT=1：并发视觉请求会破坏过期判断与回复顺序，故硬限制为 1

线程：DanmuApp 在 Qt 主线程；AiRunnable 在 QThreadPool 中调 AiWorker，finished 信号队列回主线程。

Phase 4 冻结（勿迁移出本模块）：ai_in_flight、reply_buffer、QTimer/QThreadPool、_latest_screenshot 等，
见 docs/archive/architecture-phases/phase4-freeze.md。

入口：python main.py → main()。
"""
import base64
import io
import multiprocessing
import os
import sys
import time
import traceback
from datetime import datetime

from app.ai_client import AiWorker
from app.api_schedule import (
    api_schedule_debug_enabled,
    format_api_schedule_log,
    min_api_interval_elapsed,
    pixels_per_second,
    time_to_anchor_boundary,
)
from app.application.config_service import apply_web_config_patch
from app.application.diagnostic_snapshot import DiagnosticSnapshotBuilder, build_diagnostic_report
from app.application.request_scheduler import RequestScheduler
from app.application.request_timing_service import RequestTimingService
from app.application.stats_state import StatsState
from app.application.status_snapshot import StatusSnapshotBuilder
from app.application.web_runtime_state import WebRuntimeState
from app.config_store import ConfigStore
from app.danmu_engine import (
    DanmuEngine,
    DanmuItem,
    dedup_profile_enabled,
    log_dedup_profile_summary,
    normalize_danmu_display_text,
)
from app.danmu_pool import any_danmu_pool_source_enabled, sample_danmu_for_config
from app.history import DanmuHistory
from app.history_writer import HistoryWriter
from app.hotkey import HotkeyManager
from app.lifetime_stats import LifetimeStats
from app.live_freshness import (
    LiveStatusSnapshot,
    prune_stale_drop_times,
    screenshot_interval_ms,
    should_backoff_screenshot,
)
from app.logger import SanitizedLogger
from app.memory.activity import RecentActivityState
from app.memory.activity_prompt import append_activity_line_to_user_pt, format_activity_prompt_line
from app.memory.types import MEMORY_MODE_OFF, bullet_angle_from_index
from app.mic_encode import pcm_to_wav_data_uri
from app.mic_prompt import build_mic_insert_user_pt
from app.mic_service import MicService, mic_mode_enabled, mic_window_sec_from_config
from app.mic_test import pcm_metrics
from app.mic_utterance import (
    MicUtteranceDetector,
    calibrate_noise_floor_rms,
    mic_utterance_config_from_store,
)
from app.model_providers import (
    is_doubao_mode,
    model_likely_supports_mic_audio,
    resolve_active_model_id,
)
from app.overlay import DanmuOverlay
from app.personae import (
    PersonaManager,
    normal_reply_count_from_config,
    persona_display_name,
)
from app.reply_parser import (
    normalize_reply_batch,
    parse_ai_reply_payload,
    parse_ai_reply_with_memory,
)
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply
from app.scene_fingerprint import (
    fingerprint_from_pixmap,
    scene_debug_enabled,
    scene_probe_size_from_config,
)
from app.scene_memory import SceneMemoryStore, append_memory_to_user_pt, memory_window_from_config
from app.snipper import ScreenCapturer, resolve_screen_index
from app.templates import TemplateManager
from app.translations import Translator, tr
from app.tray import TrayManager
from app.window_info import classify_foreground_window, get_foreground_window_info
from PIL import Image
from PyQt6.QtCore import QObject, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication, QMessageBox

IMAGE_MAX_WIDTH = 768
IMAGE_JPEG_QUALITY = 85


def compress_screenshot(pixmap: QPixmap, max_width: int = IMAGE_MAX_WIDTH, quality: int = IMAGE_JPEG_QUALITY) -> str:
    qimage = pixmap.toImage()
    width, height = qimage.width(), qimage.height()
    bits = qimage.bits()
    bits.setsize(height * qimage.bytesPerLine())
    pil_image = Image.frombuffer("RGBA", (width, height), bits, "raw", "BGRA", qimage.bytesPerLine(), 1)
    pil_image = pil_image.convert("RGB")
    if width > max_width:
        ratio = max_width / width
        new_height = int(height * ratio)
        pil_image = pil_image.resize((max_width, new_height), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    pil_image.save(buf, format="JPEG", quality=quality)
    b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


VISUAL_INFLIGHT_WARN_SEC = 45.0


class BatchTracker:
    """当前视觉批次的锚点元数据（普通模式）。

    anchor_item：本批首条成功上屏弹幕；滚到屏幕 75% 宽处时写入 next_generation_time，
    供 API 调度 debug 日志（_log_api_schedule）与批次观测，不驱动额外截图定时器。
    """

    def __init__(self, batch_id: int):
        self.batch_id = batch_id
        self.anchor_item: DanmuItem | None = None
        self.next_generation_time: float = 0.0


class DanmuApp(QObject):
    """单例应用状态机：bootstrap、生命周期与 Web 公开 façade 的持有者。

    普通模式（当前产品路径）：按 normal_recognition_interval_sec 截图，成功后立即 _trigger_api_call；
    _is_reply_stale 不做 TTL 硬过期，避免队列积压时误丢。
    麦克风轨：与视觉 ai_in_flight 独立，request_round 为负数以区分 _pending_request_meta。

    配置中遗留的 danmu_display_mode=realtime 会在加载时规范为 normal。

    下列对象/字段禁止在未更新架构文档前迁出本类：reply_buffer、QPixmap 截图缓存、
    QTimer、QThreadPool、_mic_service（见 docs/final-architecture-baseline.md）。
    """

    state_changed = pyqtSignal(bool)  # running / paused
    config_changed = pyqtSignal()

    def __init__(self, web_launch_mode: str = "webview"):
        super().__init__()
        # --- Web 桥接状态（FastAPI/uvicorn 在独立线程；改 Qt 对象须经 web_bridge 信号）---
        self.web_launch_mode = web_launch_mode
        self.web_server = None
        self.web_bridge = None
        self.webview_shell = None
        self.web_runtime_state = WebRuntimeState()
        self._region_selector = None
        self._region_selection_state = "idle"
        self._region_selection_screen_index: int | None = None
        # --- 核心子系统（配置、截图、弹幕引擎、叠加层、托盘、全局热键）---
        self.config = ConfigStore()
        Translator.set_language(
            Translator.resolve_language(self.config.get("language", ""))
        )
        self.logger = SanitizedLogger()
        self.personae = PersonaManager(self.config)
        self.templates = TemplateManager(self.config)
        self.history = DanmuHistory(self.config)
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
        self.tray = TrayManager(self)
        self.hotkey = HotkeyManager(self)

        # --- 视觉 AI 请求与截图定时（MAX_IN_FLIGHT=1：并发会破坏过期与顺序判定）---
        self.ai_worker = AiWorker(self.config)
        self.ai_worker.finished.connect(self._on_ai_reply)
        self.ai_worker.error.connect(self._on_ai_error)

        self.screenshot_round = 0
        self.screenshot_timer = QTimer()
        self.screenshot_timer.timeout.connect(self._on_screenshot_timer)

        self.ai_in_flight = 0
        self.MAX_IN_FLIGHT = 1
        self.mic_in_flight = 0
        self.MAX_MIC_IN_FLIGHT = 1
        self._mic_request_seq = 0
        self._mic_batch_id = 0
        self._pending_request_meta: dict[str, dict] = {}
        # --- 麦克风双轨（mic_in_flight 与视觉独立；负 request_round 区分 meta 来源）---
        self._mic_utterance_detector: MicUtteranceDetector | None = None
        self._mic_poll_timer = QTimer(self)
        self._mic_poll_ms = 400
        self._mic_poll_timer.setInterval(self._mic_poll_ms)
        self._mic_poll_timer.timeout.connect(self._poll_mic_utterance)

        # --- 最新帧与批次节拍（_is_generating=意图标记；ai_in_flight=在途计数，二者不同步混用）---
        self._latest_screenshot: QPixmap | None = None
        self._latest_screenshot_time: float = 0.0
        self._is_generating: bool = False
        self._batch_id: int = 0
        self._current_batch: BatchTracker | None = None

        # --- 回复 FIFO 与自适应消费（reply_timer 单次触发，按屏上密度调节间隔）---
        self.reply_buffer = AIReplyFIFOBuffer(max_items=8)
        self.danmu_queue = self.reply_buffer  # 遗留别名；主路径请用 reply_buffer
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

        # --- 场景代际与截图 ID 链（代际淘汰旧回复/弹幕；ID 链判定 supersede 与 TTL）---
        self._pending = False
        self._latest_displayed_round = 0
        self._request_timing_service = RequestTimingService()
        self._last_scene_hash: int | None = None
        self._active_scene_probe_size: int = scene_probe_size_from_config(self.config)
        self._scene_generation: int = 0
        self._inflight_scene_generation: int = 0
        self._stale_scene_inflight_drop_count: int = 0
        self._stale_scene_consume_drop_count: int = 0
        self._latest_screenshot_id: int = 0
        self._latest_requested_screenshot_id: int = 0
        self._latest_queued_screenshot_id: int = 0
        self._latest_displayed_screenshot_id: int = 0
        self._scene_rhythm_pause_until: float = 0.0
        self._scene_captures_after_change: int = 0
        self._scene_api_gate_active: bool = False
        self._scene_gate_prev_hash: int | None = None
        self._scene_generation_bumped_at: float = 0.0
        # RequestScheduler / RequestTimingService：Phase 4 真实所有权；DanmuApp 仅保留 @property 兼容 façade
        self._request_scheduler = RequestScheduler()
        self._scene_memory = SceneMemoryStore()
        self._activity_state = RecentActivityState()
        self._last_activity_collect_at: float = 0.0
        self._mic_service = MicService(log_fn=lambda msg: self.logger.info(msg))

        # --- 会话统计（Token/弹幕计数；stop/quit 时并入 LifetimeStats）---
        self.stats_state = StatsState()

        # 连续失败退避机制
        self._consecutive_failures = 0
        self._failure_backoff_paused = False
        self._last_error_message = ""
        self.MAX_CONSECUTIVE_FAILURES = 5

        # Latest-frame-first freshness
        self._inflight_screenshot_id: int = 0
        self._inflight_started_at: float = 0.0
        self._stale_drop_count: int = 0
        self._stale_drop_times: list[float] = []
        self._screenshot_backoff_level: int = 0
        self._live_status_timer = QTimer(self)
        self._live_status_timer.setInterval(500)
        self._live_status_timer.timeout.connect(self._publish_live_status)

        self.tray.show()
        self.hotkey.register()
        self.config_changed.connect(self._on_config_changed)
        if self.config.get("danmu_display_mode", "").strip().lower() == "realtime":
            self.config.set("danmu_display_mode", "normal")

        # 统计数据（会话内 + 持久化累计）
        from app.session_run_log import SessionRunLog

        self.session_run_log = SessionRunLog(self.config)
        self.lifetime_stats = LifetimeStats(self.config)
        self._lifetime_flush_timer = QTimer(self)
        self._lifetime_flush_timer.setInterval(2000)
        self._lifetime_flush_timer.timeout.connect(self.lifetime_stats.flush_pending)

        startup_notice = self.config.get_startup_notice()
        if startup_notice:
            self.logger.info(startup_notice)

        from app.web_console import attach_web_console, open_web_console_browser

        self.web_server = attach_web_console(self)
        initial = "/#settings" if not self.config.get_api_key() else "/"
        if self.web_server.startup_ok:
            self.logger.info(
                f"Web 控制台: {self.web_server.base_url} （托盘可再次打开）"
            )
            if self.web_launch_mode == "browser":
                QTimer.singleShot(
                    900, lambda: open_web_console_browser(self.web_server, initial)
                )
            else:
                from app.bundle_paths import is_frozen
                from app.webview_shell import attach_webview_shell

                webview_delay_ms = 2000 if is_frozen() else 600
                QTimer.singleShot(
                    webview_delay_ms,
                    lambda: attach_webview_shell(
                        self, self.web_server, initial_path=initial
                    ),
                )
                self.logger.info(
                    "桌面壳: pywebview（--web-browser 可改用系统浏览器）"
                )
        else:
            self.logger.error(
                f"Web 控制台未能启动: {self.web_server.base_url} "
                "（端口可能被占用，请关闭其它 DanmuAI 实例后重启）"
            )
            from app.webview_shell import notify_web_console_failure

            notify_web_console_failure(self, "web_console.startup_failed")

        self._sync_reply_batch_config()

    def _get_request_scheduler(self) -> RequestScheduler:
        try:
            return object.__getattribute__(self, "_request_scheduler")
        except AttributeError:
            # bind_minimal_danmu_app 等测试可能未走完整 __init__
            scheduler = RequestScheduler()
            object.__setattr__(self, "_request_scheduler", scheduler)
            return scheduler

    # --- Phase 4 兼容 façade：真实数据在 application 层服务，禁止在 DanmuApp 新增并行节流/timing 字段 ---
    @property
    def _last_api_trigger_at(self) -> float:
        return self._get_request_scheduler().last_api_trigger_at

    @_last_api_trigger_at.setter
    def _last_api_trigger_at(self, value: float) -> None:
        self._get_request_scheduler().last_api_trigger_at = float(value)

    def _get_request_timing_service(self) -> RequestTimingService:
        try:
            return object.__getattribute__(self, "_request_timing_service")
        except AttributeError:
            service = RequestTimingService()
            object.__setattr__(self, "_request_timing_service", service)
            return service

    @property
    def _request_started_at_by_id(self) -> dict[str, float]:
        return self._get_request_timing_service().request_started_at_by_id

    @_request_started_at_by_id.setter
    def _request_started_at_by_id(self, value: dict[str, float]) -> None:
        self._get_request_timing_service().request_started_at_by_id = value

    @property
    def _rtt_history(self) -> list[float]:
        return self._get_request_timing_service().rtt_history

    @_rtt_history.setter
    def _rtt_history(self, value: list[float]) -> None:
        self._get_request_timing_service().rtt_history = value

    def _normal_recognition_interval_ms(self) -> int:
        try:
            sec = int(self.config.get("normal_recognition_interval_sec", "5"))
        except (TypeError, ValueError):
            sec = 5
        sec = max(1, min(sec, 60))
        return sec * 1000

    def _normal_reply_count(self) -> int:
        return normal_reply_count_from_config(self.config)

    def _sync_reply_batch_config(self) -> None:
        count = self._normal_reply_count()
        self._reply_scene_count = count
        self._reply_filler_count = 0
        self._queue_batch_size = count
        self._queue_low_watermark = max(1, count // 2)

    def _scene_probe_size(self) -> int:
        return scene_probe_size_from_config(self.config)

    def _optional_instance_attr(self, name: str):
        """Read instance attr without QObject __getattr__ (safe for DanmuApp.__new__ tests)."""
        try:
            return object.__getattribute__(self, name)
        except AttributeError:
            return None

    def _ensure_stats_state(self) -> StatsState:
        """会话统计真实所有者；danmu_count / _total_*_tokens 的 @property 仅作旧代码兼容。"""
        state = self._optional_instance_attr("stats_state")
        if state is None:
            state = StatsState()
            object.__setattr__(self, "stats_state", state)
        return state

    def _ensure_web_runtime_state(self) -> WebRuntimeState:
        state = self._optional_instance_attr("web_runtime_state")
        if state is None:
            state = WebRuntimeState()
            object.__setattr__(self, "web_runtime_state", state)
        return state

    @property
    def danmu_count(self) -> int:
        return self._ensure_stats_state().danmu_count

    @danmu_count.setter
    def danmu_count(self, value: int) -> None:
        self._ensure_stats_state().danmu_count = int(value or 0)

    @property
    def _total_input_tokens(self) -> int:
        return self._ensure_stats_state().total_input_tokens

    @_total_input_tokens.setter
    def _total_input_tokens(self, value: int) -> None:
        self._ensure_stats_state().total_input_tokens = int(value or 0)

    @property
    def _total_output_tokens(self) -> int:
        return self._ensure_stats_state().total_output_tokens

    @_total_output_tokens.setter
    def _total_output_tokens(self, value: int) -> None:
        self._ensure_stats_state().total_output_tokens = int(value or 0)

    @property
    def _start_time(self) -> float:
        return self._ensure_stats_state().start_time

    @_start_time.setter
    def _start_time(self, value: float) -> None:
        self._ensure_stats_state().start_time = float(value or 0.0)

    @property
    def _web_error_message(self) -> str:
        return self._ensure_web_runtime_state().error_message

    @_web_error_message.setter
    def _web_error_message(self, value: str) -> None:
        self._ensure_web_runtime_state().error_message = str(value or "")

    @property
    def _web_error_is_error(self) -> bool:
        return self._ensure_web_runtime_state().is_error

    @_web_error_is_error.setter
    def _web_error_is_error(self, value: bool) -> None:
        self._ensure_web_runtime_state().is_error = bool(value)

    @property
    def _cached_danmu_lines(self) -> int:
        return self._ensure_web_runtime_state().cached_danmu_lines

    @_cached_danmu_lines.setter
    def _cached_danmu_lines(self, value: int) -> None:
        state = self._ensure_web_runtime_state()
        state.cached_danmu_lines = int(value or 0)

    @property
    def _cached_layout_mode(self) -> str:
        return self._ensure_web_runtime_state().cached_layout_mode

    @_cached_layout_mode.setter
    def _cached_layout_mode(self, value: str) -> None:
        state = self._ensure_web_runtime_state()
        state.cached_layout_mode = str(value or "fullscreen")

    def _sync_scene_probe_size(self) -> None:
        probe = self._scene_probe_size()
        if probe != getattr(self, "_active_scene_probe_size", probe):
            self._last_scene_hash = None
            self._active_scene_probe_size = probe

    def _on_config_changed(self):
        self._sync_reply_batch_config()
        self._sync_scene_probe_size()
        web_runtime_state = self._ensure_web_runtime_state()
        self.screenshot_timer.setInterval(self._normal_recognition_interval_ms())
        self.MAX_IN_FLIGHT = 1
        self.reply_buffer.set_max_items(self._queue_capacity())
        new_lines = self.config.get_int("danmu_lines", 0)
        lines_changed = new_lines != web_runtime_state.cached_danmu_lines
        if lines_changed:
            self.engine.reload_tracks(preserve_visible=True)
        new_layout = self.config.get("layout_mode", "fullscreen")
        layout_changed = new_layout != web_runtime_state.cached_layout_mode
        if layout_changed:
            if self.engine.running:
                self.overlay.show_for_screen(
                    resolve_screen_index(self.config),
                    reload_tracks=True,
                )
        if lines_changed or layout_changed:
            web_runtime_state.set_overlay_cache(
                danmu_lines=new_lines,
                layout_mode=new_layout,
            )
        hotkey_str = self.config.get("hotkey", "Ctrl+Shift+B")
        self.hotkey.set_keys(hotkey_str)
        if self.engine.running:
            self.overlay.show_for_screen(resolve_screen_index(self.config))
            self.overlay.ensure_render_loop()
        self._sync_mic_service()

    def _mic_audio_supported(self) -> bool:
        default_model_id = self.config.get_default_model_id()
        if default_model_id:
            for model in self.config.get_custom_models():
                if model.get("modelId") == default_model_id:
                    if not is_doubao_mode(model.get("mode", "")):
                        return False
                    return model_likely_supports_mic_audio(default_model_id)
        if not is_doubao_mode(self.config.get("api_mode", "doubao")):
            return False
        return model_likely_supports_mic_audio(resolve_active_model_id(self.config))

    def _sync_mic_service(self) -> None:
        """按配置与运行状态启停 MicService / 端点检测器，避免保存配置时反复开关默认录音设备。

        关闭 mic 模式时才 stop 采集（蓝牙耳机在 Windows 上易因反复 open/close 断连）。
        弹幕未运行时仅预热或保持采集，utterance 检测在 engine.running 且模型支持音频后才启动。
        """
        mic_on = mic_mode_enabled(self.config)
        # 仅在校验关闭麦克风模式时 stop，避免「保存配置 → 生成弹幕」之间反复开关
        # 默认录音设备（蓝牙耳机在 Windows 上尤其容易因此断连）。
        if not mic_on:
            self._mic_service.sync(enabled=False)
            self._stop_mic_utterance_detector()
            return
        if self.engine.running:
            self._mic_service.sync(enabled=True)
        elif not self._mic_service.is_running():
            self._stop_mic_utterance_detector()
            self.logger.info("mic mode enabled; capture starts when danmu is running")
            return
        else:
            self._stop_mic_utterance_detector()
            self.logger.info(
                "mic mode enabled; keeping mic capture open until danmu starts"
            )
            return
        if not self._mic_service.is_running():
            err = self._mic_service.last_error() or "unknown"
            self.logger.warning(f"mic capture not running: {err}")
            self._stop_mic_utterance_detector()
            return
        if not self._mic_audio_supported():
            model_id = resolve_active_model_id(self.config)
            self.logger.warning(tr("mic.warn_unsupported_model").format(model=model_id or "?"))
            self._stop_mic_utterance_detector()
            return
        self._start_mic_utterance_detector()

    def _start_mic_utterance_detector(self) -> None:
        if self._mic_utterance_detector is None:
            self._mic_utterance_detector = MicUtteranceDetector(
                on_utterance_end=self._on_mic_utterance_end,
                config=mic_utterance_config_from_store(self.config),
            )
        else:
            self._mic_utterance_detector.update_config(mic_utterance_config_from_store(self.config))
        if not self._mic_poll_timer.isActive():
            self._mic_poll_timer.start()
        QTimer.singleShot(1500, self._calibrate_mic_noise_floor)

    def _calibrate_mic_noise_floor(self) -> None:
        if self._mic_utterance_detector is None:
            return
        if not mic_mode_enabled(self.config) or not self.engine.running:
            return
        if not self._mic_service.is_running():
            return
        pcm = self._mic_service.snapshot_pcm_ms(1500)
        floor = calibrate_noise_floor_rms(pcm)
        self._mic_utterance_detector.set_noise_floor(floor)
        enter = self._mic_utterance_detector.enter_threshold()
        self.logger.info(
            f"mic utterance calibrated: noise_floor={floor} enter_rms>={enter} "
            f"poll_ms={self._mic_poll_ms}"
        )

    def _stop_mic_utterance_detector(self) -> None:
        self._mic_poll_timer.stop()
        if self._mic_utterance_detector is not None:
            self._mic_utterance_detector.reset()

    def _poll_mic_utterance(self) -> None:
        if not mic_mode_enabled(self.config) or not self.engine.running:
            return
        if not self._mic_service.is_running() or self._mic_utterance_detector is None:
            return
        pcm = self._mic_service.snapshot_pcm_ms(self._mic_poll_ms)
        self._mic_utterance_detector.poll(pcm)

    def _on_mic_utterance_end(self) -> None:
        if not mic_mode_enabled(self.config) or not self.engine.running:
            return
        if self._has_mic_request_in_flight():
            self.logger.info("mic insert skipped: request already in flight")
            return
        if not self._mic_audio_supported():
            return
        window = mic_window_sec_from_config(self.config)
        pcm = self._mic_service.snapshot_pcm(window)
        rms, _ = pcm_metrics(pcm)
        self.logger.info(
            f"mic utterance end: snapshot_window={window}s pcm_bytes={len(pcm)} rms={rms}"
        )
        self._trigger_mic_api_call(pcm)

    def _has_mic_request_in_flight(self) -> bool:
        return self.mic_in_flight > 0

    def _register_request_meta(
        self,
        request_round: int,
        screenshot_id: int,
        scene_generation: int,
        source: str,
    ) -> str:
        key = self._reply_request_id(request_round, screenshot_id, scene_generation)
        self._pending_request_meta[key] = {"source": source}
        return key

    def _pop_request_meta(
        self,
        request_round: int,
        screenshot_id: int,
        scene_generation: int,
    ) -> dict:
        key = self._reply_request_id(request_round, screenshot_id, scene_generation)
        meta = self._pending_request_meta.pop(key, None)
        if meta is None:
            self.logger.warning(
                "request_meta_missing: request_id=%s screenshot_id=%s request_round=%s "
                "scene_generation=%s reason=pop_before_reply",
                key,
                screenshot_id,
                request_round,
                scene_generation,
            )
            return {}
        return meta

    def _release_inflight_for_source(self, source: str) -> None:
        if source == "mic":
            self.mic_in_flight = max(0, self.mic_in_flight - 1)
            return
        self.ai_in_flight = max(0, self.ai_in_flight - 1)
        self._is_generating = False
        self._inflight_started_at = 0.0
        self._inflight_screenshot_id = 0
        self._inflight_scene_generation = 0

    def _trigger_mic_api_call(self, pcm: bytes) -> None:
        """语音段结束时插入一发 AI：附最新截图 + PCM，与视觉轨共享 AiWorker 但独立 mic_in_flight。

        request_round 取负递增（-_mic_request_seq），与视觉正 round 区分，防止 _pending_request_meta 混淆。
        """
        if not mic_mode_enabled(self.config) or not self.engine.running:
            return
        if self._has_mic_request_in_flight():
            return
        if not self._mic_audio_supported():
            model_id = resolve_active_model_id(self.config)
            self.logger.warning(tr("mic.warn_unsupported_model").format(model=model_id or "?"))
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
        now = datetime.now().strftime("%H:%M:%S")
        user_pt = user_pt.replace("{current_time}", now)
        user_pt = user_pt.replace("{round}", str(self.screenshot_round))
        user_pt = build_mic_insert_user_pt(user_pt, self.config)

        self.mic_in_flight += 1
        mic_request_id = self._reply_request_id(request_round, screenshot_id, scene_generation)
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
        from PyQt6.QtCore import QThreadPool

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
        QThreadPool.globalInstance().start(runnable)

    def _set_error_status_safe(self, message: str, is_error: bool):
        self._ensure_web_runtime_state().set_error_status(message, is_error=is_error)
        bridge = getattr(self, "web_bridge", None)
        if bridge:
            bridge.publish_status()

    # --- Web/API 公开 façade：新逻辑必须经下列入口，禁止 danmu_app._xxx / ai_worker._xxx ---
    # build_status_snapshot → StatusSnapshotBuilder；apply_web_config_payload → ConfigService
    def set_web_error_status(self, message: str, *, is_error: bool) -> None:
        self._set_error_status_safe(message, is_error=is_error)

    def build_status_snapshot(self) -> dict[str, object]:
        return StatusSnapshotBuilder(self).build()

    def build_diagnostic_snapshot(self) -> dict[str, object]:
        return DiagnosticSnapshotBuilder(self).build()

    def build_diagnostic_report(self) -> str:
        return build_diagnostic_report(self.build_diagnostic_snapshot())

    def apply_web_config_payload(self, payload: dict[str, object]) -> None:
        apply_web_config_patch(self, payload)

    def attach_web_status_timer(self, timer: QTimer) -> QTimer:
        current = getattr(self, "_web_status_timer", None)
        if current is timer:
            return timer
        if current is not None:
            try:
                current.stop()
            except RuntimeError:
                pass
        self._web_status_timer = timer
        return timer

    def detach_web_status_timer(self) -> QTimer | None:
        timer = getattr(self, "_web_status_timer", None)
        self._web_status_timer = None
        return timer

    def stop_web_status_timer(self) -> None:
        timer = getattr(self, "_web_status_timer", None)
        if timer is None:
            return
        try:
            timer.stop()
        except RuntimeError:
            pass

    def set_active_personae(self, active: list[str]) -> None:
        self.personae.set_active(active)
        self.config_changed.emit()

    def get_capture_region_status(self) -> dict[str, object]:
        from app.web_api.capture_region import read_capture_region_status

        state = self._region_selection_state
        if state not in ("selecting", "saved", "cancelled", "invalid"):
            state = "idle"
        return read_capture_region_status(self.config, selection_state=state)

    def request_capture_region_selection(self) -> None:
        from app.region_selector import RegionSelectorOverlay, screen_for_index
        from app.snipper import resolve_screen_index
        from app.web_api.capture_region import SELECTION_SELECTING

        if self._region_selection_state == SELECTION_SELECTING and self._region_selector is not None:
            self.logger.debug("capture region selection already in progress")
            return

        self._close_region_selector()
        screen_index = resolve_screen_index(self.config)
        self._region_selection_screen_index = screen_index
        screen = screen_for_index(screen_index)
        if screen is None:
            self._region_selection_state = "invalid"
            self.logger.warning("capture region selection: no screen available")
            self._publish_capture_region_status()
            return

        self._region_selection_state = SELECTION_SELECTING
        overlay = RegionSelectorOverlay(screen)
        overlay.selection_finished.connect(self._on_region_selection_finished)
        overlay.selection_cancelled.connect(self._on_region_selection_cancelled)
        overlay.destroyed.connect(self._on_region_selector_destroyed)
        self._region_selector = overlay
        overlay.showFullScreen()
        self._publish_capture_region_status()

    def reset_capture_region(self) -> None:
        from app.web_api.capture_region import clear_capture_region

        self._close_region_selector()
        self._region_selection_state = "idle"
        self._region_selection_screen_index = None
        clear_capture_region(self.config)
        self.config_changed.emit()
        self._publish_capture_region_status()

    def _on_app_focus_changed(self, _old_widget, _new_widget) -> None:
        if self.engine.running and self.overlay.isVisible():
            self.overlay.reassert_topmost_zorder()

    def _close_region_selector(self) -> None:
        overlay = self._region_selector
        self._region_selector = None
        if overlay is None:
            return
        try:
            overlay.selection_finished.disconnect(self._on_region_selection_finished)
        except (TypeError, RuntimeError):
            pass
        try:
            overlay.selection_cancelled.disconnect(self._on_region_selection_cancelled)
        except (TypeError, RuntimeError):
            pass
        try:
            overlay.destroyed.disconnect(self._on_region_selector_destroyed)
        except (TypeError, RuntimeError):
            pass
        try:
            overlay.close()
        except RuntimeError:
            pass
        if self.engine.running and self.overlay.isVisible():
            self.overlay.reassert_topmost_zorder()

    def _on_region_selector_destroyed(self, *_args) -> None:
        if self._region_selector is not None:
            self._region_selector = None

    def _on_region_selection_finished(self, rect) -> None:
        from app.region_selector import screen_for_index
        from app.web_api.capture_region import (
            SELECTION_INVALID,
            SELECTION_SAVED,
            apply_capture_region,
        )

        self._region_selector = None
        screen_index = self._region_selection_screen_index
        if screen_index is None:
            screen_index = self.config.get_int("screen_index", 0)
        screen = screen_for_index(screen_index)
        if screen is None:
            self._region_selection_state = SELECTION_INVALID
            self._publish_capture_region_status()
            return

        geo = screen.geometry()
        applied = apply_capture_region(
            self.config,
            rect.x(),
            rect.y(),
            rect.width(),
            rect.height(),
            screen_width=geo.width(),
            screen_height=geo.height(),
        )
        if applied is None:
            self._region_selection_state = SELECTION_INVALID
            self.logger.info("capture region selection rejected: invalid or too small")
        else:
            self._region_selection_state = SELECTION_SAVED
            self.logger.info(
                "capture region saved "
                f"x={applied[0]} y={applied[1]} w={applied[2]} h={applied[3]} "
                f"screen_index={screen_index}"
            )
            self.config_changed.emit()
        self._publish_capture_region_status()

    def _on_region_selection_cancelled(self) -> None:
        from app.web_api.capture_region import SELECTION_CANCELLED

        self._region_selector = None
        self._region_selection_state = SELECTION_CANCELLED
        self.logger.debug("capture region selection cancelled")
        self._publish_capture_region_status()

    def _publish_capture_region_status(self) -> None:
        bridge = getattr(self, "web_bridge", None)
        if bridge:
            bridge.publish_status()

    def resolve_request_credentials(self):
        return self.ai_worker._resolve_request_credentials()

    def run_mic_test(self, duration_sec: float, *, send_to_ai: bool = False) -> dict[str, object]:
        from dataclasses import asdict

        if send_to_ai:
            from app.mic_test_send import run_mic_test_send

            resolved = self.resolve_request_credentials()
            active_model = resolved[2] if resolved else ""
            result = run_mic_test_send(self, duration_sec)
            self.logger.info(
                "mic test send "
                f"model={active_model or 'unknown'} "
                f"ok={result.ok} level={result.level} pcm_bytes={result.pcm_bytes} "
                f"rms={result.rms} audio_attached={result.audio_attached} "
                f"input_tokens={result.input_tokens} output_tokens={result.output_tokens} "
                f"error={result.error or 'none'}"
            )
            return asdict(result)

        from app.mic_test import run_mic_test

        keep_running = mic_mode_enabled(self.config)
        result = run_mic_test(
            self._mic_service,
            duration_sec,
            keep_running=keep_running,
        )
        self.logger.info(
            "mic test "
            f"ok={result.ok} level={result.level} pcm_bytes={result.pcm_bytes} "
            f"rms={result.rms} peak={result.peak} wav_ok={result.wav_ok} "
            f"device={result.default_input or 'unknown'}"
        )
        return asdict(result)

    def _has_visual_request_in_flight(self) -> bool:
        return self._is_generating or self.ai_in_flight > 0

    def _record_stale_drop(self):
        now = time.monotonic()
        self._stale_drop_count += 1
        self._stale_drop_times.append(now)
        self._stale_drop_times = prune_stale_drop_times(self._stale_drop_times, now)
        if should_backoff_screenshot(self._stale_drop_times, now):
            self._screenshot_backoff_level = min(
                self._screenshot_backoff_level + 1,
                4,
            )
            self._apply_screenshot_interval_backoff()
            self.logger.info(
                tr("app.screenshot_backoff").format(level=self._screenshot_backoff_level)
            )
        self._publish_live_status()

    def _apply_screenshot_interval_backoff(self):
        old_ms = self.screenshot_timer.interval()
        try:
            base_sec = int(self.config.get("normal_recognition_interval_sec", "5"))
        except (TypeError, ValueError):
            base_sec = 5
        base_sec = max(1, min(base_sec, 60))
        new_ms = screenshot_interval_ms(base_sec, self._screenshot_backoff_level)
        self.screenshot_timer.setInterval(new_ms)
        self.logger.info(
            "screenshot_interval_backoff "
            f"backoff_level={self._screenshot_backoff_level} "
            f"old_interval_ms={old_ms} new_interval_ms={new_ms} "
            f"reason=stale_drop_burst"
        )

    def _current_danmu_delay_sec(self) -> float:
        if self._has_visual_request_in_flight() and self._inflight_started_at > 0:
            return max(0.0, time.monotonic() - self._inflight_started_at)
        head = self.reply_buffer.peek()
        if head and head.captured_at > 0:
            return max(0.0, time.monotonic() - head.captured_at)
        if self._latest_screenshot_time > 0:
            return max(0.0, time.monotonic() - self._latest_screenshot_time)
        return 0.0

    def _build_live_status_snapshot(self) -> LiveStatusSnapshot:
        in_flight = self._has_visual_request_in_flight()
        return LiveStatusSnapshot(
            analyzing=in_flight,
            local_fallback=False,
            delay_sec=self._current_danmu_delay_sec(),
            stale_drops=self._stale_drop_count,
        )

    def _publish_live_status(self):
        if not self.engine.running:
            return
        bridge = getattr(self, "web_bridge", None)
        if bridge:
            bridge.publish_status()

    def _capture_frame_hash(self, pixmap: QPixmap | None = None) -> int | None:
        target = pixmap if pixmap is not None else self._latest_screenshot
        if target is None:
            return None
        return fingerprint_from_pixmap(target, probe_size=self._scene_probe_size())

    def _scene_api_block_reason(self) -> str:
        return ""

    def _scene_api_blocked(self) -> bool:
        return bool(self._scene_api_block_reason())

    def _api_schedule_block_reason(self, *, enforce_min_interval: bool) -> str:
        """委托 RequestScheduler 判断视觉请求是否应阻塞；不发起 HTTP、不改队列。

        返回非空字符串时 _trigger_api_call 直接 return（如 in_flight、min_api_interval）。
        """
        scheduler = self._get_request_scheduler()
        return scheduler.block_reason(
            has_visual_request_in_flight=self._has_visual_request_in_flight(),
            scene_block_reason=self._scene_api_block_reason(),
            enforce_min_interval=enforce_min_interval,
            last_trigger_at=scheduler.last_api_trigger_at,
            min_interval_elapsed=min_api_interval_elapsed,
        )

    def _rhythm_cooldown_left_ms(self) -> int:
        left = self._scene_rhythm_pause_until - time.monotonic()
        return max(0, int(left * 1000))

    def _log_api_schedule(
        self,
        *,
        decision: str,
        source: str,
        block_reason: str = "",
    ) -> None:
        if not api_schedule_debug_enabled():
            return
        batch = self._current_batch
        batch_id = batch.batch_id if batch else None
        next_gen = batch.next_generation_time if batch else 0.0
        self.logger.debug(
            format_api_schedule_log(
                decision=decision,
                source=source,
                batch_id=batch_id,
                next_generation_time=next_gen,
                rtt_avg=self._rtt_avg(),
                buffer_size=self.reply_buffer.size(),
                visible_count=self._visible_display_count(),
                in_flight=self._has_visual_request_in_flight(),
                block_reason=block_reason,
                scene_gen=self._scene_generation,
                cooldown_left_ms=self._rhythm_cooldown_left_ms(),
            )
        )

    def _consume_request_timing(
        self,
        request_round: int,
        screenshot_id: int,
        scene_generation: int,
    ) -> None:
        request_id = self._reply_request_id(request_round, screenshot_id, scene_generation)
        timing_service = self._get_request_timing_service()
        rtt = timing_service.consume_timing(
            request_id=request_id,
            now=time.monotonic(),
        )
        if rtt is None:
            self.logger.warning(
                "RTT 样本缺失: request_id=%s screenshot_id=%s request_round=%s "
                "scene_generation=%s reason=timing_not_started",
                request_id,
                screenshot_id,
                request_round,
                scene_generation,
            )
            return
        self.logger.debug(
            f"[DEBUG] RTT={rtt:.1f}s, avg={self._rtt_avg():.1f}s, request_id={request_id}"
        )

    def _is_reply_stale(
        self,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        *,
        source: str = "ai",
    ) -> tuple[bool, str]:
        """普通模式与 mic：不做 TTL / 代际硬过期，避免队列积压时误丢。"""
        return False, ""

    def _log_reply_drop(self, reason: str, screenshot_id: int, request_round: int, scene_generation: int):
        if reason == "stale_scene_in_flight":
            self._stale_scene_inflight_drop_count += 1
        elif reason == "stale_scene":
            self._stale_scene_consume_drop_count += 1
        self._record_stale_drop()
        self.logger.info(
            tr("app.stale_reply_dropped").format(
                reason=reason,
                screenshot_id=screenshot_id,
                request_round=request_round,
                scene_generation=scene_generation,
            )
        )
        if scene_debug_enabled():
            self.logger.debug(
                "scene_drop "
                f"reason={reason} req_gen={scene_generation} cur_gen={self._scene_generation} "
                f"inflight_drops={self._stale_scene_inflight_drop_count} "
                f"consume_drops={self._stale_scene_consume_drop_count}"
            )

    def _should_clear_batch_on_scene_change(self) -> bool:
        if self.config.get("freshness", "medium") == "strict":
            return True
        return self.config.get("clear_batch_on_scene_change", "0") == "1"

    def _scene_debug_log(self, message: str) -> None:
        if scene_debug_enabled():
            self.logger.debug(message)

    def _freshness_mode(self) -> str:
        return self.config.get("freshness", "medium")

    def _memory_tone_hint(self, persona_id: str) -> str:
        if not persona_id:
            return ""
        return persona_display_name(persona_id)

    def _memory_mode(self) -> str:
        return (self.config.get("memory_mode", MEMORY_MODE_OFF) or MEMORY_MODE_OFF).strip().lower()

    def _memory_enabled(self) -> bool:
        return self._memory_mode() != MEMORY_MODE_OFF

    def _collect_activity_observation(self) -> None:
        if not self._memory_enabled():
            return
        now = time.monotonic()
        if now - self._last_activity_collect_at < 1.0:
            return
        self._last_activity_collect_at = now
        try:
            info = get_foreground_window_info()
            if info is None:
                return
            obs = classify_foreground_window(info.title, info.exe_name)
            obs.scene_generation = self._scene_generation
            self._activity_state.record_observation(obs)
        except Exception:
            pass

    def _append_scene_memory_to_user_pt(self, user_pt: str) -> str:
        mode = self._memory_mode()
        if mode == MEMORY_MODE_OFF:
            return user_pt
        activity_line = format_activity_prompt_line(self._activity_state)
        if activity_line:
            return append_activity_line_to_user_pt(user_pt, activity_line)
        block = self._scene_memory.format_prompt_for_generation(self._scene_generation, mode)
        return append_memory_to_user_pt(user_pt, block)

    def _record_scene_memory_display(self, queued: QueuedReply) -> None:
        if not self._memory_enabled():
            return
        if not queued.memory_eligible or queued.is_fallback or queued.source != "ai":
            return
        angle = bullet_angle_from_index(queued.content_index, self._reply_scene_count)
        self._scene_memory.record_displayed_bullet(
            queued.content,
            queued.scene_generation,
            window=memory_window_from_config(self.config),
            angle=angle,
        )
        if not self._scene_memory.context.tone_hint:
            hint = self._memory_tone_hint(queued.persona_id)
            if hint:
                self._scene_memory.context.tone_hint = hint

    def _queue_capacity(self) -> int:
        return max(8, self._normal_reply_count() * 2)

    def _reply_request_id(self, request_round: int, screenshot_id: int, scene_generation: int) -> str:
        return f"{request_round}:{screenshot_id}:{scene_generation}"

    def _min_density_target(self) -> int:
        return self.engine.min_on_screen()

    def _density_right_target(self, min_n: int) -> int:
        if min_n <= 0:
            return 2
        return max(1, min_n // 3)

    def _maybe_pool_topup(self) -> int:
        if not self.engine.running:
            return 0
        if not any_danmu_pool_source_enabled(self.config):
            return 0
        deficit = self.engine.deficit_below_min()
        if deficit <= 0:
            return 0
        texts = sample_danmu_for_config(self.config, min(deficit, 8))
        if not texts:
            return 0
        added = 0
        for text in texts:
            if self.engine.deficit_below_min() <= 0:
                break
            item = self.engine.add_text(
                text,
                persona="",
                batch_id=0,
                scene_generation=self._scene_generation,
            )
            if item:
                added += 1
        return added

    def _estimated_reply_gap_ms(self) -> int:
        if self.reply_timer.isActive():
            current_interval = self.reply_timer.interval()
            if current_interval > 0:
                return current_interval

        if hasattr(self.engine, "visibility_counts"):
            visible_total, right_count = self.engine.visibility_counts()
        else:
            visible_total = self._visible_display_count()
            right_count = self._right_visible_count()
        min_n = self._min_density_target()
        right_target = self._density_right_target(min_n)
        if min_n > 0 and visible_total < min_n:
            return 200
        if visible_total == 0:
            return 120
        if min_n > 0 and visible_total >= min_n and right_count >= right_target:
            return 1000
        if right_count >= right_target:
            return 1000
        if right_count > 0:
            return 500
        return 200

    def _capture_screenshot(self):
        if not self.engine.running:
            return
        if self._failure_backoff_paused:
            return
        pixmap = self.capturer.grab()
        if pixmap is None:
            self.logger.warning(tr("app.capture_failed"))
            return
        if pixmap.isNull() or pixmap.width() <= 0 or pixmap.height() <= 0:
            screen_index = self.config.get_int("screen_index", 0)
            region_x = self.config.get_int("region_x", 0)
            region_y = self.config.get_int("region_y", 0)
            region_w = self.config.get_int("region_w", 0)
            region_h = self.config.get_int("region_h", 0)
            self.logger.warning(
                "截图无效: is_null=%s width=%s height=%s screen_index=%s "
                "region_x=%s region_y=%s region_w=%s region_h=%s reason=invalid_pixmap",
                pixmap.isNull(),
                pixmap.width(),
                pixmap.height(),
                screen_index,
                region_x,
                region_y,
                region_w,
                region_h,
            )
            return
        self._latest_screenshot = pixmap
        self._latest_screenshot_time = time.monotonic()
        self._latest_screenshot_id += 1
        self.logger.debug(
            tr("app.screenshot_updated").format(
                screenshot_id=self._latest_screenshot_id,
                scene_generation=self._scene_generation,
                width=pixmap.width(),
                height=pixmap.height(),
            )
        )
        self._collect_activity_observation()

    def _on_screenshot_timer(self):
        self._on_normal_capture_tick()

    def _on_normal_capture_tick(self):
        # 普通模式主链路：无视觉 in-flight 才截图；成功则同 tick 内触发 API（不等待 reply_timer）
        if self._has_visual_request_in_flight():
            elapsed_ms = 0
            if self._inflight_started_at > 0:
                elapsed_ms = int((time.monotonic() - self._inflight_started_at) * 1000)
            warn_ms = int(VISUAL_INFLIGHT_WARN_SEC * 1000)
            if elapsed_ms >= warn_ms:
                self.logger.warning(
                    "视觉请求 in-flight 超时: screenshot_id=%s elapsed_ms=%s ai_in_flight=%s "
                    "reason=inflight_watchdog",
                    self._inflight_screenshot_id,
                    elapsed_ms,
                    self.ai_in_flight,
                )
            else:
                self.logger.debug(
                    "跳过截图 tick: reason=in_flight screenshot_id=%s elapsed_ms=%s",
                    self._inflight_screenshot_id,
                    elapsed_ms,
                )
            return
        self._capture_screenshot()
        if self._latest_screenshot is None:
            return
        self._trigger_api_call(source="normal_interval")

    def _trigger_api_call(self, source: str = "unknown"):
        """占用唯一视觉 in-flight 槽位，用当前 _latest_screenshot 发起 AiRunnable。

        递增 screenshot_round / _batch_id，登记 _inflight_* 与 _pending_request_meta 供回复到达时
        做过期判断；成功触发后清除 local_fallback 标记，避免与真 AI 回复重复占位。
        """
        block = self._api_schedule_block_reason(enforce_min_interval=True)
        if block:
            self._log_api_schedule(decision="block", source=source, block_reason=block)
            if block == "in_flight":
                self.logger.debug(tr("app.skip_api_generating"))
            return
        if self._latest_screenshot is None:
            self._log_api_schedule(decision="block", source=source, block_reason="no_screenshot")
            self.logger.debug(tr("app.skip_api_no_screenshot"))
            return

        trigger_at = time.monotonic()
        self._get_request_scheduler().record_trigger_time(now=trigger_at)
        self._log_api_schedule(decision="fire", source=source)
        pixmap = self._latest_screenshot
        self._is_generating = True
        self.ai_in_flight += 1
        self.screenshot_round += 1
        request_round = self.screenshot_round
        screenshot_id = self._latest_screenshot_id
        captured_at = self._latest_screenshot_time
        self._batch_id += 1
        batch_id = self._batch_id
        self._latest_requested_screenshot_id = screenshot_id
        self._inflight_screenshot_id = screenshot_id
        self._inflight_scene_generation = self._scene_generation
        self._inflight_started_at = time.monotonic()
        self._publish_live_status()

        persona = self.personae.pick_random()
        system_pt, user_pt = self.personae.get_prompt(persona)

        request_id = self._reply_request_id(request_round, screenshot_id, self._scene_generation)
        self.logger.info(
            tr("app.api_triggered").format(
                batch_id=batch_id,
                screenshot_id=screenshot_id,
                scene_generation=self._scene_generation,
                persona=persona_display_name(persona),
            )
            + f" request_round={request_round} request_id={request_id}"
        )

        now = datetime.now().strftime("%H:%M:%S")
        user_pt = user_pt.replace("{current_time}", now)
        user_pt = user_pt.replace("{round}", str(self.screenshot_round))
        user_pt = self._append_scene_memory_to_user_pt(user_pt)

        self._current_persona = persona
        self._get_request_timing_service().mark_started(
            request_id=request_id,
            now=time.monotonic(),
        )
        self._register_request_meta(request_round, screenshot_id, self._scene_generation, "visual")

        from app.runnable import AiRunnable
        from PyQt6.QtCore import QThreadPool

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
            self._scene_generation,
            lambda p: compress_screenshot(p, image_max_width, image_quality),
            image_quality=image_quality,
        )
        QThreadPool.globalInstance().start(runnable)

    def _danmu_pixels_per_second(self, speed: float | None = None) -> float:
        if speed is None:
            from app.config_defaults import DEFAULT_DANMU_SPEED

            speed = self.config.get_float("danmu_speed", DEFAULT_DANMU_SPEED)
        factor = 1.0
        if getattr(self.engine, "_accel_remaining", 0) > 0:
            factor = min(getattr(self.engine, "_accel_peak", 1.0), 2.0)
        return pixels_per_second(speed, factor)

    def _default_batch_interval(self) -> float:
        from app.config_defaults import DEFAULT_DANMU_SPEED

        speed = self.config.get_float("danmu_speed", DEFAULT_DANMU_SPEED)
        speed_per_second = self._danmu_pixels_per_second(speed)
        if speed_per_second <= 0:
            return 5.0
        distance = self.engine.screen_width * 0.25
        return distance / speed_per_second

    def _reply_low_watermark(self) -> int:
        return max(0, self.config.get_int("reply_low_watermark", 1))

    def _empty_accel_enabled(self) -> bool:
        return self.config.get("empty_accel", "1") == "1"

    def _visible_display_count(self) -> int:
        if hasattr(self.engine, "visible_display_count"):
            return self.engine.visible_display_count()
        return self.engine.current_display_count()

    def _right_visible_count(self) -> int:
        if hasattr(self.engine, "right_visible_count"):
            return self.engine.right_visible_count()
        return self.engine.right_zone_count()

    def _broadcast_live_overlay_item(self, item, text: str, *, source: str) -> None:
        """Qt 上屏后旁路同步单条弹幕到网页层（含轨道 Y，与 Overlay 对齐）。"""
        state = getattr(self, "__dict__", None) or {}
        server = state.get("web_server")
        hub = getattr(server, "live_overlay_hub", None) if server else None
        if not hub or not text:
            return
        try:
            hub.broadcast_item(
                text,
                y=float(item.y),
                screen_width=float(self.engine.screen_width),
                screen_height=float(self.engine.screen_height),
                speed=float(item.speed),
                source=source,
            )
        except Exception as exc:
            self.logger.debug(f"live overlay broadcast skipped: {exc!r}")

    def _enqueue_reply_batch(
        self,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        normalized_items: list[str],
        *,
        from_local_fallback: bool = False,
        from_mic_insert: bool = False,
    ):
        """构造 QueuedReply 批次写入 reply_buffer；副作用：更新 _latest_queued_screenshot_id。

        普通视觉批次走 extend（队尾）；mic / local_fallback 走 prepend_batch（队首优先）。
        不在此调用 engine.add_text——上屏仅由 _consume_reply_queue 串行完成。
        """
        request_id = self._reply_request_id(request_round, screenshot_id, scene_generation)
        if from_mic_insert:
            self._mic_batch_id += 1
            batch_id = self._mic_batch_id
        else:
            batch_id = self._batch_id
        if from_mic_insert:
            source = "mic"
            replaceable = False
            memory_eligible = True
            is_fallback = False
        elif from_local_fallback:
            source = "fallback"
            replaceable = True
            memory_eligible = False
            is_fallback = True
        else:
            source = "ai"
            replaceable = False
            memory_eligible = True
            is_fallback = False

        batch_items = [
            QueuedReply(
                persona_id,
                request_round,
                content_index,
                item_text,
                screenshot_round=request_round,
                screenshot_id=screenshot_id,
                captured_at=captured_at,
                scene_generation=scene_generation,
                batch_id=batch_id,
                request_id=request_id,
                is_fallback=is_fallback,
                source=source,
                replaceable=replaceable,
                memory_eligible=memory_eligible,
            )
            for content_index, item_text in enumerate(normalized_items)
        ]

        if not from_mic_insert:
            self._latest_queued_screenshot_id = max(self._latest_queued_screenshot_id, screenshot_id)
        if from_mic_insert or from_local_fallback:
            self.reply_buffer.prepend_batch(
                batch_items,
                preserve_existing=self._queue_fallback_keep,
                preserve_scene_generation=scene_generation,
                preserve_replaceable=from_local_fallback,
            )
        else:
            self.reply_buffer.extend(batch_items)

        if from_local_fallback:
            self.logger.info(tr("app.local_fallback_batch").format(count=len(normalized_items)))
        elif from_mic_insert:
            self.logger.info(f"mic insert batch: count={len(normalized_items)} batch_id={batch_id}")
        else:
            self.logger.info(
                tr("app.batch_created").format(
                    batch_id=self._batch_id,
                    count=len(normalized_items),
                    interval=self._default_batch_interval(),
                )
            )

    def _on_ai_reply(self, text: str, persona_id: str, request_round: int, screenshot_id: int, captured_at: float, scene_generation: int, input_tokens: int = 0, output_tokens: int = 0):
        """AiWorker.finished 主线程入口：释放在途 → 解析入队 → 驱动 _consume_reply_queue。"""
        self.logger.debug(f"[DEBUG] _on_ai_reply called, text length={len(text)}")
        meta = self._pop_request_meta(request_round, screenshot_id, scene_generation)
        source = meta.get("source") or "visual"
        is_mic = source == "mic"

        self._release_inflight_for_source(source)

        stats_state = self._ensure_stats_state()
        stats_state.add_tokens(input_tokens, output_tokens)
        self.lifetime_stats.add_tokens(input_tokens, output_tokens)
        if input_tokens > 0 or output_tokens > 0:
            self.logger.debug(
                f"[DEBUG] Tokens: input={input_tokens}, output={output_tokens}, "
                f"total_input={stats_state.total_input_tokens}, total_output={stats_state.total_output_tokens}"
            )

        if is_mic:
            self._handle_mic_ai_reply(
                text,
                persona_id,
                request_round,
                screenshot_id,
                captured_at,
                scene_generation,
            )
            return

        if self._consecutive_failures > 0:
            self._consecutive_failures = 0
            self._last_error_message = ""
            if self._failure_backoff_paused:
                self._failure_backoff_paused = False
                self._set_error_status_safe("", is_error=False)
                if self.engine.running and not self.screenshot_timer.isActive():
                    self.screenshot_timer.start()

        self._consume_request_timing(request_round, screenshot_id, scene_generation)

        is_stale, stale_reason = self._is_reply_stale(screenshot_id, captured_at, scene_generation, source="ai")
        if is_stale:
            self._log_reply_drop(stale_reason, screenshot_id, request_round, scene_generation)
            return

        if self._screenshot_backoff_level > 0:
            self._screenshot_backoff_level = max(0, self._screenshot_backoff_level - 1)
            self._apply_screenshot_interval_backoff()

        raw_items, memory_update = parse_ai_reply_with_memory(text, scene_generation)
        normalized_items = normalize_reply_batch(
            raw_items,
            scene_count=self._reply_scene_count,
            filler_count=self._reply_filler_count,
            config=self.config,
        )
        if not normalized_items:
            request_id = self._reply_request_id(request_round, screenshot_id, scene_generation)
            self.logger.warning(
                "AI 回复解析为空: request_id=%s screenshot_id=%s request_round=%s "
                "scene_generation=%s text_len=%s raw_count=%s reason=empty_parse",
                request_id,
                screenshot_id,
                request_round,
                scene_generation,
                len(text or ""),
                len(raw_items),
            )
            return

        if self._memory_enabled():
            if memory_update is not None:
                if memory_update.scene_generation <= 0:
                    memory_update.scene_generation = scene_generation
                self._scene_memory.update_from_visual_result(memory_update)

        self._enqueue_reply_batch(
            persona_id,
            request_round,
            screenshot_id,
            captured_at,
            scene_generation,
            normalized_items,
            from_local_fallback=False,
        )
        self._publish_live_status()

        if not self.reply_timer.isActive():
            self._consume_reply_queue()
        elif self.reply_buffer.size() > self._queue_low_watermark:
            self.reply_timer.stop()
            self._consume_reply_queue()
        else:
            self.reply_timer.setInterval(min(self.reply_timer.interval(), 200))

    def _handle_mic_ai_reply(
        self,
        text: str,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
    ) -> None:
        is_stale, stale_reason = self._is_reply_stale(
            screenshot_id, captured_at, scene_generation, source="mic"
        )
        if is_stale:
            self._log_reply_drop(stale_reason, screenshot_id, request_round, scene_generation)
            return

        normalized_items = normalize_reply_batch(
            parse_ai_reply_payload(text),
            scene_count=self._reply_scene_count,
            filler_count=self._reply_filler_count,
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

    def _consume_reply_queue(self):
        """从 FIFO 弹出一条回复上屏；成功时更新 BatchTracker 锚点与 next_generation_time。

        消费前二次 _is_reply_stale；fallback/mic 可 skip_dedup。锚点弹幕滚到 75% 屏宽处的时间
        写入 batch.next_generation_time（debug/批次元数据）。拒因（去重/入口过载）不入历史。
        """
        queued = self.reply_buffer.pop()
        if queued is None:
            return

        is_stale, stale_reason = self._is_reply_stale(
            queued.screenshot_id,
            queued.captured_at,
            queued.scene_generation,
            source=queued.source,
        )
        if is_stale:
            self._log_reply_drop(stale_reason, queued.screenshot_id, queued.screenshot_round, queued.scene_generation)
            if not self.reply_buffer.is_empty():
                self.reply_timer.start(100)
            return

        self.logger.info(f"[{persona_display_name(queued.persona_id)}] {queued.content}")
        display_content = normalize_danmu_display_text(queued.content, self.config)
        skip_dedup = queued.is_fallback or queued.source == "fallback"
        item = self.engine.add_text(
            queued.content,
            queued.persona_id,
            batch_id=queued.batch_id,
            scene_generation=queued.scene_generation,
            skip_dedup=skip_dedup,
        )
        if item:
            self._latest_displayed_round = max(self._latest_displayed_round, queued.screenshot_round)
            self._latest_displayed_screenshot_id = max(self._latest_displayed_screenshot_id, queued.screenshot_id)
            self.history_writer.enqueue(queued.content, queued.persona_id, queued.batch_index)
            self._record_scene_memory_display(queued)
            overlay_source = queued.source if queued.source in ("ai", "mic", "test") else "ai"
            self._broadcast_live_overlay_item(item, display_content, source=overlay_source)

            batch = self._current_batch
            if batch and batch.anchor_item is None and item.batch_id == batch.batch_id:
                batch.anchor_item = item
                target_x = self.engine.screen_width * 0.75
                distance = item.x - target_x
                if distance > 0 and item.speed > 0:
                    factor = 1.0
                    if getattr(self.engine, "_accel_remaining", 0) > 0:
                        factor = min(getattr(self.engine, "_accel_peak", 1.0), 2.0)
                    time_to_boundary = time_to_anchor_boundary(
                        distance, item.speed, factor
                    )
                    batch.next_generation_time = time.monotonic() + time_to_boundary
                    self.logger.info(
                        tr("app.batch_anchor").format(
                            batch_id=batch.batch_id,
                            x=item.x,
                            target_x=target_x,
                            time_to_boundary=time_to_boundary,
                        )
                    )
                else:
                    batch.next_generation_time = time.monotonic()
        else:
            if (not skip_dedup) and self.engine.is_duplicate(display_content):
                reject = "去重"
            elif self.engine.entry_zone_overloaded():
                reject = "入口区过载"
            else:
                reject = "轨道/布局"
            self.logger.info(
                tr("app.danmu_not_entered").format(content=f"{queued.content[:20]}...")
                + f" [{reject}]"
            )

        if not self.reply_buffer.is_empty():
            delay = 100 if item is None else self._estimated_reply_gap_ms()
            self.reply_timer.start(delay)

        self._update_stats(success=item is not None)
        self._maybe_pool_topup()

    def _calc_auto_interval(self) -> int:
        min_n = self._min_density_target()
        base = self.config.get_int("screenshot_interval", 3)
        freshness = self.config.get("freshness", "medium")
        freshness_factor = {"loose": 1.5, "medium": 1.0, "strict": 0.6}
        factor = freshness_factor.get(freshness, 1.0)
        if min_n > 0:
            per_danmu = max(1, int(base * factor))
            return per_danmu
        return base

    def _rtt_avg(self) -> float:
        return self._get_request_timing_service().avg_rtt()

    def _smart_cooldown_ms(self) -> int:
        return self._get_request_timing_service().smart_cooldown_ms(
            fallback_interval_sec=self.config.get_int("screenshot_interval", 3),
        )

    def _on_ai_error(self, msg: str, persona_id: str, request_round: int, screenshot_id: int, captured_at: float, scene_generation: int, input_tokens: int = 0, output_tokens: int = 0):
        """AiWorker.error 主线程入口：释放在途、累计失败；401/403/余额等 fatal 时停截图定时器。

        与 _on_ai_reply 对称释放 _pending_request_meta；连续失败达阈值进入 _failure_backoff_paused。
        不在此解析弹幕或入队。
        """
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

        self._consume_request_timing(request_round, screenshot_id, scene_generation)
        self.logger.error(
            "%s [persona=%s, round=%s, screenshot_id=%s, scene_generation=%s, "
            "input_tokens=%s, output_tokens=%s]",
            msg, persona_id, request_round, screenshot_id, scene_generation,
            input_tokens, output_tokens,
        )

        self._consecutive_failures += 1
        self._last_error_message = msg

        lower_msg = msg.lower()
        is_fatal = (
            "401" in msg
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

        if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            self.logger.warning(
                tr("app.failure_paused").format(count=self._consecutive_failures, message=msg)
            )
            self._failure_backoff_paused = True
            self.screenshot_timer.stop()
            self._set_error_status_safe(
                tr("app.failure_paused").format(count=self.MAX_CONSECUTIVE_FAILURES, message=msg),
                is_error=True
            )
            return

    def _maybe_log_dedup_profile(self) -> None:
        if not dedup_profile_enabled():
            return
        every = 25
        try:
            last_at = int(self._dedup_profile_log_at_count)
        except (AttributeError, RuntimeError):
            last_at = 0
        if self.danmu_count - last_at < every:
            return
        try:
            self._dedup_profile_log_at_count = self.danmu_count
        except RuntimeError:
            object.__setattr__(self, "_dedup_profile_log_at_count", self.danmu_count)
        log_dedup_profile_summary(self.logger)

    def _update_stats(self, *, success: bool = True):
        if success:
            self._ensure_stats_state().add_danmu(1)
            self.lifetime_stats.add_danmu(1)
        self._maybe_log_dedup_profile()

    def start(self):
        """开始一轮会话：清零代际/在途/队列/统计，启动 screenshot_timer 与 reply_timer，显示 Overlay。

        必须完整重置 start() 内列出的状态，遗漏会导致 stop 后再 start 沿用旧 scene_generation 或
        陈旧 in-flight 元数据。eviction_mode=accelerate 时触发引擎加速清空旧弹幕。
        """
        if not self.config.get_api_key():
            self.logger.warning(tr("app.api_key_missing_warning"))
            if self.web_server:
                self._open_web_console("/#settings")
            return
        self.engine.start()
        self.engine.clear_dedup_window()
        self.ai_worker.reset_stopping()
        self.ai_in_flight = 0
        self._is_generating = False
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
        self._last_scene_hash = None
        self._scene_generation = 0
        self._inflight_scene_generation = 0
        self._stale_scene_inflight_drop_count = 0
        self._stale_scene_consume_drop_count = 0
        self._stale_drop_count = 0
        self._stale_drop_times = []
        self._screenshot_backoff_level = 0
        self._inflight_started_at = 0.0
        self._inflight_screenshot_id = 0
        self._scene_rhythm_pause_until = 0.0
        self._scene_captures_after_change = 0
        self._scene_api_gate_active = False
        self._scene_gate_prev_hash = None
        self._scene_generation_bumped_at = 0.0
        self._get_request_scheduler().reset_trigger_time()
        self._mic_request_seq = 0
        self._mic_batch_id = 0
        self._pending_request_meta.clear()
        self._scene_memory.reset()
        self._activity_state.reset()
        self._last_activity_collect_at = 0.0
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
        eviction = self.config.get("eviction_mode", "natural")
        if eviction == "accelerate":
            self.engine.trigger_acceleration(60)
        self.overlay.show_for_screen(resolve_screen_index(self.config))
        self.overlay.start_render_loop()
        self._pool_topup_timer.start()
        self.tray.update_state(running=True)
        self.state_changed.emit(True)
        self._set_error_status_safe("", is_error=False)
        self.logger.info(tr("app.started"))
        self._sync_mic_service()

    def _flush_session_runtime_to_lifetime(self) -> None:
        stats_state = self._ensure_stats_state()
        if stats_state.start_time > 0:
            self.lifetime_stats.flush_runtime(stats_state.runtime_sec())
            stats_state.clear_runtime()

    def stop(self):
        """暂停弹幕：停定时器、mark_stopping AI、清空队列与在途 meta，hide Overlay；不销毁 Config/Web。

        与 quit() 区别：stop 可再次 start()；会话统计写入 session_run_log 并 flush lifetime。
        """
        self.session_run_log.complete(
            ended_at=time.time(),
            input_tokens=self._ensure_stats_state().total_input_tokens,
            output_tokens=self._ensure_stats_state().total_output_tokens,
            danmu_count=self._ensure_stats_state().danmu_count,
        )
        self._lifetime_flush_timer.stop()
        self.lifetime_stats.flush_pending()
        self._flush_session_runtime_to_lifetime()
        self.screenshot_timer.stop()
        self._live_status_timer.stop()
        self._pending = False
        self.ai_worker.mark_stopping()
        self.ai_in_flight = 0
        self.mic_in_flight = 0
        self._pending_request_meta.clear()
        self._stop_mic_utterance_detector()
        self._is_generating = False
        self._inflight_started_at = 0.0
        self._inflight_screenshot_id = 0
        self._current_batch = None
        self.reply_timer.stop()
        self._pool_topup_timer.stop()
        self.reply_buffer.clear()
        self._get_request_timing_service().clear_started()
        self._latest_requested_screenshot_id = 0
        self._latest_queued_screenshot_id = 0
        self._latest_displayed_screenshot_id = 0
        self._last_scene_hash = None
        self._scene_generation = 0
        self._inflight_scene_generation = 0
        self.engine.stop()
        self._mic_service.stop()
        self.overlay.stop_render_loop()
        self.overlay.hide()
        self.tray.update_state(running=False)
        self.state_changed.emit(False)
        self.logger.info(tr("app.stopped"))

    def toggle(self):
        if self.engine.running:
            self.stop()
        else:
            self.start()

    def _open_web_console(self, path: str = "/") -> None:
        shell = getattr(self, "webview_shell", None)
        if shell:
            shell.open(path)
            return
        if self.web_server:
            from app.web_console import open_web_console_browser

            open_web_console_browser(self.web_server, path)

    def show_settings(self):
        if self.web_server:
            self._open_web_console("/#settings")

    def quit(self):
        """进程退出：先 stop() 停弹幕，再释放热键/托盘/httpx/历史/配置/WebView/uvicorn。

        顺序 intentional：须先 stop 释放在途 AI，再 close httpx 并 waitForDone 线程池，
        否则 QThreadPool 内仍可能访问已关闭客户端。最后 QApplication.quit()。
        """
        self.logger.info(tr("app.quitting"))

        # 1. 停止弹幕引擎和截图（清零在途与队列，避免线程池仍持有旧 runnable）
        self.stop()

        # 2. 卸载快捷键（避免进程退出后 keyboard 钩子仍驻留）
        self.hotkey.unregister()

        # 3. 隐藏托盘图标
        self.tray.hide()

        # 4. 关闭 AI HTTP 客户端，等待线程池，再关闭历史写入与配置库
        self.ai_worker.close()
        from PyQt6.QtCore import QThreadPool
        QThreadPool.globalInstance().waitForDone(2000)
        self.history_writer.stop()
        self.config.close()

        # 5. 隐藏覆盖层
        self.overlay.hide()

        shell = getattr(self, "webview_shell", None)
        if shell:
            shell.destroy()

        self.stop_web_status_timer()
        server = getattr(self, "web_server", None)
        if server:
            server.stop()

        self.logger.info(tr("app.quit_done"))
        QApplication.quit()


def global_exception_hook(exc_type, exc_value, exc_tb):
    if exc_type in (KeyboardInterrupt, SystemExit):
        return
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        from app.logger import SanitizedLogger
        logger = SanitizedLogger()
        logger.error(tr("app.unhandled_exception_log").format(message=msg))
    except Exception:
        import re
        safe_msg = re.sub(r"sk-[A-Za-z0-9_-]{20,}", "sk-****", msg)
        print(f"FATAL: {safe_msg}", file=sys.stderr)
    if issubclass(exc_type, RuntimeError) and "has been deleted" in str(exc_value):
        return
    try:
        if QApplication.instance() is not None:
            QMessageBox.critical(
                None,
                tr("app.error_title"),
                tr("app.unhandled_exception").format(message=exc_value),
            )
    except Exception:
        pass
    sys.exit(1)


_DEPRECATED_LAUNCH_MSG = (
    "已移除 Qt 主窗（--qt-ui）。请使用: python main.py 或 python main.py --web-browser\n"
    "设置、日志、人格均在 Web 控制台（http://127.0.0.1:18765）。\n"
)


def _check_deprecated_launch_args() -> None:
    reasons: list[str] = []
    if "--qt-ui" in sys.argv or "--legacy-ui" in sys.argv:
        reasons.append("命令行参数 --qt-ui / --legacy-ui")
    env_qt = os.environ.get("DANMU_QT_UI", "").strip().lower()
    if env_qt in ("1", "true", "yes", "on"):
        reasons.append("环境变量 DANMU_QT_UI")
    env_web = os.environ.get("DANMU_WEB_CONSOLE", "").strip().lower()
    if env_web in ("0", "false", "no", "off"):
        reasons.append("环境变量 DANMU_WEB_CONSOLE=0")
    if not reasons:
        return
    sys.stderr.write(_DEPRECATED_LAUNCH_MSG)
    sys.stderr.write("废弃入口: " + "、".join(reasons) + "\n")
    sys.exit(2)


def _web_launch_mode_from_argv() -> str:
    """webview = pywebview 桌面窗（默认）；browser = 系统浏览器。"""
    if "--web-browser" in sys.argv:
        return "browser"
    env = os.environ.get("DANMU_WEB_LAUNCH", "").strip().lower()
    if env in ("browser", "webview"):
        return env
    return "webview"


def main():
    multiprocessing.freeze_support()
    _check_deprecated_launch_args()
    sys.excepthook = global_exception_hook
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    from app.single_instance import SingleInstanceGuard

    instance_guard = SingleInstanceGuard()
    if not instance_guard.try_acquire():
        return sys.exit(0)

    launch_mode = _web_launch_mode_from_argv()
    _danmu = DanmuApp(web_launch_mode=launch_mode)
    instance_guard.bind_activate(_danmu.show_settings)
    return sys.exit(app.exec())


if __name__ == "__main__":
    main()
