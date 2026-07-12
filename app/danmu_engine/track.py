"""DanmuEngine 轨道/核心子模块：DanmuEngine 类主定义与核心方法。

从原 app/danmu_engine.py 拆出，保持零业务逻辑变更。
"""

import heapq
import logging
import random
import time
from collections import deque

from PyQt6.QtCore import QObject

import app.danmu_engine as _de_pkg
from app import danmu_engine_dedup as dedup_profile
from app.danmu_engine_dedup import (  # noqa: F401 — re-exported for app.danmu_engine callers
    DedupProfileStats,
    dedup_profile_enabled,
    get_last_duplicate_observation,
    is_duplicate_in_recent,
    log_dedup_profile_summary,
    reset_dedup_profile_for_tests,
    snapshot_dedup_profile,
)
from app.danmu_engine_models import DanmuItem, Track  # noqa: F401
from app.danmu_engine_models import _DANMU_FALLBACK_CHAR_WIDTH

from .render import ENTRY_ZONE_PX
from .screen import (
    MAX_EVICT_ITERATIONS,
    layout_height_ratio,
    normalize_danmu_display_text,
    resolve_danmu_color,
    resolve_danmu_pending_entry_cap,
    resolve_danmu_track_retention_cap,
    track_layout_metrics,
)

_log = logging.getLogger(__name__)

# 与 app.config_defaults 保持同步（避免循环导入）
_DANMU_SPEED_FALLBACK = 2.0
_DEDUP_THRESHOLD_FALLBACK = 0.5
_DANMU_RECENT_TTL_FALLBACK = 30

_LEVENSHTEIN_UNAVAILABLE = dedup_profile._LEVENSHTEIN_UNAVAILABLE
_LEVENSHTEIN_RATIO = dedup_profile._LEVENSHTEIN_RATIO
def _get_levenshtein_ratio():
    # 通过 _de_pkg 属性访问，使测试 patch("app.danmu_engine._LEVENSHTEIN_RATIO", ...) 生效
    dedup_profile._LEVENSHTEIN_RATIO = _de_pkg._LEVENSHTEIN_RATIO
    ratio = dedup_profile._get_levenshtein_ratio()
    _de_pkg._LEVENSHTEIN_RATIO = dedup_profile._LEVENSHTEIN_RATIO
    return ratio
