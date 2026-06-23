from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from PyQt6.QtGui import QColor, QPixmap

if TYPE_CHECKING:
    from app.danmu_engine import DanmuEngine

_ENTRY_ZONE_PX_FALLBACK = 300.0

# 防御性 fallback 常量：当 item.width <= 0 时使用。
# DanmuEngine.add_text() 会用 _estimate_content_width() 覆盖为更精确的动态估算值。
_DANMU_FALLBACK_CHAR_WIDTH = 25.0


@dataclass
class DanmuItem:
    """单条弹幕条目，包含位置、速度、可见性与渲染缓存状态。"""

    content: str
    persona: str = ""
    color: QColor = field(default_factory=lambda: QColor(255, 255, 255))
    x: float = 0.0
    y: float = 0.0
    speed: float = 3.0
    width: float = 0.0
    batch_id: int = 0
    scene_generation: int = 0
    _pixmap: QPixmap | None = field(default=None, repr=False, compare=False)
    _opacity_cache_bucket: int | None = field(default=None, repr=False, compare=False)
    _cached_opacity: float | None = field(default=None, repr=False, compare=False)
    _vis_on_screen: bool = field(default=False, repr=False, compare=False)
    _right_vis_on_screen: bool = field(default=False, repr=False, compare=False)
    _in_fade_zone: bool = field(default=False, repr=False, compare=False)
    _cached_engine_entry_zone: bool = field(default=False, repr=False, compare=False)
    _cached_offscreen_pending: bool = field(default=False, repr=False, compare=False)
    _cached_track_entry_zone: bool = field(default=False, repr=False, compare=False)
    _needs_motion_tick: bool = field(default=False, repr=False, compare=False)


class Track:
    """单条水平轨道：持有该行 DanmuItem，并维护入口区密度与更新。"""

    def __init__(self, y: float):
        self.y = y
        self.items: list[DanmuItem] = []
        self.entry_zone_count_cached: int = 0
        self.tail_right_edge: float = float("-inf")
        self._tail_item: DanmuItem | None = None
        self.furthest_offscreen_x: float = float("-inf")
        self._furthest_offscreen_item: DanmuItem | None = None

    @staticmethod
    def item_right_edge(item: DanmuItem) -> float:
        w = item.width if item.width > 0 else len(item.content) * _DANMU_FALLBACK_CHAR_WIDTH
        return item.x + w

    def can_accept(self, item: DanmuItem, screen_width: float, min_gap: float = 150.0) -> bool:
        if not self.items:
            return True
        last = self.items[-1]
        w = last.width if last.width > 0 else (len(last.content) * _DANMU_FALLBACK_CHAR_WIDTH)
        return last.x + w + min_gap < screen_width

    def entry_zone_count(
        self,
        screen_width: float,
        zone: float = _ENTRY_ZONE_PX_FALLBACK,
    ) -> int:
        zone_left = screen_width - zone
        live = sum(
            1 for it in self.items if it.x + it.width > zone_left and it.x < screen_width
        )
        if zone != _ENTRY_ZONE_PX_FALLBACK:
            return live
        if live != self.entry_zone_count_cached:
            self.entry_zone_count_cached = live
        return self.entry_zone_count_cached

    def rightmost_edge(self) -> float:
        if not self.items:
            return float("-inf")
        if self._tail_item is not None and self._tail_item in self.items:
            return self.tail_right_edge
        tail_item = max(self.items, key=Track.item_right_edge)
        self._tail_item = tail_item
        self.tail_right_edge = Track.item_right_edge(tail_item)
        return self.tail_right_edge

    def add(self, item: DanmuItem):
        item.y = self.y
        self.items.append(item)

    def update(self, speed_factor: float, dt_sec: float, engine: "DanmuEngine"):
        scale = dt_sec / (1.0 / 60.0)
        i = 0
        while i < len(self.items):
            item = self.items[i]
            old_x = item.x
            item.x -= item.speed * speed_factor * scale
            if item.x + item.width <= 0:
                engine._detach_item_visibility(item)
                item._pixmap = None
                self.items.pop(i)
                engine._unregister_item(self, item)
            else:
                if item.x != old_x:
                    engine._on_item_x_changed(self, item, old_x)
                engine._refresh_item_visibility(item)
                i += 1

    def drop_pending(self, screen_width: float) -> int:
        kept: list[DanmuItem] = []
        dropped = 0
        for item in self.items:
            if item.x >= screen_width:
                item._pixmap = None
                dropped += 1
            else:
                kept.append(item)
        self.items = kept
        return dropped


__all__ = ["DanmuItem", "Track"]
