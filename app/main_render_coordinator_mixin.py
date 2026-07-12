"""DanmuApp render mode / live status / display routing mixin.

职责边界：
- danmu_render_mode 与模式门控
- live status 投影与发布
- 按 render mode 路由上屏与测试注入
- 不迁出 Overlay / floating panel / bililive 子模块实现
"""

from __future__ import annotations

import time

from app.config_defaults import resolve_danmu_render_mode
from app.danmu_engine_models import DanmuItem
from app.live_freshness import LiveStatusSnapshot
from app.reply_queue import QueuedReply
from app.translations import tr


class DanmuAppRenderCoordinatorMixin:
    def _danmu_render_mode(self) -> str:
        return resolve_danmu_render_mode(self.config)

    def _pet_barrage_mode_enabled(self) -> bool:
        return self.config.get("pet_barrage_mode_enabled", "0") == "1"

    def _bililive_dm_mode_enabled(self) -> bool:
        return self.config.get("bililive_dm_mode_enabled", "0") == "1"

    def _overlay_display_enabled(self) -> bool:
        if self._pet_barrage_mode_enabled():
            return False
        if self._bililive_dm_mode_enabled():
            return False
        return self._danmu_render_mode() == "scrolling"

    def _floating_panel_v2_enabled(self) -> bool:
        if self._pet_barrage_mode_enabled():
            return False
        if self._bililive_dm_mode_enabled():
            return False
        return self._danmu_render_mode() == "floating_panel"

    def _current_danmu_delay_sec(self) -> float:
        from app.application.live_status_projection import current_danmu_delay_sec

        return current_danmu_delay_sec(
            has_visual_request_in_flight=self._has_visual_request_in_flight(),
            inflight_started_at=self._inflight_started_at,
            reply_buffer=self.reply_buffer,
            latest_screenshot_time=self._latest_screenshot_time,
        )

    def _build_live_status_snapshot(self) -> LiveStatusSnapshot:
        from app.application.live_status_projection import build_live_status_snapshot

        return build_live_status_snapshot(
            has_visual_request_in_flight=self._has_visual_request_in_flight(),
            inflight_started_at=self._inflight_started_at,
            reply_buffer=self.reply_buffer,
            latest_screenshot_time=self._latest_screenshot_time,
            local_fallback=self._local_fallback_active,
        )

    def _publish_live_status(self):
        if not self.engine.running:
            return
        web_timer = getattr(self, "_web_status_timer", None)
        if web_timer is not None and web_timer.isActive():
            return
        bridge = getattr(self, "web_bridge", None)
        if bridge:
            bridge.publish_status()

    def _visible_display_count(self) -> int:
        if self._danmu_render_mode() == "floating_panel":
            overlay = self.__dict__.get("floating_panel_overlay")
            if overlay is not None and hasattr(overlay, "active_count"):
                return int(overlay.active_count())
            return 0
        if hasattr(self.engine, "visible_display_count"):
            return self.engine.visible_display_count()
        return self.engine.current_display_count()

    def _right_visible_count(self) -> int:
        if hasattr(self.engine, "right_visible_count"):
            return self.engine.right_visible_count()
        return self.engine.right_zone_count()

    def _broadcast_live_overlay_item(self, item, text: str, *, source: str) -> None:
        """Qt 上屏后旁路同步单条弹幕到网页层（仅横向 DanmuItem）。"""
        if text:
            self._schedule_bililive_dm_formula_push(text, source=source, persona="")
        if not isinstance(item, DanmuItem):
            return
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
        except (RuntimeError, ValueError, TypeError) as exc:
            self.logger.debug(f"live overlay broadcast skipped: {exc!r}")

    def _display_danmu_text(
        self,
        content: str,
        persona_id: str,
        *,
        batch_id: int,
        scene_generation: int,
        skip_dedup: bool,
        pre_resolved: bool = False,
    ):
        """按 danmu_render_mode 路由上屏：互斥，floating_panel 不触碰 DanmuEngine。"""
        if self._pet_barrage_mode_enabled():
            return None
        if self._bililive_dm_mode_enabled():
            return None
        if self._danmu_render_mode() == "floating_panel":
            return self._display_floating_panel_text(
                content,
                persona_id,
                batch_id=batch_id,
                scene_generation=scene_generation,
                skip_dedup=skip_dedup,
                pre_resolved=pre_resolved,
            )
        return self.engine.add_text(
            content,
            persona_id,
            batch_id=batch_id,
            scene_generation=scene_generation,
            skip_dedup=skip_dedup,
            pre_resolved=pre_resolved,
        )

    def inject_test_danmu_batch(
        self,
        items: list[str],
        *,
        persona_id: str = "测试",
    ) -> dict[str, object]:
        """主线程测试入口：按正常 reply -> overlay -> history 链路注入一批弹幕。"""
        from app.danmu_engine import resolve_danmu_display_text

        normalized_items = [str(item).strip() for item in items if str(item).strip()]
        if not normalized_items:
            raise ValueError(tr("overlay.test.atLeastOne"))
        if len(normalized_items) > 20:
            raise ValueError(tr("overlay.test.maxInject"))

        request_round = max(int(getattr(self, "screenshot_round", 0)), 0)
        latest_screenshot_id = max(
            int(getattr(self, "_latest_screenshot_id", 0)),
            int(getattr(self, "_latest_queued_screenshot_id", 0)),
            int(getattr(self, "_latest_displayed_screenshot_id", 0)),
            1,
        )
        scene_generation = int(getattr(self, "_scene_generation", 0))
        captured_at = time.monotonic()

        self._batch_id += 1
        batch_id = self._batch_id
        request_id = self._reply_request_id(
            request_round,
            latest_screenshot_id,
            scene_generation,
        )
        batch_items = [
            QueuedReply(
                persona_id,
                request_round,
                content_index,
                item_text,
                screenshot_round=request_round,
                screenshot_id=latest_screenshot_id,
                captured_at=captured_at,
                scene_generation=scene_generation,
                batch_id=batch_id,
                request_id=request_id,
                source="test",
            )
            for content_index, item_text in enumerate(normalized_items)
        ]

        self._latest_queued_screenshot_id = max(
            self._latest_queued_screenshot_id,
            latest_screenshot_id,
        )
        self.reply_buffer.extend(batch_items)
        self._publish_live_status()

        if not self.reply_timer.isActive():
            self._consume_reply_queue()
        elif self.reply_buffer.size() > self._queue_low_watermark:
            self.reply_timer.stop()
            self._consume_reply_queue()
        else:
            self.reply_timer.setInterval(min(self.reply_timer.interval(), 200))

        expected_texts = [
            resolve_danmu_display_text(item_text, self.config, persona_id)
            for item_text in normalized_items
        ]
        visible_texts = []
        if self._danmu_render_mode() == "floating_panel":
            fp_engine = self.__dict__.get("floating_panel_engine")
            if fp_engine is not None:
                visible_texts = [it.content for it in fp_engine.visible_items()]
        elif hasattr(self.engine, "visible_display_texts"):
            visible_texts = list(self.engine.visible_display_texts())
        active_texts = []
        if self._danmu_render_mode() != "floating_panel":
            tracks = getattr(self.engine, "tracks", None)
            if tracks:
                for track in tracks:
                    for item in getattr(track, "items", []):
                        active_texts.append(item.content)

        return {
            "ok": True,
            "queued": len(batch_items),
            "screenshot_id": latest_screenshot_id,
            "expected_texts": expected_texts,
            "visible_texts": visible_texts,
            "active_texts": active_texts,
        }
