"""DanmuApp 浮动面板可见性与上屏 mixin。

职责边界：
- floating_panel V2 显隐同步
- floating_panel 文本上屏
- 不迁出 app/floating_panel_*.py 实现
"""

from __future__ import annotations

from app.snipper import resolve_screen_index


class DanmuAppFloatingPanelMixin:
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
