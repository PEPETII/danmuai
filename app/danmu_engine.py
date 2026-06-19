"""弹幕引擎：多轨道分配、去重、加速动画与可见性统计。

默认 danmu_pending_entry_cap=300、danmu_track_retention_cap=600 作性能保护；
用户显式配置 0 表示无限制。超 cap 时对屏外 pending 做淘汰，避免无限内存增长。

轨道分配策略（_pick_track）：
  1. 空闲轨道优先（随机选一条）
  2. 无空闲时按入口区逆密度加权随机（入口区越空权重越高）
  3. 全满 fallback：从 rightmost_edge 最小的前 3 条中随机选，并调整 item.x 避免重叠

去重算法（_is_duplicate）：
  - 精确集合匹配（recent_exact_set）O(1) → 命中即重复
  - 长度预剪枝：|len(a)-len(b)| / max_len > (1-threshold) 时跳过
  - Levenshtein 相似度 > threshold（默认 0.5）时判定重复
  - 容许趣味性变体（"哈哈" vs "哈哈哈"），过滤实质重复

加速动画（trigger_acceleration）：
  先升后降三次曲线：前 33% 升速到 peak，后 67% 降回原速。
  用于场景切换时快速清空旧弹幕。

调用方：DanmuOverlay._tick() → engine.update()；DanmuApp.add_text() → engine.add_text()
"""

import logging
import random
import time
from collections import deque

from PyQt6.QtCore import QObject

from app import danmu_engine_dedup as dedup_profile
from app.api_schedule import ENGINE_BASE_FPS
from app.danmu_engine_dedup import (  # noqa: F401 — re-exported for app.danmu_engine callers
    DedupProfileStats,
    dedup_profile_enabled,
    get_last_duplicate_observation,
    is_duplicate_in_recent,
    log_dedup_profile_summary,
    reset_dedup_profile_for_tests,
    snapshot_dedup_profile,
)
from app.danmu_engine_models import DanmuItem, Track
from app.translations import Translator

_log = logging.getLogger(__name__)

# 与 app.config_defaults 保持同步（避免循环导入）
_DANMU_SPEED_FALLBACK = 2.0
_DEDUP_THRESHOLD_FALLBACK = 0.5
_DANMU_RECENT_TTL_FALLBACK = 30
_DEFAULT_DANMU_PENDING_ENTRY_CAP = 300
_DEFAULT_DANMU_TRACK_RETENTION_CAP = 600

# 淡入淡出与入口区像素距离（与 overlay._item_opacity 协同）
FADE_IN_PX = 120.0    # 右侧淡入区宽度，弹幕从右侧进入时在此区间渐显
FADE_OUT_PX = 90.0    # 左侧淡出区宽度，弹幕离开时在此区间渐隐
ENTRY_ZONE_PX = 300.0 # 入口区宽度，轨道选择和过载判断用此值

# 弹幕最大字数（截断阈值 + ... 后缀）
DEFAULT_DANMU_MAX_CHARS_ZH = 20   # 中文默认最大字数
DEFAULT_DANMU_MAX_CHARS_EN = 50   # 英文默认最大字符数
DANMU_MAX_CHARS_MIN = 5
DANMU_MAX_CHARS_MAX = 80

# 轨道行数范围
DANMU_LINES_MIN = 12
DANMU_LINES_MAX = 20
DEFAULT_DANMU_LINES = 20

# 0 = 无限制；>0 时仅作性能保护（屏外淘汰，非拒绝上屏）
DANMU_PENDING_ENTRY_CAP_MAX = 9999
DANMU_TRACK_RETENTION_CAP_MAX = 9999

LAYOUT_MODE_RATIOS: dict[str, float] = {
    "fullscreen": 1.0,
    "3/4": 0.75,
    "1/2": 0.5,
    "1/4": 0.25,
}
DEFAULT_LAYOUT_MODE = "fullscreen"


def normalize_layout_mode(mode: str | None) -> str:
    key = (mode or DEFAULT_LAYOUT_MODE).strip()
    return key if key in LAYOUT_MODE_RATIOS else DEFAULT_LAYOUT_MODE


def layout_height_ratio(config) -> float:
    return LAYOUT_MODE_RATIOS[normalize_layout_mode(config.get("layout_mode", DEFAULT_LAYOUT_MODE))]


