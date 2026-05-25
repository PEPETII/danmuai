import os
import random
import time
from collections import deque
from dataclasses import dataclass, field

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QColor, QPixmap

from app.api_schedule import ENGINE_BASE_FPS
from app.translations import Translator

# Keep in sync with app.config_defaults (avoid importing config_defaults → circular import).
_DANMU_SPEED_FALLBACK = 2.0
_DEDUP_THRESHOLD_FALLBACK = 0.5

FADE_IN_PX = 120.0
FADE_OUT_PX = 90.0
ENTRY_ZONE_PX = 300.0

DEFAULT_DANMU_MAX_CHARS_ZH = 15
DEFAULT_DANMU_MAX_CHARS_EN = 40
DANMU_MAX_CHARS_MIN = 5
DANMU_MAX_CHARS_MAX = 80

DANMU_LINES_MIN = 12
DANMU_LINES_MAX = 20
DEFAULT_DANMU_LINES = 20

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


def resolve_danmu_max_chars(config, *, lang: str | None = None) -> int:
    """上屏弹幕最大字数；未配置时中文 15、英文 40。"""
    if lang is None:
        lang = Translator.get_language()
    fallback = DEFAULT_DANMU_MAX_CHARS_EN if lang == "en" else DEFAULT_DANMU_MAX_CHARS_ZH
    raw = config.get_int("danmu_max_chars", 0)
    value = raw if raw > 0 else fallback
    return max(DANMU_MAX_CHARS_MIN, min(value, DANMU_MAX_CHARS_MAX))


def normalize_danmu_display_text(content: str, config, *, lang: str | None = None) -> str:
    """与 add_text 上屏前一致的截断规则，供去重判断与日志拒因对齐。"""
    max_len = resolve_danmu_max_chars(config, lang=lang)
    if len(content) > max_len:
        return content[:max_len] + "..."
    return content

_LEVENSHTEIN_RATIO = None
_LEVENSHTEIN_UNAVAILABLE = object()
_DEDUP_PROFILE_FLAG: bool | None = None


@dataclass
class DedupProfileStats:
    duplicate_checks: int = 0
    duplicate_hits: int = 0
    exact_set_hits: int = 0
    length_pruned: int = 0
    similarity_calls: int = 0
    similarity_fallback_calls: int = 0
    is_duplicate_ns: int = 0
    similarity_ns: int = 0


_dedup_profile_stats = DedupProfileStats()


def dedup_profile_enabled() -> bool:
    global _DEDUP_PROFILE_FLAG
    if _DEDUP_PROFILE_FLAG is None:
        value = os.environ.get("DANMU_DEDUP_PROFILE", "").strip().lower()
        _DEDUP_PROFILE_FLAG = value in ("1", "true", "yes", "on")
    return _DEDUP_PROFILE_FLAG


def reset_dedup_profile_for_tests(clear_env_cache: bool = True) -> None:
    global _DEDUP_PROFILE_FLAG, _dedup_profile_stats
    if clear_env_cache:
        _DEDUP_PROFILE_FLAG = None
    _dedup_profile_stats = DedupProfileStats()


def snapshot_dedup_profile() -> dict:
    stats = _dedup_profile_stats
    checks = max(stats.duplicate_checks, 1)
    similarity_calls = max(stats.similarity_calls, 1)
    return {
        "enabled": dedup_profile_enabled(),
        "duplicate_checks": stats.duplicate_checks,
        "duplicate_hits": stats.duplicate_hits,
        "exact_set_hits": stats.exact_set_hits,
        "length_pruned": stats.length_pruned,
        "similarity_calls": stats.similarity_calls,
        "similarity_fallback_calls": stats.similarity_fallback_calls,
        "avg_is_duplicate_us": round(stats.is_duplicate_ns / checks / 1000, 3),
        "avg_similarity_us": round(stats.similarity_ns / similarity_calls / 1000, 3)
        if stats.similarity_calls
        else 0.0,
        "is_duplicate_total_ms": round(stats.is_duplicate_ns / 1_000_000, 3),
        "similarity_total_ms": round(stats.similarity_ns / 1_000_000, 3),
    }


def log_dedup_profile_summary(logger) -> None:
    if not dedup_profile_enabled():
        return
    logger.debug(f"dedup profile: {snapshot_dedup_profile()}")


