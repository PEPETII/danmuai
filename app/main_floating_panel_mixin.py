"""DanmuApp 浮动面板可见性与上屏 mixin。

职责边界：
- floating_panel V2 显隐同步（QPainter Overlay 或 pywebview Web 面板）
- floating_panel 文本上屏（Engine 去重/堆积 + WS card 或 Overlay 渲染）
- 不迁出 app/floating_panel_*.py 算法/QPainter 实现
"""

from __future__ import annotations

import time
import uuid
from typing import Any
from urllib.parse import urlencode

from app.snipper import resolve_screen_index


class DanmuAppFloatingPanelMixin:
    def _ensure_panel_web_components(self) -> None:
        if self.__dict__.get("_panel_bridge") is None:
            server = getattr(self, "web_server", None)
            bridge = getattr(server, "bridge", None) if server is not None else None
            panel_bridge = getattr(bridge, "panel_bridge", None) if bridge is not None else None
            if panel_bridge is None:
                from app.floating_panel_web.panel_bridge import PanelBridge

                panel_bridge = PanelBridge()
            self._panel_bridge = panel_bridge
        if self.__dict__.get("_panel_process") is None:
            from app.floating_panel_web.panel_process import PanelProcess

            self._panel_process = PanelProcess(logger_=self.logger)
        if self.__dict__.get("_panel_web_active") is None:
            self._panel_web_active = False

    def _should_use_web_panel(self) -> bool:
        """WebView2 可用 + floating_panel_use_web 默认开 + 重启未超限。"""
        self._ensure_panel_web_components()
        process = self._panel_process
        if getattr(process, "fallback_to_qpainter_called", False):
            return False
        if int(getattr(process, "restart_count", 0) or 0) >= 3 and not process.is_alive():
            return False
        try:
            from app.webview2_runtime import is_webview2_runtime_available

            if not is_webview2_runtime_available():
                return False
        except Exception:
            return False
        flag = str(self.config.get("floating_panel_use_web", "1") or "1").strip()
        return flag == "1"

    def _panel_click_through_enabled(self) -> bool:
        return str(self.config.get("floating_panel_click_through", "0") or "0").strip() == "1"

    def _panel_html_url(self) -> str | None:
        server = getattr(self, "web_server", None)
        if server is None:
            return None
        base = str(getattr(server, "base_url", "") or "").rstrip("/")
        token = str(getattr(server, "token", "") or "")
        if not base:
            return None
        query = urlencode({"ws_token": token}) if token else ""
        path = f"{base}/static/floating_panel/index.html"
        return f"{path}?{query}" if query else path

    def _panel_geometry(self) -> tuple[int, int, int, int]:
        """Return (width, height, x, y) in screen coordinates."""
        from PyQt6.QtWidgets import QApplication

        width = 360
        x_off = 20
        y_off = 80
        try:
            width = max(200, min(800, int(self.config.get("floating_panel_width", "360") or 360)))
        except (TypeError, ValueError):
            pass
        try:
            x_off = max(0, min(400, int(self.config.get("floating_panel_x_offset", "20") or 20)))
        except (TypeError, ValueError):
            pass
        try:
            y_off = max(0, min(400, int(self.config.get("floating_panel_y_offset", "80") or 80)))
        except (TypeError, ValueError):
            pass

        screens = QApplication.screens()
        idx = resolve_screen_index(self.config)
        if not screens:
            return width, 600, x_off, y_off
        screen = screens[max(0, min(idx, len(screens) - 1))]
        geo = screen.availableGeometry()
        height = max(160, int(geo.height()) - y_off * 2)
        x = int(geo.x()) + int(geo.width()) - width - x_off
        y = int(geo.y()) + y_off
        return width, height, x, y

    def _start_web_panel(self) -> bool:
        self._ensure_panel_web_components()
        url = self._panel_html_url()
        if not url:
            return False
        width, height, x, y = self._panel_geometry()
        ok = self._panel_process.start(
            url,
            width=width,
            height=height,
            x=x,
            y=y,
            click_through=self._panel_click_through_enabled(),
        )
        self._panel_web_active = bool(ok)
        if ok:
            self._push_panel_config()
        return ok

    def _stop_web_panel(self) -> None:
        process = self.__dict__.get("_panel_process")
        if process is not None:
            try:
                process.stop()
            except Exception as exc:
                self.logger.debug(f"panel process stop skipped: {exc!r}")
        self._panel_web_active = False
        bridge = self.__dict__.get("_panel_bridge")
        if bridge is not None:
            try:
                bridge.enqueue_message({"type": "clear", "reason": "user_action"})
            except Exception:
                pass

    def _push_panel_config(self) -> None:
        bridge = self.__dict__.get("_panel_bridge")
        if bridge is None:
            return
        try:
            from app.floating_panel_style import style_snapshot_from_mapping
            from app.floating_panel_web.panel_protocol import ConfigMessage

            snap = style_snapshot_from_mapping(self.config)
            width, height, _x, _y = self._panel_geometry()
            msg = ConfigMessage(
                max_cards=max(1, int(snap.max_items or 6)),
                stack_gap=int(snap.stack_gap or 8),
                panel_padding=16,
                entry_duration_ms=int(snap.entry_duration_ms or 250),
                exit_duration_ms=int(snap.exit_duration_ms or 250),
                panel_position="bottom-left",
                panel_width=int(width),
                panel_height=int(height),
                panel_opacity=int(snap.panel_opacity or 85),
            )
            bridge.enqueue_message(msg.to_dict())
        except Exception as exc:
            self.logger.debug(f"panel config push skipped: {exc!r}")

    def _build_web_panel_card_dict(
        self,
        content: str,
        persona_id: str,
        *,
        style_index: int = 0,
    ) -> dict[str, Any]:
        from app.floating_panel_style import pick_palette_color, style_snapshot_from_mapping
        from app.floating_panel_web.panel_protocol import CardMessage, CardStyle

        snap = style_snapshot_from_mapping(self.config)
        idx = int(style_index)
        card_color = pick_palette_color(
            snap.card_colors, snap.card_color_mode, snap.card_color_weights, idx,
            fallback="#fff7ed",
        )
        text_color = pick_palette_color(
            snap.text_colors, snap.text_color_mode, snap.text_color_weights, idx,
            fallback="#1f2937",
        )
        username = str(snap.username_text or "").strip() or (persona_id or "AI")

        # Build box_shadow string from snap shadow fields (respect shadow_color)
        if snap.shadow_enabled:
            raw_sc = str(snap.shadow_color or "#000000").lstrip("#")
            try:
                if len(raw_sc) >= 6:
                    sr = int(raw_sc[0:2], 16)
                    sg = int(raw_sc[2:4], 16)
                    sb = int(raw_sc[4:6], 16)
                else:
                    sr, sg, sb = 0, 0, 0
            except ValueError:
                sr, sg, sb = 0, 0, 0
            sa = max(0, min(100, int(snap.shadow_opacity or 0))) / 100.0
            box_shadow = (
                f"{snap.shadow_offset_x}px {snap.shadow_offset_y}px "
                f"{snap.shadow_blur}px "
                f"rgba({sr},{sg},{sb},{sa})"
            )
        else:
            box_shadow = "none"

        style = CardStyle(
            card_bg=str(card_color),
            card_border=str(snap.border_color or "#fbbf24"),
            username_color=str(snap.username_color or "#f59e0b"),
            content_color=str(text_color),
            outline_color=str(snap.outline_color or "#ffffff"),
            font_family=str(snap.font_family or "Microsoft YaHei, PingFang SC, sans-serif"),
            font_size_username=int(snap.username_size or 12),
            font_size_content=int(snap.content_size or snap.font_size or 14),
            border_radius=int(snap.radius or 12),
            max_width=max(120, int(snap.width or 280) - 40),
            box_shadow=box_shadow,
            # 新增扩展字段
            shape=str(snap.shape or "bubble"),
            card_opacity=int(snap.card_opacity or 88),
            border_enabled=bool(snap.border_enabled),
            border_width=int(snap.border_width or 1),
            border_opacity=int(snap.border_opacity or 40),
            outline_enabled=bool(snap.outline_enabled),
            outline_width=int(snap.outline_width or 2),
            shadow_enabled=bool(snap.shadow_enabled),
            padding_x=int(snap.padding_x or 14),
            padding_y=int(snap.padding_y or 10),
            tail_enabled=bool(snap.tail_enabled),
            tail_style=str(snap.tail_style or "round"),
            tail_width=int(snap.tail_width or 8),
            tail_height=int(snap.tail_height or 10),
            tail_offset_y=int(snap.tail_offset_y or 38),
            username_enabled=bool(snap.username_enabled),
            username_weight=int(snap.username_weight or 700),
            username_separator=str(snap.username_separator or "："),
            content_weight=int(snap.content_weight or 400),
            content_line_height=int(snap.content_line_height or 140),
            gap_username_content=int(snap.gap_username_content or 4),
            font_bold=bool(snap.font_bold),
        )
        msg = CardMessage(
            id=str(uuid.uuid4()),
            username=username,
            content=str(content),
            persona_id=str(persona_id or ""),
            style=style,
            timestamp=int(time.time() * 1000),
        )
        return msg.to_dict()

    def _sync_floating_panel_visibility(self) -> None:
        """engine.running 时按 danmu_render_mode 显示或隐藏侧边悬浮窗 V2。"""
        if not self.engine.running:
            self._stop_web_panel()
            return
        overlay = self.__dict__.get("floating_panel_overlay")
        engine = self.__dict__.get("floating_panel_engine")
        if overlay is None or engine is None:
            return
        if self._floating_panel_v2_enabled():
            engine.start()
            if self._should_use_web_panel():
                # hide QPainter layer while web panel is active
                try:
                    overlay.stop_render_loop()
                    overlay.hide()
                except Exception:
                    pass
                if not self.__dict__.get("_panel_web_active") or not self._panel_process.is_alive():
                    if not self._start_web_panel():
                        # fallback QPainter
                        overlay.show_for_screen(resolve_screen_index(self.config))
                        self._panel_web_active = False
            else:
                self._stop_web_panel()
                overlay.show_for_screen(resolve_screen_index(self.config))
        else:
            self._stop_web_panel()
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
        pre_resolved: bool = False,
    ):
        engine = self.__dict__.get("floating_panel_engine")
        overlay = self.__dict__.get("floating_panel_overlay")
        if engine is None:
            return None

        use_web = bool(self.__dict__.get("_panel_web_active")) and self._should_use_web_panel()
        if use_web:
            self._ensure_panel_web_components()
            try:
                item_height = 56.0
                if overlay is not None:
                    try:
                        item_height = float(overlay._estimate_item_height())  # noqa: SLF001
                    except Exception:
                        item_height = 56.0
                item = engine.add_text(
                    content,
                    persona_id or "",
                    item_height=item_height,
                    batch_id=batch_id,
                    scene_generation=scene_generation,
                    skip_dedup=skip_dedup,
                    pre_resolved=pre_resolved,
                )
                if item is None:
                    return None
                card = self._build_web_panel_card_dict(
                    item.content,
                    persona_id or "",
                    style_index=int(getattr(item, "style_index", 0) or 0),
                )
                self._panel_bridge.enqueue_card(card)
                return item
            except (RuntimeError, ValueError, TypeError) as exc:
                self.logger.debug(f"floating panel web display skipped: {exc!r}")
                return None

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

    def stop(self) -> None:
        try:
            self._stop_web_panel()
        except Exception:
            pass
        super().stop()

    def quit(self) -> None:
        try:
            self._stop_web_panel()
            bridge = self.__dict__.get("_panel_bridge")
            if bridge is not None:
                bridge.shutdown()
        except Exception:
            pass
        super().quit()