def clamp_danmu_lines(value: int) -> int:
    return max(DANMU_LINES_MIN, min(int(value), DANMU_LINES_MAX))


def resolve_danmu_pending_entry_cap(config) -> int:
    """入口区 pending 上限；0 表示无限制。"""
    raw = config.get_int("danmu_pending_entry_cap", _DEFAULT_DANMU_PENDING_ENTRY_CAP)
    return max(0, min(raw, DANMU_PENDING_ENTRY_CAP_MAX))


def resolve_danmu_track_retention_cap(config) -> int:
    """全轨道总保留条数；0 表示无限制。"""
    raw = config.get_int("danmu_track_retention_cap", _DEFAULT_DANMU_TRACK_RETENTION_CAP)
    return max(0, min(raw, DANMU_TRACK_RETENTION_CAP_MAX))


def resolve_danmu_max_chars(config, *, lang: str | None = None) -> int:
    """上屏弹幕最大字数；未配置时中文 15、英文 40。"""
    if lang is None:
        lang = Translator.get_language()
    fallback = DEFAULT_DANMU_MAX_CHARS_EN if lang == "en" else DEFAULT_DANMU_MAX_CHARS_ZH
    raw = config.get_int("danmu_max_chars", 0)
    value = raw if raw > 0 else fallback
    return max(DANMU_MAX_CHARS_MIN, min(value, DANMU_MAX_CHARS_MAX))


def normalize_danmu_display_text(content: str, config, *, lang: str | None = None) -> str:
    """与 add_text 上屏前一致的截断规则，供去重判断与日志拒因对齐。

    公式化弹幕（自定义库、烂梗库）完整展示；仅 AI 等来源受 danmu_max_chars 限制。
    """
    from app.danmu_pool import is_formula_danmu_text

    raw = str(content).strip()
    if is_formula_danmu_text(config, raw):
        return raw
    max_len = resolve_danmu_max_chars(config, lang=lang)
    if len(raw) > max_len:
        return raw[:max_len] + "..."
    return raw


def is_persona_name_prefix_enabled(config) -> bool:
    return str(config.get("persona_name_prefix_enabled", "0")).strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def resolve_danmu_display_text(
    content: str,
    config,
    persona_id: str = "",
    *,
    lang: str | None = None,
) -> str:
    """最终上屏文本：先截断正文，再按需拼接人格显示名前缀。"""
    body = normalize_danmu_display_text(content, config, lang=lang)
    if not body or not persona_id or not is_persona_name_prefix_enabled(config):
        return body
    from app.personae import persona_display_name

    name = persona_display_name(persona_id).strip()
    return f"{name}：{body}" if name else body


def is_normalized_danmu_overlay_safe(content: str, config, *, lang: str | None = None) -> bool:
    """对已 normalize 的弹幕做 overlay 校验（含 ... 后缀时的长度上限）。"""
    from app.danmu_pool_overlay import is_overlay_safe

    max_len = resolve_danmu_max_chars(config, lang=lang)
    if content.endswith("..."):
        max_len += 3
    return is_overlay_safe(content, max_chars=max_len)