def _get_levenshtein_ratio():
    global _LEVENSHTEIN_RATIO
    if _LEVENSHTEIN_RATIO is None:
        try:
            from Levenshtein import ratio as _ratio

            _LEVENSHTEIN_RATIO = _ratio
        except ImportError:
            _LEVENSHTEIN_RATIO = _LEVENSHTEIN_UNAVAILABLE
    if _LEVENSHTEIN_RATIO is _LEVENSHTEIN_UNAVAILABLE:
        return None
    return _LEVENSHTEIN_RATIO


@dataclass
class DanmuItem:
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


class Track:
    def __init__(self, y: float):
        self.y = y
        self.items: list[DanmuItem] = []

    def can_accept(self, item: DanmuItem, screen_width: float, min_gap: float = 150.0) -> bool:
        if not self.items:
            return True
        last = self.items[-1]
        w = last.width if last.width > 0 else (len(last.content) * 25.0)
        return last.x + w + min_gap < screen_width

    def rightmost_edge(self) -> float:
        if not self.items:
            return float('-inf')
        return max(it.x + (it.width if it.width > 0 else len(it.content) * 25.0) for it in self.items)

    def add(self, item: DanmuItem):
        item.y = self.y
        self.items.append(item)

    def update(self, speed_factor: float, dt_sec: float, engine: "DanmuEngine"):
        scale = dt_sec / (1.0 / 60.0)
        i = 0
        while i < len(self.items):
            item = self.items[i]
            item.x -= item.speed * speed_factor * scale
            if item.x + item.width <= 0:
                engine._detach_item_visibility(item)
                item._pixmap = None
                self.items.pop(i)
            else:
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


