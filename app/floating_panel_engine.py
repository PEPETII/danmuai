"""侧边悬浮窗弹幕引擎：底部进入后持续上滚，越顶即移除。



W-FP-V3-002：修复 V2 的“堆叠停留 + 固定写死速度”语义，改为接线

``floating_panel_speed`` 的持续向上滚动模型。



W-FP-V3-003：竖向 min_gap 准入与独立调度；间距逻辑与横向 ``DanmuEngine._calc_min_gap`` 无关。

"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.danmu_engine import normalize_danmu_display_text
from app.danmu_engine_dedup import is_duplicate_in_recent

if TYPE_CHECKING:

    from app.config_store import ConfigStore



_DEDUP_WINDOW = 30

_DEFAULT_MAX_ITEMS = 12

_DEFAULT_SPEED_SCALE = 1.0

_MIN_SPEED_SCALE = 0.5

_MAX_SPEED_SCALE = 5.0

_PIXELS_PER_SECOND_BASE = 120.0

_MIN_GAP_BASE = 12.0

_ENTRY_DELAY_MS_MIN = 50

_ENTRY_DELAY_MS_MAX = 1000

_ENTRY_DELAY_MS_READY = 100

_ENTRY_FRAME_BUFFER_MS = 16

_FADE_ZONE_PX = 48.0





@dataclass

class FloatingPanelItem:

    """单条悬浮窗消息的状态（主线程读写）。"""



    content: str

    current_y: float

    height: float

    created_at: float

    opacity: float = 1.0

    batch_id: int = 0

    pixmap: object | None = None





class FloatingPanelEngine:

    """底部进入后以统一速度持续上滚，越顶后删除。"""



    def __init__(self, config: "ConfigStore"):

        self.config = config

        self._items: list[FloatingPanelItem] = []

        self._recent: deque[str] = deque(maxlen=_DEDUP_WINDOW)

        self._recent_exact_set: set[str] = set()

        self.running: bool = False

        self._panel_height: float = 600.0

        self._max_items: int = _DEFAULT_MAX_ITEMS

        self._speed_scale: float = _DEFAULT_SPEED_SCALE

        self._pixels_per_second: float = _PIXELS_PER_SECOND_BASE * _DEFAULT_SPEED_SCALE

        self.apply_config()



    def apply_config(self) -> None:

        raw_max = self.config.get("floating_panel_max_items", "")

        try:

            self._max_items = max(1, min(int(raw_max or _DEFAULT_MAX_ITEMS), 50))

        except (TypeError, ValueError):

            self._max_items = _DEFAULT_MAX_ITEMS



        raw_speed = self.config.get("floating_panel_speed", "")

        try:

            self._speed_scale = max(

                _MIN_SPEED_SCALE,

                min(float(raw_speed or _DEFAULT_SPEED_SCALE), _MAX_SPEED_SCALE),

            )

        except (TypeError, ValueError):

            self._speed_scale = _DEFAULT_SPEED_SCALE

        self._pixels_per_second = _PIXELS_PER_SECOND_BASE * self._speed_scale



    def set_panel_height(self, height: float) -> None:

        self._panel_height = max(1.0, float(height))



    def start(self) -> None:

        self.running = True



    def stop(self) -> None:

        self.running = False



    def clear(self) -> None:

        self._items.clear()

        self._recent.clear()

        self._recent_exact_set.clear()



    def visible_items(self) -> list[FloatingPanelItem]:

        return list(self._items)



    def visible_count(self) -> int:

        return len(self._items)



    def active_count(self) -> int:

        return self.visible_count()



    @property

    def pixels_per_second(self) -> float:

        return self._pixels_per_second



    def needs_render_tick(self) -> bool:

        return bool(self._items)



    def is_duplicate(self, content: str) -> bool:

        return is_duplicate_in_recent(

            content,

            self._recent,

            self._recent_exact_set,

            self.config,

        )



    def _remember(self, content: str) -> None:

        evicted = None

        if self._recent.maxlen and len(self._recent) == self._recent.maxlen:

            evicted = self._recent[0]

        self._recent.append(content)

        self._recent_exact_set.add(content)

        if evicted is not None and evicted not in self._recent:

            self._recent_exact_set.discard(evicted)



    def _enforce_max_items(self) -> None:

        """超限时仅丢弃已滚出顶部的条目；在屏条目不瞬删，等自然上滚离屏。"""

        self._items = [item for item in self._items if item.current_y + item.height > 0.0]

        while len(self._items) > self._max_items:

            off_screen = [it for it in self._items if it.current_y + it.height <= 0.0]

            if not off_screen:

                break

            victim = min(off_screen, key=lambda it: it.created_at)

            self._items.remove(victim)



    @staticmethod

    def min_vertical_gap(item_height: float) -> float:

        """竖向最小间距（内部常量，非配置项）。"""

        height = max(24.0, float(item_height))

        return max(_MIN_GAP_BASE, height * 0.25)



    def relayout_vertical_gaps(self) -> None:

        """字号热更新后轻量重排，保证相邻条目仍满足 min_gap。"""

        if len(self._items) < 2:

            return

        items = sorted(self._items, key=lambda it: it.current_y)

        for idx in range(1, len(items)):

            upper, lower = items[idx - 1], items[idx]

            min_gap = self.min_vertical_gap(lower.height)

            needed_y = upper.current_y + upper.height + min_gap

            if lower.current_y < needed_y:

                lower.current_y = needed_y



    def _trailing_bottom_edge(self) -> float:

        if not self._items:

            return 0.0

        return max(item.current_y + item.height for item in self._items)



    def can_accept_new_item(self, item_height: float) -> bool:

        """末条底边 + min_gap 不超过面板底边时可从底部进入。"""

        if not self._items:

            return True

        min_gap = self.min_vertical_gap(item_height)

        return self._trailing_bottom_edge() + min_gap <= self._panel_height



    def estimate_entry_delay_ms(self, item_height: float) -> int:

        """估算底部留出 min_gap 所需等待毫秒数；可进入时返回较短固定节奏。"""

        if self.can_accept_new_item(item_height):

            return _ENTRY_DELAY_MS_READY

        min_gap = self.min_vertical_gap(item_height)

        deficit_px = (self._trailing_bottom_edge() + min_gap) - self._panel_height

        if deficit_px <= 0.0:

            return _ENTRY_DELAY_MS_READY

        speed = max(self._pixels_per_second, 1.0)

        delay_ms = int(deficit_px / speed * 1000.0) + _ENTRY_FRAME_BUFFER_MS

        return max(_ENTRY_DELAY_MS_MIN, min(_ENTRY_DELAY_MS_MAX, delay_ms))



    def add_text(

        self,

        content: str,

        persona: str = "",

        *,

        item_height: float,

        batch_id: int = 0,

        scene_generation: int = 0,

        skip_dedup: bool = False,

        pre_resolved: bool = False,

        now: float | None = None,

    ) -> FloatingPanelItem | None:

        del persona, scene_generation  # API 对齐 DanmuEngine.add_text

        if pre_resolved:
            text = str(content).strip()
        else:
            text = normalize_danmu_display_text(content, self.config)

        if not text:

            return None

        if not skip_dedup and self.is_duplicate(text):

            return None



        ts = 0.0 if now is None else float(now)

        height = max(24.0, float(item_height))

        if not self.can_accept_new_item(height):

            return None

        # 准入后从面板底部基线加入；竖向间距由 can_accept 时机保证，不做瞬间重排。

        start_y = self._panel_height

        item = FloatingPanelItem(

            content=text,

            current_y=start_y,

            height=height,

            created_at=ts,

            batch_id=batch_id,

        )

        self._items.append(item)

        self._remember(text)

        self._enforce_max_items()

        return item



    def update_item_height(self, item: FloatingPanelItem, height: float) -> None:

        """Overlay 实测高度后回调；连续上滚语义下不做重排。"""

        item.height = max(24.0, float(height))



    def _apply_fade_opacity(self, item: FloatingPanelItem) -> None:

        visible_bottom = item.current_y + item.height

        if visible_bottom <= 0.0:

            item.opacity = 0.0

        elif visible_bottom <= _FADE_ZONE_PX:

            item.opacity = max(0.0, min(1.0, visible_bottom / _FADE_ZONE_PX))

        else:

            item.opacity = 1.0



    def update(self, dt_sec: float, now: float | None = None) -> bool:

        """推进动画；返回是否仍需渲染 tick。"""

        if not self._items:

            return False

        del now

        dt = max(0.0, min(float(dt_sec), 0.1))

        move = self._pixels_per_second * dt



        surviving: list[FloatingPanelItem] = []

        for item in self._items:

            item.current_y -= move

            if item.current_y + item.height < 0.0:

                continue

            self._apply_fade_opacity(item)

            surviving.append(item)



        self._items = surviving

        self._enforce_max_items()

        return self.needs_render_tick()