_LEVENSHTEIN_UNAVAILABLE = dedup_profile._LEVENSHTEIN_UNAVAILABLE
_LEVENSHTEIN_RATIO = dedup_profile._LEVENSHTEIN_RATIO
def _get_levenshtein_ratio():
    global _LEVENSHTEIN_RATIO
    dedup_profile._LEVENSHTEIN_RATIO = _LEVENSHTEIN_RATIO
    ratio = dedup_profile._get_levenshtein_ratio()
    _LEVENSHTEIN_RATIO = dedup_profile._LEVENSHTEIN_RATIO
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
        try:
            rows = self.config.conn.execute(
                "SELECT content FROM history ORDER BY id DESC LIMIT 30"
            ).fetchall()
            for row in reversed(rows):
                self._remember_content(row[0])
        except Exception:
            pass

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
        line_height = 40
        top_margin = 50
        bottom_margin = 80
        ratio = layout_height_ratio(self.config)
        drawable_height = self.screen_height * ratio
        configured = self.config.get_int("danmu_lines", 0)
        try:
            val = int(configured)
        except Exception:
            val = 0

        if val > 0:
            line_count = clamp_danmu_lines(val)
        else:
            usable = max(line_height, drawable_height - top_margin - bottom_margin)
            line_count = clamp_danmu_lines(int(usable / line_height))
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

    def set_screen_width(self, w: float):
        if w != self.screen_width:
            self.screen_width = w
            self._mark_visibility_stale()
            self._mark_capacity_stale()
            self._mark_motion_tick_stale()

    def set_screen_height(self, h: float):
        self.screen_height = h

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

    @staticmethod
    def _scan_motion_tick_count(tracks: list[Track], screen_width: float) -> int:
        enter_x = screen_width + FADE_IN_PX
        return sum(
            1
            for track in tracks
            for item in track.items
            if item.x + item.width > 0 and item.x < enter_x
        )

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
        old_edge = old_x + (item.width if item.width > 0 else len(item.content) * 25.0)
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

    def drawable_height(self) -> float:
        """当前 layout_mode 下弹幕可绘制区域高度（与 _init_tracks / Overlay clip 一致）。"""
        return self.screen_height * layout_height_ratio(self.config)

    def _item_in_drawable_band(self, item: DanmuItem) -> bool:
        """轨道重载前：旧 item.y 是否仍落在新可绘制带内。"""
        return item.y < self.drawable_height() - 1.0

    def _right_zone_threshold(self) -> float:
        return self.screen_width * 2 / 3

    def _item_right_edge(self, item: DanmuItem) -> float:
        w = item.width if item.width > 0 else len(item.content) * 25.0
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
        safety = max(self.current_display_count(), pending_cap, retention_cap, 1) + 8
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

    def _item_visible(self, item: DanmuItem) -> bool:
        return item.x < self.screen_width and item.x + item.width > 0

    def _item_right_visible(self, item: DanmuItem) -> bool:
        threshold = self._right_zone_threshold()
        return threshold <= item.x < self.screen_width and item.x + item.width > 0

    @staticmethod
    def _item_in_fade_zone(item: DanmuItem, screen_width: float) -> bool:
        if item.x >= screen_width or item.x + item.width <= 0:
            return False
        if item.x > screen_width - FADE_IN_PX:
            return True
        right_edge = item.x + item.width
        return right_edge < FADE_OUT_PX

    def _update_item_fade_zone(self, item: DanmuItem) -> None:
        in_fade = self._item_in_fade_zone(item, self.screen_width)
        if item._in_fade_zone == in_fade:
            return
        if in_fade:
            self._fade_zone_count += 1
        else:
            self._fade_zone_count -= 1
        item._in_fade_zone = in_fade

    def _mark_visibility_stale(self) -> None:
        self._visibility_stale = True

    def _mark_motion_tick_stale(self) -> None:
        self._motion_tick_stale = True

    def _item_needs_render_tick(self, item: DanmuItem) -> bool:
        if item.x + item.width <= 0:
            return False
        return item.x < self.screen_width + FADE_IN_PX

    def _update_item_motion_tick_state(self, item: DanmuItem) -> None:
        needs = self._item_needs_render_tick(item)
        if item._needs_motion_tick == needs:
            return
        if needs:
            self._motion_tick_count += 1
        else:
            self._motion_tick_count = max(0, self._motion_tick_count - 1)
        item._needs_motion_tick = needs
        self._motion_tick_seeded = True
        self._motion_tick_stale = False

    def _rebuild_motion_tick_count(self) -> None:
        count = 0
        for track in self.tracks:
            for item in track.items:
                needs = self._item_needs_render_tick(item)
                item._needs_motion_tick = needs
                if needs:
                    count += 1
        self._motion_tick_count = count
        self._motion_tick_stale = False
        self._motion_tick_seeded = True

    def _ensure_motion_tick_count(self) -> None:
        if self._motion_tick_stale or not self._motion_tick_seeded:
            self._rebuild_motion_tick_count()

    def _set_item_visibility(self, item: DanmuItem, visible: bool, right: bool) -> None:
        if item._vis_on_screen != visible:
            self._visible_count += 1 if visible else -1
            item._vis_on_screen = visible
        if item._right_vis_on_screen != right:
            self._right_visible_count += 1 if right else -1
            item._right_vis_on_screen = right

    def _refresh_item_visibility(self, item: DanmuItem) -> None:
        visible = self._item_visible(item)
        right = self._item_right_visible(item) if visible else False
        self._set_item_visibility(item, visible, right)
        self._update_item_fade_zone(item)
        self._visibility_counts_seeded = True

    def _detach_item_visibility(self, item: DanmuItem) -> None:
        if item._in_fade_zone:
            self._fade_zone_count -= 1
            item._in_fade_zone = False
        self._set_item_visibility(item, False, False)

    def _rebuild_visibility_counts(self) -> None:
        visible = 0
        right = 0
        fade = 0
        threshold = self._right_zone_threshold()
        sw = self.screen_width
        for track in self.tracks:
            for item in track.items:
                item_visible = item.x < sw and item.x + item.width > 0
                item._vis_on_screen = item_visible
                if item_visible:
                    visible += 1
                    item_right = threshold <= item.x < sw
                    item._right_vis_on_screen = item_right
                    if item_right:
                        right += 1
                    in_fade = self._item_in_fade_zone(item, sw)
                    item._in_fade_zone = in_fade
                    if in_fade:
                        fade += 1
                else:
                    item._right_vis_on_screen = False
                    item._in_fade_zone = False
        self._visible_count = visible
        self._right_visible_count = right
        self._fade_zone_count = fade
        self._visibility_stale = False
        self._visibility_counts_seeded = True

    def visibility_counts(self) -> tuple[int, int]:
        """返回 (全屏可见数, 右侧 2/3 可见数)；_visibility_stale 时惰性全量重建。"""
        if self._visibility_stale or not self._visibility_counts_seeded:
            self._rebuild_visibility_counts()
        return self._visible_count, self._right_visible_count

    def add_item(self, item: DanmuItem) -> bool:
        self._sync_dedup_window_generation(item.scene_generation)
        if self._is_duplicate(item.content):
            return False

        track = self._pick_track(item)
        if track is None:
            return False
        track.add(item)
        self._register_item(track, item)
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
        """弹幕入轨：截断 → 去重 → 可选屏外淘汰 → _pick_track → 记入 recent 窗口。

        默认无固定上屏数量上限；初始 x 在屏幕右缘外（待滚入）。
        skip_dedup 用于池补齐等已在外层去重的文本。
        pre_resolved=True 时 content 已是最终上屏文本（含人格前缀），不再二次截断。
        公式化弹幕经 normalize_danmu_display_text 完整展示；AI 弹幕受 danmu_max_chars 限制。
        """
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

        item.x = float(self.screen_width) + random.uniform(20.0, 90.0)
        item.speed = self.config.get_float("danmu_speed", _DANMU_SPEED_FALLBACK)
        item.width = float(len(content) * 25.0)

        track = self._pick_track(item)
        if track is None:
            return None
        track.add(item)
        self._register_item(track, item)
        self._remember_content(content)
        if self.overlay is not None:
            self.overlay.measure_item_width(item)
            if self.overlay.isVisible():
                self.overlay.ensure_render_loop()
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
        candidates = sorted(self.tracks, key=lambda t: t.rightmost_edge())[:3]
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

    def needs_render_tick(self) -> bool:
        """True when overlay should run: accel or any item in/approaching the fade band."""
        if self._accel_remaining > 0:
            return True
        self._ensure_motion_tick_count()
        return self._motion_tick_count > 0

    def right_zone_count(self) -> int:
        threshold = self.screen_width * 2 / 3
        count = 0
        for track in self.tracks:
            for item in track.items:
                if item.x >= threshold:
                    count += 1
        return count

    def visible_display_count(self) -> int:
        """当前在屏可见弹幕数（与 min_on_screen / needs_refill 联动）。"""
        if self._visibility_stale or not self._visibility_counts_seeded:
            self._rebuild_visibility_counts()
        return self._visible_count

    def visible_display_texts(self) -> list[str]:
        """当前在屏可见弹幕正文（去重，供读弹幕 TTS 抽样）。"""
        if self._visibility_stale or not self._visibility_counts_seeded:
            self._rebuild_visibility_counts()
        seen: set[str] = set()
        texts: list[str] = []
        for track in self.tracks:
            for item in track.items:
                if not item._vis_on_screen:
                    continue
                if item.content in seen:
                    continue
                seen.add(item.content)
                texts.append(item.content)
        return texts

    def items_in_fade_zone(self) -> bool:
        if self._visibility_stale or not self._visibility_counts_seeded:
            self._rebuild_visibility_counts()
        return self._fade_zone_count > 0

    def right_visible_count(self) -> int:
        if self._visibility_stale or not self._visibility_counts_seeded:
            self._rebuild_visibility_counts()
        return self._right_visible_count

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

    def drop_items_with_batch_id(self, batch_id: int) -> int:
        """Remove on-screen (and pending) danmu for a batch after scene change (strict)."""
        if batch_id <= 0:
            return 0
        dropped = 0
        for track in self.tracks:
            to_drop: list[DanmuItem] = []
            kept: list[DanmuItem] = []
            for item in track.items:
                if item.batch_id == batch_id:
                    to_drop.append(item)
                else:
                    kept.append(item)
            track.items = kept
            for item in to_drop:
                self._detach_item_visibility(item)
                item._pixmap = None
                self._forget_content(item.content)
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

    def trigger_acceleration(self, duration_frames: int = 60, peak: float = 2.0):
        """场景切换时触发先升后降加速；update() 内按进度在 1.0～peak 间插值。"""
        self._accel_peak = peak
        self._accel_total = duration_frames
        self._accel_remaining = duration_frames

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

    def update(self, speed_factor: float = 1.0, dt_sec: float = 1.0 / 60.0):
        # 加速段：前 33% 进度升到 peak，后 67% 落回 1.0（与 trigger_acceleration 配对）
        if self._accel_remaining > 0 and self._accel_total > 0:
            progress = 1.0 - (self._accel_remaining / self._accel_total)
            if progress < 0.33:
                factor = 1.0 + (self._accel_peak - 1.0) * (progress / 0.33)
            else:
                factor = self._accel_peak - (self._accel_peak - 1.0) * ((progress - 0.33) / 0.67)
            speed_factor *= factor
            self._accel_remaining -= dt_sec * ENGINE_BASE_FPS
            if self._accel_remaining < 0:
                self._accel_remaining = 0
        for track in self.tracks:
            track.update(speed_factor, dt_sec, self)

    def start(self):
        self.running = True
        self._mark_visibility_stale()

    def stop(self):
        self.running = False

    def _item_needs_motion(self, item: DanmuItem) -> bool:
        return self._item_needs_render_tick(item)

    def _collect_items_for_track_reload(self, *, clip_to_drawable: bool = False) -> list[DanmuItem]:
        preserved: list[DanmuItem] = []
        for track in self.tracks:
            for item in track.items:
                if not self._item_needs_motion(item):
                    continue
                if clip_to_drawable and not self._item_in_drawable_band(item):
                    continue
                preserved.append(item)
        return preserved

    def _nearest_track_for_y(self, y: float) -> Track | None:
        """放置算法：返回 y 坐标最近的轨道（reload_tracks 时用于保留可见弹幕位置）。"""
        if not self.tracks:
            return None
        return min(self.tracks, key=lambda t: abs(t.y - y))

    def reload_tracks(
        self,
        *,
        preserve_visible: bool = True,
        clip_to_drawable: bool = False,
    ) -> None:
        """重载轨道：layout_mode 缩小时 clip_to_drawable=True 丢弃带外弹幕。

        原因：_nearest_track_for_y 会把带外条目挤到底部轨道，导致视觉错乱。
        preserve_visible=True 时保留屏上可见条目。
        """
        if preserve_visible:
            preserved = self._collect_items_for_track_reload(
                clip_to_drawable=clip_to_drawable,
            )
        else:
            preserved = []
        self._init_tracks()
        for item in preserved:
            track = self._nearest_track_for_y(item.y)
            if track is not None:
                track.add(item)
        if preserved:
            self._rebuild_visibility_counts()
            self._rebuild_capacity_counts()
            self._rebuild_motion_tick_count()
        else:
            self._visible_count = 0
            self._right_visible_count = 0
            self._fade_zone_count = 0
            self._visibility_stale = False
            self._visibility_counts_seeded = False
            self._pending_entry_count = 0
            self._offscreen_pending_count = 0
            self._total_item_count = 0
            self._capacity_counts_seeded = False
            self._capacity_counts_stale = False
            self._motion_tick_count = 0
            self._motion_tick_stale = False
            self._motion_tick_seeded = False

    def track_count(self) -> int:
        return len(self.tracks)

    def get_display_count(self) -> int:
        return self.current_display_count()