class DanmuEngine(QObject):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.running = False
        self.overlay = None
        self.recent: deque[str] = deque(maxlen=30)
        self.recent_exact_set: set[str] = set()
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

    def _remember_content(self, content: str) -> None:
        evicted = None
        if self.recent.maxlen and len(self.recent) == self.recent.maxlen:
            evicted = self.recent[0]
        self.recent.append(content)
        self.recent_exact_set.add(content)
        if evicted is not None and evicted not in self.recent:
            self.recent_exact_set.discard(evicted)

    def _forget_content(self, content: str) -> None:
        """从去重窗口移除一条上屏记录（如弹幕被场景/批次清屏）。"""
        try:
            self.recent.remove(content)
        except ValueError:
            pass
        if content not in self.recent:
            self.recent_exact_set.discard(content)

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

    def set_screen_width(self, w: float):
        if w != self.screen_width:
            self.screen_width = w
            self._mark_visibility_stale()

    def set_screen_height(self, h: float):
        self.screen_height = h

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
        return sum(
            1 for track in self.tracks for item in track.items if self._in_entry_zone(item)
        )

    def offscreen_pending_count(self) -> int:
        return sum(
            1 for track in self.tracks for item in track.items if self._is_offscreen_pending(item)
        )

    def right_entry_count(self) -> int:
        return self.pending_entry_count()

    def max_pending_entry(self) -> int:
        track_count = len(self.tracks)
        if track_count <= 0:
            return 0
        return max(track_count, track_count * 2)

    def _offscreen_refill_cap(self) -> int:
        track_count = len(self.tracks)
        if track_count <= 0:
            return 1
        return max(1, track_count // 2)

    def entry_zone_overloaded(self) -> bool:
        cap = self.max_pending_entry()
        if cap <= 0:
            return False
        return self.pending_entry_count() >= cap

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
        if self._visibility_stale or not self._visibility_counts_seeded:
            self._rebuild_visibility_counts()
        return self._visible_count, self._right_visible_count

    def add_item(self, item: DanmuItem) -> bool:
        if self._is_duplicate(item.content):
            return False

        track = self._pick_track(item)
        if track is None:
            return False
        track.add(item)
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
    ) -> DanmuItem | None:
        content = normalize_danmu_display_text(content, self.config)

        if not skip_dedup and self._is_duplicate(content):
            return None

        if not self._can_accept_more():
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
        self._remember_content(content)
        if self.overlay is not None:
            self.overlay.measure_item_width(item)
            self.overlay.prepare_item_pixmap(item)
            if self.overlay.isVisible():
                self.overlay.ensure_render_loop()
        self._refresh_item_visibility(item)
        return item

    def _calc_min_gap(self, item: DanmuItem) -> float:
        return max(80.0, item.width * 0.5)

    def _pick_track(self, item: DanmuItem) -> Track | None:
        if not self.tracks:
            return None

        min_gap = self._calc_min_gap(item)

        # 1. 空闲轨道优先
        idle = [t for t in self.tracks if not t.items]
        if idle:
            return random.choice(idle)

        # 2. 可接受轨道：按逆密度加权随机（items 越少权重越高）
        acceptable = [t for t in self.tracks if t.can_accept(item, self.screen_width, min_gap)]
        if acceptable:
            weights = [1.0 / (1 + len(t.items)) for t in acceptable]
            total = sum(weights)
            weights = [w / total for w in weights]
            return random.choices(acceptable, weights=weights, k=1)[0]

        # 3. 全满 fallback：入口区已过载或队尾过远则拒绝，否则选 rightmost_edge 最小的轨道
        if self.entry_zone_overloaded():
            return None
        best_track = min(self.tracks, key=lambda t: t.rightmost_edge())
        tail_edge = best_track.rightmost_edge()
        if tail_edge > self.screen_width + ENTRY_ZONE_PX:
            return None
        item.x = max(item.x, tail_edge + random.uniform(50.0, 250.0))
        cap = self.screen_width + FADE_IN_PX - 1.0
        if item.x > cap:
            item.x = cap
        return best_track

    def danmu_pool_enabled(self) -> bool:
        from app.danmu_pool import danmu_pool_enabled_from_config

        return danmu_pool_enabled_from_config(self.config)

    def min_on_screen(self) -> int:
        if not self.danmu_pool_enabled():
            return 0
        return self.config.get_int("min_on_screen", 5)

    def deficit_below_min(self) -> int:
        min_n = self.min_on_screen()
        if min_n <= 0:
            return 0
        return max(0, min_n - self.visible_display_count())

    def current_display_count(self) -> int:
        count = 0
        for track in self.tracks:
            count += len(track.items)
        return count

    def needs_render_tick(self) -> bool:
        """True when overlay should run: accel or any item in/approaching the fade band."""
        if self._accel_remaining > 0:
            return True
        sw = self.screen_width
        enter_x = sw + FADE_IN_PX
        for track in self.tracks:
            for item in track.items:
                if item.x + item.width <= 0:
                    continue
                if item.x < enter_x:
                    return True
        return False

    def right_zone_count(self) -> int:
        threshold = self.screen_width * 2 / 3
        count = 0
        for track in self.tracks:
            for item in track.items:
                if item.x >= threshold:
                    count += 1
        return count

    def visible_display_count(self) -> int:
        if self._visibility_stale or not self._visibility_counts_seeded:
            self._rebuild_visibility_counts()
        return self._visible_count

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
        for track in self.tracks:
            for item in track.items:
                if item.x >= self.screen_width:
                    self._detach_item_visibility(item)
            dropped += track.drop_pending(self.screen_width)
        return dropped

    def drop_items_with_batch_id(self, batch_id: int) -> int:
        """Remove on-screen (and pending) danmu for a batch after scene change (strict)."""
        if batch_id <= 0:
            return 0
        dropped = 0
        for track in self.tracks:
            kept: list[DanmuItem] = []
            for item in track.items:
                if item.batch_id == batch_id:
                    self._detach_item_visibility(item)
                    item._pixmap = None
                    self._forget_content(item.content)
                    dropped += 1
                else:
                    kept.append(item)
            track.items = kept
        if dropped:
            self._visibility_stale = True
        return dropped

    def clear_dedup_window(self) -> None:
        self.recent.clear()
        self.recent_exact_set.clear()

    def drop_pending_below_generation(self, min_generation: int) -> int:
        dropped = 0
        sw = self.screen_width
        for track in self.tracks:
            kept: list[DanmuItem] = []
            for item in track.items:
                if item.scene_generation < min_generation and item.x >= sw:
                    self._detach_item_visibility(item)
                    item._pixmap = None
                    dropped += 1
                else:
                    kept.append(item)
            track.items = kept
        if dropped:
            self._visibility_stale = True
        return dropped

    def drop_items_below_scene_generation(self, min_generation: int) -> int:
        dropped = 0
        for track in self.tracks:
            kept: list[DanmuItem] = []
            for item in track.items:
                if item.scene_generation < min_generation:
                    self._detach_item_visibility(item)
                    item._pixmap = None
                    self._forget_content(item.content)
                    dropped += 1
                else:
                    kept.append(item)
            track.items = kept
        if dropped:
            self._visibility_stale = True
        return dropped

    def _can_accept_more(self) -> bool:
        return not self.entry_zone_overloaded()

    def needs_refill(self) -> bool:
        min_n = self.min_on_screen()
        if min_n <= 0:
            return False
        if self.entry_zone_overloaded():
            return False
        if self.offscreen_pending_count() >= self._offscreen_refill_cap():
            return False
        self._rebuild_visibility_counts()
        return self._visible_count < min_n

    def trigger_acceleration(self, duration_frames: int = 60, peak: float = 2.0):
        self._accel_peak = peak
        self._accel_total = duration_frames
        self._accel_remaining = duration_frames

    def is_duplicate(self, text: str) -> bool:
        return self._is_duplicate(text)

    def get_dedup_profile_snapshot(self) -> dict:
        return snapshot_dedup_profile()

    def _is_duplicate(self, content: str) -> bool:
        profile = dedup_profile_enabled()
        started = time.perf_counter_ns() if profile else 0

        if content in self.recent_exact_set:
            if profile:
                _dedup_profile_stats.exact_set_hits += 1
            result = True
        elif not self.recent:
            result = False
        else:
            threshold = self.config.get_float("dedup_threshold", _DEDUP_THRESHOLD_FALLBACK)
            result = False
            for prev in self.recent:
                # 快速路径：完全相同
                if content == prev:
                    result = True
                    break
                # 快速跳过：长度差异太大时不需要计算相似度
                if threshold >= 1.0:
                    continue
                len_diff = abs(len(content) - len(prev))
                max_len = max(len(content), len(prev))
                if max_len > 0 and len_diff / max_len > (1 - threshold):
                    if profile:
                        _dedup_profile_stats.length_pruned += 1
                    continue
                if self._similarity(content, prev) > threshold:
                    result = True
                    break

        if profile:
            _dedup_profile_stats.duplicate_checks += 1
            if result:
                _dedup_profile_stats.duplicate_hits += 1
            _dedup_profile_stats.is_duplicate_ns += time.perf_counter_ns() - started
        return result

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        profile = dedup_profile_enabled()
        started = time.perf_counter_ns() if profile else 0

        if not a or not b:
            result = 0.0
        else:
            ratio_fn = _get_levenshtein_ratio()
            if ratio_fn is not None:
                result = ratio_fn(a, b)
            else:
                if profile:
                    _dedup_profile_stats.similarity_fallback_calls += 1
                m, n = len(a), len(b)
                if m > n:
                    a, b = b, a
                    m, n = n, m
                prev_row = list(range(n + 1))
                for i in range(1, m + 1):
                    curr = [i] + [0] * n
                    for j in range(1, n + 1):
                        cost = 0 if a[i - 1] == b[j - 1] else 1
                        curr[j] = min(curr[j - 1] + 1, prev_row[j] + 1, prev_row[j - 1] + cost)
                    prev_row = curr
                dist = prev_row[n]
                result = 1 - dist / max(len(a), len(b))

        if profile:
            _dedup_profile_stats.similarity_calls += 1
            _dedup_profile_stats.similarity_ns += time.perf_counter_ns() - started
        return result

    def update(self, speed_factor: float = 1.0, dt_sec: float = 1.0 / 60.0):
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
        self._visibility_stale = False
        self._visibility_counts_seeded = True

    def start(self):
        self.running = True

    def stop(self):
        self.running = False

    def _item_needs_motion(self, item: DanmuItem) -> bool:
        if item.x + item.width <= 0:
            return False
        return item.x < self.screen_width + FADE_IN_PX

    def _collect_items_for_track_reload(self) -> list[DanmuItem]:
        preserved: list[DanmuItem] = []
        for track in self.tracks:
            for item in track.items:
                if self._item_needs_motion(item):
                    preserved.append(item)
        return preserved

    def _nearest_track_for_y(self, y: float) -> Track | None:
        if not self.tracks:
            return None
        return min(self.tracks, key=lambda t: abs(t.y - y))

    def reload_tracks(self, *, preserve_visible: bool = True) -> None:
        preserved = self._collect_items_for_track_reload() if preserve_visible else []
        self._init_tracks()
        for item in preserved:
            track = self._nearest_track_for_y(item.y)
            if track is not None:
                track.add(item)
        self._visible_count = 0
        self._right_visible_count = 0
        self._fade_zone_count = 0
        self._visibility_stale = True
        self._visibility_counts_seeded = False

    def track_count(self) -> int:
        return len(self.tracks)

    def get_display_count(self) -> int:
        return self.current_display_count()
