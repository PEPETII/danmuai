"""DanmuAI 应用入口与单例状态机（DanmuApp）。

职责边界（bootstrap / lifecycle / façade）：
- 截图定时、视觉/麦克风双轨 AI 调度、回复队列消费、场景代际淘汰、失败退避
- 与 DanmuOverlay / DanmuEngine 协同上屏；Web 控制台经 bridge 信号回主线程改配置
- 运行态对外展示委托 StatusSnapshotBuilder / DiagnosticSnapshotBuilder，勿在 Web 层拼私有字段

主链路（普通模式，详见 docs/MAIN_PIPELINE.md）：
  screenshot_timer → _on_normal_capture_tick → _schedule_capture → CaptureRunnable
  → _on_capture_completed → _trigger_api_call → AiRunnable → _on_ai_reply → ...

关键设计：
- screenshot_id：每帧截图递增，用于「更新帧优于在途回复」的 supersede 判定
- scene_generation：场景配置指纹版本（live_topic/user_nickname/screen_index/region_* 变更递增；start/stop 重置；截图不推进）
- MAX_IN_FLIGHT=1：并发视觉请求会破坏过期判断与回复顺序，故硬限制为 1

线程：DanmuApp 在 Qt 主线程；CaptureRunnable 在 capture_worker_pool 抓屏；
AiRunnable 在 ai_worker_pool 中调 AiWorker，finished 信号队列回主线程。

Phase 4 冻结（勿迁移出本模块）：ai_in_flight、reply_buffer、QTimer/QThreadPool、_latest_screenshot 等，
见 docs/archive/architecture-phases/phase4-freeze.md。

入口：python main.py → main()。
"""
import multiprocessing
import sys
import time
from datetime import datetime

from app.api_schedule import pixels_per_second, time_to_anchor_boundary
from app.application.config_service import ConfigService
from app.application.status_snapshot import StatusSnapshotBuilder
from app.danmu_engine import (
    resolve_danmu_display_text,
)
from app.danmu_engine_dedup import get_last_duplicate_observation
from app.live_freshness import (
    build_local_fallback_batch,
    is_model_slow,
)
from app.main_display_mixin import DanmuAppDisplayMixin
from app.main_helpers import (
    MAX_IN_FLIGHT,
    VISUAL_INFLIGHT_RECOVER_SEC,
    VISUAL_INFLIGHT_WARN_SEC,
    BatchTracker,  # noqa: F401 — re-exported for tests
)
from app.main_launch import (
    DEPRECATED_LAUNCH_MSG,
    check_deprecated_launch_args,
    global_exception_hook,
    show_startup_notice_if_needed,  # noqa: F401 — re-exported for tests
    web_launch_mode_from_argv,
)
from app.main_launch_mixin import DanmuAppLaunchMixin
from app.main_lifecycle_mixin import DanmuAppLifecycleMixin
from app.main_meme_mixin import DanmuAppMemeMixin
from app.main_mic_mixin import MIC_POLL_MS, MIC_POLL_PHASE_MS, DanmuAppMicMixin  # noqa: F401
from app.main_request_context_mixin import (
    DanmuAppRequestContextMixin,
    format_reply_request_id,
)
from app.main_state_mixin import DanmuAppStateMixin
from app.main_web_facade_mixin import DanmuAppWebFacadeMixin
from app.model_providers import (
    mic_audio_supported_for_mic_config,  # noqa: F401
    resolve_active_model_id,  # noqa: F401 — re-exported for tests
)
from app.personae import (
    append_live_topic_to_system_pt,
    append_nickname_to_system_pt,
    persona_display_name,
    persona_display_name_with_config,
)
from app.reply_parser import (
    normalize_reply_batch,
    parse_ai_reply_payload,
)
from app.screenshot_compress import (
    IMAGE_JPEG_QUALITY,
    IMAGE_MAX_WIDTH,
    compress_screenshot,
)
from app.snipper import resolve_screen_index  # noqa: F401
from app.translations import tr
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtCore import QTimer as QTimer  # noqa: F401 — re-exported for tests
from PyQt6.QtWidgets import QApplication

_MIC_PROBE_WAIT_TIMEOUT_SEC = 120.0
_WEBVIEW_ATTACH_MAX_ATTEMPTS = 2
_WEBVIEW_ATTACH_RETRY_MS = 1200

