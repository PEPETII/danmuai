"""DanmuApp bililive_dm 旁路推送 mixin。

职责边界：
- 弹幕姬模式下 AI / 公式化弹幕旁路推送到 bililive_dm 插件
- 不迁出 app/application/bililive_dm_push_service.py 实现
"""

from __future__ import annotations

# W-BILILIVE-DM-PLUGIN-FORMULA-008 — 公式化弹幕上屏后旁路推送到 bililive_dm 的来源标识。
_FORMULA_BILILIVE_SOURCES = frozenset(
    {"pool_topup", "pool_duplicate_topup", "meme_barrage"}
)


class DanmuAppBililiveDmMixin:
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
