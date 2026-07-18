"""侧边悬浮窗弹幕引擎：底部锚定的聊天记录式堆积。

W-FP-STACK-ENGINE-001：由「底部进入后持续上滚」改为聊天/日志列表语义——
新条从容器底进入，旧条在新消息到达时整体上移，空闲静止，仅完全越顶后移除。

兼容：保留 ``can_accept_new_item`` / ``estimate_entry_delay_ms`` / ``pixels_per_second``
方法名与返回类型；``floating_panel_speed`` 仍可读但不驱动堆积动画。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field
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
_DEFAULT_STACK_GAP = 8.0
_DEFAULT_ENTRY_DURATION_MS = 200
_DEFAULT_PUSH_DURATION_MS = 180
_DEFAULT_EXIT_DURATION_MS = 200
_ENTRY_DELAY_MS_READY = 100
_POSITION_EPS = 0.5


@dataclass
class FloatingPanelItem:
    """单条悬浮窗消息的状态（主线程读写）。

    ``current_y`` 为渲染坐标（条目顶边）；``target_y`` 为堆积布局目标。
    ``style_index`` 在创建时固定，动画期间不得重抽。
    """

    content: str
    current_y: float
    height: float
    created_at: float
    opacity: float = 1.0
    batch_id: int = 0
    pixmap: object | None = None
    target_y: float = 0.0
    style_index: int = 0
    exiting: bool = False
    anim_from_y: float = 0.0
    anim_elapsed_ms: float = 0.0
    anim_duration_ms: float = 0.0
    is_entry: bool = False
    _anim_active: bool = field(default=False, repr=False)


class FloatingPanelEngine:
    """底部锚定堆积：入场 / 顶推 / 越顶退出动画；静止时不驱动 current_y。"""

    def __init__(self, config: "ConfigStore"):
        self.config = config
        self._items: list[FloatingPanelItem] = []
        self._recent: deque[str] = deque(maxlen=_DEDUP_WINDOW)
        self._recent_exact_set: set[str] = set()
        self._recent_timestamps: dict[str, float] = {}
        self.running: bool = False
        self._panel_height: float = 600.0
        self._max_items: int = _DEFAULT_MAX_ITEMS
        self._speed_scale: float = _DEFAULT_SPEED_SCALE
        self._pixels_per_second: float = _PIXELS_PER_SECOND_BASE * _DEFAULT_SPEED_SCALE
        self._stack_gap: float = _DEFAULT_STACK_GAP
        self._entry_duration_ms: float = float(_DEFAULT_ENTRY_DURATION_MS)
        self._push_duration_ms: float = float(_DEFAULT_PUSH_DURATION_MS)
        self._exit_duration_ms: float = float(_DEFAULT_EXIT_DURATION_MS)
        self._next_style_index: int = 0
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

        self._stack_gap = self._read_float_config(
            "floating_panel_stack_gap",
            _DEFAULT_STACK_GAP,
            lo=0.0,
            hi=48.0,
        )
        self._entry_duration_ms = self._read_float_config(
            "floating_panel_entry_duration_ms",
            float(_DEFAULT_ENTRY_DURATION_MS),
            lo=0.0,
            hi=2000.0,
        )
        self._push_duration_ms = self._read_float_config(
            "floating_panel_push_duration_ms",
            float(_DEFAULT_PUSH_DURATION_MS),
            lo=0.0,
            hi=2000.0,
        )
        self._exit_duration_ms = self._read_float_config(
            "floating_panel_exit_duration_ms",
            float(_DEFAULT_EXIT_DURATION_MS),
            lo=0.0,
            hi=2000.0,
        )

        # 配置变更后重算目标布局，不清空正常可见条；退出中条目保持退出态。
        if self._items:
            self._recompute_stack_layout(reason="apply_config")

    def _read_float_config(
        self, key: str, default: float, *, lo: float, hi: float
    ) -> float:
        raw = self.config.get(key, "")
        try:
            value = float(raw if raw not in (None, "") else default)
        except (TypeError, ValueError):
            value = default
        return max(lo, min(value, hi))

    def set_panel_height(self, height: float) -> None:
        new_h = max(1.0, float(height))
        if abs(new_h - self._panel_height) < 1e-6:
            return
        self._panel_height = new_h
        if self._items:
            self._recompute_stack_layout(reason="panel_height")

    def start(self) -> None:
        self.running = True

    def stop(self) -> None:
        self.running = False

    def clear(self) -> None:
        self._items.clear()
        self._recent.clear()
        self._recent_exact_set.clear()
        self._recent_timestamps.clear()

    def visible_items(self) -> list[FloatingPanelItem]:
        return list(self._items)

    def visible_count(self) -> int:
        return len(self._items)

    def active_count(self) -> int:
        return sum(1 for it in self._items if not it.exiting)

    def min_on_screen(self) -> int:
        """公式化补足目标条数；池关闭时为 0（与 DanmuEngine 对齐 duck-type）。"""
        from app.danmu_pool import effective_min_on_screen

        return effective_min_on_screen(self.config)

    def deficit_below_min(self) -> int:
        """相对 min_on_screen 的不足条数（按非退出 active_count 计）。"""
        min_n = self.min_on_screen()
        if min_n <= 0:
            return 0
        return max(0, min_n - self.active_count())

    def needs_refill(self) -> bool:
        return self.deficit_below_min() > 0

    @property
    def pixels_per_second(self) -> float:
        """兼容旧 API：仍由 floating_panel_speed 派生，不驱动堆积动画。"""
        return self._pixels_per_second

    @property
    def stack_gap(self) -> float:
        return self._stack_gap

    def needs_render_tick(self) -> bool:
        for item in self._items:
            if item.exiting:
                return True
            if item._anim_active:
                return True
            if abs(item.current_y - item.target_y) > _POSITION_EPS:
                return True
        return False

    def is_duplicate(self, content: str) -> bool:
        self._prune_recent_by_ttl()
        return is_duplicate_in_recent(
            content,
            self._recent,
            self._recent_exact_set,
            self.config,
        )

    def _remember(self, content: str) -> None:
        self._prune_recent_by_ttl()
        evicted = None
        if self._recent.maxlen and len(self._recent) == self._recent.maxlen:
            evicted = self._recent[0]
        self._recent.append(content)
        self._recent_exact_set.add(content)
        self._recent_timestamps[content] = time.monotonic()
        if evicted is not None and evicted not in self._recent:
            self._recent_exact_set.discard(evicted)
            self._recent_timestamps.pop(evicted, None)

    def _recent_ttl_sec(self) -> int:
        value = self.config.get_int("danmu_recent_ttl_sec", 120)
        return max(1, min(int(value), 600))

    def _prune_recent_by_ttl(self) -> None:
        ttl = self._recent_ttl_sec()
        if ttl <= 0:
            return
        cutoff = time.monotonic() - ttl
        removed = [content for content, ts in self._recent_timestamps.items() if ts < cutoff]
        if not removed:
            return
        for content in removed:
            self._recent_timestamps.pop(content, None)
            try:
                self._recent.remove(content)
            except ValueError:
                pass
            if content not in self._recent:
                self._recent_exact_set.discard(content)

    def _start_anim(
        self,
        item: FloatingPanelItem,
        *,
        target_y: float,
        duration_ms: float,
        is_entry: bool = False,
    ) -> None:
        item.target_y = float(target_y)
        item.anim_from_y = float(item.current_y)
        item.anim_elapsed_ms = 0.0
        item.anim_duration_ms = max(0.0, float(duration_ms))
        item.is_entry = is_entry
        if item.anim_duration_ms <= 0.0 or abs(item.anim_from_y - item.target_y) <= _POSITION_EPS:
            item.current_y = item.target_y
            item._anim_active = False
            item.anim_elapsed_ms = item.anim_duration_ms
        else:
            item._anim_active = True

    def _begin_exit(self, item: FloatingPanelItem) -> None:
        if item.exiting:
            return
        item.exiting = True
        item.is_entry = False
        # 目标：主体完全越过顶部（底边 <= 0）
        off_top_y = -float(item.height)
        self._start_anim(item, target_y=off_top_y, duration_ms=self._exit_duration_ms)

    def _active_items(self) -> list[FloatingPanelItem]:
        return [it for it in self._items if not it.exiting]

    def _compute_targets_bottom_up(
        self, active: list[FloatingPanelItem]
    ) -> dict[int, float]:
        """从底部向上：最新条目底边贴容器底；间距 stack_gap。返回 id(item)->target_y。"""
        targets: dict[int, float] = {}
        if not active:
            return targets
        cursor_bottom = self._panel_height
        gap = self._stack_gap
        for item in reversed(active):
            target_y = cursor_bottom - item.height
            targets[id(item)] = target_y
            cursor_bottom = target_y - gap
        return targets

    def _recompute_stack_layout(
        self,
        *,
        reason: str = "",
        entry_item: FloatingPanelItem | None = None,
    ) -> None:
        """重算非退出条目目标；超高 / 超 max_items 时最旧条进入顶部退出。"""
        del reason  # 诊断用占位，避免未使用参数

        # 反复标记退出直到活跃集合可完整落在面板内且不超过 max_items
        safety = 0
        while safety < 64:
            safety += 1
            active = self._active_items()
            if not active:
                return

            # max_items：仅计非退出条目；超出则最旧进入退出
            if len(active) > self._max_items:
                oldest = min(active, key=lambda it: (it.created_at, id(it)))
                self._begin_exit(oldest)
                continue

            targets = self._compute_targets_bottom_up(active)
            # 总高度超出：最旧条目目标完全在顶边之上时进入退出
            # （底边 target_y+height <= 0）；部分越顶仍保留（由 Overlay 裁剪）。
            overflow_victims = [
                it
                for it in active
                if targets.get(id(it), it.target_y) + it.height <= 0.0
            ]
            if overflow_victims:
                oldest = min(overflow_victims, key=lambda it: (it.created_at, id(it)))
                self._begin_exit(oldest)
                continue

            # 稳定：为活跃条目启动入场/顶推动画
            for item in active:
                new_target = targets[id(item)]
                if item is entry_item:
                    # 新条：从面板底边外入场
                    if not item._anim_active or abs(item.target_y - new_target) > _POSITION_EPS:
                        item.current_y = self._panel_height
                        self._start_anim(
                            item,
                            target_y=new_target,
                            duration_ms=self._entry_duration_ms,
                            is_entry=True,
                        )
                    else:
                        item.target_y = new_target
                else:
                    if abs(item.target_y - new_target) > _POSITION_EPS or abs(
                        item.current_y - new_target
                    ) > _POSITION_EPS:
                        # 已有条目：从当前位置顶推到新目标
                        if abs(item.current_y - new_target) <= _POSITION_EPS:
                            item.current_y = new_target
                            item.target_y = new_target
                            item._anim_active = False
                        else:
                            self._start_anim(
                                item,
                                target_y=new_target,
                                duration_ms=self._push_duration_ms,
                                is_entry=False,
                            )
                    else:
                        item.target_y = new_target
            return

    @staticmethod
    def min_vertical_gap(item_height: float) -> float:
        """兼容旧 API：历史 min_gap 公式；堆积布局以 stack_gap 为准。"""
        height = max(24.0, float(item_height))
        return max(_MIN_GAP_BASE, height * 0.25)

    def relayout_vertical_gaps(self) -> None:
        """兼容旧 API：改为按 stack_gap 重算目标布局。"""
        if self._items:
            self._recompute_stack_layout(reason="relayout_vertical_gaps")

    def _trailing_bottom_edge(self) -> float:
        active = self._active_items()
        if not active:
            return 0.0
        return max(item.current_y + item.height for item in active)

    def can_accept_new_item(self, item_height: float) -> bool:
        """兼容旧调用方：不再表示底部空间不足；堆积模型始终可加入。

        仅在高度非法时返回 False（防御性）。后续 pipeline 应停止用本方法做空间准入。
        """
        del item_height
        return True

    def estimate_entry_delay_ms(self, item_height: float) -> int:
        """兼容旧调用方：不制造等待队列，固定返回就绪节奏。"""
        del item_height
        return _ENTRY_DELAY_MS_READY

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
        style_index: int | None = None,
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

        if style_index is None:
            fixed_style = self._next_style_index
            self._next_style_index = (self._next_style_index + 1) % 1024
        else:
            fixed_style = int(style_index)

        # 立即可见入场：current_y 从面板底开始，目标由布局计算
        item = FloatingPanelItem(
            content=text,
            current_y=self._panel_height,
            height=height,
            created_at=ts,
            batch_id=batch_id,
            target_y=self._panel_height - height,
            style_index=fixed_style,
            is_entry=True,
        )
        self._items.append(item)
        self._remember(text)
        self._recompute_stack_layout(reason="add_text", entry_item=item)
        return item

    def update_item_height(self, item: FloatingPanelItem, height: float) -> None:
        """Overlay 实测高度后回调：重算目标布局，不清空可见条。"""
        new_h = max(24.0, float(height))
        if abs(new_h - item.height) < 1e-6:
            return
        item.height = new_h
        if item.exiting:
            # 退出中：更新 off-top 目标，继续退出动画
            item.target_y = -item.height
            if not item._anim_active:
                self._start_anim(
                    item, target_y=item.target_y, duration_ms=self._exit_duration_ms
                )
            return
        self._recompute_stack_layout(reason="update_item_height")

    def _apply_exit_opacity(self, item: FloatingPanelItem) -> None:
        if not item.exiting:
            if not item.is_entry:
                item.opacity = 1.0
            return
        if item.anim_duration_ms <= 0.0:
            item.opacity = 0.0
            return
        t = min(1.0, max(0.0, item.anim_elapsed_ms / item.anim_duration_ms))
        item.opacity = max(0.0, 1.0 - t)

    def _apply_entry_opacity(self, item: FloatingPanelItem) -> None:
        if item.exiting or not item.is_entry:
            return
        if item.anim_duration_ms <= 0.0 or not item._anim_active:
            item.opacity = 1.0
            return
        t = min(1.0, max(0.0, item.anim_elapsed_ms / item.anim_duration_ms))
        item.opacity = max(0.0, min(1.0, t))

    def update(self, dt_sec: float, now: float | None = None) -> bool:
        """推进入场/顶推/退出动画；静止时不改变 current_y。返回是否仍需渲染 tick。"""
        del now
        if not self._items:
            return False

        dt_ms = max(0.0, min(float(dt_sec), 0.1)) * 1000.0

        for item in self._items:
            if not item._anim_active:
                # 静止：锁定在目标，不因 update 漂移
                if not item.exiting:
                    item.current_y = item.target_y
                    item.opacity = 1.0
                continue

            item.anim_elapsed_ms += dt_ms
            duration = item.anim_duration_ms
            if duration <= 0.0:
                t = 1.0
            else:
                t = min(1.0, item.anim_elapsed_ms / duration)
            item.current_y = item.anim_from_y + (item.target_y - item.anim_from_y) * t
            if item.exiting:
                self._apply_exit_opacity(item)
            elif item.is_entry:
                self._apply_entry_opacity(item)
            else:
                item.opacity = 1.0
            if t >= 1.0:
                item.current_y = item.target_y
                item.anim_elapsed_ms = duration
                item._anim_active = False
                if item.is_entry:
                    item.is_entry = False
                    item.opacity = 1.0

        # 完全越顶才移除（允许离场动画期间部分越过顶部）
        surviving: list[FloatingPanelItem] = []
        for item in self._items:
            fully_past_top = item.current_y + item.height <= 0.0
            if item.exiting and fully_past_top and not item._anim_active:
                continue
            if item.exiting and fully_past_top and item.anim_duration_ms <= 0.0:
                continue
            # 退出动画结束且已完全越顶
            if item.exiting and fully_past_top and item.anim_elapsed_ms >= item.anim_duration_ms:
                continue
            surviving.append(item)
        self._items = surviving

        return self.needs_render_tick()
