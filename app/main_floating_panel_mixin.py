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

from app.floating_panel_geometry import compute_panel_geometry
from app.snipper import resolve_screen_index

_PANEL_POSITION_SETTLE_SEC = 0.25


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
        return str(self.config.get("floating_panel_click_through", "1") or "1").strip() == "1"

    def _sync_web_panel_click_through(self) -> None:
        """配置热变更时同步 WebView 穿透状态，必要时重建窗口。"""
        process = self.__dict__.get("_panel_process")
        enabled = self._panel_click_through_enabled()
        if not self.__dict__.get("_panel_web_active") or process is None:
            if enabled:
                self._stop_panel_position_tracking(force=True)
            return
        if enabled:
            # Capture the native origin before changing transparency: a state
            # change restarts the child and must reuse the final dragged origin.
            self._stop_panel_position_tracking(force=True)
        try:
            process.set_click_through(enabled)
        except Exception as exc:
            self.logger.debug(f"panel click-through sync skipped: {exc!r}")
        finally:
            if enabled:
                self._stop_panel_position_tracking(force=True)
            else:
                self._start_panel_position_tracking()

    def _panel_current_position(self) -> tuple[int, int] | None:
        process = self.__dict__.get("_panel_process")
        if self.__dict__.get("_panel_web_active") and process is not None:
            try:
                position = process.current_position()
            except Exception as exc:
                self.logger.debug(f"panel position read skipped: {exc!r}")
                position = None
            if position is not None:
                return int(position[0]), int(position[1])
        overlay = self.__dict__.get("floating_panel_overlay")
        if overlay is not None:
            try:
                if overlay.isVisible():
                    return int(overlay.x()), int(overlay.y())
            except (RuntimeError, TypeError, ValueError):
                pass
        return None

    def _save_panel_position(self, position: tuple[int, int] | None) -> None:
        if position is None:
            return
        x = max(-32000, min(32000, int(position[0])))
        y = max(-32000, min(32000, int(position[1])))
        items: dict[str, str] = {}
        if str(self.config.get("floating_panel_x", "") or "") != str(x):
            items["floating_panel_x"] = str(x)
        if str(self.config.get("floating_panel_y", "") or "") != str(y):
            items["floating_panel_y"] = str(y)
        if items:
            self.config.set_batch(items)
        self.__dict__["_panel_position_last_saved"] = (x, y)

    def _start_panel_position_tracking(self) -> None:
        timer = self.__dict__.get("_panel_position_timer")
        if timer is None:
            return
        position = self._panel_current_position()
        state = self.__dict__
        state["_panel_position_candidate"] = position
        state["_panel_position_last_changed_at"] = time.monotonic()
        state["_panel_position_last_saved"] = position
        try:
            timer.start()
        except (RuntimeError, TypeError):
            pass

    def _stop_panel_position_tracking(self, *, force: bool) -> None:
        timer = self.__dict__.get("_panel_position_timer")
        if timer is not None:
            try:
                timer.stop()
            except (RuntimeError, TypeError):
                pass
        state = self.__dict__
        if force:
            position = self._panel_current_position()
            if position is None:
                position = state.get("_panel_position_candidate")
            self._save_panel_position(position)
        state["_panel_position_candidate"] = None
        state["_panel_position_last_changed_at"] = 0.0

    def _on_panel_position_tick(self) -> None:
        """Persist a settled native origin without touching Qt window objects."""
        if (
            not self.__dict__.get("_panel_web_active")
            or self.__dict__.get("_panel_process") is None
            or self._panel_click_through_enabled()
        ):
            self._stop_panel_position_tracking(force=False)
            return
        position = self._panel_current_position()
        if position is None:
            return
        state = self.__dict__
        now = time.monotonic()
        candidate = state.get("_panel_position_candidate")
        if candidate != position:
            state["_panel_position_candidate"] = position
            state["_panel_position_last_changed_at"] = now
            return
        if now - float(state.get("_panel_position_last_changed_at", now)) < _PANEL_POSITION_SETTLE_SEC:
            return
        if state.get("_panel_position_last_saved") != position:
            self._save_panel_position(position)

    def _recover_web_panel_position_after_screen_change(self) -> None:
        """Recreate the existing WebView at a clamped origin after monitor changes."""
        process = self.__dict__.get("_panel_process")
        if not self.__dict__.get("_panel_web_active") or process is None:
            return
        interactive = not self._panel_click_through_enabled()
        if interactive:
            # A topology change can arrive before the 250 ms settle window. Capture
            # the real native origin before clamping it to the remaining screens.
            self._stop_panel_position_tracking(force=True)
        try:
            recovered = process.set_geometry(*self._panel_geometry())
            if interactive and recovered:
                self._start_panel_position_tracking()
        except Exception as exc:
            self.logger.debug(f"panel screen geometry recovery skipped: {exc!r}")

    def _panel_html_url(self) -> str | None:
        server = getattr(self, "web_server", None)
        if server is None:
            return None
        base = str(getattr(server, "base_url", "") or "").rstrip("/")
        token = str(getattr(server, "token", "") or "")
        if not base:
            return None
        query = urlencode(
            {
                **({"ws_token": token} if token else {}),
                "click_through": "1" if self._panel_click_through_enabled() else "0",
            }
        )
        path = f"{base}/static/floating_panel/index.html"
        return f"{path}?{query}"

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

        return compute_panel_geometry(
            list(QApplication.screens()),
            config=self.config,
            width=width,
            x_offset=x_off,
            y_offset=y_off,
            preferred_screen_index=resolve_screen_index(self.config),
            use_available_geometry=True,
        )

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
            if self._panel_click_through_enabled():
                self._stop_panel_position_tracking(force=False)
            else:
                self._start_panel_position_tracking()
            self._push_panel_config()
        return ok

    def _stop_web_panel(self) -> None:
        self._stop_panel_position_tracking(force=True)
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
                max_cards=max(1, int(snap.max_items)),
                stack_gap=max(0, int(snap.stack_gap)),
                panel_padding=16,
                entry_animation=str(snap.entry_animation or "fade"),
                entry_duration_ms=max(0, int(snap.entry_duration_ms)),
                push_duration_ms=max(0, int(snap.push_duration_ms)),
                exit_animation=str(snap.exit_animation or "fade"),
                exit_duration_ms=max(0, int(snap.exit_duration_ms)),
                panel_position="bottom-left",
                panel_width=int(width),
                panel_height=int(height),
                panel_opacity=max(0, min(100, int(snap.panel_opacity))),
                click_through=self._panel_click_through_enabled(),
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
        from app.persona_display import persona_display_name_with_config

        username = ""
        if str(persona_id or "").strip():
            username = persona_display_name_with_config(persona_id, self.config).strip()
        username = username or str(snap.username_text or "").strip() or "AI"

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

        # Keep valid zero-valued style fields (transparent classic preset,
        # zero radius/padding) instead of treating them as missing defaults.
        def _style_int(value: int | None, fallback: int) -> int:
            return fallback if value is None else int(value)

        style = CardStyle(
            card_bg=str(card_color),
            card_border=str(snap.border_color or "#fbbf24"),
            username_color=str(snap.username_color or "#f59e0b"),
            content_color=str(text_color),
            outline_color=str(snap.outline_color or "#ffffff"),
            font_family=str(snap.font_family or "Microsoft YaHei, PingFang SC, sans-serif"),
            font_size_username=int(snap.username_size or 12),
            font_size_content=int(snap.content_size or snap.font_size or 14),
            border_radius=_style_int(snap.radius, 12),
            max_width=max(120, int(snap.width or 280) - 40),
            box_shadow=box_shadow,
            # 新增扩展字段
            shape=str(snap.shape or "bubble"),
            card_opacity=_style_int(snap.card_opacity, 88),
            border_enabled=bool(snap.border_enabled),
            border_width=_style_int(snap.border_width, 1),
            border_opacity=_style_int(snap.border_opacity, 40),
            outline_enabled=bool(snap.outline_enabled),
            outline_width=_style_int(snap.outline_width, 2),
            shadow_enabled=bool(snap.shadow_enabled),
            padding_x=_style_int(snap.padding_x, 14),
            padding_y=_style_int(snap.padding_y, 10),
            tail_enabled=bool(snap.tail_enabled),
            tail_style=str(snap.tail_style or "round"),
            tail_width=_style_int(snap.tail_width, 8),
            tail_height=_style_int(snap.tail_height, 10),
            tail_offset_y=_style_int(snap.tail_offset_y, 38),
            username_enabled=bool(snap.username_enabled),
            username_weight=int(snap.username_weight or 700),
            # Preserve empty separator (blivechat_line); only default when missing/None
            username_separator=(
                "" if snap.username_separator is None else str(snap.username_separator)
            ),
            content_weight=int(snap.content_weight or 400),
            content_line_height=int(snap.content_line_height or 140),
            gap_username_content=int(snap.gap_username_content or 4),
            font_bold=bool(snap.font_bold),
            layout=str(snap.layout or "inline"),
            tail_border=int(snap.tail_border if snap.tail_border is not None else 8),
            tail_long_side=int(
                snap.tail_long_side if snap.tail_long_side is not None else 18
            ),
            tail_rotate_deg=int(
                snap.tail_rotate_deg if snap.tail_rotate_deg is not None else 35
            ),
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
