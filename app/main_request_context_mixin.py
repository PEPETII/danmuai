"""DanmuApp request context / memory / queue 辅助 mixin。

职责边界：
- 保留 DanmuApp 作为主链路 façade 与冻结字段持有者
- 迁出 request meta、timing、memory、密度/队列辅助
- 不迁出 capture / trigger / reply / consume 主流程入口
"""

from __future__ import annotations

import time

from app.api_schedule import min_api_interval_elapsed
from app.danmu_engine import dedup_profile_enabled, log_dedup_profile_summary
from app.main_helpers import (
    VISUAL_INFLIGHT_RECOVER_SEC,
    density_right_target,
    queue_capacity,
    reply_request_id,
)
from app.reply_queue import QueuedReply
from app.translations import tr


class DanmuAppRequestContextMixin:
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

    def _acquire_visual_inflight(self, screenshot_id: int, scene_generation: int) -> None:
        """W-MAIN-INFLIGHT-ATOMIC-001：视觉 in-flight 计数与关联字段同处写入（主线程）。"""
        self.ai_in_flight += 1
        self._is_generating = True
        self._inflight_screenshot_id = screenshot_id
        self._inflight_scene_generation = scene_generation
        self._inflight_started_at = time.monotonic()

    def _release_inflight_for_source(self, source: str) -> None:
        if source == "mic":
            self.mic_in_flight = max(0, self.mic_in_flight - 1)
            return
        self.ai_in_flight = max(0, self.ai_in_flight - 1)
        self._is_generating = False
        self._inflight_started_at = 0.0
        self._inflight_screenshot_id = 0
        self._inflight_scene_generation = 0

    def _pop_request_meta_for_inflight(
        self,
        screenshot_id: int,
        scene_generation: int,
    ) -> list[str]:
        """Pop pending meta keys matching inflight screenshot/scene (main thread)."""
        suffix = f":{screenshot_id}:{scene_generation}"
        popped: list[str] = []
        for key in list(self._pending_request_meta.keys()):
            if not key.endswith(suffix):
                continue
            if self._pending_request_meta.pop(key, None) is not None:
                popped.append(key)
        return popped

    def _try_recover_stale_visual_inflight(self) -> bool:
        """Force-release visual in-flight when HTTP never completes (S-011 / S-024).

        Main thread only. Complements W-015 (_request exception); does not bypass
        RequestScheduler for future triggers — only clears a stuck slot and orphan meta.
        """
        if not self._has_visual_request_in_flight():
            return False
        if self._inflight_started_at <= 0:
            return False
        elapsed = time.monotonic() - self._inflight_started_at
        if elapsed < VISUAL_INFLIGHT_RECOVER_SEC:
            return False

        screenshot_id = self._inflight_screenshot_id
        scene_generation = self._inflight_scene_generation
        popped_keys = self._pop_request_meta_for_inflight(screenshot_id, scene_generation)
        timing_service = self._get_request_timing_service()
        now = time.monotonic()
        for key in popped_keys:
            timing_service.consume_timing(request_id=key, now=now)
        purged = timing_service.purge_stale(now=now)

        self._release_inflight_for_source("visual")
        self._consecutive_failures += 1
        self.logger.error(
            "视觉请求 in-flight 强制恢复: screenshot_id=%s scene_generation=%s "
            "elapsed_ms=%s popped_meta=%s purged_timing=%s reason=inflight_watchdog_recover",
            screenshot_id,
            scene_generation,
            int(elapsed * 1000),
            popped_keys,
            purged,
        )
        self._publish_live_status()
        return True

    def _api_schedule_block_reason(self, *, enforce_min_interval: bool) -> str:
        """委托 RequestScheduler 判断视觉请求是否应阻塞。"""
        scheduler = self._get_request_scheduler()
        return scheduler.block_reason(
            has_visual_request_in_flight=self._has_visual_request_in_flight(),
            enforce_min_interval=enforce_min_interval,
            last_trigger_at=scheduler.last_api_trigger_at,
            min_interval_elapsed=min_api_interval_elapsed,
        )

    def _log_api_schedule(
        self,
        *,
        decision: str,
        source: str,
        block_reason: str = "",
    ) -> None:
        from app.main_helpers import log_api_schedule

        log_api_schedule(
            self.logger,
            decision=decision,
            source=source,
            block_reason=block_reason,
            batch=self._current_batch,
            rtt_avg=self._rtt_avg(),
            buffer_size=self.reply_buffer.size(),
            visible_count=self._visible_display_count(),
            in_flight=self._has_visual_request_in_flight(),
            scene_gen=self._scene_generation,
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

    def _queue_capacity(self) -> int:
        return queue_capacity(self.config, self._normal_reply_count())

    def _reply_request_id(
        self,
        request_round: int,
        screenshot_id: int,
        scene_generation: int,
    ) -> str:
        return reply_request_id(request_round, screenshot_id, scene_generation)

    def _min_density_target(self) -> int:
        return self.engine.min_on_screen()

    def _density_right_target(self, min_n: int) -> int:
        return density_right_target(min_n)

    def _maybe_pool_topup(self) -> int:
        from app.danmu_pool import maybe_pool_topup

        return maybe_pool_topup(self.engine, self.config, self._scene_generation)

    def _estimated_reply_gap_ms(self) -> int:
        if self.reply_timer.isActive():
            current_interval = self.reply_timer.interval()
            if current_interval > 0:
                return current_interval

        if self._danmu_render_mode() == "floating_panel":
            fp_engine = self.__dict__.get("floating_panel_engine")
            fp_overlay = self.__dict__.get("floating_panel_overlay")
            if fp_engine is not None and fp_overlay is not None:
                est_h = fp_overlay.estimate_item_height()
                if not fp_engine.can_accept_new_item(est_h):
                    return fp_engine.estimate_entry_delay_ms(est_h)
                return 120
            return 200

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

    def _reply_low_watermark(self) -> int:
        return max(0, self.config.get_int("reply_low_watermark", 1))

    def _empty_accel_enabled(self) -> bool:
        return self.config.get("empty_accel", "1") == "1"

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
        """构造 QueuedReply 批次写入 reply_buffer。"""
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

    def _rtt_avg(self) -> float:
        return self._get_request_timing_service().avg_rtt()

    def _smart_cooldown_ms(self) -> int:
        return self._get_request_timing_service().smart_cooldown_ms(
            fallback_interval_sec=self.config.get_int("screenshot_interval", 3),
        )

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
