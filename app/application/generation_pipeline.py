"""生成管线回复消费与三路分发服务（W-GENPIPELINE-EXTRACT）。

从 DanmuApp 主链路回复消费方法抽离。DanmuApp 持有引用并经 façade 方法委托调用；
``reply_timer`` / ``reply_buffer`` 所有权仍属 DanmuApp，本服务只通过
``self._app.reply_timer.start()`` 驱动自调度（不实例化 Qt 对象）。

治理：由 ``scripts/boundary_guard`` 的 ``check_generation_pipeline_service`` 规则约束，
禁止实例化 QTimer / QThreadPool / QPixmap，禁止调用主链路触发函数
（``_trigger_api_call`` / ``_on_ai_reply`` 等，仍属 DanmuApp）。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from app.api_schedule import time_to_anchor_boundary
from app.danmu_engine import resolve_danmu_display_text
from app.danmu_engine_dedup import get_last_duplicate_observation
from app.main_request_context_mixin import format_reply_request_id
from app.personae import persona_display_name_with_config
from app.reply_parser import normalize_reply_batch, parse_ai_reply_payload
from app.translations import tr

if TYPE_CHECKING:
    from main import DanmuApp


class GenerationPipeline:
    """主链路回复消费与三路分发服务。

    Phase 2：真三路分发——pet / floating_panel / overlay 各自独立方法，
    打破 Phase 1 的 floating_panel 预检 + fall-through 模式。共享锚点更新
    逻辑抽到 ``_compute_anchor_update``。
    """

    def __init__(self, app: "DanmuApp") -> None:
        self._app = app

    def consume_reply_queue(self) -> None:
        """从 reply_buffer 取出回复，分发到 pet / floating_panel / overlay 三条通道。

        调用线程：Qt 主线程（reply_timer 单次触发回调；自适应间隔 100-1000ms）。
        三路分发各自独立 return，无 fall-through。
        """
        app = self._app
        if app._pet_barrage_mode_enabled():
            self._dispatch_to_pet(app)
            return
        if app._danmu_render_mode() == "floating_panel":
            self._dispatch_to_floating_panel(app)
            return
        self._dispatch_to_overlay(app)

    def handle_reply_parsed(
        self,
        text: str,
        persona_id: str,
        request_round: int,
        screenshot_id: int,
        captured_at: float,
        scene_generation: int,
        request_started_at: float,
        reply_received_at: float,
    ) -> None:
        """处理已通过门控的视觉回复：解析 → 入队 → 驱动 consume_reply_queue。

        从 DanmuApp._on_ai_reply 后置段抽离（main.py:679-753）。
        调用线程：Qt 主线程（ai_worker.finished 信号回调）。
        前置门控（释放在途/token 统计/scene_generation 门控/mic 分流/失败计数重置
        /timing 消费）仍属 DanmuApp._on_ai_reply。
        """
        app = self._app
        raw_items = parse_ai_reply_payload(text)
        normalized_items = normalize_reply_batch(
            raw_items,
            scene_count=app._reply_scene_count,
            filler_count=app._reply_filler_count,
            config=app.config,
        )
        if not normalized_items:
            request_id = app._reply_request_id(request_round, screenshot_id, scene_generation)
            app._log_reply_pipeline(
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
            app.logger.warning(
                "AI 回复解析为空: request_id=%s screenshot_id=%s request_round=%s "
                "scene_generation=%s text_len=%s raw_count=%s reason=empty_parse",
                request_id,
                screenshot_id,
                request_round,
                scene_generation,
                len(text or ""),
                len(raw_items),
            )
            app._record_undisplayed("empty_parse", persona_id=persona_id)
            return

        request_id = app._reply_request_id(request_round, screenshot_id, scene_generation)
        app._log_reply_pipeline(
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
        app.reply_buffer.drop_replaceable_fallbacks(
            request_id=request_id,
            batch_id=app._batch_id,
            scene_generation=scene_generation,
        )
        app._enqueue_reply_batch(
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
        app._notify_pet_visual_success()
        app._publish_live_status()

        if not app.reply_timer.isActive():
            self.consume_reply_queue()
        elif app.reply_buffer.size() > app._queue_low_watermark:
            app.reply_timer.stop()
            self.consume_reply_queue()
        else:
            app.reply_timer.setInterval(min(app.reply_timer.interval(), 200))

    def _dispatch_to_pet(self, app: "DanmuApp") -> None:
        """桌宠气泡分发：批量 pop（最多 5 条）→ 渲染 → deliver_batch。"""
        barrage = (
            app.optional_pet_barrage_controller()
            if callable(getattr(app, "optional_pet_barrage_controller", None))
            else getattr(app, "pet_barrage_controller", None)
        )
        if barrage is None:
            return
        batch: list = []
        while len(batch) < 5 and not app.reply_buffer.is_empty():
            queued_item = app.reply_buffer.pop()
            if queued_item is None:
                break
            batch.append(queued_item)
        if not batch:
            return
        rendered_rows: list[tuple[object, str]] = []
        for queued_item in batch:
            display_text = resolve_danmu_display_text(
                queued_item.content,
                app.config,
                queued_item.persona_id,
            )
            if not display_text:
                app.logger.info(
                    tr("app.danmu_not_entered").format(content=f"{queued_item.content[:20]}...")
                    + f" [{tr('log.reject.pet_empty')}]"
                )
                app._log_reply_pipeline_from_queued(
                    "reply_displayed",
                    queued_item,
                    displayed=False,
                )
                continue
            rendered_rows.append((queued_item, display_text))
        if not rendered_rows:
            if not app.reply_buffer.is_empty():
                app.reply_timer.start(100)
            app._update_stats(success=False)
            app._maybe_pool_topup()
            return
        barrage.deliver_batch(
            [text for _, text in rendered_rows[:5]],
            persona_id=rendered_rows[0][0].persona_id,
            batch_id=rendered_rows[0][0].batch_id,
            scene_generation=rendered_rows[0][0].scene_generation,
            source=rendered_rows[0][0].source,
        )
        for queued_item, text in rendered_rows[:5]:
            app.history_writer.enqueue(text, queued_item.persona_id, queued_item.batch_index)
            app._log_reply_pipeline_from_queued(
                "reply_displayed",
                queued_item,
                displayed=True,
            )
        app._latest_displayed_round = max(
            app._latest_displayed_round,
            max(item.screenshot_round for item, _ in rendered_rows),
        )
        app._latest_displayed_screenshot_id = max(
            app._latest_displayed_screenshot_id,
            max(item.screenshot_id for item, _ in rendered_rows),
        )
        if not app.reply_buffer.is_empty():
            app.reply_timer.start(app._estimated_reply_gap_ms())
        app._update_stats(success=True, count=len(rendered_rows[:5]))
        app._maybe_pool_topup()

    def _dispatch_to_floating_panel(self, app: "DanmuApp") -> None:
        """浮动面板分发：peek 预检（容量/空文本/去重）→ pop + 上屏 + 锚点 + 失败回插。

        与 overlay 分支解耦：失败时 floating_panel 间距拒因走 prepend_batch 回插队首，
        避免静默丢失。成功时锚点更新经 ``_compute_anchor_update`` 共享。
        """
        # peek 预检（容量/空文本/去重 early-return）
        queued_peek = app.reply_buffer.peek()
        if queued_peek is None:
            return
        optional_engine = getattr(app, "optional_floating_panel_engine", None)
        optional_overlay = getattr(app, "optional_floating_panel_overlay", None)
        if callable(optional_engine):
            fp_engine = optional_engine()
        else:
            fp_engine = getattr(app, "floating_panel_engine", None)
        if callable(optional_overlay):
            fp_overlay = optional_overlay()
        else:
            fp_overlay = getattr(app, "floating_panel_overlay", None)
        if fp_engine is not None and fp_overlay is not None:
            est_h = fp_overlay.estimate_item_height()
            if not fp_engine.can_accept_new_item(est_h):
                delay = fp_engine.estimate_entry_delay_ms(est_h)
                if not app.reply_buffer.is_empty():
                    app.reply_timer.start(max(50, delay))
                return

            display_peek = resolve_danmu_display_text(
                queued_peek.content,
                app.config,
                queued_peek.persona_id,
            )
            skip_dedup_peek = queued_peek.is_fallback or queued_peek.source == "fallback"
            if not display_peek:
                queued = app.reply_buffer.pop()
                app.logger.info(
                    tr("app.danmu_not_entered").format(content=f"{queued.content[:20]}...")
                    + f" [{tr('log.reject.floating_panel_empty')}]"
                )
                app._log_reply_pipeline_from_queued(
                    "reply_displayed",
                    queued,
                    displayed=False,
                )
                app._record_undisplayed("empty_text", persona_id=queued.persona_id)
                if not app.reply_buffer.is_empty():
                    app.reply_timer.start(100)
                app._update_stats(success=False)
                app._maybe_pool_topup()
                return
            if not skip_dedup_peek and fp_engine.is_duplicate(display_peek):
                queued = app.reply_buffer.pop()
                duplicate_observation = get_last_duplicate_observation()
                duplicate_match_type = str(duplicate_observation.get("match_type") or "")
                duplicate_stats = app._track_duplicate_rejection(
                    queued,
                    match_type=duplicate_match_type or "duplicate",
                )
                app.logger.info(
                    tr("app.danmu_not_entered").format(content=f"{queued.content[:20]}...")
                    + f" [{tr('log.reject.dedup')}]"
                )
                app._log_reply_pipeline_from_queued(
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
                app._record_undisplayed("duplicate", persona_id=queued.persona_id)
                app._record_undisplayed(
                    "duplicate_exact_set_hit",
                    persona_id=queued.persona_id,
                )
                if not app.reply_buffer.is_empty():
                    app.reply_timer.start(100)
                app._update_stats(success=False)
                app._maybe_pool_topup()
                return

        # pop + 上屏
        queued = app.reply_buffer.pop()
        if queued is None:
            return

        app.logger.info(f"[{persona_display_name_with_config(queued.persona_id, app.config)}] {queued.content}")
        display_content = resolve_danmu_display_text(
            queued.content,
            app.config,
            queued.persona_id,
        )
        skip_dedup = queued.is_fallback or queued.source == "fallback"
        item = app._display_danmu_text(
            display_content,
            queued.persona_id,
            batch_id=queued.batch_id,
            scene_generation=queued.scene_generation,
            skip_dedup=skip_dedup,
            pre_resolved=True,
        )
        if item:
            app._latest_displayed_round = max(app._latest_displayed_round, queued.screenshot_round)
            app._latest_displayed_screenshot_id = max(app._latest_displayed_screenshot_id, queued.screenshot_id)
            app._log_reply_pipeline_from_queued(
                "reply_displayed",
                queued,
                displayed=True,
            )
            app.history_writer.enqueue(display_content, queued.persona_id, queued.batch_index)
            from app.danmu_engine_models import DanmuItem

            if isinstance(item, DanmuItem):
                overlay_source = queued.source if queued.source in ("ai", "mic", "test") else "ai"
                app._broadcast_live_overlay_item(item, display_content, source=overlay_source)

            self._compute_anchor_update(app, item)
        else:
            duplicate_match_type = ""
            if fp_engine and (not skip_dedup) and fp_engine.is_duplicate(display_content):
                duplicate_observation = get_last_duplicate_observation()
                duplicate_match_type = str(duplicate_observation.get("match_type") or "")
                reject = tr("log.reject.dedup")
                diag_reason = "duplicate"
            else:
                reject = tr("log.reject.floating_panel")
                diag_reason = "floating_panel_spacing"
            app._record_undisplayed(diag_reason, persona_id=queued.persona_id)
            extra_fields: dict = {}
            if diag_reason == "duplicate":
                duplicate_stats = app._track_duplicate_rejection(
                    queued,
                    match_type=duplicate_match_type or "duplicate",
                )
                duplicate_topup_added = app._maybe_duplicate_loss_topup(
                    queued,
                    duplicate_stats,
                )
                app._record_undisplayed(
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
            app._log_reply_pipeline_from_queued(
                "reply_displayed",
                queued,
                displayed=False,
                **extra_fields,
            )
            app.logger.info(
                tr("app.danmu_not_entered").format(content=f"{queued.content[:20]}...")
                + f" [{reject}]"
            )
            if diag_reason == "floating_panel_spacing":
                app.reply_buffer.prepend_batch([queued])
                app.logger.warning(tr("log.floating_panel_requeued"))

        if not app.reply_buffer.is_empty():
            delay = 100 if item is None else app._estimated_reply_gap_ms()
            app.reply_timer.start(delay)

        app._update_stats(success=item is not None)
        app._maybe_pool_topup()

    def _dispatch_to_overlay(self, app: "DanmuApp") -> None:
        """overlay 主路径：pop → _display_danmu_text 上屏 → 锚点更新 / 拒因诊断。

        失败拒因：duplicate / entry_zone_overload / layout_rejection（不含
        floating_panel 间距拒因，该分支已迁入 _dispatch_to_floating_panel）。
        """
        queued = app.reply_buffer.pop()
        if queued is None:
            return

        app.logger.info(f"[{persona_display_name_with_config(queued.persona_id, app.config)}] {queued.content}")
        display_content = resolve_danmu_display_text(
            queued.content,
            app.config,
            queued.persona_id,
        )
        skip_dedup = queued.is_fallback or queued.source == "fallback"
        item = app._display_danmu_text(
            display_content,
            queued.persona_id,
            batch_id=queued.batch_id,
            scene_generation=queued.scene_generation,
            skip_dedup=skip_dedup,
            pre_resolved=True,
        )
        if item:
            app._latest_displayed_round = max(app._latest_displayed_round, queued.screenshot_round)
            app._latest_displayed_screenshot_id = max(app._latest_displayed_screenshot_id, queued.screenshot_id)
            app._log_reply_pipeline_from_queued(
                "reply_displayed",
                queued,
                displayed=True,
            )
            app.history_writer.enqueue(display_content, queued.persona_id, queued.batch_index)
            from app.danmu_engine_models import DanmuItem

            if isinstance(item, DanmuItem):
                overlay_source = queued.source if queued.source in ("ai", "mic", "test") else "ai"
                app._broadcast_live_overlay_item(item, display_content, source=overlay_source)

            self._compute_anchor_update(app, item)
        else:
            duplicate_match_type = ""
            if (not skip_dedup) and app.engine.is_duplicate(display_content):
                duplicate_observation = get_last_duplicate_observation()
                duplicate_match_type = str(duplicate_observation.get("match_type") or "")
                reject = tr("log.reject.dedup")
                diag_reason = "duplicate"
            elif app.engine.entry_zone_overloaded():
                reject = tr("log.reject.entry_zone_overload")
                diag_reason = "entry_zone_overload"
            else:
                reject = tr("log.reject.layout")
                diag_reason = "layout_rejection"
            app._record_undisplayed(diag_reason, persona_id=queued.persona_id)
            extra_fields: dict = {}
            if diag_reason == "duplicate":
                duplicate_stats = app._track_duplicate_rejection(
                    queued,
                    match_type=duplicate_match_type or "duplicate",
                )
                duplicate_topup_added = app._maybe_duplicate_loss_topup(
                    queued,
                    duplicate_stats,
                )
                app._record_undisplayed(
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
            app._log_reply_pipeline_from_queued(
                "reply_displayed",
                queued,
                displayed=False,
                **extra_fields,
            )
            app.logger.info(
                tr("app.danmu_not_entered").format(content=f"{queued.content[:20]}...")
                + f" [{reject}]"
            )

        if not app.reply_buffer.is_empty():
            delay = 100 if item is None else app._estimated_reply_gap_ms()
            app.reply_timer.start(delay)

        app._update_stats(success=item is not None)
        app._maybe_pool_topup()

    def _compute_anchor_update(self, app: "DanmuApp", item) -> None:
        """共享锚点更新：成功上屏后设置 batch.anchor_item 与 next_generation_time。

        floating_panel 与 overlay 成功路径共用。抽自原 _dispatch_to_overlay 锚点段。
        """
        from app.danmu_engine_models import DanmuItem

        batch = app._current_batch
        if (
            batch
            and batch.anchor_item is None
            and isinstance(item, DanmuItem)
            and item.batch_id == batch.batch_id
        ):
            batch.anchor_item = item
            target_x = app.engine.screen_width * 0.75
            distance = item.x - target_x
            if distance > 0 and item.speed > 0:
                factor = 1.0
                if getattr(app.engine, "_accel_remaining", 0) > 0:
                    factor = min(getattr(app.engine, "_accel_peak", 1.0), 2.0)
                time_to_boundary = time_to_anchor_boundary(
                    distance, item.speed, factor
                )
                batch.next_generation_time = time.monotonic() + time_to_boundary
                app.logger.info(
                    tr("app.batch_anchor").format(
                        batch_id=batch.batch_id,
                        x=item.x,
                        target_x=target_x,
                        time_to_boundary=time_to_boundary,
                    )
                )
            else:
                batch.next_generation_time = time.monotonic()
