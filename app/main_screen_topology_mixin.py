"""DanmuApp 屏幕拓扑与 Overlay 置顶健康 mixin。

职责边界：
- 多显示器拓扑变更恢复
- Overlay / floating_panel 置顶健康检查与兼容警告
- 不迁出 app/win32_overlay_zorder.py 实现
"""

from __future__ import annotations

import sys
import time

from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from app.snipper import resolve_screen_index, resolve_screen_index_with_meta
from app.translations import tr
from app.win32_overlay_zorder import get_foreground_hwnd, probe_exclusive_fullscreen_risk


class DanmuAppScreenTopologyMixin:
    def _bind_screen_recovery_signals(self) -> None:
        """Reconnect overlay when displays become available after RDP/GPU recovery."""
        app = QApplication.instance()
        if app is None or getattr(self, "_screen_recovery_bound", False):
            return
        app.screenAdded.connect(self._on_screen_topology_changed)
        app.screenRemoved.connect(self._on_screen_topology_changed)
        self._screen_recovery_bound = True

    def _on_screen_topology_changed(self, *_args) -> None:
        if not self.engine.running:
            return
        self._sync_overlay_visibility()
        self._sync_floating_panel_visibility()
        self._update_overlay_compat_warning()
        bridge = getattr(self, "web_bridge", None)
        if bridge is not None:
            bridge.publish_status()

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

    def _update_overlay_compat_warning(self, *, foreground_hwnd: int | None = None) -> None:
        runtime = self._ensure_web_runtime_state()
        if sys.platform != "win32" or not self.engine.running:
            runtime.set_overlay_compat_warning("")
            self.__dict__["_last_fullscreen_at_risk"] = False
            return
        screens = QApplication.screens()
        danmu_overlay = getattr(self, "overlay", None)
        fp_overlay = self.__dict__.get("floating_panel_overlay")
        overlay_unavailable = bool(
            getattr(danmu_overlay, "_overlay_screen_unavailable", False)
        )
        fp_unavailable = bool(getattr(fp_overlay, "_screen_unavailable", False))
        if not screens or overlay_unavailable or fp_unavailable:
            message = tr("overlay.screens_unavailable_hint")
            prev = str(getattr(runtime, "overlay_compat_warning", "") or "")
            runtime.set_overlay_compat_warning(message)
            self.__dict__["_last_fullscreen_at_risk"] = False
            if message != prev:
                bridge = getattr(self, "web_bridge", None)
                if bridge:
                    bridge.publish_status()
            return
        layer = self._active_overlay_layer()
        if layer is None:
            runtime.set_overlay_compat_warning("")
            self.__dict__["_last_fullscreen_at_risk"] = False
            return
        try:
            overlay_hwnd = int(layer.winId())
        except (RuntimeError, ValueError, TypeError):
            runtime.set_overlay_compat_warning("")
            self.__dict__["_last_fullscreen_at_risk"] = False
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
            foreground_hwnd=foreground_hwnd,
        )
        self.__dict__["_last_fullscreen_at_risk"] = at_risk
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
        layer = self._active_overlay_layer()
        if layer is None:
            self._ensure_web_runtime_state().set_overlay_compat_warning("")
            self.__dict__["_last_foreground_hwnd"] = 0
            self.__dict__["_last_fullscreen_at_risk"] = False
            return

        from app.main_helpers import TOPMOST_HEALTH_HEARTBEAT_TICKS

        fg = get_foreground_hwnd()
        state = self.__dict__
        last_fg = int(state.get("_last_foreground_hwnd", 0) or 0)
        fg_changed = fg != last_fg
        state["_last_foreground_hwnd"] = fg

        fail_streak = int(getattr(layer, "_topmost_fail_streak", 0) or 0)
        tick = int(state.get("_topmost_health_tick", 0) or 0) + 1
        state["_topmost_health_tick"] = tick
        heartbeat = tick % TOPMOST_HEALTH_HEARTBEAT_TICKS == 0

        needs_reassert = fg_changed or fail_streak > 0 or heartbeat
        last_at_risk = bool(state.get("_last_fullscreen_at_risk", False))
        needs_probe = needs_reassert or last_at_risk

        if needs_reassert:
            self._reassert_active_overlay_topmost()
        if needs_probe:
            self._update_overlay_compat_warning(foreground_hwnd=fg or None)
        self._update_screen_index_fallback_warning()