class DanmuEngine(QObject):
    """弹幕引擎核心：多轨道列表、deque(30) 去重窗口、可见性惰性计数与加速动画状态。

    不负责 AI 请求、Web/API、主链路调度；仅由 DanmuApp._consume_reply_queue 调用 add_text。
    _pick_track 为加权随机（非轮询），单测需 monkeypatch random.choices 才能确定性断言。
    overlay 持有本实例并在 _tick 中调用 update()；宽度测量与 pixmap 预渲染暂依赖 Overlay（Phase 2 待收口）。
    """

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = False
        self.overlay = None
        self.recent: deque[str] = deque(maxlen=30)
        self.recent_exact_set: set[str] = set()
        self.recent_timestamps: dict[str, float] = {}
        self._dedup_scene_generation = 0
        self.tracks: list[Track] = []
        self.screen_width: float = 1920.0
        self.screen_height: float = 1080.0
        self._accel_peak = 2.0
        self._accel_total = 0
        self._accel_remaining = 0
        self._visible_count = 0
        self._right_visible_count = 0
        self._visibility_stale = False
        self._visibility_counts_seeded = False
        self._fade_zone_count = 0
        self._pending_entry_count = 0
        self._offscreen_pending_count = 0
        self._total_item_count = 0
        self._dropped_by_cap_count = 0
        self._capacity_counts_stale = False
        self._capacity_counts_seeded = False
        self._motion_tick_count = 0
        self._motion_tick_stale = False
        self._motion_tick_seeded = False
        self._init_tracks()
        self._load_recent_from_history()

    def _load_recent_from_history(self):
        for content in self.config.get_recent_history(30):
            self._remember_content(content)

    def _recent_ttl_sec(self) -> int:
        value = self.config.get_int("danmu_recent_ttl_sec", _DANMU_RECENT_TTL_FALLBACK)
        return max(1, min(int(value), 600))

    def _prune_recent_by_ttl(self) -> None:
        ttl = self._recent_ttl_sec()
        if ttl <= 0:
            return
        cutoff = time.monotonic() - ttl
        removed = [content for content, ts in self.recent_timestamps.items() if ts < cutoff]
        if not removed:
            return
        for content in removed:
            self.recent_timestamps.pop(content, None)
            try:
                self.recent.remove(content)
            except ValueError:
                pass
            if content not in self.recent:
                self.recent_exact_set.discard(content)

    def _sync_dedup_window_generation(self, scene_generation: int) -> None:
        if int(scene_generation) != int(getattr(self, "_dedup_scene_generation", 0)):
            self.clear_dedup_window()
            self._dedup_scene_generation = int(scene_generation)

    def _remember_content(self, content: str) -> None:
        self._prune_recent_by_ttl()
        evicted = None
        if self.recent.maxlen and len(self.recent) == self.recent.maxlen:
            evicted = self.recent[0]
        self.recent.append(content)
        self.recent_exact_set.add(content)
        self.recent_timestamps[content] = time.monotonic()
        if evicted is not None and evicted not in self.recent:
            self.recent_exact_set.discard(evicted)
            self.recent_timestamps.pop(evicted, None)

    def _forget_content(self, content: str) -> None:
        """从去重窗口移除一条上屏记录（如弹幕被场景/批次清屏）。"""
        try:
            self.recent.remove(content)
        except ValueError:
            pass
        if content not in self.recent:
            self.recent_exact_set.discard(content)
            self.recent_timestamps.pop(content, None)

    def _init_tracks(self):
        metrics = track_layout_metrics(self.config)
        line_height = metrics["line_height"]
        top_margin = metrics["top_margin"]
        bottom_margin = metrics["bottom_margin"]
        self._track_line_height = line_height
        self._track_top_margin = top_margin
        self._track_bottom_margin = bottom_margin
        ratio = layout_height_ratio(self.config)
        drawable_height = self.screen_height * ratio
        configured = self.config.get_int("danmu_lines", 0)
        try:
            val = int(configured)
        except (TypeError, ValueError):
            val = 0

        if val > 0:
            line_count = _de_pkg.clamp_danmu_lines(val)
        else:
            usable = max(line_height, drawable_height - top_margin - bottom_margin)
            line_count = _de_pkg.clamp_danmu_lines(int(usable / line_height))
        max_y = max(top_margin, drawable_height - bottom_margin - line_height)
        start_y = top_margin
        self.tracks = []
        for i in range(line_count):
            y = float(start_y + i * line_height)
            if y > max_y:
                break
            self.tracks.append(Track(y))
        self._pending_entry_count = 0
        self._offscreen_pending_count = 0
        self._total_item_count = 0
        self._capacity_counts_seeded = False
        self._capacity_counts_stale = False
        self._motion_tick_count = 0
        self._motion_tick_stale = False
        self._motion_tick_seeded = False

    def _mark_capacity_stale(self) -> None:
        self._capacity_counts_stale = True

    @staticmethod
    def _scan_pending_entry_count(tracks: list[Track], screen_width: float) -> int:
        zone_left = screen_width - ENTRY_ZONE_PX
        return sum(1 for track in tracks for item in track.items if item.x >= zone_left)

    @staticmethod
    def _scan_offscreen_pending_count(tracks: list[Track], screen_width: float) -> int:
        return sum(1 for track in tracks for item in track.items if item.x >= screen_width)

    @staticmethod
    def _scan_current_display_count(tracks: list[Track]) -> int:
        return sum(len(track.items) for track in tracks)

    def _item_in_track_entry_zone(self, item: DanmuItem) -> bool:
        zone_left = self.screen_width - ENTRY_ZONE_PX
        return item.x + item.width > zone_left and item.x < self.screen_width

    def _classify_item_zones(self, item: DanmuItem) -> tuple[bool, bool, bool]:
        return (
            self._in_entry_zone(item),
            self._is_offscreen_pending(item),
            self._item_in_track_entry_zone(item),
        )

    def _recompute_track_tail_edge(self, track: Track) -> None:
        if not track.items:
            track.tail_right_edge = float("-inf")
            track._tail_item = None
            return
        tail_item = max(track.items, key=Track.item_right_edge)
        track._tail_item = tail_item
        track.tail_right_edge = Track.item_right_edge(tail_item)

    def _recompute_track_offscreen_meta(self, track: Track) -> None:
        sw = self.screen_width
        best_x = float("-inf")
        best_item: DanmuItem | None = None
        for item in track.items:
            if item.x >= sw and item.x > best_x:
                best_x = item.x
                best_item = item
        track.furthest_offscreen_x = best_x
        track._furthest_offscreen_item = best_item

    def _apply_item_zone_flags(
        self,
        item: DanmuItem,
        *,
        engine_entry: bool,
        offscreen: bool,
        track_entry: bool,
    ) -> None:
        if item._cached_engine_entry_zone != engine_entry:
            self._pending_entry_count += 1 if engine_entry else -1
            item._cached_engine_entry_zone = engine_entry
        if item._cached_offscreen_pending != offscreen:
            self._offscreen_pending_count += 1 if offscreen else -1
            item._cached_offscreen_pending = offscreen
        if item._cached_track_entry_zone != track_entry:
            item._cached_track_entry_zone = track_entry

    def _register_item(self, track: Track, item: DanmuItem) -> None:
        self._total_item_count += 1
        engine_entry, offscreen, track_entry = self._classify_item_zones(item)
        self._apply_item_zone_flags(
            item,
            engine_entry=engine_entry,
            offscreen=offscreen,
            track_entry=track_entry,
        )
        if track_entry:
            track.entry_zone_count_cached += 1
        edge = Track.item_right_edge(item)
        if edge > track.tail_right_edge:
            track.tail_right_edge = edge
            track._tail_item = item
        if offscreen and item.x > track.furthest_offscreen_x:
            track.furthest_offscreen_x = item.x
            track._furthest_offscreen_item = item
        self._capacity_counts_seeded = True
        self._capacity_counts_stale = False
        self._update_item_motion_tick_state(item)

    def _unregister_item(self, track: Track, item: DanmuItem) -> None:
        self._total_item_count = max(0, self._total_item_count - 1)
        if item._needs_motion_tick:
            self._motion_tick_count = max(0, self._motion_tick_count - 1)
            item._needs_motion_tick = False
        if item._cached_engine_entry_zone:
            self._pending_entry_count -= 1
            item._cached_engine_entry_zone = False
        if item._cached_offscreen_pending:
            self._offscreen_pending_count -= 1
            item._cached_offscreen_pending = False
        if item._cached_track_entry_zone:
            track.entry_zone_count_cached = max(0, track.entry_zone_count_cached - 1)
            item._cached_track_entry_zone = False
        if item is track._tail_item:
            self._recompute_track_tail_edge(track)
        if item is track._furthest_offscreen_item:
            self._recompute_track_offscreen_meta(track)

    def _detach_track_item(self, track: Track, item: DanmuItem) -> None:
        """从轨道移除 item 并撤销 _register_item 副作用（add_text/add_item 异常回滚）。"""
        if item in track.items:
            self._detach_item_visibility(item)
            item._pixmap = None
            track.items.remove(item)
            self._unregister_item(track, item)

    def _on_item_x_changed(self, track: Track, item: DanmuItem, old_x: float) -> None:
        engine_entry, offscreen, track_entry = self._classify_item_zones(item)
        was_track_entry = item._cached_track_entry_zone
        self._apply_item_zone_flags(
            item,
            engine_entry=engine_entry,
            offscreen=offscreen,
            track_entry=track_entry,
        )
        if was_track_entry != track_entry:
            if track_entry:
                track.entry_zone_count_cached += 1
            else:
                track.entry_zone_count_cached = max(0, track.entry_zone_count_cached - 1)
        old_edge = old_x + (item.width if item.width > 0 else len(item.content) * _DANMU_FALLBACK_CHAR_WIDTH)
        new_edge = Track.item_right_edge(item)
        if new_edge > track.tail_right_edge:
            track.tail_right_edge = new_edge
            track._tail_item = item
        elif item is track._tail_item:
            track.tail_right_edge = new_edge
            if new_edge < old_edge:
                self._recompute_track_tail_edge(track)
        was_offscreen = old_x >= self.screen_width
        if offscreen:
            if item.x > track.furthest_offscreen_x:
                track.furthest_offscreen_x = item.x
                track._furthest_offscreen_item = item
            elif item is track._furthest_offscreen_item:
                self._recompute_track_offscreen_meta(track)
        elif was_offscreen and item is track._furthest_offscreen_item:
            self._recompute_track_offscreen_meta(track)
        self._update_item_motion_tick_state(item)

    def _rebuild_capacity_counts(self) -> None:
        sw = self.screen_width
        pending = 0
        offscreen = 0
        total = 0
        for track in self.tracks:
            track.entry_zone_count_cached = 0
            track.tail_right_edge = float("-inf")
            track._tail_item = None
            track.furthest_offscreen_x = float("-inf")
            track._furthest_offscreen_item = None
            for item in track.items:
                total += 1
                engine_entry = item.x >= sw - ENTRY_ZONE_PX
                item_offscreen = item.x >= sw
                track_entry = item.x + item.width > sw - ENTRY_ZONE_PX and item.x < sw
                item._cached_engine_entry_zone = engine_entry
                item._cached_offscreen_pending = item_offscreen
                item._cached_track_entry_zone = track_entry
                if engine_entry:
                    pending += 1
                if item_offscreen:
                    offscreen += 1
                    if item.x > track.furthest_offscreen_x:
                        track.furthest_offscreen_x = item.x
                        track._furthest_offscreen_item = item
                if track_entry:
                    track.entry_zone_count_cached += 1
                edge = Track.item_right_edge(item)
                if edge > track.tail_right_edge:
                    track.tail_right_edge = edge
                    track._tail_item = item
        self._pending_entry_count = pending
        self._offscreen_pending_count = offscreen
        self._total_item_count = total
        self._capacity_counts_stale = False
        self._capacity_counts_seeded = True

    def _ensure_capacity_counts(self) -> None:
        if self._capacity_counts_stale or not self._capacity_counts_seeded:
            self._rebuild_capacity_counts()

    def _item_right_edge(self, item: DanmuItem) -> float:
        w = item.width if item.width > 0 else len(item.content) * _DANMU_FALLBACK_CHAR_WIDTH
        return item.x + w

    def _in_entry_zone(self, item: DanmuItem) -> bool:
        return item.x >= self.screen_width - ENTRY_ZONE_PX

    def _is_offscreen_pending(self, item: DanmuItem) -> bool:
        return item.x >= self.screen_width

    def pending_entry_count(self) -> int:
        self._ensure_capacity_counts()
        return self._pending_entry_count

    def offscreen_pending_count(self) -> int:
        self._ensure_capacity_counts()
        return self._offscreen_pending_count

    def right_entry_count(self) -> int:
        return self.pending_entry_count()

    def max_pending_entry(self) -> int:
        """入口区 pending 上限；0 表示无固定上限。"""
        return resolve_danmu_pending_entry_cap(self.config)

    def _offscreen_refill_cap(self) -> int:
        """池补足时的屏外 pending 参考上限；0 表示不阻塞补足。"""
        return resolve_danmu_pending_entry_cap(self.config)

    def entry_zone_overloaded(self) -> bool:
        cap = self.max_pending_entry()
        if cap <= 0:
            return False
        return self.pending_entry_count() >= cap

    def dropped_by_cap_count(self) -> int:
        """返回因入区容量不足而被丢弃的弹幕累计数。"""
        return self._dropped_by_cap_count

    def reset_dropped_cap_count(self) -> None:
        """重置丢弃计数器（通常在场景切换或手动重置时调用）。"""
        self._dropped_by_cap_count = 0

    def _track_retention_cap(self) -> int:
        return resolve_danmu_track_retention_cap(self.config)

    def _evict_furthest_offscreen_pending(self, max_drop: int = 1) -> int:
        """淘汰 x >= screen_width 中最远的 pending 条目，释放 pixmap/可见性计数。"""
        if max_drop <= 0:
            return 0
        dropped = 0
        for _ in range(max_drop):
            best_track: Track | None = None
            best_x = float("-inf")
            for track in self.tracks:
                if track.furthest_offscreen_x > best_x:
                    best_x = track.furthest_offscreen_x
                    best_track = track
            if best_track is None or best_x == float("-inf"):
                break
            best_item = best_track._furthest_offscreen_item
            if best_item is None or best_item.x < self.screen_width:
                self._recompute_track_offscreen_meta(best_track)
                if best_track.furthest_offscreen_x == float("-inf"):
                    break
                best_item = best_track._furthest_offscreen_item
                if best_item is None:
                    break
            if best_item not in best_track.items:
                self._recompute_track_offscreen_meta(best_track)
                continue
            self._detach_item_visibility(best_item)
            best_item._pixmap = None
            self._forget_content(best_item.content)
            best_track.items.remove(best_item)
            self._unregister_item(best_track, best_item)
            dropped += 1
        if dropped:
            self._visibility_stale = True
        return dropped

    def _prepare_capacity_for_new_item(self) -> bool:
        """超配置 cap 时先屏外淘汰；默认无 cap 时恒 True。"""
        pending_cap = self.max_pending_entry()
        retention_cap = self._track_retention_cap()
        if pending_cap <= 0 and retention_cap <= 0:
            return True
        safety = min(max(self.current_display_count(), pending_cap, retention_cap, 1) + 8, MAX_EVICT_ITERATIONS)
        for _ in range(safety):
            pending_over = pending_cap > 0 and self.pending_entry_count() >= pending_cap
            retention_over = retention_cap > 0 and self.current_display_count() >= retention_cap
            if not pending_over and not retention_over:
                return True
            if self._evict_furthest_offscreen_pending(1) <= 0:
                break
        pending_over = pending_cap > 0 and self.pending_entry_count() >= pending_cap
        retention_over = retention_cap > 0 and self.current_display_count() >= retention_cap
        return not pending_over and not retention_over

    def add_item(self, item: DanmuItem) -> bool:
        if not item.content or not item.content.strip():
            return False
        self._sync_dedup_window_generation(item.scene_generation)
        if self._is_duplicate(item.content):
            return False

        track = self._pick_track(item)
        if track is None:
            return False
        track.add(item)
        try:
            self._register_item(track, item)
        except Exception:
            self._detach_track_item(track, item)
            raise
        self._remember_content(item.content)
        self._refresh_item_visibility(item)
        return True

    def add_text(
        self,
        content: str,
        persona: str = "",
        batch_id: int = 0,
        scene_generation: int = 0,
        *,
        skip_dedup: bool = False,
        pre_resolved: bool = False,
    ) -> DanmuItem | None:
        """弹幕入轨：规范化 → 去重 → 可选屏外淘汰 → _pick_track → 记入 recent 窗口。

        默认无固定上屏数量上限；初始 x 在屏幕右缘外（待滚入）。
        skip_dedup 用于池补齐等已在外层去重的文本。
        pre_resolved=True 时 content 已是最终上屏文本（含人格前缀），不再二次规范化。
        """
        if not content or not content.strip():
            return None
        if pre_resolved:
            content = str(content).strip()
        else:
            content = normalize_danmu_display_text(content, self.config)
        if not content:
            return None

        self._sync_dedup_window_generation(scene_generation)

        if not skip_dedup and self._is_duplicate(content):
            return None

        if not self._prepare_capacity_for_new_item():
            self._dropped_by_cap_count += 1
            _log.warning(
                "danmu_dropped reason=dropped_by_cap count=%d pending=%d cap=%d",
                self._dropped_by_cap_count,
                self.pending_entry_count(),
                self.max_pending_entry(),
            )
            return None

        item = DanmuItem(
            content=content,
            persona=persona,
            batch_id=batch_id,
            scene_generation=scene_generation,
        )
        item.color = resolve_danmu_color(self.config)

        item.x = float(self.screen_width) + random.uniform(20.0, 90.0)
        item.speed = self.config.get_float("danmu_speed", _DANMU_SPEED_FALLBACK)
        item.width = self._estimate_content_width(content)

        track = self._pick_track(item)
        if track is None:
            return None
        track.add(item)
        try:
            self._register_item(track, item)
        except Exception:
            self._detach_track_item(track, item)
            raise
        self._remember_content(content)
        if self.overlay is not None:
            self.overlay.measure_item_width(item)
            if self.overlay.isVisible():
                self.overlay.ensure_render_loop()
            # 入待渲染队列，避免 _prepare_pixmaps_near_visible 每帧全量扫描
            self.overlay._pending_render.append(item)
            self._update_item_motion_tick_state(item)
        self._refresh_item_visibility(item)
        return item

    def _calc_min_gap(self, item: DanmuItem) -> float:
        return max(80.0, item.width * 0.5)

    def _pick_track(self, item: DanmuItem) -> Track | None:
        """加权随机选轨道（非轮询）：避免弹幕机械均匀分布，模拟自然错落感。

        优先级：1) 空闲轨道随机选 → 2) 入口区逆密度加权 → 3) 全满 fallback（rightmost_edge 最小前 3 条随机）。
        """
        if not self.tracks:
            return None

        min_gap = self._calc_min_gap(item)

        # 1. 空闲轨道优先
        idle = [t for t in self.tracks if not t.items]
        if idle:
            return random.choice(idle)

        # 2. 可接受轨道：按入口区逆密度加权随机（入口区越空权重越高）
        acceptable = [t for t in self.tracks if t.can_accept(item, self.screen_width, min_gap)]
        if acceptable:
            if self._capacity_counts_seeded:
                zone_counts = [t.entry_zone_count_cached for t in acceptable]
            else:
                zone_counts = [t.entry_zone_count(self.screen_width) for t in acceptable]
            weights = [1.0 / (1 + count) for count in zone_counts]
            total = sum(weights)
            if total == 0:  # 防护除零错误：所有轨道权重为0时随机选择
                return random.choice(acceptable)
            weights = [w / total for w in weights]
            return random.choices(acceptable, weights=weights, k=1)[0]

        # 3. 全满 fallback：允许在任意右侧 x 排队（仅 min_gap 防重叠，无固定数量上限）
        candidates = heapq.nsmallest(3, self.tracks, key=lambda t: t.rightmost_edge())
        best_track = random.choice(candidates)
        tail_edge = best_track.rightmost_edge()
        item.x = max(item.x, tail_edge + random.uniform(50.0, 250.0))
        if item.x < tail_edge + min_gap:
            item.x = tail_edge + min_gap
        return best_track

    def danmu_pool_enabled(self) -> bool:
        from app.danmu_pool import danmu_pool_use_custom_from_config

        return danmu_pool_use_custom_from_config(self.config)

    def min_on_screen(self) -> int:
        from app.danmu_pool import effective_min_on_screen

        return effective_min_on_screen(self.config)

    def deficit_below_min(self) -> int:
        min_n = self.min_on_screen()
        if min_n <= 0:
            return 0
        return max(0, min_n - self.visible_display_count())

    def current_display_count(self) -> int:
        self._ensure_capacity_counts()
        return self._total_item_count

    def drop_pending_items(self) -> int:
        dropped = 0
        sw = self.screen_width
        for track in self.tracks:
            to_drop = [item for item in track.items if item.x >= sw]
            for item in to_drop:
                self._detach_item_visibility(item)
                item._pixmap = None
                track.items.remove(item)
                self._unregister_item(track, item)
                dropped += 1
        if dropped:
            self._visibility_stale = True
        return dropped

    def clear_dedup_window(self) -> None:
        self.recent.clear()
        self.recent_exact_set.clear()
        self.recent_timestamps.clear()
        self._dedup_scene_generation = int(getattr(self, "_dedup_scene_generation", 0))

    def drop_pending_below_generation(self, min_generation: int) -> int:
        """丢弃旧场景代际且仍在屏外的 pending 弹幕（medium 策略：保留已滚入可见区的）。"""
        dropped = 0
        sw = self.screen_width
        for track in self.tracks:
            to_drop: list[DanmuItem] = []
            kept: list[DanmuItem] = []
            for item in track.items:
                if item.scene_generation < min_generation and item.x >= sw:
                    to_drop.append(item)
                else:
                    kept.append(item)
            track.items = kept
            for item in to_drop:
                self._detach_item_visibility(item)
                item._pixmap = None
                self._unregister_item(track, item)
                dropped += 1
        if dropped:
            self._visibility_stale = True
        return dropped

    def _can_accept_more(self) -> bool:
        """兼容调用点：默认无 cap 时恒 True；有 cap 时尝试屏外淘汰后再判定。"""
        return self._prepare_capacity_for_new_item()

    def needs_refill(self) -> bool:
        min_n = self.min_on_screen()
        if min_n <= 0:
            return False
        offscreen_cap = self._offscreen_refill_cap()
        if offscreen_cap > 0 and self.offscreen_pending_count() >= offscreen_cap:
            return False
        return self.visible_display_count() < min_n

    def is_duplicate(self, text: str) -> bool:
        return self._is_duplicate(text)

    def get_dedup_profile_snapshot(self) -> dict:
        return snapshot_dedup_profile()

    def _is_duplicate(self, content: str) -> bool:
        """去重：委托 danmu_engine_dedup.is_duplicate_in_recent（与悬浮窗共用）。"""
        self._prune_recent_by_ttl()
        return is_duplicate_in_recent(
            content,
            self.recent,
            self.recent_exact_set,
            self.config,
            threshold_fallback=_DEDUP_THRESHOLD_FALLBACK,
        )

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        from app.danmu_engine_dedup import similarity

        return similarity(a, b)

    def start(self):
        self.running = True
        self._mark_visibility_stale()

    def stop(self):
        self.running = False

    def track_count(self) -> int:
        return len(self.tracks)

    def get_display_count(self) -> int:
        return self.current_display_count()
