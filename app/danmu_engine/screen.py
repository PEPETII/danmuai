"""DanmuEngine 屏幕适配子模块：模块级函数、常量与屏幕适配方法。

从原 app/danmu_engine.py 拆出，保持零业务逻辑变更。
"""

import json
import random

from PyQt6.QtGui import QColor

from app.danmu_engine_models import DanmuItem, Track
from app.translations import Translator

# 与 app.config_defaults 保持同步（避免循环导入）
_DEFAULT_DANMU_PENDING_ENTRY_CAP = 300
_DEFAULT_DANMU_TRACK_RETENTION_CAP = 600

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
MAX_EVICT_ITERATIONS = 512  # _prepare_capacity_for_new_item 淘汰循环硬性上限

LAYOUT_MODE_RATIOS: dict[str, float] = {
    "fullscreen": 1.0,
    "3/4": 0.75,
    "1/2": 0.5,
    "1/4": 0.25,
}
DEFAULT_LAYOUT_MODE = "fullscreen"

# 轨道布局基线（逻辑像素 @ 100% DPI）；_init_tracks 按 ui_scale_factor 缩放
TRACK_LINE_HEIGHT_BASE = 40
TRACK_TOP_MARGIN_BASE = 50
TRACK_BOTTOM_MARGIN_BASE = 80


def ui_scale_factor() -> float:
    """UI 缩放因子；高分屏下与 QFont DPI 放大对齐。"""
    try:
        from PyQt6.QtGui import QGuiApplication

        app = QGuiApplication.instance()
        if app is None:
            return 1.0
        screen = app.primaryScreen()
        if screen is None:
            return 1.0
        return max(1.0, float(screen.devicePixelRatio()))
    except Exception:
        return 1.0


def track_layout_metrics(config=None) -> dict[str, float]:
    """返回缩放后的轨道行高与上下边距（与 _init_tracks / Overlay clip 一致）。"""
    del config  # 预留：未来若按 font_size 微调可在此读取
    scale = ui_scale_factor()
    return {
        "line_height": float(TRACK_LINE_HEIGHT_BASE) * scale,
        "top_margin": float(TRACK_TOP_MARGIN_BASE) * scale,
        "bottom_margin": float(TRACK_BOTTOM_MARGIN_BASE) * scale,
    }


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


def resolve_danmu_color(config) -> QColor:
    """根据颜色配置返回一个 QColor。

    读取 danmu_font_color_selected（JSON 列表）和 danmu_font_color_mode / weights，
    按平均或加权随机抽样。解析失败或列表为空时 fallback 白色。
    """
    raw_selected = config.get("danmu_font_color_selected", "")
    try:
        selected = json.loads(raw_selected)
    except (json.JSONDecodeError, TypeError):
        selected = []
    if not isinstance(selected, list) or not selected:
        return QColor(255, 255, 255)

    # 去重并过滤非字符串项
    selected = [str(c).strip().upper() for c in selected if isinstance(c, str) and c.strip()]
    if not selected:
        return QColor(255, 255, 255)
    if len(selected) == 1:
        return QColor(selected[0])

    mode = str(config.get("danmu_font_color_mode", "equal")).strip().lower()
    if mode == "weighted":
        raw_weights = config.get("danmu_font_color_weights", "{}")
        try:
            weights_map = json.loads(raw_weights)
        except (json.JSONDecodeError, TypeError):
            weights_map = {}
        if not isinstance(weights_map, dict):
            weights_map = {}
        weights = []
        for color in selected:
            w = weights_map.get(color)
            if w is None:
                w = weights_map.get(color.lower(), 0)
            try:
                weights.append(float(w))
            except (TypeError, ValueError):
                weights.append(0.0)
        total = sum(weights)
        if total > 0:
            return QColor(random.choices(selected, weights=weights, k=1)[0])
        # 权重全 0 fallback 等概率
        return QColor(random.choice(selected))

    # 默认等概率
    return QColor(random.choice(selected))


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
    from app.personae import persona_display_name_with_config

    name = persona_display_name_with_config(persona_id, config).strip()
    return f"{name}：{body}" if name else body


# --- DanmuEngine 屏幕适配方法（模块级函数，由 _mount_methods 挂载到类）---


def _engine_set_screen_width(self, w: float):
    if w != self.screen_width:
        self.screen_width = w
        self._mark_visibility_stale()
        self._mark_capacity_stale()
        self._mark_motion_tick_stale()


def _engine_set_screen_height(self, h: float):
    if h != self.screen_height:
        self.screen_height = h
        self._mark_capacity_stale()
        self._mark_motion_tick_stale()


def _engine_drawable_height(self) -> float:
    """当前 layout_mode 下弹幕可绘制区域高度（与 _init_tracks / Overlay clip 一致）。"""
    return self.screen_height * layout_height_ratio(self.config)


def _engine_item_in_drawable_band(self, item: DanmuItem) -> bool:
    """轨道重载前：旧 item.y 是否仍落在新可绘制带内。"""
    return item.y < self.drawable_height() - 1.0


def _engine_estimate_char_width(self) -> float:
    """根据字体配置估算单个全角字符的平均像素宽度。

    全角字符宽度 ≈ font_size（非粗体）~ font_size × 1.08（粗体）。
    粗体字横向膨胀约 5-10%，取 1.08 中值。
    """
    font_size = self.config.get_int("font_size", 24)
    bold = (
        str(self.config.get("danmu_font_bold", "1") or "1")
        .strip()
        .lower()
        not in ("0", "false", "no")
    )
    return float(font_size) * (1.08 if bold else 1.0)


def _engine_estimate_content_width(self, content: str) -> float:
    """估算文本渲染像素宽度。

    统计全角与半角字符数量，分别乘以对应估算宽度后求和。
    比纯 len()*常数 更准确，尤其对中英混合文本。
    """
    char_width = self._estimate_char_width()
    fullwidth_count = sum(
        1
        for ch in content
        if ord(ch) > 0x2000 or ch in "　，。！？、：；""''（）【】《》"
    )
    halfwidth_count = len(content) - fullwidth_count
    # 半角字符（ASCII等）宽度约为全角的 0.55
    return float(fullwidth_count) * char_width + float(halfwidth_count) * char_width * 0.55


def _engine_collect_items_for_track_reload(self, *, clip_to_drawable: bool = False) -> list[DanmuItem]:
    preserved: list[DanmuItem] = []
    for track in self.tracks:
        for item in track.items:
            if not self._item_needs_motion(item):
                continue
            if clip_to_drawable and not self._item_in_drawable_band(item):
                continue
            preserved.append(item)
    return preserved


def _engine_nearest_track_for_y(self, y: float) -> Track | None:
    """放置算法：返回 y 坐标最近的轨道（reload_tracks 时用于保留可见弹幕位置）。"""
    if not self.tracks:
        return None
    return min(self.tracks, key=lambda t: abs(t.y - y))


def _engine_reload_tracks(
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


def _mount_methods(cls) -> None:
    """将屏幕适配方法挂载到 DanmuEngine 类（由 __init__.py 在类定义后调用）。"""
    cls.set_screen_width = _engine_set_screen_width
    cls.set_screen_height = _engine_set_screen_height
    cls.drawable_height = _engine_drawable_height
    cls._item_in_drawable_band = _engine_item_in_drawable_band
    cls._estimate_char_width = _engine_estimate_char_width
    cls._estimate_content_width = _engine_estimate_content_width
    cls._collect_items_for_track_reload = _engine_collect_items_for_track_reload
    cls._nearest_track_for_y = _engine_nearest_track_for_y
    cls.reload_tracks = _engine_reload_tracks
