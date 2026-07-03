"""DanmuEngine 渲染子模块：渲染常量与渲染/可见性方法。

从原 app/danmu_engine.py 拆出，保持零业务逻辑变更。
"""

from app.api_schedule import ENGINE_BASE_FPS
from app.danmu_engine_models import DanmuItem, Track

# 淡入淡出与入口区像素距离（与 overlay._item_opacity 协同）
FADE_IN_PX = 120.0    # 右侧淡入区宽度，弹幕从右侧进入时在此区间渐显
FADE_OUT_PX = 90.0    # 左侧淡出区宽度，弹幕离开时在此区间渐隐
ENTRY_ZONE_PX = 300.0 # 入口区宽度，轨道选择和过载判断用此值


# --- DanmuEngine 渲染/可见性方法（模块级函数，由 _mount_methods 挂载到类）---


def _engine_scan_motion_tick_count(tracks: list[Track], screen_width: float) -> int:
    enter_x = screen_width + FADE_IN_PX
    return sum(
        1
        for track in tracks
        for item in track.items
        if item.x + item.width > 0 and item.x < enter_x
    )


def _engine_right_zone_threshold(self) -> float:
    return self.screen_width * 2 / 3


def _engine_item_visible(self, item: DanmuItem) -> bool:
    return item.x < self.screen_width and item.x + item.width > 0


def _engine_item_right_visible(self, item: DanmuItem) -> bool:
    threshold = self._right_zone_threshold()
    return threshold <= item.x < self.screen_width and item.x + item.width > 0


def _engine_item_in_fade_zone(item: DanmuItem, screen_width: float) -> bool:
    if item.x >= screen_width or item.x + item.width <= 0:
        return False
    if item.x > screen_width - FADE_IN_PX:
        return True
    right_edge = item.x + item.width
    return right_edge < FADE_OUT_PX


def _engine_update_item_fade_zone(self, item: DanmuItem) -> None:
    in_fade = self._item_in_fade_zone(item, self.screen_width)
    if item._in_fade_zone == in_fade:
        return
    if in_fade:
        self._fade_zone_count += 1
    else:
        self._fade_zone_count -= 1
    item._in_fade_zone = in_fade


def _engine_mark_visibility_stale(self) -> None:
    self._visibility_stale = True


def _engine_mark_motion_tick_stale(self) -> None:
    self._motion_tick_stale = True


def _engine_item_needs_render_tick(self, item: DanmuItem) -> bool:
    if item.x + item.width <= 0:
        return False
    return item.x < self.screen_width + FADE_IN_PX


def _engine_update_item_motion_tick_state(self, item: DanmuItem) -> None:
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


def _engine_rebuild_motion_tick_count(self) -> None:
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


def _engine_ensure_motion_tick_count(self) -> None:
    if self._motion_tick_stale or not self._motion_tick_seeded:
        self._rebuild_motion_tick_count()


def _engine_set_item_visibility(self, item: DanmuItem, visible: bool, right: bool) -> None:
    if item._vis_on_screen != visible:
        self._visible_count += 1 if visible else -1
        item._vis_on_screen = visible
    if item._right_vis_on_screen != right:
        self._right_visible_count += 1 if right else -1
        item._right_vis_on_screen = right


def _engine_refresh_item_visibility(self, item: DanmuItem) -> None:
    visible = self._item_visible(item)
    right = self._item_right_visible(item) if visible else False
    self._set_item_visibility(item, visible, right)
    self._update_item_fade_zone(item)
    self._visibility_counts_seeded = True


def _engine_detach_item_visibility(self, item: DanmuItem) -> None:
    if item._in_fade_zone:
        self._fade_zone_count -= 1
        item._in_fade_zone = False
    self._set_item_visibility(item, False, False)


def _engine_rebuild_visibility_counts(self) -> None:
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