class DanmuApp(
    DanmuAppLaunchMixin,
    DanmuAppWebFacadeMixin,
    DanmuAppStateMixin,
    DanmuAppMicMixin,
    DanmuAppDisplayMixin,
    DanmuAppRequestContextMixin,
    DanmuAppMemeMixin,
    DanmuAppLifecycleMixin,
    QObject,
):
    """单例应用状态机：bootstrap、生命周期与 Web 公开 façade 的持有者。

    普通模式（当前产品路径）：按 normal_recognition_interval_sec 截图，成功后立即 _trigger_api_call；
    不做截图 hash 场景判定；慢模型下允许轻微滞后，优先弹幕连续。
    麦克风轨：与视觉 ai_in_flight 独立，request_round 为负数以区分 _pending_request_meta。

    配置中遗留的 danmu_display_mode=realtime 会在加载时规范为 normal。

    下列对象/字段禁止在未更新架构文档前迁出本类：reply_buffer、QPixmap 截图缓存、
    QTimer、QThreadPool、_mic_service（见 docs/final-architecture-baseline.md）。
    """

    state_changed = pyqtSignal(bool)  # running / paused
    config_changed = pyqtSignal()

    def build_status_snapshot(self) -> dict[str, object]:
        return StatusSnapshotBuilder(self).build()

    def apply_web_config_payload(self, payload: dict[str, object]) -> None:
        ConfigService(self).apply_web_payload(payload)

    def __init__(self, web_launch_mode: str = "webview"):
        """初始化 DanmuApp 状态机与全部子系统。

        线程归属：主线程（Qt GUI 线程）。
        初始化顺序：Web 桥接 → 核心子系统(config/engine/overlay/tray) → 视觉 AI 请求管线
        → 回复 FIFO → 场景代际链 → 麦克风双轨 → 启动 Web 控制台。
        任何新增的 QTimer / QThreadPool / signal 须同步 docs/main-pipeline-sequence.md。
        """
        super().__init__()
        from app.startup_trace import log_startup

        log_startup("danmu_app.init.begin")
        init_started = time.perf_counter()
        self._init_runtime_bridge_state(web_launch_mode)
        self._init_core_subsystems(log_startup)
        self._init_request_pipeline_state()
        self._init_runtime_tracking_state()
        self._init_startup_services(log_startup)
        self._start_web_console_stack(log_startup)
        self._sync_reply_batch_config()
        log_startup(
            "danmu_app.init.end",
            ms=(time.perf_counter() - init_started) * 1000.0,
            startup_ok=bool(self.web_server and self.web_server.startup_ok),
        )

    def _has_visual_request_in_flight(self) -> bool:
        return self._is_generating or self.ai_in_flight >= MAX_IN_FLIGHT

    def _maybe_pool_topup(self) -> int:
        from app.danmu_pool import plan_pool_topup

        limit, texts = plan_pool_topup(self.engine, self.config)
        if limit <= 0 or not texts:
            return 0
        scene_generation = int(getattr(self, "_scene_generation", 0))
        added = 0
        for text in texts:
            if added >= limit:
                break
            item = self.engine.add_text(
                text,
                persona="",
                batch_id=0,
                scene_generation=scene_generation,
                skip_dedup=True,
            )
            if item:
                self._broadcast_live_overlay_item(item, item.content, source="pool_topup")
                added += 1
        return added

    def _maybe_duplicate_loss_topup(
        self,
        queued,
        stats: dict[str, int | str],
    ) -> int:
        if int(stats.get("duplicate_topup_triggered", 0)) > 0:
            return 0
        from app.danmu_pool import plan_duplicate_loss_topup

        texts = plan_duplicate_loss_topup(
            self.engine,
            self.config,
            duplicate_loss_total=int(stats.get("duplicate_loss_total", 0)),
        )
        if not texts:
            return 0
        scene_generation = int(getattr(queued, "scene_generation", 0))
        added = 0
        for text in texts:
            item = self.engine.add_text(
                text,
                persona="",
                batch_id=0,
                scene_generation=scene_generation,
                skip_dedup=True,
            )
            if item:
                self._broadcast_live_overlay_item(
                    item,
                    item.content,
                    source="pool_duplicate_topup",
                )
                added += 1
        if added > 0:
            stats["duplicate_topup_triggered"] = 1
        return added

    def _record_undisplayed(self, reason: str, *, persona_id: str = "") -> None:
        """安全记录未上屏事件（兼容 minimal DanmuApp 测试模式）。"""
        recorder = self.__dict__.get("_danmu_diagnostics")
        if recorder is not None:
            recorder.record(reason, persona_id=persona_id)

    def _maybe_inject_local_fallback(self) -> None:
        """慢模型 in-flight 时注入公式化弹幕库轻量批次，避免长时间空窗。"""
        if not self.engine.running or self._local_fallback_active:
            return
        if not self._has_visual_request_in_flight():
            return
        inflight_elapsed = 0.0
        if self._inflight_started_at > 0:
            inflight_elapsed = time.monotonic() - self._inflight_started_at
        if not is_model_slow(
            self._get_request_timing_service().rtt_history,
            inflight_elapsed,
            in_flight=True,
        ):
            return
        normalized_items = build_local_fallback_batch(config=self.config)
        if not normalized_items:
            return
        captured_at = self._latest_screenshot_time or time.monotonic()
        self._enqueue_reply_batch(
            "本地兜底",
            self.screenshot_round,
            self._inflight_screenshot_id,
            captured_at,
            self._inflight_scene_generation,
            normalized_items,
            from_local_fallback=True,
        )
        self._local_fallback_active = True
        if not self.reply_timer.isActive():
            self._consume_reply_queue()
        elif not self.reply_buffer.is_empty():
            self.reply_timer.setInterval(min(self.reply_timer.interval(), 200))
        self._publish_live_status()

    def _apply_capture_result(self, pixmap):
        """主线程：校验 worker 回传的 pixmap，更新 _latest_screenshot*。

        无效帧（None / isNull / 零尺寸）仅记 warning，不递增 screenshot_id。
        """
        if pixmap is None:
            self.logger.warning(tr("app.capture_failed"))
            self._note_capture_failure()
            self._record_undisplayed("capture_failure")
            return
        if pixmap.isNull() or pixmap.width() <= 0 or pixmap.height() <= 0:
            screen_index = self.config.get_int("screen_index", 0)
            region_x = self.config.get_int("region_x", 0)
            region_y = self.config.get_int("region_y", 0)
            region_w = self.config.get_int("region_w", 0)
            region_h = self.config.get_int("region_h", 0)
            self.logger.warning(
                "截图无效: is_null=%s width=%s height=%s screen_index=%s "
                "region_x=%s region_y=%s region_w=%s region_h=%s reason=null_pixmap",
                pixmap.isNull(),
                pixmap.width(),
                pixmap.height(),
                screen_index,
                region_x,
                region_y,
                region_w,
                region_h,
            )
            self._note_capture_failure()
            self._record_undisplayed("capture_failure")
            return
        self._note_capture_success()
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

    def _capture_screenshot(self):
        """同步截图（测试/脚本用）；生产主链路经 _schedule_capture 走 worker。"""
        if not self.engine.running:
            return
        if self._failure_backoff_paused:
            return
        self._apply_capture_result(self.capturer.grab())

    def _schedule_capture(self) -> None:
        """主线程：构建 CapturePlan 并投递 capture_worker_pool。"""
        if not self.engine.running:
            return
        if self._failure_backoff_paused:
            return
        if self._capture_in_flight:
            self.logger.debug("跳过截图调度: reason=capture_in_flight")
            return
        plan = self.capturer.build_plan()
        if plan is None:
            self.logger.warning(tr("app.capture_failed"))
            self._note_capture_failure()
            return
        self._capture_in_flight = True
        from app.runnable import CaptureRunnable
        from app.worker_pools import capture_worker_pool

        runnable = CaptureRunnable(
            plan,
            self._capture_coordinator,
            self.ai_worker._stopping,
        )
        capture_worker_pool().start(runnable)

    def _on_capture_completed(self, pixmap) -> None:
        """CaptureCoordinator.completed 主线程槽：应用截图结果并触发 API。"""
        self._capture_in_flight = False
        if not self.engine.running or self.ai_worker._stopping.is_set():
            return
        if self._failure_backoff_paused:
            return
        self._apply_capture_result(pixmap)
        if self._latest_screenshot is None:
            return
        source = self._pending_api_trigger_source or "normal_interval"
        self._pending_api_trigger_source = None
        self._trigger_api_call(
            source=source,
            enforce_min_interval=(source != "scene_refresh"),
        )
        if self._scene_refresh_wanted and not self._has_visual_request_in_flight():
            self._try_scene_refresh()

    def _on_screenshot_timer(self):
        """screenshot_timer 超时回调（主线程 QTimer）；转发到 _on_normal_capture_tick。"""
        self._on_normal_capture_tick()

    def _on_normal_capture_tick(self):
        """普通模式主链路入口（主线程）：检查 ai_in_flight 闸门 → 异步截图 → 完成时触发 API。

        调用线程：主线程（screenshot_timer.timeout 信号）。
        关键副作用：成功路径在 capture worker 回传后调用 _trigger_api_call（不等待 reply_timer）。
        """
        # 普通模式主链路：无视觉 in-flight 才截图；成功则 capture 完成后触发 API（不等待 reply_timer）
        if self._has_visual_request_in_flight():
            elapsed_ms = 0
            if self._inflight_started_at > 0:
                elapsed_ms = int((time.monotonic() - self._inflight_started_at) * 1000)
            warn_ms = int(VISUAL_INFLIGHT_WARN_SEC * 1000)  # 45s，模块常量（main_helpers），非 DanmuApp 字段
            recover_ms = int(VISUAL_INFLIGHT_RECOVER_SEC * 1000)
            if elapsed_ms >= recover_ms:
                if self._try_recover_stale_visual_inflight():
                    return
            elif elapsed_ms >= warn_ms:
                self.logger.warning(
                    "视觉请求 in-flight 超时: screenshot_id=%s elapsed_ms=%s ai_in_flight=%s "
                    "reason=inflight_watchdog_warn",
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
            self._maybe_inject_local_fallback()
            return
        self._schedule_capture()

    def _borrow_latest_screenshot_for_request(self) -> tuple[object, int, float]:
        """Return borrowed screenshot ref and metadata for AiRunnable handoff.

        Caller must only invoke on the fire path after guards pass. Production
        visual in-flight gate prevents _latest_screenshot replacement while
        AiRunnable retains the borrowed reference.
        """
        return (
            self._latest_screenshot,
            self._latest_screenshot_id,
            self._latest_screenshot_time,
        )

    def _trigger_api_call(self, source: str = "unknown", *, enforce_min_interval: bool = True):
        """占用唯一视觉 in-flight 槽位，用当前 _latest_screenshot 发起 AiRunnable。

        调用线程：主线程（由 _on_normal_capture_tick 或 local fallback 调用）。
        关键副作用：
        - 注册 _pending_request_meta（复合键 {request_round}:{screenshot_id}:{scene_generation}）
        - RequestTimingService.mark_started（RTT 跟踪）
        - QThreadPool.start(AiRunnable)（AI 请求在 QThreadPool 执行）
        - 递增 screenshot_round / _batch_id，登记 _inflight_* 供回复到达时做过期判断
        - 成功触发后清除 local_fallback 标记，避免与真 AI 回复重复占位
        """
        block = self._api_schedule_block_reason(enforce_min_interval=enforce_min_interval)
        if block:
            self._log_api_schedule(decision="block", source=source, block_reason=block)
            if block == "in_flight":
                self.logger.debug(tr("app.skip_api_generating"))
            return
        if self.ai_in_flight >= MAX_IN_FLIGHT:
            self._log_api_schedule(decision="block", source=source, block_reason="in_flight")
            self.logger.debug(tr("app.skip_api_generating"))
            return
        if self._latest_screenshot is None:
            self._log_api_schedule(decision="block", source=source, block_reason="no_screenshot")
            self.logger.debug(tr("app.skip_api_no_screenshot"))
            return

        trigger_at = time.monotonic()
        self._local_fallback_active = False
        self._get_request_scheduler().record_trigger_time(now=trigger_at)
        self._log_api_schedule(decision="fire", source=source)
        self._scene_refresh_wanted = False
        pixmap, screenshot_id, captured_at = self._borrow_latest_screenshot_for_request()
        self.screenshot_round += 1
        request_round = self.screenshot_round
        self._batch_id += 1
        batch_id = self._batch_id
        self._latest_requested_screenshot_id = screenshot_id
        self._acquire_visual_inflight(screenshot_id, self._scene_generation)
        self._publish_live_status()

        persona = self.personae.pick_random()
        system_pt, user_pt = self.personae.get_prompt(persona)
        if not (system_pt or "").strip():
            self.logger.warning(
                "skip api: reason=empty_persona_prompt persona=%s screenshot_id=%s",
                persona,
                screenshot_id,
            )
            self._release_inflight_for_source("visual")
            self._publish_live_status()
            return
        system_pt = append_nickname_to_system_pt(system_pt, self.config)  # W-NICKNAME-001
        system_pt = append_live_topic_to_system_pt(system_pt, self.config)  # W-LIVE-TOPIC-001

        request_id = self._reply_request_id(request_round, screenshot_id, self._scene_generation)
        self.logger.info(
            tr("app.api_triggered").format(
                batch_id=batch_id,
                screenshot_id=screenshot_id,
                scene_generation=self._scene_generation,
                persona=persona_display_name_with_config(persona, self.config),
            )
            + f" request_round={request_round} request_id={request_id}"
        )

        now = datetime.now().strftime("%H:%M:%S")
        user_pt = user_pt.replace("{current_time}", now)
        user_pt = user_pt.replace("{round}", str(self.screenshot_round))

        # PET-006：调度已通过且 record_trigger_time 完成，才消费桌宠待注入指令
        pet_svc = self.__dict__.get("pet_command_service")
        if pet_svc is not None:
            from app.pet.pet_prompt import (
                append_pet_command_to_system_pt,
                build_pet_command_user_pt,
            )

            command_text = pet_svc.consume_for_prompt()
            if command_text:
                user_pt = build_pet_command_user_pt(user_pt, command_text)
                system_pt = append_pet_command_to_system_pt(system_pt, command_text)

        self._current_persona = persona
        request_started_at = self._get_request_timing_service().mark_started(
            request_id=request_id,
            now=time.monotonic(),
        )
        self._log_reply_pipeline(
            "request_started",
            request_id=format_reply_request_id(request_round, screenshot_id, self._scene_generation),
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            request_started_at=request_started_at,
            scene_generation=self._scene_generation,
            dropped_as_stale=False,
            enqueued=False,
            displayed=False,
        )
        self._register_request_meta(request_round, screenshot_id, self._scene_generation, "visual")

        from app.runnable import AiRunnable
        from app.worker_pools import ai_worker_pool

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
        ai_worker_pool().start(runnable)

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

    def _on_ai_reply(self, text: str, persona_id: str, request_round: int, screenshot_id: int, captured_at: float, scene_generation: int, input_tokens: int = 0, output_tokens: int = 0):
        """AiWorker.finished 主线程入口：释放在途 → 解析入队 → 驱动 _consume_reply_queue。

        调用线程：主线程（ai_worker.finished signal 回调）。
        关键副作用：
        - 释放 ai_in_flight / mic_in_flight 槽位
        - 统计 token 消耗
        - 视觉回复：解析 JSON → normalize → _enqueue_reply_batch
        - 麦克风回复：走 _handle_mic_ai_reply 独立路径
        """
        self.logger.debug(f"[DEBUG] _on_ai_reply called, text length={len(text)}")
        reply_received_at = time.monotonic()
        meta = self._pop_request_meta(request_round, screenshot_id, scene_generation)
        # W-RACE-001（bug-03 缺陷 3 修复）：陈旧 AiRunnable 在 stop()→start() 之间
        # 完成时，_pending_request_meta 已被 stop() 清空，_pop_request_meta 返回
        # 空 dict（既有 request_meta_missing warning 仍保留作可观测性）。本判断作为
        # 第二道防线：若 meta 为空（stop 后到位的 reply），既不释放新会话的 in-flight
        # 槽位，也不入队。
        if not meta:
            self._log_reply_pipeline(
                "reply_received",
                request_id=format_reply_request_id(request_round, screenshot_id, scene_generation),
                request_round=request_round,
                screenshot_id=screenshot_id,
                captured_at=captured_at,
                request_started_at=self._peek_request_started_at(
                    request_round, screenshot_id, scene_generation
                ),
                reply_received_at=reply_received_at,
                scene_generation=scene_generation,
                dropped_as_stale=True,
                enqueued=False,
                displayed=False,
            )
            self.logger.warning(
                "stale_reply_dropped: request_round=%s screenshot_id=%s "
                "scene_generation=%s reason=meta_missing_after_stop",
                request_round,
                screenshot_id,
                scene_generation,
            )
            return
        source = meta.get("source") or "visual"
        is_mic = source == "mic"

        if not is_mic:
            stale_reason = self._visual_reply_stale_reason(scene_generation)
            if stale_reason:
                self._release_inflight_for_source(source)
                self._consume_request_timing(request_round, screenshot_id, scene_generation)
                self._log_reply_pipeline(
                    "reply_received",
                    request_id=format_reply_request_id(
                        request_round, screenshot_id, scene_generation
                    ),
                    request_round=request_round,
                    screenshot_id=screenshot_id,
                    captured_at=captured_at,
                    request_started_at=self._peek_request_started_at(
                        request_round, screenshot_id, scene_generation
                    ),
                    reply_received_at=reply_received_at,
                    scene_generation=scene_generation,
                    current_scene_generation=self._scene_generation,
                    dropped_as_stale=True,
                    enqueued=False,
                    displayed=False,
                )
                self.logger.warning(
                    "stale_reply_dropped: request_round=%s screenshot_id=%s "
                    "scene_generation=%s current_scene_generation=%s reason=%s",
                    request_round,
                    screenshot_id,
                    scene_generation,
                    self._scene_generation,
                    stale_reason,
                )
                self._try_scene_refresh()
                return

        self._release_inflight_for_source(source)

        stats_state = self._ensure_stats_state()
        stats_state.add_tokens(input_tokens, output_tokens)
        self.lifetime_stats.add_tokens(input_tokens, output_tokens)
        if input_tokens > 0 or output_tokens > 0:
            self.logger.debug(
                "tokens: input=%s, output=%s, total_input=%s, total_output=%s",
                input_tokens, output_tokens,
                stats_state.total_input_tokens, stats_state.total_output_tokens,
            )

        request_started_at = self._peek_request_started_at(
            request_round, screenshot_id, scene_generation
        )
        if is_mic:
            self._log_reply_pipeline(
                "reply_received",
                request_id=format_reply_request_id(request_round, screenshot_id, scene_generation),
                request_round=request_round,
                screenshot_id=screenshot_id,
                captured_at=captured_at,
                request_started_at=request_started_at,
                reply_received_at=reply_received_at,
                scene_generation=scene_generation,
                source="mic",
                dropped_as_stale=False,
                enqueued=False,
                displayed=False,
            )
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

        raw_items = parse_ai_reply_payload(text)
        normalized_items = normalize_reply_batch(
            raw_items,
            scene_count=self._reply_scene_count,
            filler_count=self._reply_filler_count,
            config=self.config,
        )
        if not normalized_items:
            request_id = self._reply_request_id(request_round, screenshot_id, scene_generation)
            self._log_reply_pipeline(
                "reply_received",
                request_id=format_reply_request_id(request_round, screenshot_id, scene_generation),
                request_round=request_round,
                screenshot_id=screenshot_id,
                captured_at=captured_at,
                request_started_at=request_started_at,
                reply_received_at=reply_received_at,
                scene_generation=scene_generation,
                dropped_as_stale=False,
                enqueued=False,
                displayed=False,
            )
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
            self._record_undisplayed("empty_parse", persona_id=persona_id)
            return

        request_id = self._reply_request_id(request_round, screenshot_id, scene_generation)
        self._log_reply_pipeline(
            "reply_received",
            request_id=format_reply_request_id(request_round, screenshot_id, scene_generation),
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            request_started_at=request_started_at,
            reply_received_at=reply_received_at,
            scene_generation=scene_generation,
            dropped_as_stale=False,
            enqueued=True,
            displayed=False,
        )
        self.reply_buffer.drop_replaceable_fallbacks(
            request_id=request_id,
            batch_id=self._batch_id,
            scene_generation=scene_generation,
        )
        self._enqueue_reply_batch(
            persona_id,
            request_round,
            screenshot_id,
            captured_at,
            scene_generation,
            normalized_items,
            from_local_fallback=False,
            request_started_at=request_started_at,
            reply_received_at=reply_received_at,
        )
        self._notify_pet_visual_success()
        self._publish_live_status()

        if not self.reply_timer.isActive():
            self._consume_reply_queue()
        elif self.reply_buffer.size() > self._queue_low_watermark:
            self.reply_timer.stop()
            self._consume_reply_queue()
        else:
            self.reply_timer.setInterval(min(self.reply_timer.interval(), 200))

    def _consume_reply_queue(self):
        """从 FIFO 弹出一条回复上屏；成功时更新 BatchTracker 锚点与 next_generation_time。

        调用线程：主线程（reply_timer 单次触发回调；自适应间隔 100-1000ms）。
        fallback/mic 可 skip_dedup。
        锚点弹幕滚到 75% 屏宽处的时间写入 batch.next_generation_time（debug/批次元数据）。
        拒因（去重/入口过载）不入历史。
        floating_panel：间距阻塞 peek 不 pop；空文本/去重须在 pop 前判定并主动丢弃；
        意外上屏失败时回插队首，避免静默丢失。
        """
        floating_panel = self._danmu_render_mode() == "floating_panel"
        if self._pet_barrage_mode_enabled():
            barrage = self.__dict__.get("pet_barrage_controller")
            if barrage is None:
                return
            batch = []
            while len(batch) < 5 and not self.reply_buffer.is_empty():
                queued_item = self.reply_buffer.pop()
                if queued_item is None:
                    break
                batch.append(queued_item)
            if not batch:
                return
            rendered_rows: list[tuple[object, str]] = []
            for queued_item in batch:
                display_text = resolve_danmu_display_text(
                    queued_item.content,
                    self.config,
                    queued_item.persona_id,
                )
                if not display_text:
                    self.logger.info(
                        tr("app.danmu_not_entered").format(content=f"{queued_item.content[:20]}...")
                        + " [桌宠气泡/空文本]"
                    )
                    self._log_reply_pipeline_from_queued(
                        "reply_displayed",
                        queued_item,
                        displayed=False,
                    )
                    continue
                rendered_rows.append((queued_item, display_text))
            if not rendered_rows:
                if not self.reply_buffer.is_empty():
                    self.reply_timer.start(100)
                self._update_stats(success=False)
                self._maybe_pool_topup()
                return
            barrage.deliver_batch(
                [text for _, text in rendered_rows[:5]],
                persona_id=rendered_rows[0][0].persona_id,
                batch_id=rendered_rows[0][0].batch_id,
                scene_generation=rendered_rows[0][0].scene_generation,
                source=rendered_rows[0][0].source,
            )
            for queued_item, text in rendered_rows[:5]:
                self.history_writer.enqueue(text, queued_item.persona_id, queued_item.batch_index)
                self._log_reply_pipeline_from_queued(
                    "reply_displayed",
                    queued_item,
                    displayed=True,
                )
            self._latest_displayed_round = max(
                self._latest_displayed_round,
                max(item.screenshot_round for item, _ in rendered_rows),
            )
            self._latest_displayed_screenshot_id = max(
                self._latest_displayed_screenshot_id,
                max(item.screenshot_id for item, _ in rendered_rows),
            )
            if not self.reply_buffer.is_empty():
                self.reply_timer.start(self._estimated_reply_gap_ms())
            self._update_stats(success=True, count=len(rendered_rows[:5]))
            self._maybe_pool_topup()
            return
        if floating_panel:
            queued_peek = self.reply_buffer.peek()
            if queued_peek is None:
                return
            fp_engine = self.__dict__.get("floating_panel_engine")
            fp_overlay = self.__dict__.get("floating_panel_overlay")
            if fp_engine is not None and fp_overlay is not None:
                est_h = fp_overlay.estimate_item_height()
                if not fp_engine.can_accept_new_item(est_h):
                    delay = fp_engine.estimate_entry_delay_ms(est_h)
                    if not self.reply_buffer.is_empty():
                        self.reply_timer.start(max(50, delay))
                    return

                display_peek = resolve_danmu_display_text(
                    queued_peek.content,
                    self.config,
                    queued_peek.persona_id,
                )
                skip_dedup_peek = queued_peek.is_fallback or queued_peek.source == "fallback"
                if not display_peek:
                    queued = self.reply_buffer.pop()
                    self.logger.info(
                        tr("app.danmu_not_entered").format(content=f"{queued.content[:20]}...")
                        + " [悬浮窗/空文本]"
                    )
                    self._log_reply_pipeline_from_queued(
                        "reply_displayed",
                        queued,
                        displayed=False,
                    )
                    self._record_undisplayed("empty_text", persona_id=queued.persona_id)
                    if not self.reply_buffer.is_empty():
                        self.reply_timer.start(100)
                    self._update_stats(success=False)
                    self._maybe_pool_topup()
                    return
                if not skip_dedup_peek and fp_engine.is_duplicate(display_peek):
                    queued = self.reply_buffer.pop()
                    duplicate_observation = get_last_duplicate_observation()
                    duplicate_match_type = str(duplicate_observation.get("match_type") or "")
                    duplicate_stats = self._track_duplicate_rejection(
                        queued,
                        match_type=duplicate_match_type or "duplicate",
                    )
                    self.logger.info(
                        tr("app.danmu_not_entered").format(content=f"{queued.content[:20]}...")
                        + " [去重]"
                    )
                    self._log_reply_pipeline_from_queued(
                        "reply_displayed",
                        queued,
                        displayed=False,
                        duplicate_match_type=duplicate_match_type or "duplicate",
                        duplicate_loss=1,
                        duplicate_loss_total=duplicate_stats["duplicate_loss_total"],
                        duplicate_exact_set_hit=duplicate_stats["duplicate_exact_set_hit"],
                        duplicate_exact_window_hit=duplicate_stats["duplicate_exact_window_hit"],
                        duplicate_similarity_hit=duplicate_stats["duplicate_similarity_hit"],
                    )
                    self._record_undisplayed("duplicate", persona_id=queued.persona_id)
                    self._record_undisplayed(
                        "duplicate_exact_set_hit",
                        persona_id=queued.persona_id,
                    )
                    if not self.reply_buffer.is_empty():
                        self.reply_timer.start(100)
                    self._update_stats(success=False)
                    self._maybe_pool_topup()
                    return

        queued = self.reply_buffer.pop()
        if queued is None:
            return

        self.logger.info(f"[{persona_display_name_with_config(queued.persona_id, self.config)}] {queued.content}")
        display_content = resolve_danmu_display_text(
            queued.content,
            self.config,
            queued.persona_id,
        )
        skip_dedup = queued.is_fallback or queued.source == "fallback"
        item = self._display_danmu_text(
            display_content,
            queued.persona_id,
            batch_id=queued.batch_id,
            scene_generation=queued.scene_generation,
            skip_dedup=skip_dedup,
            pre_resolved=True,
        )
        if item:
            self._latest_displayed_round = max(self._latest_displayed_round, queued.screenshot_round)
            self._latest_displayed_screenshot_id = max(self._latest_displayed_screenshot_id, queued.screenshot_id)
            self._log_reply_pipeline_from_queued(
                "reply_displayed",
                queued,
                displayed=True,
            )
            self.history_writer.enqueue(display_content, queued.persona_id, queued.batch_index)
            from app.danmu_engine_models import DanmuItem

            if isinstance(item, DanmuItem):
                overlay_source = queued.source if queued.source in ("ai", "mic", "test") else "ai"
                self._broadcast_live_overlay_item(item, display_content, source=overlay_source)

            batch = self._current_batch
            if (
                batch
                and batch.anchor_item is None
                and isinstance(item, DanmuItem)
                and item.batch_id == batch.batch_id
            ):
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
            duplicate_match_type = ""
            if self._danmu_render_mode() == "floating_panel":
                fp_engine = self.__dict__.get("floating_panel_engine")
                if fp_engine and (not skip_dedup) and fp_engine.is_duplicate(display_content):
                    duplicate_observation = get_last_duplicate_observation()
                    duplicate_match_type = str(duplicate_observation.get("match_type") or "")
                    reject = "去重"
                    diag_reason = "duplicate"
                else:
                    reject = "悬浮窗"
                    diag_reason = "floating_panel_spacing"
            elif (not skip_dedup) and self.engine.is_duplicate(display_content):
                duplicate_observation = get_last_duplicate_observation()
                duplicate_match_type = str(duplicate_observation.get("match_type") or "")
                reject = "去重"
                diag_reason = "duplicate"
            elif self.engine.entry_zone_overloaded():
                reject = "入口区过载"
                diag_reason = "entry_zone_overload"
            else:
                reject = "轨道/布局"
                diag_reason = "layout_rejection"
            self._record_undisplayed(diag_reason, persona_id=queued.persona_id)
            extra_fields = {}
            if diag_reason == "duplicate":
                duplicate_stats = self._track_duplicate_rejection(
                    queued,
                    match_type=duplicate_match_type or "duplicate",
                )
                duplicate_topup_added = self._maybe_duplicate_loss_topup(
                    queued,
                    duplicate_stats,
                )
                self._record_undisplayed(
                    f"duplicate_{duplicate_match_type or 'duplicate'}",
                    persona_id=queued.persona_id,
                )
                extra_fields = {
                    "duplicate_match_type": duplicate_match_type or "duplicate",
                    "duplicate_loss": 1,
                    "duplicate_loss_total": duplicate_stats["duplicate_loss_total"],
                    "duplicate_exact_set_hit": duplicate_stats["duplicate_exact_set_hit"],
                    "duplicate_exact_window_hit": duplicate_stats["duplicate_exact_window_hit"],
                    "duplicate_similarity_hit": duplicate_stats["duplicate_similarity_hit"],
                    "duplicate_topup_triggered": duplicate_stats["duplicate_topup_triggered"],
                    "duplicate_topup_added": duplicate_topup_added,
                }
            self._log_reply_pipeline_from_queued(
                "reply_displayed",
                queued,
                displayed=False,
                **extra_fields,
            )
            self.logger.info(
                tr("app.danmu_not_entered").format(content=f"{queued.content[:20]}...")
                + f" [{reject}]"
            )
            if floating_panel and reject == "悬浮窗":
                self.reply_buffer.prepend_batch([queued])
                self.logger.warning(
                    "floating_panel display failed after pop; re-queued head item"
                )

        if not self.reply_buffer.is_empty():
            delay = 100 if item is None else self._estimated_reply_gap_ms()
            self.reply_timer.start(delay)

        self._update_stats(success=item is not None)
        self._maybe_pool_topup()


_check_deprecated_launch_args = check_deprecated_launch_args
_web_launch_mode_from_argv = web_launch_mode_from_argv


def main():
    from app.startup_trace import log_startup, mark_app_start
    from app.velopack_runtime import run_startup_apply_if_needed

    multiprocessing.freeze_support()
    mark_app_start()
    log_startup("main.begin")
    check_deprecated_launch_args()
    run_startup_apply_if_needed()
    sys.excepthook = global_exception_hook
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    log_startup("qapplication.created")
    from app.single_instance import SingleInstanceAcquireKind, SingleInstanceGuard
    instance_guard = SingleInstanceGuard()
    acquire_result = instance_guard.try_acquire()
    if acquire_result.kind is SingleInstanceAcquireKind.ACTIVATED_EXISTING:
        log_startup(
            "single_instance.done",
            acquired=False,
            activated_existing=True,
        )
        return sys.exit(0)
    # BUG-A09: Retry on ACTIVATION_FAILED to cover the race window where the
    # original instance's QLocalServer is not yet ready.
    if acquire_result.kind is SingleInstanceAcquireKind.ACTIVATION_FAILED:
        log_startup("single_instance.retry_begin")
        for _attempt in range(2):
            time.sleep(0.5)
            acquire_result = instance_guard.try_acquire()
            if acquire_result.kind is SingleInstanceAcquireKind.ACTIVATED_EXISTING:
                log_startup(
                    "single_instance.done",
                    acquired=False,
                    activated_existing=True,
                    retry=True,
                )
                return sys.exit(0)
            if acquire_result.kind is SingleInstanceAcquireKind.PRIMARY:
                log_startup(
                    "single_instance.done",
                    acquired=True,
                    activated_existing=False,
                    retry=True,
                )
                break
        else:
            log_startup("single_instance.retry_exhausted")
            return sys.exit(2)
    log_startup(
        "single_instance.done",
        acquired=acquire_result.became_primary,
        activated_existing=False,
    )
    launch_mode = web_launch_mode_from_argv()
    _danmu = DanmuApp(web_launch_mode=launch_mode)
    instance_guard.bind_activate(_danmu.show_settings)
    return sys.exit(app.exec())
if __name__ == "__main__":
    main()
