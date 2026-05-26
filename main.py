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
from app.config_store import ConfigStore
from app.danmu_engine import (
    DanmuEngine,
    DanmuItem,
    dedup_profile_enabled,
    log_dedup_profile_summary,
    normalize_danmu_display_text,
)
from app.danmu_pool import sample_danmu
from app.history import DanmuHistory
from app.history_writer import HistoryWriter
from app.hotkey import HotkeyManager
from app.lifetime_stats import LifetimeStats
from app.live_freshness import (
    SCENE_CHANGE_DEBOUNCE_SEC,
    SCENE_CHANGE_FORCE_DIST,
    SCENE_RHYTHM_PAUSE_SEC,
    LiveStatusSnapshot,
    build_local_fallback_batch,
    is_model_slow,
    prune_stale_drop_times,
    screenshot_interval_ms,
    should_backoff_screenshot,
)
from app.logger import SanitizedLogger
from app.memory.types import MEMORY_MODE_OFF, bullet_angle_from_index
from app.memory.visual_update import infer_visual_update_from_batch
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
    is_normal_display_mode,
    normal_reply_count_from_config,
    persona_display_name,
    reply_counts_from_config,
)
from app.reply_parser import (
    normalize_reply_batch,
    parse_ai_reply_payload,
    parse_ai_reply_with_memory,
)
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply
from app.scene_fingerprint import (
    HAMMING_THRESHOLD,
    fingerprint_from_pixmap,
    hamming_distance,
    is_scene_change,
    scene_debug_enabled,
    scene_probe_size_from_config,
)
from app.scene_memory import SceneMemoryStore, append_memory_to_user_pt, memory_window_from_config
from app.snipper import ScreenCapturer, resolve_screen_index
from app.templates import TemplateManager
from app.translations import Translator, tr
from app.tray import TrayManager
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


class BatchTracker:
    def __init__(self, batch_id: int):
        self.batch_id = batch_id
        self.anchor_item: DanmuItem | None = None
        self.next_generation_time: float = 0.0
        self.next_generation_triggered: bool = False