def _engine_visibility_counts(self) -> tuple[int, int]:
    """返回 (全屏可见数, 右侧 2/3 可见数)；_visibility_stale 时惰性全量重建。"""
    if self._visibility_stale or not self._visibility_counts_seeded:
        self._rebuild_visibility_counts()
    return self._visible_count, self._right_visible_count


def _engine_needs_render_tick(self) -> bool:
    """True when overlay should run: accel or any item in/approaching the fade band."""
    if self._accel_remaining > 0:
        return True
    self._ensure_motion_tick_count()
    return self._motion_tick_count > 0


def _engine_right_zone_count(self) -> int:
    threshold = self.screen_width * 2 / 3
    count = 0
    for track in self.tracks:
        for item in track.items:
            if item.x >= threshold:
                count += 1
    return count


def _engine_visible_display_count(self) -> int:
    """当前在屏可见弹幕数（与 min_on_screen / needs_refill 联动）。"""
    if self._visibility_stale or not self._visibility_counts_seeded:
        self._rebuild_visibility_counts()
    return self._visible_count


def _engine_visible_display_texts(self) -> list[str]:
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


def _engine_items_in_fade_zone(self) -> bool:
    if self._visibility_stale or not self._visibility_counts_seeded:
        self._rebuild_visibility_counts()
    return self._fade_zone_count > 0


def _engine_right_visible_count(self) -> int:
    if self._visibility_stale or not self._visibility_counts_seeded:
        self._rebuild_visibility_counts()
    return self._right_visible_count


def _engine_trigger_acceleration(self, duration_frames: int = 60, peak: float = 2.0):
    """场景切换时触发先升后降加速；update() 内按进度在 1.0～peak 间插值。"""
    self._accel_peak = peak
    self._accel_total = duration_frames
    self._accel_remaining = duration_frames


def _engine_update(self, speed_factor: float = 1.0, dt_sec: float = 1.0 / 60.0):
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


def _engine_item_needs_motion(self, item: DanmuItem) -> bool:
    return self._item_needs_render_tick(item)


def _mount_methods(cls) -> None:
    """将渲染/可见性方法挂载到 DanmuEngine 类（由 __init__.py 在类定义后调用）。"""
    cls._scan_motion_tick_count = staticmethod(_engine_scan_motion_tick_count)
    cls._right_zone_threshold = _engine_right_zone_threshold
    cls._item_visible = _engine_item_visible
    cls._item_right_visible = _engine_item_right_visible
    cls._item_in_fade_zone = staticmethod(_engine_item_in_fade_zone)
    cls._update_item_fade_zone = _engine_update_item_fade_zone
    cls._mark_visibility_stale = _engine_mark_visibility_stale
    cls._mark_motion_tick_stale = _engine_mark_motion_tick_stale
    cls._item_needs_render_tick = _engine_item_needs_render_tick
    cls._update_item_motion_tick_state = _engine_update_item_motion_tick_state
    cls._rebuild_motion_tick_count = _engine_rebuild_motion_tick_count
    cls._ensure_motion_tick_count = _engine_ensure_motion_tick_count
    cls._set_item_visibility = _engine_set_item_visibility
    cls._refresh_item_visibility = _engine_refresh_item_visibility
    cls._detach_item_visibility = _engine_detach_item_visibility
    cls._rebuild_visibility_counts = _engine_rebuild_visibility_counts
    cls.visibility_counts = _engine_visibility_counts
    cls.needs_render_tick = _engine_needs_render_tick
    cls.right_zone_count = _engine_right_zone_count
    cls.visible_display_count = _engine_visible_display_count
    cls.visible_display_texts = _engine_visible_display_texts
    cls.items_in_fade_zone = _engine_items_in_fade_zone
    cls.right_visible_count = _engine_right_visible_count
    cls.trigger_acceleration = _engine_trigger_acceleration
    cls.update = _engine_update
    cls._item_needs_motion = _engine_item_needs_motion
