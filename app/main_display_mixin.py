"""DanmuApp 显示辅助 mixin。

职责边界：
- 保留 DanmuApp 作为 Overlay、live overlay、floating panel 相关对象的持有者
- 迁出显示状态快照、旁路广播、显示模式同步与测试注入辅助
- 不迁出 start()/stop() 生命周期编排与主链路本体
"""

from __future__ import annotations

import os
import time

from app.config_defaults import resolve_danmu_render_mode
from app.danmu_engine_models import DanmuItem
from app.live_freshness import LiveStatusSnapshot
from app.reply_queue import QueuedReply
from app.snipper import resolve_screen_index


class DanmuAppDisplayMixin:
    def _danmu_render_mode(self) -> str:
        return resolve_danmu_render_mode(self.config)

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
        except Exception as exc:
            self.logger.debug(f"live overlay broadcast skipped: {exc!r}")

    def _overlay_display_enabled(self) -> bool:
        return self._danmu_render_mode() == "scrolling"

    def _floating_panel_v2_enabled(self) -> bool:
        return self._danmu_render_mode() == "floating_panel"

    def _sync_overlay_visibility(self) -> None:
        """engine.running 时按 danmu_render_mode 显示或隐藏横向 Overlay。"""
        if not self.engine.running:
            return
        if self._overlay_display_enabled():
            self.overlay.show_for_screen(resolve_screen_index(self.config))
            self.overlay.ensure_render_loop()
        else:
            self.overlay.stop_render_loop()
            self.overlay.hide()

    def _sync_pet_window_visibility(self) -> None:
        """独立于 danmu_render_mode；pet_enabled + pet_visible 控制桌宠显隐。"""
        from app.pet.pet_facade import sync_pet_window_visibility

        sync_pet_window_visibility(self)

    def get_pet_animation_hint(self) -> str:
        from app.pet.pet_facade import get_pet_animation_hint

        return get_pet_animation_hint(self)

    def get_pet_settings_snapshot(self) -> dict[str, object]:
        from app.pet.pet_facade import get_pet_settings_snapshot

        return get_pet_settings_snapshot(self)

    def apply_pet_settings_patch(self, payload: dict[str, object]) -> dict[str, object]:
        from app.pet.pet_facade import apply_pet_settings_patch

        return apply_pet_settings_patch(self, payload)

    def show_pet(self) -> dict[str, object]:
        from app.pet.pet_facade import show_pet

        return show_pet(self)

    def hide_pet(self) -> dict[str, object]:
        from app.pet.pet_facade import hide_pet

        return hide_pet(self)

    def close_pet(self) -> dict[str, object]:
        from app.pet.pet_facade import close_pet

        return close_pet(self)

    def submit_pet_command(self, text: str, *, source: str = "web_api") -> dict[str, object]:
        from app.pet.pet_facade import submit_pet_command

        return submit_pet_command(self, text, source=source)

    def get_pet_status_snapshot(self) -> dict[str, object]:
        from app.pet.pet_facade import get_pet_status_snapshot

        return get_pet_status_snapshot(self)

    def _notify_pet_visual_success(self) -> None:
        window = self.__dict__.get("pet_window")
        if window is not None:
            try:
                window.notify_reply_success()
            except Exception as exc:
                self.logger.debug(f"pet success animation skipped: {exc!r}")

    def _notify_pet_visual_error(self) -> None:
        window = self.__dict__.get("pet_window")
        if window is not None:
            try:
                window.notify_error()
            except Exception as exc:
                self.logger.debug(f"pet error animation skipped: {exc!r}")

    def _sync_floating_panel_visibility(self) -> None:
        """engine.running 时按 danmu_render_mode 显示或隐藏侧边悬浮窗 V2。"""
        if not self.engine.running:
            return
        overlay = self.__dict__.get("floating_panel_overlay")
        engine = self.__dict__.get("floating_panel_engine")
        if overlay is None or engine is None:
            return
        if self._floating_panel_v2_enabled():
            engine.start()
            overlay.show_for_screen(resolve_screen_index(self.config))
        else:
            overlay.stop_render_loop()
            overlay.hide()

    def _display_floating_panel_text(
        self,
        content: str,
        persona_id: str,
        *,
        batch_id: int,
        scene_generation: int,
        skip_dedup: bool,
    ):
        overlay = self.__dict__.get("floating_panel_overlay")
        if overlay is None:
            return None
        try:
            return overlay.add_danmu_text(
                content,
                persona_id or "",
                batch_id=batch_id,
                scene_generation=scene_generation,
                skip_dedup=skip_dedup,
            )
        except Exception as exc:
            self.logger.debug(f"floating panel display skipped: {exc!r}")
            return None

    def _display_danmu_text(
        self,
        content: str,
        persona_id: str,
        *,
        batch_id: int,
        scene_generation: int,
        skip_dedup: bool,
    ):
        """按 danmu_render_mode 路由上屏：互斥，floating_panel 不触碰 DanmuEngine。"""
        if self._danmu_render_mode() == "floating_panel":
            return self._display_floating_panel_text(
                content,
                persona_id,
                batch_id=batch_id,
                scene_generation=scene_generation,
                skip_dedup=skip_dedup,
            )
        return self.engine.add_text(
            content,
            persona_id,
            batch_id=batch_id,
            scene_generation=scene_generation,
            skip_dedup=skip_dedup,
        )

    def inject_test_danmu_batch(
        self,
        items: list[str],
        *,
        persona_id: str = "测试",
    ) -> dict[str, object]:
        """主线程测试入口：按正常 reply -> overlay -> history 链路注入一批弹幕。"""
        from app.danmu_engine import normalize_danmu_display_text

        normalized_items = [str(item).strip() for item in items if str(item).strip()]
        if not normalized_items:
            raise ValueError("请至少提供一条弹幕")
        if len(normalized_items) > 20:
            raise ValueError("单次最多注入 20 条弹幕")

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
                memory_eligible=False,
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
            normalize_danmu_display_text(item_text, self.config)
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
