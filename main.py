"""DanmuAI 应用入口与单例状态机（DanmuApp）。

职责边界（bootstrap / lifecycle / façade）：
- 截图定时、视觉/麦克风双轨 AI 调度、回复队列消费、场景代际淘汰、失败退避
- 与 DanmuOverlay / DanmuEngine 协同上屏；Web 控制台经 bridge 信号回主线程改配置
- 运行态对外展示委托 StatusSnapshotBuilder / DiagnosticSnapshotBuilder，勿在 Web 层拼私有字段

主链路（普通模式，详见 docs/main-pipeline-sequence.md）：
  screenshot_timer → _on_normal_capture_tick → _schedule_capture → CaptureRunnable
  → _on_capture_completed → _trigger_api_call → AiRunnable → _on_ai_reply → ...

关键设计：
- screenshot_id：每帧截图递增，用于「更新帧优于在途回复」的 supersede 判定
- scene_generation：场景配置指纹版本（live_topic/user_nickname/screen_index/region_* 变更递增；start/stop 重置；截图不推进）
- MAX_IN_FLIGHT=1：并发视觉请求会破坏过期判断与回复顺序，故硬限制为 1

线程：DanmuApp 在 Qt 主线程；CaptureRunnable 在 capture_worker_pool 抓屏；
AiRunnable 在 ai_worker_pool 中调 AiWorker，finished 信号队列回主线程。

Phase 4 冻结：ai_in_flight、_pending_request_meta、_scene_generation 等仍冻结于本模块；
reply_buffer/QTimer 所有权仍属本模块，回复消费逻辑已委托 app/application/generation_pipeline.py
（W-GENPIPELINE-EXTRACT，见 .local-ai/scratch/archive-phases/phase4-freeze.md）。

入口：python main.py → main()。
"""
import multiprocessing
import sys
import threading
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
from app.main_floating_panel_mixin import DanmuAppFloatingPanelMixin
from app.main_overlay_mixin import DanmuAppOverlayMixin
from app.main_pet_mixin import DanmuAppPetMixin
from app.main_render_coordinator_mixin import DanmuAppRenderCoordinatorMixin
from app.main_screen_topology_mixin import DanmuAppScreenTopologyMixin
from app.main_helpers import (
    MAX_IN_FLIGHT,
    VISUAL_INFLIGHT_RECOVER_SEC,
    VISUAL_INFLIGHT_WARN_SEC,
    BatchTracker,  # noqa: F401 — re-exported for tests
)
from app.main_launch import (
    check_deprecated_launch_args,
    global_exception_hook,
    register_unhandled_exception_notifier,
    show_fatal_startup_error,
    show_startup_notice_if_needed,  # noqa: F401 — re-exported for tests
    threading_exception_hook,
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
from app.persona_contract import (
    append_live_topic_to_system_pt,
    append_nickname_to_system_pt,
)
from app.persona_display import persona_display_name_with_config
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
    DanmuAppRenderCoordinatorMixin,
    DanmuAppPetMixin,
    DanmuAppOverlayMixin,
    DanmuAppFloatingPanelMixin,
    DanmuAppScreenTopologyMixin,
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
        try:
            self._init_runtime_bridge_state(web_launch_mode)
            self._init_core_subsystems(log_startup)
            self._init_request_pipeline_state()
            self._init_runtime_tracking_state()
            self._init_startup_services(log_startup)
            self._start_web_console_stack(log_startup)
            self._sync_reply_batch_config()
        except Exception:
            self.release_startup_failure()
            raise
        log_startup(
            "danmu_app.init.end",
            ms=(time.perf_counter() - init_started) * 1000.0,
            startup_ok=bool(self.web_server and self.web_server.startup_ok),
        )

    def _has_visual_request_in_flight(self) -> bool:
        return self._is_generating or self.ai_in_flight >= MAX_IN_FLIGHT

    def _pool_topup_target(self):
        """解析公式化补足目标面：('scrolling'|'floating_panel', plan_engine) 或 None。

        floating 时禁止写横向 DanmuEngine；scrolling 时禁止写 FP。
        pet 模式或显示面未就绪时返回 None。
        """
        if self._pet_barrage_mode_enabled():
            return None
        mode = self._danmu_render_mode()
        if mode == "floating_panel":
            eng = self.__dict__.get("floating_panel_engine")
            ov = self.__dict__.get("floating_panel_overlay")
            if eng is not None and ov is not None and bool(getattr(eng, "running", False)):
                return ("floating_panel", eng)
            return None
        if mode == "scrolling":
            engine = getattr(self, "engine", None)
            if engine is not None and bool(getattr(engine, "running", False)):
                return ("scrolling", engine)
            return None
        return None

    def _add_pool_topup_text(
        self,
        kind: str,
        text: str,
        *,
        scene_generation: int,
        source: str,
    ) -> bool:
        """按目标面写入一条补足弹幕；成功返回 True。"""
        if kind == "scrolling":
            item = self.engine.add_text(
                text,
                persona="",
                batch_id=0,
                scene_generation=scene_generation,
                skip_dedup=True,
            )
            if not item:
                return False
            self._broadcast_live_overlay_item(item, item.content, source=source)
            return True
        item = self._display_floating_panel_text(
            text,
            "",
            batch_id=0,
            scene_generation=scene_generation,
            skip_dedup=True,
        )
        return item is not None

    def _maybe_pool_topup(self) -> int:
        from app.danmu_pool import plan_pool_topup

        target = self._pool_topup_target()
        if target is None:
            return 0
        kind, plan_engine = target
        limit, texts = plan_pool_topup(plan_engine, self.config)
        if limit <= 0 or not texts:
            return 0
        scene_generation = int(getattr(self, "_scene_generation", 0))
        added = 0
        for text in texts:
            if added >= limit:
                break
            if self._add_pool_topup_text(
                kind,
                text,
                scene_generation=scene_generation,
                source="pool_topup",
            ):
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

        target = self._pool_topup_target()
        if target is None:
            return 0
        kind, plan_engine = target
        texts = plan_duplicate_loss_topup(
            plan_engine,
            self.config,
            duplicate_loss_total=int(stats.get("duplicate_loss_total", 0)),
        )
        if not texts:
            return 0
        scene_generation = int(getattr(queued, "scene_generation", 0))
        added = 0
        for text in texts:
            if self._add_pool_topup_text(
                kind,
                text,
                scene_generation=scene_generation,
                source="pool_duplicate_topup",
            ):
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

    def _on_capture_failed(self, error: str) -> None:
        """CaptureCoordinator.failed 主线程槽：释放截图槽位并记录失败。"""
        self._capture_in_flight = False
        if not self.engine.running or self.ai_worker._stopping.is_set():
            return
        self.logger.warning(
            "截图 worker 失败: %s reason=capture_worker_error",
            error,
        )
        self._note_capture_failure()

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

    def _blocked_visual_api_trigger(
        self, source: str, *, enforce_min_interval: bool
    ) -> bool:
        block = self._api_schedule_block_reason(enforce_min_interval=enforce_min_interval)
        if block:
            self._log_api_schedule(decision="block", source=source, block_reason=block)
            if block == "in_flight":
                self.logger.debug(tr("app.skip_api_generating"))
            return True
        if self.ai_in_flight >= MAX_IN_FLIGHT:
            self._log_api_schedule(decision="block", source=source, block_reason="in_flight")
            self.logger.debug(tr("app.skip_api_generating"))
            return True
        if self._latest_screenshot is None:
            self._log_api_schedule(decision="block", source=source, block_reason="no_screenshot")
            self.logger.debug(tr("app.skip_api_no_screenshot"))
            return True
        return False

    def _begin_visual_api_round(
        self, source: str
    ) -> tuple[object, int, float, int, int]:
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
        return pixmap, screenshot_id, captured_at, request_round, batch_id

    def _build_visual_prompts(
        self,
        *,
        request_round: int,
        screenshot_id: int,
        batch_id: int,
    ) -> tuple[str, str, str] | None:
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
            return None
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

        # Phase B / Wave 7（B2）：知识包检索注入到 system_pt 末尾。
        # 异常隔离：knowledge_runtime 未挂载或检索失败 → 原样返回 system_pt。
        system_pt = self._inject_knowledge_prompt(
            system_pt,
            request_round=request_round,
            screenshot_id=screenshot_id,
        )

        # BUG-AI-DEDUP-CONTEXT-001：注入最近已发送弹幕作为反重复上下文。
        # 在知识包注入之后；空列表跳过；异常隔离不阻塞 prompt 构造。
        try:
            recent_sent = self._recent_sent_danmu_for_prompt(10)
            if recent_sent:
                system_pt = (
                    system_pt
                    + "\n最近已发送的弹幕（请勿重复上述内容）："
                    + " | ".join(recent_sent)
                )
        except Exception as exc:
            self.logger.warning(
                "inject recent_sent_danmu failed: %r", exc
            )

        self._current_persona = persona
        return system_pt, user_pt, persona

    def _dispatch_visual_ai_runnable(
        self,
        pixmap: object,
        system_pt: str,
        user_pt: str,
        persona: str,
        *,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
    ) -> None:
        request_id = self._reply_request_id(request_round, screenshot_id, self._scene_generation)
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
        if self._blocked_visual_api_trigger(source, enforce_min_interval=enforce_min_interval):
            return
        pixmap, screenshot_id, captured_at, request_round, batch_id = self._begin_visual_api_round(
            source
        )
        prompts = self._build_visual_prompts(
            request_round=request_round,
            screenshot_id=screenshot_id,
            batch_id=batch_id,
        )
        if prompts is None:
            return
        system_pt, user_pt, persona = prompts
        self._dispatch_visual_ai_runnable(
            pixmap,
            system_pt,
            user_pt,
            persona,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
        )

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

    def _drop_reply_if_meta_missing(
        self,
        meta: dict,
        *,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        reply_received_at: float,
    ) -> bool:
        """W-RACE-001：meta 为空时不释放在途槽位、不入队。"""
        if meta:
            return False
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
        return True

    def _drop_stale_visual_reply_if_needed(
        self,
        *,
        is_mic: bool,
        source: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        reply_received_at: float,
    ) -> bool:
        if is_mic:
            return False
        stale_reason = self._visual_reply_stale_reason(scene_generation)
        if not stale_reason:
            return False
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
        return True

    def _account_reply_token_usage(self, input_tokens: int, output_tokens: int) -> None:
        stats_state = self._ensure_stats_state()
        stats_state.add_tokens(input_tokens, output_tokens)
        self.lifetime_stats.add_tokens(input_tokens, output_tokens)
        if input_tokens > 0 or output_tokens > 0:
            self.logger.debug(
                "tokens: input=%s, output=%s, total_input=%s, total_output=%s",
                input_tokens,
                output_tokens,
                stats_state.total_input_tokens,
                stats_state.total_output_tokens,
            )

    def _reset_failure_backoff_if_needed(self) -> None:
        if self._consecutive_failures <= 0:
            return
        self._consecutive_failures = 0
        self._last_error_message = ""
        if not self._failure_backoff_paused:
            return
        self._failure_backoff_paused = False
        self._set_error_status_safe("", is_error=False)
        if self.engine.running and not self.screenshot_timer.isActive():
            self.screenshot_timer.start()

    def _dispatch_mic_ai_reply_branch(
        self,
        text: str,
        persona_id: str,
        *,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        request_started_at: float,
        reply_received_at: float,
    ) -> None:
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

    def _dispatch_visual_reply_to_pipeline(
        self,
        text: str,
        persona_id: str,
        *,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        request_started_at: float,
        reply_received_at: float,
    ) -> None:
        self._consume_request_timing(request_round, screenshot_id, scene_generation)
        enqueued = self._generation_pipeline.handle_reply_parsed(
            text=text,
            persona_id=persona_id,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
            request_started_at=request_started_at,
            reply_received_at=reply_received_at,
        )
        if enqueued:
            self._reset_failure_backoff_if_needed()

    def _abort_ai_reply_early(
        self,
        meta: dict,
        *,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        reply_received_at: float,
    ) -> str | None:
        if self._drop_reply_if_meta_missing(
            meta,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
            reply_received_at=reply_received_at,
        ):
            return None
        source = meta.get("source") or "visual"
        if self._drop_stale_visual_reply_if_needed(
            is_mic=source == "mic",
            source=source,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
            reply_received_at=reply_received_at,
        ):
            return None
        return source

    def _on_ai_reply(self, text: str, persona_id: str, request_round: int, screenshot_id: int, captured_at: float, scene_generation: int, input_tokens: int = 0, output_tokens: int = 0):
        """AiWorker.finished 主线程入口：释放在途 → 解析入队 → 驱动 _consume_reply_queue。"""
        self.logger.debug(f"[DEBUG] _on_ai_reply called, text length={len(text)}")
        reply_received_at = time.monotonic()
        meta = self._pop_request_meta(request_round, screenshot_id, scene_generation)
        source = self._abort_ai_reply_early(
            meta,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
            reply_received_at=reply_received_at,
        )
        if source is None:
            return

        self._release_inflight_for_source(source)
        self._account_reply_token_usage(input_tokens, output_tokens)
        request_started_at = self._peek_request_started_at(
            request_round, screenshot_id, scene_generation
        )
        if source == "mic":
            self._dispatch_mic_ai_reply_branch(
                text,
                persona_id,
                request_round=request_round,
                screenshot_id=screenshot_id,
                captured_at=captured_at,
                scene_generation=scene_generation,
                request_started_at=request_started_at,
                reply_received_at=reply_received_at,
            )
            return

        self._dispatch_visual_reply_to_pipeline(
            text,
            persona_id,
            request_round=request_round,
            screenshot_id=screenshot_id,
            captured_at=captured_at,
            scene_generation=scene_generation,
            request_started_at=request_started_at,
            reply_received_at=reply_received_at,
        )

    def _consume_reply_queue(self):
        """委托给 GenerationPipeline（保留签名向后兼容，reply_timer.timeout 依赖此方法）。"""
        self._generation_pipeline.consume_reply_queue()


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
    threading.excepthook = threading_exception_hook
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
        for _attempt in range(3):
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
            instance_guard.release()
            return sys.exit(2)
    log_startup(
        "single_instance.done",
        acquired=acquire_result.became_primary,
        activated_existing=False,
    )
    launch_mode = web_launch_mode_from_argv()
    try:
        _danmu = DanmuApp(web_launch_mode=launch_mode)
    except Exception as exc:
        instance_guard.release()
        show_fatal_startup_error(exc)
        return sys.exit(1)
    register_unhandled_exception_notifier(
        lambda: _danmu.set_web_error_status(
            tr("app.error_friendly_message"),
            is_error=True,
        )
    )
    instance_guard.bind_activate(_danmu.show_settings)
    return sys.exit(app.exec())
if __name__ == "__main__":
    main()