class DanmuApp(QObject):
    state_changed = pyqtSignal(bool)  # running / paused
    config_changed = pyqtSignal()

    def __init__(self, web_launch_mode: str = "webview"):
        super().__init__()
        self.web_launch_mode = web_launch_mode
        self.web_server = None
        self.web_bridge = None
        self.webview_shell = None
        self._web_error_message = ""
        self._web_error_is_error = False
        self.config = ConfigStore()
        _rx, _ry, _rw, _rh = self.config.get_region()
        if _rw > 0 or _rh > 0:
            self.config.set_region(0, 0, 0, 0)
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
        self._cached_danmu_lines = self.config.get_int("danmu_lines", 0)
        self._cached_layout_mode = self.config.get("layout_mode", "fullscreen")
        self.tray = TrayManager(self)
        self.hotkey = HotkeyManager(self)

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
        self._mic_utterance_detector: MicUtteranceDetector | None = None
        self._mic_poll_timer = QTimer(self)
        self._mic_poll_ms = 400
        self._mic_poll_timer.setInterval(self._mic_poll_ms)
        self._mic_poll_timer.timeout.connect(self._poll_mic_utterance)
        self.STAGGER_INTERVAL = 1.0
        self._screenshot_scheduled = False

        self._latest_screenshot: QPixmap | None = None
        self._latest_screenshot_time: float = 0.0
        self._is_generating: bool = False
        self._batch_id: int = 0
        self._current_batch: BatchTracker | None = None

        self._rhythm_check_timer = QTimer()
        self._rhythm_check_timer.timeout.connect(self._check_rhythm_trigger)

        self.reply_buffer = AIReplyFIFOBuffer(max_items=8)
        self.danmu_queue = self.reply_buffer
        self.reply_timer = QTimer(self)
        self.reply_timer.setInterval(800)
        self.reply_timer.setSingleShot(True)
        self.reply_timer.timeout.connect(self._consume_reply_queue)

        self._pool_topup_timer = QTimer(self)
        self._pool_topup_timer.setInterval(500)
        self._pool_topup_timer.timeout.connect(self._maybe_pool_topup)

        self._queue_low_watermark = 3
        self._queue_fallback_keep = 3
        self._queue_run_dry_window_ms = 2000
        self._reply_scene_count = 2
        self._reply_filler_count = 3
        self._queue_batch_size = 5

        self._pending = False
        self._latest_displayed_round = 0
        self._rtt_history: list[float] = []
        self._request_started_at_by_id: dict[int, float] = {}
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
        self._last_api_trigger_at: float = 0.0
        self._scene_memory = SceneMemoryStore()
        self._mic_service = MicService(log_fn=lambda msg: self.logger.info(msg))

        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._start_time: float = 0.0

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
        self._local_fallback_active: bool = False
        self._local_fallback_for_batch: int = 0
        self._capture_failure_hint_shown: bool = False
        self._live_status_timer = QTimer(self)
        self._live_status_timer.setInterval(500)
        self._live_status_timer.timeout.connect(self._publish_live_status)

        self.tray.show()
        self.hotkey.register()
        self.config_changed.connect(self._on_config_changed)

        # 统计数据（会话内 + 持久化累计）
        self.danmu_count = 0
        from app.session_run_log import SessionRunLog

        self.session_run_log = SessionRunLog()
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

        self._sync_reply_batch_config()

    def _reply_batch_counts(self) -> tuple[int, int]:
        return reply_counts_from_config(self.config)

    def _display_mode(self) -> str:
        return "normal" if is_normal_display_mode(self.config) else "realtime"

    def _is_normal_mode(self) -> bool:
        return self._display_mode() == "normal"

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
        if self._is_normal_mode():
            count = self._normal_reply_count()
            self._reply_scene_count = count
            self._reply_filler_count = 0
            self._queue_batch_size = count
            self._queue_low_watermark = max(1, count // 2)
        else:
            scene, filler = self._reply_batch_counts()
            self._reply_scene_count = scene
            self._reply_filler_count = filler
            self._queue_batch_size = scene + filler
            self._queue_low_watermark = max(1, filler)

    def _scene_probe_size(self) -> int:
        return scene_probe_size_from_config(self.config)

    def _sync_scene_probe_size(self) -> None:
        probe = self._scene_probe_size()
        if probe != getattr(self, "_active_scene_probe_size", probe):
            self._last_scene_hash = None
            self._active_scene_probe_size = probe

    def _on_config_changed(self):
        self._sync_reply_batch_config()
        self._sync_scene_probe_size()
        if self._is_normal_mode():
            self.screenshot_timer.setInterval(self._normal_recognition_interval_ms())
        else:
            self.screenshot_timer.setInterval(1000)
        self.MAX_IN_FLIGHT = 1
        self.STAGGER_INTERVAL = 1.0
        self.reply_buffer.set_max_items(self._queue_capacity())
        new_lines = self.config.get_int("danmu_lines", 0)
        if new_lines != self._cached_danmu_lines:
            self._cached_danmu_lines = new_lines
            self.engine.reload_tracks(preserve_visible=True)
        new_layout = self.config.get("layout_mode", "fullscreen")
        if new_layout != self._cached_layout_mode:
            self._cached_layout_mode = new_layout
            if self.engine.running:
                self.overlay.show_for_screen(
                    resolve_screen_index(self.config),
                    reload_tracks=True,
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
        return self._pending_request_meta.pop(key, {"source": "visual"})

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
        self._web_error_message = message or ""
        self._web_error_is_error = is_error
        bridge = getattr(self, "web_bridge", None)
        if bridge:
            bridge.publish_status()

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
        if self._is_normal_mode():
            self.screenshot_timer.setInterval(self._normal_recognition_interval_ms())
            return
        base = self.config.get_int("screenshot_interval", 3)
        interval = screenshot_interval_ms(base, self._screenshot_backoff_level)
        self.screenshot_timer.setInterval(interval)

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
            analyzing=in_flight and not self._local_fallback_active,
            local_fallback=self._local_fallback_active,
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
        if self._is_normal_mode():
            return ""
        now = time.monotonic()
        pause_until = getattr(self, "_scene_rhythm_pause_until", 0.0)
        if now < pause_until:
            return "scene_cooldown"
        if getattr(self, "_scene_api_gate_active", False):
            captures = getattr(self, "_scene_captures_after_change", 0)
            if captures < 1:
                return "scene_settle"
            try:
                gate_prev = getattr(self, "_scene_gate_prev_hash", None)
            except RuntimeError as exc:
                if "super-class __init__" not in str(exc):
                    raise
                gate_prev = None
            frame_hash = self._capture_frame_hash()
            if gate_prev is not None and frame_hash is not None:
                dist = hamming_distance(gate_prev, frame_hash)
                if dist < HAMMING_THRESHOLD and captures < 2:
                    return "scene_settle_stale_frame"
            self._scene_api_gate_active = False
        return ""

    def _scene_api_blocked(self) -> bool:
        return bool(self._scene_api_block_reason())

    def _api_schedule_block_reason(self, *, enforce_min_interval: bool) -> str:
        if self._has_visual_request_in_flight():
            return "in_flight"
        scene_block = self._scene_api_block_reason()
        if scene_block:
            return scene_block
        last_at = getattr(self, "_last_api_trigger_at", 0.0)
        if enforce_min_interval and not min_api_interval_elapsed(last_at):
            return "min_api_interval"
        return ""

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

    def _if_ready_source(self) -> str:
        if self.reply_buffer.size() <= self._queue_low_watermark:
            return "low_watermark"
        if self._will_queue_run_dry_within():
            return "run_dry"
        return "newer_frame"

    def _trigger_api_call_if_ready(self):
        if self._is_normal_mode():
            return
        source = self._if_ready_source()
        if self._has_visual_request_in_flight():
            self._log_api_schedule(decision="block", source=source, block_reason="in_flight")
            return
        block = self._api_schedule_block_reason(enforce_min_interval=True)
        if block:
            self._log_api_schedule(decision="block", source=source, block_reason=block)
            return
        if not self.engine.running or self._failure_backoff_paused:
            self._log_api_schedule(decision="block", source=source, block_reason="not_running")
            return
        if self._latest_screenshot is None:
            self._log_api_schedule(decision="block", source=source, block_reason="no_screenshot")
            return
        if not self._should_request_new_batch():
            if self._latest_screenshot_id <= self._latest_requested_screenshot_id:
                self._log_api_schedule(decision="block", source=source, block_reason="no_newer_frame")
                return
        self._trigger_api_call(source=source)

    def _schedule_next_screenshot(self, delay_ms: int):
        if self._screenshot_scheduled:
            return
        self._screenshot_scheduled = True
        QTimer.singleShot(delay_ms, self._do_scheduled_screenshot)

    def _do_scheduled_screenshot(self):
        self._screenshot_scheduled = False
        if self.engine.running:
            self._screenshot_loop()

    def _consume_request_timing(self, screenshot_id: int):
        started_at = self._request_started_at_by_id.pop(screenshot_id, None)
        if started_at is None:
            return
        rtt = time.monotonic() - started_at
        self._rtt_history.append(rtt)
        if len(self._rtt_history) > 20:
            self._rtt_history.pop(0)
        self.logger.debug(f"[DEBUG] RTT={rtt:.1f}s, avg={self._rtt_avg():.1f}s, screenshot_id={screenshot_id}")

    def _is_reply_stale(
        self,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        *,
        source: str = "ai",
    ) -> tuple[bool, str]:
        is_mic = source == "mic"
        # 普通模式与麦克风插入均不做 TTL 硬过期（避免队列积压时误丢回复）。
        if self._is_normal_mode() or is_mic:
            if self.config.get("drop_stale", "1") != "1":
                return False, ""
            return False, ""
        if scene_generation < getattr(self, "_scene_generation", 0):
            return True, "stale_scene"
        if screenshot_id < getattr(self, "_latest_screenshot_id", 0):
            return True, "superseded_by_newer_frame"
        if screenshot_id < getattr(self, "_latest_requested_screenshot_id", 0):
            return True, "superseded_by_newer_request"
        if screenshot_id < getattr(self, "_latest_queued_screenshot_id", 0):
            return True, "superseded_by_newer_reply"
        if self.config.get("drop_stale", "1") == "1":
            max_age = {
                "loose": 12.0,
                "medium": 8.0,
                "strict": 5.0,
            }.get(self.config.get("freshness", "medium"), 8.0)
            if captured_at > 0 and (time.monotonic() - captured_at) > max_age:
                return True, "stale_ttl"
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

    def _probe_scene_change(self, pixmap: QPixmap) -> None:
        if self._is_normal_mode():
            return
        scene_hash = fingerprint_from_pixmap(pixmap, probe_size=self._scene_probe_size())
        if self._last_scene_hash is None:
            self._last_scene_hash = scene_hash
            self._scene_debug_log(
                f"scene_probe hash=0x{scene_hash:016x} prev=None dist=0 changed=0 gen={self._scene_generation}"
            )
            return

        prev_hash = self._last_scene_hash
        dist = hamming_distance(prev_hash, scene_hash)
        changed = is_scene_change(prev_hash, scene_hash)
        if changed:
            now = time.monotonic()
            last_bump = getattr(self, "_scene_generation_bumped_at", 0.0)
            if (
                last_bump > 0
                and (now - last_bump) < SCENE_CHANGE_DEBOUNCE_SEC
                and dist < SCENE_CHANGE_FORCE_DIST
            ):
                self._last_scene_hash = scene_hash
                self._scene_debug_log(
                    f"scene_probe debounced dist={dist} gen={self._scene_generation} "
                    f"elapsed={now - last_bump:.2f}s"
                )
                return
            prev_gen = self._scene_generation
            self._scene_generation += 1
            self._scene_generation_bumped_at = now
            self._last_scene_hash = scene_hash
            self._scene_debug_log(
                f"scene_probe hash=0x{scene_hash:016x} prev=0x{prev_hash:016x} "
                f"dist={dist} changed=1 gen={prev_gen}->{self._scene_generation}"
            )
            self._on_scene_generation_advanced(prev_hash=prev_hash)
        else:
            self._last_scene_hash = scene_hash
            self._scene_debug_log(
                f"scene_probe hash=0x{scene_hash:016x} prev=0x{prev_hash:016x} "
                f"dist={dist} changed=0 gen={self._scene_generation}"
            )

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

    def _append_scene_memory_to_user_pt(self, user_pt: str) -> str:
        mode = self._memory_mode()
        if mode == MEMORY_MODE_OFF:
            return user_pt
        block = self._scene_memory.format_prompt_for_generation(self._scene_generation, mode)
        return append_memory_to_user_pt(user_pt, block)

    def _record_scene_memory_display(self, queued: QueuedReply) -> None:
        if not self._memory_enabled():
            return
        if not queued.memory_eligible or queued.is_fallback or queued.source != "ai":
            return
        scene_count, _ = reply_counts_from_config(self.config)
        angle = bullet_angle_from_index(queued.content_index, scene_count)
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

    def _on_scene_generation_advanced(self, prev_hash: int | None = None) -> None:
        if self._is_normal_mode():
            return
        gen = self._scene_generation
        batch_to_drop = self._current_batch.batch_id if self._current_batch else None
        before = self.reply_buffer.size()
        self.reply_buffer.drop_older_generations(gen)
        cleared = before - self.reply_buffer.size()

        mode = self._freshness_mode()
        if mode != "loose":
            self._scene_rhythm_pause_until = time.monotonic() + SCENE_RHYTHM_PAUSE_SEC
            self._scene_captures_after_change = 0
            self._scene_api_gate_active = True
            self._scene_gate_prev_hash = prev_hash
            if self._has_visual_request_in_flight():
                self._latest_screenshot_id += 1
            QTimer.singleShot(0, self._capture_screenshot)

        if mode == "strict":
            self.engine.clear_dedup_window()
            self.engine.drop_pending_below_generation(gen)
            on_screen_dropped = self.engine.drop_items_below_scene_generation(gen)
            self._scene_debug_log(
                f"scene_change strict_drop gen={gen} on_screen_dropped={on_screen_dropped}"
            )
            if self._should_clear_batch_on_scene_change() and batch_to_drop is not None:
                dropped = self.engine.drop_items_with_batch_id(batch_to_drop)
                self._scene_debug_log(
                    f"scene_change strict_clear batch_id={batch_to_drop} on_screen_dropped={dropped}"
                )
        elif mode == "medium":
            self.engine.clear_dedup_window()
            on_screen_dropped = self.engine.drop_pending_below_generation(gen)
            self._scene_debug_log(
                f"scene_change medium_pending_drop gen={gen} dropped={on_screen_dropped}"
            )
            if self._should_clear_batch_on_scene_change() and batch_to_drop is not None:
                dropped = self.engine.drop_items_with_batch_id(batch_to_drop)
                self._scene_debug_log(
                    f"scene_change medium_clear batch_id={batch_to_drop} on_screen_dropped={dropped}"
                )
        else:
            on_screen_dropped = 0

        self._current_batch = None
        self._scene_debug_log(
            f"scene_change gen={gen} buffer_cleared={cleared} buffer_remaining={self.reply_buffer.size()}"
        )
        if self._memory_enabled():
            persona = getattr(self, "_current_persona", None) or ""
            self._scene_memory.on_scene_change(
                gen,
                self.config.get("memory_clear_policy", "medium"),
                tone_hint=self._memory_tone_hint(persona),
                memory_window=memory_window_from_config(self.config),
                memory_mode=self._memory_mode(),
            )
        QTimer.singleShot(150, self._maybe_refill_after_scene_change)

    def _maybe_refill_after_scene_change(self) -> None:
        if self._is_normal_mode():
            return
        if not self.engine.running or self._failure_backoff_paused:
            return
        if self._has_visual_request_in_flight():
            return
        if self.reply_buffer.size() > 0 or self._visible_display_count() > 0:
            return
        block = self._scene_api_block_reason()
        if block:
            QTimer.singleShot(200, self._maybe_refill_after_scene_change)
            return
        persona = getattr(self, "_current_persona", None) or self.personae.pick_random()
        items = build_local_fallback_batch(
            self._reply_scene_count,
            self._reply_filler_count,
            config=self.config,
        )
        self._enqueue_reply_batch(
            persona,
            self.screenshot_round,
            self._latest_screenshot_id,
            self._latest_screenshot_time,
            self._scene_generation,
            items,
            from_local_fallback=True,
        )
        if not self.reply_timer.isActive():
            self._consume_reply_queue()

    def _queue_capacity(self) -> int:
        if self._is_normal_mode():
            return max(8, self._normal_reply_count() * 2)
        return self._queue_batch_size + self._queue_fallback_keep

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
        if not self.engine.danmu_pool_enabled():
            return 0
        deficit = self.engine.deficit_below_min()
        if deficit <= 0:
            return 0
        texts = sample_danmu(min(deficit, 8))
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

    def _estimated_inventory_ms(self) -> int:
        inventory_units = self.reply_buffer.size() + self._visible_display_count()
        if inventory_units <= 0:
            return 0
        return inventory_units * self._estimated_reply_gap_ms()

    def _will_queue_run_dry_within(self, threshold_ms: int | None = None) -> bool:
        threshold = self._queue_run_dry_window_ms if threshold_ms is None else threshold_ms
        return self._estimated_inventory_ms() <= threshold

    def _should_request_new_batch(self) -> bool:
        if not self.engine.running:
            return False
        if self._failure_backoff_paused:
            return False
        if self._has_visual_request_in_flight():
            return False
        if self.reply_buffer.size() <= self._queue_low_watermark:
            return True
        return self._will_queue_run_dry_within()

    def _next_inventory_trigger_delay_ms(self) -> int:
        if self.reply_buffer.is_empty() and self._visible_display_count() == 0:
            return 0
        if self.reply_buffer.size() <= 1:
            return 80
        if self._will_queue_run_dry_within(1000):
            return 120
        return 250

    def _capture_screenshot(self):
        if not self.engine.running:
            return
        if self._failure_backoff_paused:
            return
        pixmap = self.capturer.grab()
        if pixmap is None:
            if sys.platform == "darwin" and not self._capture_failure_hint_shown:
                self.logger.warning(tr("app.capture_failed_macos"))
                self._capture_failure_hint_shown = True
            else:
                self.logger.warning(tr("app.capture_failed"))
            return
        self._capture_failure_hint_shown = False
        self._latest_screenshot = pixmap
        self._latest_screenshot_time = time.monotonic()
        if not self._is_normal_mode():
            self._probe_scene_change(pixmap)
            if getattr(self, "_scene_api_gate_active", False):
                self._scene_captures_after_change = getattr(self, "_scene_captures_after_change", 0) + 1
        if self._has_visual_request_in_flight() and not self._is_normal_mode():
            self.logger.debug(
                tr("app.screenshot_updated").format(
                    screenshot_id=self._latest_screenshot_id,
                    scene_generation=self._scene_generation,
                    width=pixmap.width(),
                    height=pixmap.height(),
                )
                + " (buffer refresh, id held during in-flight request)"
            )
            return
        self._latest_screenshot_id += 1
        self.logger.debug(
            tr("app.screenshot_updated").format(
                screenshot_id=self._latest_screenshot_id,
                scene_generation=self._scene_generation,
                width=pixmap.width(),
                height=pixmap.height(),
            )
        )

    def _on_screenshot_timer(self):
        if self._is_normal_mode():
            self._on_normal_capture_tick()
        else:
            self._capture_screenshot()

    def _on_normal_capture_tick(self):
        if self._has_visual_request_in_flight():
            return
        self._capture_screenshot()
        if self._latest_screenshot is None:
            return
        self._trigger_api_call(source="normal_interval")

    def _check_rhythm_trigger(self):
        if self._is_normal_mode():
            return
        if not self.engine.running:
            return
        if self._failure_backoff_paused:
            return
        scene_block = self._scene_api_block_reason()
        if scene_block:
            self._log_api_schedule(decision="block", source="rhythm", block_reason=scene_block)
            return
        self._maybe_emit_local_fallback()
        if self._has_visual_request_in_flight():
            self._log_api_schedule(decision="block", source="rhythm", block_reason="in_flight")
            return

        batch = self._current_batch
        if batch is None:
            self._trigger_api_call(source="cold_start")
            return

        if batch.next_generation_triggered:
            return

        preload_offset = self._rtt_avg()
        trigger_time = batch.next_generation_time - preload_offset

        if time.monotonic() >= trigger_time:
            batch.next_generation_triggered = True
            self._trigger_api_call(source="rhythm")

    def _trigger_api_call(self, source: str = "unknown"):
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

        self._last_api_trigger_at = time.monotonic()
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
        self._local_fallback_active = False
        self._local_fallback_for_batch = 0
        self._publish_live_status()

        persona = self.personae.pick_random()
        system_pt, user_pt = self.personae.get_prompt(persona)

        self.logger.info(
            tr("app.api_triggered").format(
                batch_id=batch_id,
                screenshot_id=screenshot_id,
                scene_generation=self._scene_generation,
                persona=persona_display_name(persona),
            )
        )

        now = datetime.now().strftime("%H:%M:%S")
        user_pt = user_pt.replace("{current_time}", now)
        user_pt = user_pt.replace("{round}", str(self.screenshot_round))
        user_pt = self._append_scene_memory_to_user_pt(user_pt)

        self._current_persona = persona
        self._request_started_at_by_id[screenshot_id] = time.monotonic()
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

    def _screenshot_loop_legacy(self):
        pass

    def _on_ai_reply_legacy(self, text: str, persona_id: str, request_round: int, screenshot_id: int, captured_at: float, scene_generation: int):
        pass

    def _maybe_schedule_screenshot_legacy(self):
        pass

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

    def _can_prefetch_with_buffer(self) -> bool:
        if self.reply_buffer.is_empty():
            return True
        if self.config.get("capture_mode", "continuous") == "smart":
            return False
        min_n = self._min_density_target()
        right_target = self._density_right_target(min_n)
        if hasattr(self.engine, "visibility_counts"):
            visible_total, right_count = self.engine.visibility_counts()
        else:
            visible_total = self._visible_display_count()
            right_count = self._right_visible_count()
        if visible_total == 0:
            return True
        if min_n > 0 and visible_total < min_n:
            return True
        if self.reply_buffer.size() > self._reply_low_watermark():
            return False
        return right_count < right_target

    def _consume_reply_queue_legacy(self):
        pass

    def _screenshot_loop(self):
        self._capture_screenshot()

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
        request_id = self._reply_request_id(request_round, screenshot_id, scene_generation)
        if from_mic_insert:
            self._mic_batch_id += 1
            batch_id = self._mic_batch_id
        else:
            batch_id = self._batch_id
        if not from_local_fallback and not from_mic_insert and not self._is_normal_mode():
            removed = self.reply_buffer.drop_replaceable_fallbacks(
                request_id=request_id,
                batch_id=batch_id,
                scene_generation=scene_generation,
            )
            if removed:
                self.logger.info(f"已替换轻量弹幕: count={removed}, request_id={request_id}, batch_id={batch_id}")
            batch = BatchTracker(batch_id)
            batch.next_generation_time = time.monotonic() + self._default_batch_interval()
            self._current_batch = batch

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
        elif self._is_normal_mode():
            self.reply_buffer.extend(batch_items)
        else:
            self.reply_buffer.prepend_batch(
                batch_items,
                preserve_existing=self._queue_fallback_keep,
                preserve_scene_generation=scene_generation,
                preserve_replaceable=from_local_fallback,
            )

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

    def _maybe_emit_local_fallback(self):
        if self._is_normal_mode():
            return
        if not self._has_visual_request_in_flight():
            if self._local_fallback_active:
                self._local_fallback_active = False
            return
        if self._local_fallback_for_batch == self._batch_id:
            return
        elapsed = (
            max(0.0, time.monotonic() - self._inflight_started_at)
            if self._inflight_started_at > 0
            else 0.0
        )
        if not is_model_slow(self._rtt_history, elapsed, in_flight=True):
            return
        if self.reply_buffer.size() > self._queue_low_watermark:
            return
        if not self._will_queue_run_dry_within(2000) and self.reply_buffer.size() > 0:
            return

        persona = getattr(self, "_current_persona", None) or self.personae.pick_random()
        screenshot_id = self._inflight_screenshot_id or self._latest_screenshot_id
        captured_at = self._latest_screenshot_time
        items = build_local_fallback_batch(
            self._reply_scene_count,
            self._reply_filler_count,
            config=self.config,
        )
        self._local_fallback_for_batch = self._batch_id
        self._local_fallback_active = True
        self._enqueue_reply_batch(
            persona,
            self.screenshot_round,
            screenshot_id,
            captured_at,
            self._scene_generation,
            items,
            from_local_fallback=True,
        )
        self.logger.info(tr("app.local_fallback_enabled"))
        self._publish_live_status()
        if not self.reply_timer.isActive():
            self._consume_reply_queue()

    def _on_ai_reply(self, text: str, persona_id: str, request_round: int, screenshot_id: int, captured_at: float, scene_generation: int, input_tokens: int = 0, output_tokens: int = 0):
        self.logger.debug(f"[DEBUG] _on_ai_reply called, text length={len(text)}")
        meta = self._pop_request_meta(request_round, screenshot_id, scene_generation)
        source = meta.get("source", "visual")
        is_mic = source == "mic"

        if (
            not self._is_normal_mode()
            and scene_generation < self._scene_generation
        ):
            self._log_reply_drop("stale_scene_in_flight", screenshot_id, request_round, scene_generation)
            self._release_inflight_for_source(source)
            if not is_mic:
                self._consume_request_timing(screenshot_id)
                self._current_batch = None
                self._trigger_api_call_if_ready()
            return

        self._release_inflight_for_source(source)

        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self.lifetime_stats.add_tokens(input_tokens, output_tokens)
        if input_tokens > 0 or output_tokens > 0:
            self.logger.debug(f"[DEBUG] Tokens: input={input_tokens}, output={output_tokens}, total_input={self._total_input_tokens}, total_output={self._total_output_tokens}")

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

        self._consume_request_timing(screenshot_id)

        is_stale, stale_reason = self._is_reply_stale(screenshot_id, captured_at, scene_generation, source="ai")
        if is_stale:
            self._log_reply_drop(stale_reason, screenshot_id, request_round, scene_generation)
            self._current_batch = None
            self._trigger_api_call_if_ready()
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
            self._trigger_api_call_if_ready()
            return

        if self._memory_enabled():
            if memory_update is not None:
                if memory_update.scene_generation <= 0:
                    memory_update.scene_generation = scene_generation
                self._scene_memory.update_from_visual_result(memory_update)
            else:
                inferred = infer_visual_update_from_batch(
                    normalized_items,
                    self._reply_scene_count,
                    scene_generation,
                )
                if inferred is not None:
                    self._scene_memory.update_from_visual_result(inferred)

        self._enqueue_reply_batch(
            persona_id,
            request_round,
            screenshot_id,
            captured_at,
            scene_generation,
            normalized_items,
            from_local_fallback=False,
        )
        self._local_fallback_active = False
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

    def _maybe_schedule_screenshot(self):
        """DEPRECATED (rhythm mode): inventory-driven screenshot prefetch removed.
        API pacing uses _rhythm_check_timer + _trigger_api_call_if_ready."""
        pass

    def _consume_reply_queue(self):
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
            else:
                self._trigger_api_call_if_ready()
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

    def _maybe_adjust_timer(self):
        """UNUSED in rhythm mode: no callers; screenshot_timer interval set in start()."""
        freq_mode = self.config.get("freq_mode", "auto")
        if freq_mode != "auto":
            return

        min_n = self._min_density_target()
        if min_n <= 0:
            return

        if hasattr(self.engine, "visibility_counts"):
            current, right_count = self.engine.visibility_counts()
        else:
            current = self._visible_display_count()
            right_count = self._right_visible_count()
        right_target = self._density_right_target(min_n)
        base_interval = self.config.get_int("screenshot_interval", 3)

        if current == 0:
            accelerated = max(1, base_interval // 2)
            self.screenshot_timer.setInterval(accelerated * 1000)
        elif current >= min_n and right_count >= right_target:
            relaxed = base_interval * 2
            self.screenshot_timer.setInterval(relaxed * 1000)
        else:
            self.screenshot_timer.setInterval(base_interval * 1000)

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
        if not self._rtt_history:
            return 0.0
        return sum(self._rtt_history) / len(self._rtt_history)

    def _smart_cooldown_ms(self) -> int:
        if len(self._rtt_history) >= 3:
            sorted_rtt = sorted(self._rtt_history)
            idx = int(len(sorted_rtt) * 0.9)
            p90 = sorted_rtt[min(idx, len(sorted_rtt) - 1)]
            return max(1500, min(int(p90 * 0.9 * 1000), 30000))
        base = self.config.get_int("screenshot_interval", 3)
        return max(2000, base * 1000)

    def _on_ai_error(self, msg: str, persona_id: str, request_round: int, screenshot_id: int, captured_at: float, scene_generation: int, input_tokens: int = 0, output_tokens: int = 0):
        meta = self._pop_request_meta(request_round, screenshot_id, scene_generation)
        source = meta.get("source", "visual")
        is_mic = source == "mic"

        if (
            not self._is_normal_mode()
            and scene_generation < self._scene_generation
        ):
            self._log_reply_drop("stale_scene_in_flight", screenshot_id, request_round, scene_generation)
            self._release_inflight_for_source(source)
            if not is_mic:
                self._local_fallback_active = False
                self._consume_request_timing(screenshot_id)
                self._current_batch = None
                self._publish_live_status()
                self._trigger_api_call_if_ready()
            return

        self._release_inflight_for_source(source)
        self._publish_live_status()

        if is_mic:
            self.logger.warning(
                f"mic insert api error: {msg} "
                f"[persona={persona_id}, round={request_round}, screenshot_id={screenshot_id}]"
            )
            return

        self._local_fallback_active = False
        self._consume_request_timing(screenshot_id)
        self.logger.error(f"{msg} [persona={persona_id}, round={request_round}, screenshot_id={screenshot_id}, scene_generation={scene_generation}]")

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
            self._screenshot_scheduled = False
            return

        if self._consecutive_failures >= self.MAX_CONSECUTIVE_FAILURES:
            self.logger.warning(
                tr("app.failure_paused").format(count=self._consecutive_failures, message=msg)
            )
            self._failure_backoff_paused = True
            self.screenshot_timer.stop()
            self._screenshot_scheduled = False
            self._set_error_status_safe(
                tr("app.failure_paused").format(count=self.MAX_CONSECUTIVE_FAILURES, message=msg),
                is_error=True
            )
            return

        self._trigger_api_call_if_ready()

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
            self.danmu_count += 1
            self.lifetime_stats.add_danmu(1)
        self._maybe_log_dedup_profile()

    def start(self):
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
        self.danmu_count = 0
        self._total_input_tokens = 0
        self._total_output_tokens = 0
        self._start_time = time.monotonic()
        self.session_run_log.begin(
            started_at=time.time(),
            model=resolve_active_model_id(self.config),
        )
        self._consecutive_failures = 0
        self._failure_backoff_paused = False
        self._last_error_message = ""
        self._request_started_at_by_id = {}
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
        self._local_fallback_active = False
        self._local_fallback_for_batch = 0
        self._inflight_started_at = 0.0
        self._inflight_screenshot_id = 0
        self._scene_rhythm_pause_until = 0.0
        self._scene_captures_after_change = 0
        self._scene_api_gate_active = False
        self._scene_gate_prev_hash = None
        self._scene_generation_bumped_at = 0.0
        self._last_api_trigger_at = 0.0
        self._mic_request_seq = 0
        self._mic_batch_id = 0
        self._pending_request_meta.clear()
        self._scene_memory.reset()
        self.reply_buffer.set_max_items(self._queue_capacity())
        self.screenshot_timer.stop()
        if self._is_normal_mode():
            self.screenshot_timer.setInterval(self._normal_recognition_interval_ms())
            self.screenshot_timer.start()
            self._live_status_timer.start()
            self._lifetime_flush_timer.start()
            self._on_normal_capture_tick()
            self.STAGGER_INTERVAL = 1.0
            self.logger.debug(
                f"[DEBUG] Normal mode: screenshot={self._normal_recognition_interval_ms()}ms"
            )
        else:
            self.screenshot_timer.setInterval(1000)
            self.screenshot_timer.start()
            self._live_status_timer.start()
            self._lifetime_flush_timer.start()
            self._capture_screenshot()
            self._rhythm_check_timer.start(200)
            self.STAGGER_INTERVAL = 1.0
            self.logger.debug("[DEBUG] Rhythm mode: screenshot=1s, rhythm_check=200ms")
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
        if self._start_time > 0:
            self.lifetime_stats.flush_runtime(time.monotonic() - self._start_time)
            self._start_time = 0.0

    def stop(self):
        self.session_run_log.complete(
            ended_at=time.time(),
            input_tokens=self._total_input_tokens,
            output_tokens=self._total_output_tokens,
            danmu_count=self.danmu_count,
        )
        self._lifetime_flush_timer.stop()
        self.lifetime_stats.flush_pending()
        self._flush_session_runtime_to_lifetime()
        self.screenshot_timer.stop()
        self._rhythm_check_timer.stop()
        self._live_status_timer.stop()
        self._pending = False
        self._screenshot_scheduled = False
        self.ai_worker.mark_stopping()
        self.ai_in_flight = 0
        self.mic_in_flight = 0
        self._pending_request_meta.clear()
        self._stop_mic_utterance_detector()
        self._is_generating = False
        self._inflight_started_at = 0.0
        self._inflight_screenshot_id = 0
        self._local_fallback_active = False
        self._current_batch = None
        self.reply_timer.stop()
        self._pool_topup_timer.stop()
        self.reply_buffer.clear()
        self._request_started_at_by_id.clear()
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
        """统一退出流程：释放所有资源"""
        self.logger.info(tr("app.quitting"))

        # 1. 停止弹幕引擎和截图
        self.stop()

        # 2. 卸载快捷键
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

        server = getattr(self, "web_server", None)
        if server:
            server.stop()

        self.logger.info(tr("app.quit_done"))
        QApplication.quit()


def global_exception_hook(exc_type, exc_value, exc_tb):
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
    """webview = pywebview 桌面窗；browser = 系统浏览器。"""
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
    app.setApplicationName("DanmuAI")
    app.setOrganizationName("DanmuAI")
    app.setQuitOnLastWindowClosed(False)

    launch_mode = _web_launch_mode_from_argv()
    _danmu = DanmuApp(web_launch_mode=launch_mode)
    return sys.exit(app.exec())


if __name__ == "__main__":
    main()
