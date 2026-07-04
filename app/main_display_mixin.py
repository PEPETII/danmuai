"""DanmuApp 显示辅助 mixin。

职责边界：
- 保留 DanmuApp 作为 Overlay、live overlay、floating panel 相关对象的持有者
- 迁出显示状态快照、旁路广播、显示模式同步与测试注入辅助
- 不迁出 start()/stop() 生命周期编排与主链路本体
"""

from __future__ import annotations

import sys
import time

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from app.config_defaults import resolve_danmu_render_mode
from app.danmu_engine_models import DanmuItem
from app.live_freshness import LiveStatusSnapshot
from app.reply_queue import QueuedReply
from app.snipper import resolve_screen_index, resolve_screen_index_with_meta
from app.translations import tr
from app.win32_overlay_zorder import probe_exclusive_fullscreen_risk

# W-BILILIVE-DM-PLUGIN-FORMULA-008 — 公式化弹幕上屏后旁路推送到 bililive_dm 的来源标识。
_FORMULA_BILILIVE_SOURCES = frozenset(
    {"pool_topup", "pool_duplicate_topup", "meme_barrage"}
)


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
        if source in _FORMULA_BILILIVE_SOURCES and text:
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
        # 未初始化且配置不要求显示桌宠 → 快速跳过（保留 PERF-002 惰性初始化收益）
        if self.__dict__.get("pet_window") is None:
            if self.config.get("pet_enabled", "0") != "1":
                return
            if self.config.get("pet_visible", "0") != "1":
                return
            self._ensure_pet_components()
        from app.pet.pet_facade import sync_pet_window_visibility

        sync_pet_window_visibility(self)

    def _pet_barrage_mode_enabled(self) -> bool:
        return self.config.get("pet_barrage_mode_enabled", "0") == "1"

    def _bililive_dm_mode_enabled(self) -> bool:
        return self.config.get("bililive_dm_mode_enabled", "0") == "1"

    def get_pet_animation_hint(self) -> str:
        from app.pet.pet_facade import get_pet_animation_hint

        return get_pet_animation_hint(self)

    def get_pet_settings_snapshot(self) -> dict[str, object]:
        from app.pet.pet_facade import get_pet_settings_snapshot

        return get_pet_settings_snapshot(self)

    def apply_pet_settings_patch(self, payload: dict[str, object]) -> dict[str, object]:
        from app.pet.pet_facade import apply_pet_settings_patch

        return apply_pet_settings_patch(self, payload)

    def import_pet_asset_via_dialog(self) -> dict[str, object]:
        from app.pet.pet_facade import import_pet_asset_via_dialog

        return import_pet_asset_via_dialog(self)

    def import_pet_barrage_slot_asset_via_dialog(self, slot_id: int) -> dict[str, object]:
        from app.pet.pet_facade import import_pet_barrage_slot_asset_via_dialog

        return import_pet_barrage_slot_asset_via_dialog(self, slot_id)

    def reset_pet_asset_to_builtin(self) -> dict[str, object]:
        from app.pet.pet_facade import reset_pet_asset_to_builtin

        return reset_pet_asset_to_builtin(self)

    def set_pet_barrage_slot_asset(
        self,
        slot_id: int,
        *,
        asset_source: str,
        asset_path: str,
    ) -> dict[str, object]:
        from app.pet.pet_facade import set_pet_barrage_slot_asset

        return set_pet_barrage_slot_asset(
            self,
            slot_id,
            asset_source=asset_source,
            asset_path=asset_path,
        )

    def reset_pet_barrage_slot_asset(self, slot_id: int) -> dict[str, object]:
        from app.pet.pet_facade import reset_pet_barrage_slot_asset

        return reset_pet_barrage_slot_asset(self, slot_id)

    def show_pet(self) -> dict[str, object]:
        self._ensure_pet_components()
        from app.pet.pet_facade import show_pet

        return show_pet(self)

    def hide_pet(self) -> dict[str, object]:
        self._ensure_pet_components()
        from app.pet.pet_facade import hide_pet

        return hide_pet(self)

    def close_pet(self) -> dict[str, object]:
        self._ensure_pet_components()
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
        barrage = self.__dict__.get("pet_barrage_controller")
        if barrage is not None and hasattr(barrage, "notify_success"):
            try:
                barrage.notify_success()
            except RuntimeError as exc:
                self.logger.debug(f"pet barrage success animation skipped: {exc!r}")
        if window is not None:
            try:
                window.notify_reply_success()
            except RuntimeError as exc:
                self.logger.debug(f"pet success animation skipped: {exc!r}")

    def _notify_pet_visual_error(self) -> None:
        window = self.__dict__.get("pet_window")
        barrage = self.__dict__.get("pet_barrage_controller")
        if barrage is not None and hasattr(barrage, "notify_error"):
            try:
                barrage.notify_error()
            except RuntimeError as exc:
                self.logger.debug(f"pet barrage error animation skipped: {exc!r}")
        if window is not None:
            try:
                window.notify_error()
            except RuntimeError as exc:
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

    def _active_overlay_layer(self):
        """当前 danmu_render_mode 下可见的弹幕层（横向 Overlay 或 floating_panel）。"""
        if not self.engine.running:
            return None
        if self._overlay_display_enabled():
            layer = getattr(self, "overlay", None)
            if layer is not None and layer.isVisible():
                return layer
            return None
        if self._floating_panel_v2_enabled():
            layer = self.__dict__.get("floating_panel_overlay")
            if layer is not None and layer.isVisible():
                return layer
        return None

    def _overlay_own_hwnds(self) -> tuple[int, ...]:
        hwnds: list[int] = []
        for key in ("overlay", "floating_panel_overlay", "pet_window"):
            widget = self.__dict__.get(key)
            if widget is None or not widget.isVisible():
                continue
            try:
                hwnd = int(widget.winId())
            except (RuntimeError, ValueError, TypeError):
                hwnd = 0
            if hwnd:
                hwnds.append(hwnd)
        return tuple(hwnds)

    def _reassert_pet_above_overlays(self) -> None:
        pet = self.__dict__.get("pet_window")
        if pet is None or not pet.isVisible():
            return
        settings = getattr(pet, "_settings", None)
        if settings is None or not getattr(settings, "always_on_top", False):
            return
        reassert = getattr(pet, "_reassert_topmost", None)
        if callable(reassert):
            reassert()

    def _reassert_active_overlay_topmost(self) -> None:
        layer = self._active_overlay_layer()
        if layer is None:
            return
        reassert = getattr(layer, "reassert_topmost_zorder", None)
        if callable(reassert):
            reassert()
        self._reassert_pet_above_overlays()

    def _update_screen_index_fallback_warning(self) -> None:
        runtime = self._ensure_web_runtime_state()
        if not self.engine.running:
            runtime.set_screen_index_fallback_warning("")
            return
        _, clamped = resolve_screen_index_with_meta(self.config)
        message = tr("overlay.screen_index_fallback_hint") if clamped else ""
        prev = str(getattr(runtime, "screen_index_fallback_warning", "") or "")
        runtime.set_screen_index_fallback_warning(message)
        if message != prev:
            bridge = getattr(self, "web_bridge", None)
            if bridge:
                bridge.publish_status()

    def _update_overlay_compat_warning(self) -> None:
        runtime = self._ensure_web_runtime_state()
        layer = self._active_overlay_layer()
        if layer is None or sys.platform != "win32":
            runtime.set_overlay_compat_warning("")
            return
        try:
            overlay_hwnd = int(layer.winId())
        except (RuntimeError, ValueError, TypeError):
            runtime.set_overlay_compat_warning("")
            return
        screens = QApplication.screens()
        if not screens:
            runtime.set_overlay_compat_warning("")
            return
        screen_index = resolve_screen_index(self.config)
        screen_index = max(0, min(screen_index, len(screens) - 1))
        geo = screens[screen_index].geometry()
        at_risk = probe_exclusive_fullscreen_risk(
            overlay_hwnd=overlay_hwnd,
            screen_x=geo.x(),
            screen_y=geo.y(),
            screen_w=geo.width(),
            screen_h=geo.height(),
            own_hwnds=self._overlay_own_hwnds(),
        )
        # BUG-004: 连续 3 次 SetWindowPos 失败 → 置顶已失效，优先级高于独占全屏风险启发式
        fail_streak = getattr(layer, "_topmost_fail_streak", 0)
        if fail_streak >= 3:
            message = tr("overlay.topmost_lost")
        elif at_risk:
            message = tr("overlay.exclusive_fullscreen_hint")
        else:
            message = ""
        prev = str(getattr(runtime, "overlay_compat_warning", "") or "")
        runtime.set_overlay_compat_warning(message)
        if message != prev:
            bridge = getattr(self, "web_bridge", None)
            if bridge:
                bridge.publish_status()
        if at_risk:
            _last_fs_warn_key = "_last_fullscreen_warn_tick"
            last_warn = getattr(self, _last_fs_warn_key, 0)
            now = time.monotonic()
            if now - last_warn > 30:
                setattr(self, _last_fs_warn_key, now)
                try:
                    tray_mgr = getattr(self, "tray", None)
                    tray = getattr(tray_mgr, "tray", None) if tray_mgr else None
                except (RuntimeError, AttributeError):
                    tray = None
                if tray is not None and QSystemTrayIcon.isSystemTrayAvailable():
                    tray.showMessage(
                        "DanmuAI",
                        tr("overlay.exclusive_fullscreen_hint"),
                        QSystemTrayIcon.MessageIcon.Warning,
                        8000,
                    )

    def _on_topmost_health_tick(self) -> None:
        if not self.engine.running:
            return
        if self._active_overlay_layer() is None:
            self._ensure_web_runtime_state().set_overlay_compat_warning("")
            return
        self._reassert_active_overlay_topmost()
        self._update_overlay_compat_warning()
        self._update_screen_index_fallback_warning()

    def _display_floating_panel_text(
        self,
        content: str,
        persona_id: str,
        *,
        batch_id: int,
        scene_generation: int,
        skip_dedup: bool,
        pre_resolved: bool = False,
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
                pre_resolved=pre_resolved,
            )
        except (RuntimeError, ValueError, TypeError) as exc:
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

    def _schedule_bililive_dm_push_items(
        self,
        *,
        batch_id: int,
        items: list[str],
        persona: str,
        log_source: str,
    ) -> None:
        """主线程：弹幕姬模式开启时，把最终显示文本旁路推送到 bililive_dm 插件。"""
        if not self._bililive_dm_mode_enabled():
            return
        from app.application.bililive_dm_push_service import schedule_push_batch
        from app.danmu_engine import resolve_danmu_display_text

        display_items = [
            resolve_danmu_display_text(item_text, self.config, persona)
            for item_text in items
            if str(item_text).strip()
        ]
        if not display_items:
            return
        self.logger.debug(
            "bililive_dm_push: scheduling source=%s batch_id=%s count=%d",
            log_source,
            batch_id,
            len(display_items),
        )
        schedule_push_batch(
            batch_id=batch_id,
            items=display_items,
            persona=persona or None,
        )

    def _schedule_bililive_dm_push(
        self,
        persona_id: str,
        batch_id: int,
        normalized_items: list[str],
    ) -> None:
        """主线程：弹幕姬模式开启时，把 AI 批次最终显示文本旁路推送到 bililive_dm 插件。"""
        self._schedule_bililive_dm_push_items(
            batch_id=batch_id,
            items=normalized_items,
            persona=persona_id,
            log_source="ai",
        )

    def _schedule_bililive_dm_formula_push(
        self,
        text: str,
        *,
        source: str,
        persona: str = "",
    ) -> None:
        """主线程：公式化弹幕上屏后旁路推送到 bililive_dm（不经过 reply_buffer）。"""
        if source not in _FORMULA_BILILIVE_SOURCES:
            return
        log_source = "meme_barrage" if source == "meme_barrage" else "formula_pool"
        self._batch_id = int(getattr(self, "_batch_id", 0)) + 1
        self._schedule_bililive_dm_push_items(
            batch_id=self._batch_id,
            items=[text],
            persona=persona,
            log_source=log_source,
        )
