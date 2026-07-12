"""DanmuApp 横向 Overlay 可见性 mixin。

职责边界：
- engine.running 时按 danmu_render_mode 显示或隐藏横向 Overlay
- 不迁出 app/overlay.py 实现
"""

from __future__ import annotations

from app.snipper import resolve_screen_index


class DanmuAppOverlayMixin:
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
