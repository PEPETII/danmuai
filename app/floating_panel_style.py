"""从下到上浮动面板样式契约（Qt / Web 共享纯数据源）。

W-FP-STYLE-CONTRACT-001：字段键、预设、归一化与只读预设快照。

扁平存储约定（禁止单一 JSON 样式档）
--------------------------------
- 普通标量：纯字符串，如 ``"wechat"``、``"12"``、``"1"`` / ``"0"``。
- 调色板（``*_colors``）：**独立字段**保存 JSON **数组**字符串，
  例如 ``'["#FFECD2","#DDF5D7"]'``。
- 权重（``*_weights``）：**独立字段**保存 JSON **对象**字符串，
  例如 ``'{"#FFECD2":1.0}'``（键为规范化颜色，值为非负浮点）。
- 颜色：仅 ``#RRGGBB`` 或 ``#RRGGBBAA``（大小写不敏感，归一化后为大写）。
- 选色 ``equal`` / ``weighted``：``equal`` 等概率，**不得**依赖全局随机状态
  做契约测试；实际抽样由下游 Qt 层在创建条目时固定样式索引。

默认预设为 ``wechat``；``custom`` 非法值回退 wechat 工厂默认，不写空值。
预设展开 patch **不得**改 ``danmu_render_mode`` 或横向 scrolling 字段。
本模块不导入 Qt / FastAPI / Web 对象。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Mapping

# ---------------------------------------------------------------------------
# 枚举与版本
# ---------------------------------------------------------------------------

STYLE_CONTRACT_VERSION = 1

STYLE_PRESET_IDS: tuple[str, ...] = ("classic", "wechat")
STYLE_PRESET_CHOICES: tuple[str, ...] = ("classic", "wechat", "custom")
DEFAULT_STYLE_PRESET = "wechat"

SHAPE_CHOICES: tuple[str, ...] = ("card", "bubble")
COLOR_MODE_CHOICES: tuple[str, ...] = ("equal", "weighted")
DEFAULT_COLOR_MODE = "equal"

ENTRY_ANIMATION_CHOICES: tuple[str, ...] = ("none", "fade", "slide_up")
EXIT_ANIMATION_CHOICES: tuple[str, ...] = ("none", "fade")
DEFAULT_ENTRY_ANIMATION = "fade"
DEFAULT_EXIT_ANIMATION = "fade"

TAIL_STYLE_CHOICES: tuple[str, ...] = ("round", "sharp", "none")
DEFAULT_TAIL_STYLE = "round"

_HEX_COLOR_RE = re.compile(r"^#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})$")

PALETTE_MIN_COLORS = 1
PALETTE_MAX_COLORS = 16

# ---------------------------------------------------------------------------
# 数值安全范围：(min, max, wechat 工厂默认)
# ---------------------------------------------------------------------------

# key -> (min, max, wechat_default)
STYLE_INT_RANGES: dict[str, tuple[int, int, int]] = {
    "floating_panel_card_opacity": (0, 100, 78),  # 200/255 ≈ 暖色气泡 alpha
    "floating_panel_outline_width": (0, 8, 2),
    "floating_panel_shadow_blur": (0, 32, 12),
    "floating_panel_shadow_offset_x": (-20, 20, 2),
    "floating_panel_shadow_offset_y": (-20, 20, 2),
    "floating_panel_shadow_opacity": (0, 100, 30),
    "floating_panel_border_width": (0, 8, 1),
    "floating_panel_border_opacity": (0, 100, 40),
    "floating_panel_padding_x": (0, 48, 14),
    "floating_panel_padding_y": (0, 48, 10),
    "floating_panel_radius": (0, 48, 16),
    "floating_panel_tail_width": (0, 32, 8),
    "floating_panel_tail_height": (0, 32, 10),
    "floating_panel_tail_size": (0, 32, 10),
    "floating_panel_tail_offset_y": (0, 100, 38),
    "floating_panel_username_size": (8, 32, 14),
    "floating_panel_username_weight": (100, 900, 700),
    "floating_panel_content_size": (8, 32, 16),
    "floating_panel_content_weight": (100, 900, 400),
    "floating_panel_content_line_height": (100, 200, 140),
    "floating_panel_gap_username_content": (0, 24, 4),
    "floating_panel_entry_duration_ms": (0, 2000, 200),
    "floating_panel_push_duration_ms": (0, 2000, 180),
    "floating_panel_exit_duration_ms": (0, 2000, 200),
    "floating_panel_stack_gap": (0, 48, 8),
}

# 沿用既有基础字段范围（与 ConfigService 一致；缺失时 snapshot 用）
BASE_INT_RANGES: dict[str, tuple[int, int, int]] = {
    "floating_panel_width": (200, 800, 360),
    "floating_panel_max_items": (1, 50, 12),
    "floating_panel_opacity": (0, 100, 85),
    "floating_panel_font_size": (12, 48, 20),
}

# ---------------------------------------------------------------------------
# 字段键集合
# ---------------------------------------------------------------------------

# 新增样式字段（须进入 CONFIG_DEFAULTS / WEB_CONFIG_KEYS）
STYLE_FIELD_KEYS: tuple[str, ...] = (
    "floating_panel_style_preset",
    "floating_panel_shape",
    "floating_panel_card_colors",
    "floating_panel_card_color_mode",
    "floating_panel_card_color_weights",
    "floating_panel_text_colors",
    "floating_panel_text_color_mode",
    "floating_panel_text_color_weights",
    "floating_panel_card_opacity",
    "floating_panel_outline_enabled",
    "floating_panel_outline_color",
    "floating_panel_outline_width",
    "floating_panel_shadow_enabled",
    "floating_panel_shadow_color",
    "floating_panel_shadow_opacity",
    "floating_panel_shadow_blur",
    "floating_panel_shadow_offset_x",
    "floating_panel_shadow_offset_y",
    "floating_panel_border_enabled",
    "floating_panel_border_color",
    "floating_panel_border_width",
    "floating_panel_border_opacity",
    "floating_panel_padding_x",
    "floating_panel_padding_y",
    "floating_panel_radius",
    "floating_panel_tail_enabled",
    "floating_panel_tail_style",
    "floating_panel_tail_width",
    "floating_panel_tail_height",
    "floating_panel_tail_size",
    "floating_panel_tail_offset_y",
    "floating_panel_username_enabled",
    "floating_panel_username_text",
    "floating_panel_username_color",
    "floating_panel_username_size",
    "floating_panel_username_weight",
    "floating_panel_username_separator",
    "floating_panel_content_size",
    "floating_panel_content_weight",
    "floating_panel_content_line_height",
    "floating_panel_gap_username_content",
    "floating_panel_entry_animation",
    "floating_panel_entry_duration_ms",
    "floating_panel_push_duration_ms",
    "floating_panel_exit_animation",
    "floating_panel_exit_duration_ms",
    "floating_panel_stack_gap",
)

# 样式恢复默认分组：新字段 + 与外观相关的既有基础字段
STYLE_RESTORE_KEYS: tuple[str, ...] = STYLE_FIELD_KEYS + (
    "floating_panel_width",
    "floating_panel_max_items",
    "floating_panel_speed",
    "floating_panel_opacity",
    "floating_panel_font_family",
    "floating_panel_font_size",
    "floating_panel_font_bold",
)

# 预设展开写入的键（不含 danmu_render_mode / scrolling / 布局偏移）
STYLE_PRESET_APPLY_KEYS: tuple[str, ...] = STYLE_FIELD_KEYS + (
    "floating_panel_font_family",
    "floating_panel_font_size",
    "floating_panel_font_bold",
    "floating_panel_opacity",
)

PALETTE_KEYS: tuple[str, ...] = (
    "floating_panel_card_colors",
    "floating_panel_text_colors",
)

WEIGHT_KEYS: tuple[str, ...] = (
    "floating_panel_card_color_weights",
    "floating_panel_text_color_weights",
)

BOOL_KEYS: tuple[str, ...] = (
    "floating_panel_outline_enabled",
    "floating_panel_shadow_enabled",
    "floating_panel_tail_enabled",
    "floating_panel_border_enabled",
    "floating_panel_username_enabled",
    "floating_panel_font_bold",
)

# ---------------------------------------------------------------------------
# 预设 canonical（测试锁定）
# ---------------------------------------------------------------------------

CLASSIC_CARD_COLORS: tuple[str, ...] = (
    "#FFFFFF",
    "#F5D401",
    "#3CA0FB",
    "#3ACD2E",
)
WECHAT_CARD_COLORS: tuple[str, ...] = (
    "#FFECD2",  # 暖色气泡首色（W-FP-BUBBLE-001）
    "#DDF5D7",
    "#DDEBFF",
    "#FFDDE8",
)
WECHAT_TEXT_COLOR = "#281C12"  # QColor(40, 28, 18)
CLASSIC_TEXT_COLOR = "#000000"

# classic：shape=card、无尾巴；深色描边、轻阴影、黑字
_CLASSIC_FLAT: dict[str, str] = {
    "floating_panel_style_preset": "classic",
    "floating_panel_shape": "card",
    "floating_panel_card_colors": json.dumps(list(CLASSIC_CARD_COLORS), ensure_ascii=False),
    "floating_panel_card_color_mode": "equal",
    "floating_panel_card_color_weights": "{}",
    "floating_panel_text_colors": json.dumps([CLASSIC_TEXT_COLOR], ensure_ascii=False),
    "floating_panel_text_color_mode": "equal",
    "floating_panel_text_color_weights": "{}",
    "floating_panel_card_opacity": "95",
    "floating_panel_outline_enabled": "1",
    "floating_panel_outline_color": "#1A1A1A",
    "floating_panel_outline_width": "1",
    "floating_panel_shadow_enabled": "0",
    "floating_panel_shadow_color": "#000000",
    "floating_panel_shadow_opacity": "20",
    "floating_panel_shadow_blur": "8",
    "floating_panel_shadow_offset_x": "0",
    "floating_panel_shadow_offset_y": "2",
    "floating_panel_border_enabled": "0",
    "floating_panel_border_color": "#FFFFFF",
    "floating_panel_border_width": "1",
    "floating_panel_border_opacity": "30",
    "floating_panel_padding_x": "12",
    "floating_panel_padding_y": "8",
    "floating_panel_radius": "10",
    "floating_panel_tail_enabled": "0",
    "floating_panel_tail_style": DEFAULT_TAIL_STYLE,
    "floating_panel_tail_width": "0",
    "floating_panel_tail_height": "0",
    "floating_panel_tail_size": "0",
    "floating_panel_tail_offset_y": "38",
    "floating_panel_username_enabled": "0",
    "floating_panel_username_text": "弹幕",
    "floating_panel_username_color": CLASSIC_TEXT_COLOR,
    "floating_panel_username_size": "14",
    "floating_panel_username_weight": "700",
    "floating_panel_username_separator": "：",
    "floating_panel_content_size": "16",
    "floating_panel_content_weight": "400",
    "floating_panel_content_line_height": "140",
    "floating_panel_gap_username_content": "4",
    "floating_panel_entry_animation": DEFAULT_ENTRY_ANIMATION,
    "floating_panel_entry_duration_ms": "200",
    "floating_panel_push_duration_ms": "180",
    "floating_panel_exit_animation": DEFAULT_EXIT_ANIMATION,
    "floating_panel_exit_duration_ms": "200",
    "floating_panel_stack_gap": "8",
    "floating_panel_font_family": "Microsoft YaHei",
    "floating_panel_font_size": "20",
    "floating_panel_font_bold": "1",
    "floating_panel_opacity": "100",
}

# wechat：shape=bubble、左尾；暖色首色与柔和变体，向 blivechat 直播气泡靠拢
_WECHAT_FLAT: dict[str, str] = {
    "floating_panel_style_preset": "wechat",
    "floating_panel_shape": "bubble",
    "floating_panel_card_colors": json.dumps(list(WECHAT_CARD_COLORS), ensure_ascii=False),
    "floating_panel_card_color_mode": "equal",
    "floating_panel_card_color_weights": "{}",
    "floating_panel_text_colors": json.dumps([WECHAT_TEXT_COLOR], ensure_ascii=False),
    "floating_panel_text_color_mode": "equal",
    "floating_panel_text_color_weights": "{}",
    "floating_panel_card_opacity": "88",
    "floating_panel_outline_enabled": "0",
    "floating_panel_outline_color": "#FFFFFF",
    "floating_panel_outline_width": "2",
    "floating_panel_shadow_enabled": "1",
    "floating_panel_shadow_color": "#000000",
    "floating_panel_shadow_opacity": "25",
    "floating_panel_shadow_blur": "12",
    "floating_panel_shadow_offset_x": "2",
    "floating_panel_shadow_offset_y": "2",
    "floating_panel_border_enabled": "1",
    "floating_panel_border_color": "#FFFFFF",
    "floating_panel_border_width": "1",
    "floating_panel_border_opacity": "45",
    "floating_panel_padding_x": "14",
    "floating_panel_padding_y": "10",
    "floating_panel_radius": "16",
    "floating_panel_tail_enabled": "1",
    "floating_panel_tail_style": DEFAULT_TAIL_STYLE,
    "floating_panel_tail_width": "8",
    "floating_panel_tail_height": "10",
    "floating_panel_tail_size": "10",
    "floating_panel_tail_offset_y": "38",
    "floating_panel_username_enabled": "1",
    "floating_panel_username_text": "弹幕",
    "floating_panel_username_color": WECHAT_TEXT_COLOR,
    "floating_panel_username_size": "14",
    "floating_panel_username_weight": "700",
    "floating_panel_username_separator": "：",
    "floating_panel_content_size": "16",
    "floating_panel_content_weight": "400",
    "floating_panel_content_line_height": "140",
    "floating_panel_gap_username_content": "4",
    "floating_panel_entry_animation": DEFAULT_ENTRY_ANIMATION,
    "floating_panel_entry_duration_ms": "200",
    "floating_panel_push_duration_ms": "180",
    "floating_panel_exit_animation": DEFAULT_EXIT_ANIMATION,
    "floating_panel_exit_duration_ms": "200",
    "floating_panel_stack_gap": "8",
    "floating_panel_font_family": "Microsoft YaHei",
    "floating_panel_font_size": "20",
    "floating_panel_font_bold": "1",
    "floating_panel_opacity": "85",
}


def _copy_preset(src: dict[str, str]) -> dict[str, str]:
    return {k: str(v) for k, v in src.items()}


STYLE_PRESETS: dict[str, dict[str, str]] = {
    "classic": _copy_preset(_CLASSIC_FLAT),
    "wechat": _copy_preset(_WECHAT_FLAT),
}


def wechat_factory_defaults() -> dict[str, str]:
    """wechat 工厂默认扁平字段（custom 非法值兜底）。"""
    return _copy_preset(_WECHAT_FLAT)


def classic_factory_defaults() -> dict[str, str]:
    return _copy_preset(_CLASSIC_FLAT)


def style_defaults_for_config() -> dict[str, str]:
    """写入 CONFIG_DEFAULTS 的新样式键默认值（wechat）。"""
    base = wechat_factory_defaults()
    return {k: base[k] for k in STYLE_FIELD_KEYS}


def preset_style_patch(preset_id: str) -> dict[str, str]:
    """展开预设为样式字段 patch；非法 preset → wechat。

    返回键仅含 STYLE_PRESET_APPLY_KEYS，**不含** danmu_render_mode / scrolling。
    """
    pid = str(preset_id or "").strip().lower()
    if pid not in STYLE_PRESETS:
        pid = DEFAULT_STYLE_PRESET
    src = STYLE_PRESETS[pid]
    return {k: src[k] for k in STYLE_PRESET_APPLY_KEYS if k in src}


# ---------------------------------------------------------------------------
# 解析 / 归一化原语
# ---------------------------------------------------------------------------


def normalize_hex_color(value: Any, *, fallback: str) -> str:
    """规范化为 #RRGGBB 或 #RRGGBBAA 大写；非法回退 fallback。"""
    raw = str(value or "").strip()
    if _HEX_COLOR_RE.match(raw):
        return "#" + raw[1:].upper()
    fb = str(fallback or "").strip()
    if _HEX_COLOR_RE.match(fb):
        return "#" + fb[1:].upper()
    return WECHAT_TEXT_COLOR


def normalize_bool01(value: Any, *, default: str = "0") -> str:
    raw = str(value if value is not None else default).strip().lower()
    if raw in ("1", "true", "yes", "on"):
        return "1"
    if raw in ("0", "false", "no", "off", ""):
        return "0"
    # 非法 → default（再规整一次）
    d = str(default).strip().lower()
    return "1" if d in ("1", "true", "yes", "on") else "0"


def clamp_style_int(value: Any, key: str, *, fallback: int | None = None) -> str:
    ranges = STYLE_INT_RANGES.get(key) or BASE_INT_RANGES.get(key)
    if ranges is None:
        try:
            return str(int(value))
        except (TypeError, ValueError):
            return "0"
    lo, hi, default = ranges
    if fallback is not None:
        default = fallback
    try:
        n = int(float(str(value).strip()))
    except (TypeError, ValueError):
        n = default
    return str(max(lo, min(hi, n)))


def normalize_palette_json(
    raw: Any,
    *,
    fallback_colors: list[str] | tuple[str, ...],
) -> str:
    """解析调色板 JSON 数组；空/非法/越界 → fallback 规范化色列表。"""
    fb = [normalize_hex_color(c, fallback=WECHAT_TEXT_COLOR) for c in fallback_colors]
    if not fb:
        fb = [WECHAT_CARD_COLORS[0]]

    text = str(raw if raw is not None else "").strip()
    if not text:
        return json.dumps(fb, ensure_ascii=False)

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return json.dumps(fb, ensure_ascii=False)

    if not isinstance(data, list) or not data:
        return json.dumps(fb, ensure_ascii=False)

    colors: list[str] = []
    for item in data:
        if not isinstance(item, str):
            continue
        c = str(item).strip()
        if not _HEX_COLOR_RE.match(c):
            continue
        colors.append("#" + c[1:].upper())
        if len(colors) >= PALETTE_MAX_COLORS:
            break

    if len(colors) < PALETTE_MIN_COLORS:
        return json.dumps(fb, ensure_ascii=False)
    return json.dumps(colors, ensure_ascii=False)


def normalize_weights_json(raw: Any, *, fallback: str = "{}") -> str:
    text = str(raw if raw is not None else "").strip()
    if not text:
        return "{}"
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return "{}" if fallback == "{}" else "{}"
    if not isinstance(data, dict):
        return "{}"
    out: dict[str, float] = {}
    for k, v in data.items():
        raw_k = str(k or "").strip()
        if not _HEX_COLOR_RE.match(raw_k):
            continue
        color = "#" + raw_k[1:].upper()
        try:
            w = float(v)
        except (TypeError, ValueError):
            continue
        if w < 0:
            w = 0.0
        out[color] = w
    return json.dumps(out, ensure_ascii=False)


def _choice(value: Any, allowed: tuple[str, ...], default: str) -> str:
    v = str(value or "").strip().lower()
    return v if v in allowed else default


# ---------------------------------------------------------------------------
# 字段级归一化 / 预设展开
# ---------------------------------------------------------------------------


def normalize_floating_panel_style_items(items: dict[str, str]) -> None:
    """就地归一化 Web/Config 样式 patch。

    - ``style_preset`` ∈ classic|wechat|custom；非法 → wechat
    - classic/wechat：展开完整 STYLE_PRESET_APPLY_KEYS（覆盖同批样式字段）
    - custom / 部分提交：非法值以 wechat 工厂默认兜底，不写空
    - **不**写入 ``danmu_render_mode`` 或横向 scrolling 键
    """
    factory = wechat_factory_defaults()
    style_touched = any(k in items for k in STYLE_FIELD_KEYS) or any(
        k in items for k in STYLE_PRESET_APPLY_KEYS
    )
    if not style_touched and "floating_panel_style_preset" not in items:
        return

    preset_raw = items.get("floating_panel_style_preset")
    if preset_raw is not None:
        preset = _choice(preset_raw, STYLE_PRESET_CHOICES, DEFAULT_STYLE_PRESET)
        items["floating_panel_style_preset"] = preset
    else:
        preset = None

    if preset in STYLE_PRESETS:
        patch = preset_style_patch(preset)
        # 预设展开：覆盖全部样式应用键；保留用户同批可能提交的非样式键
        for key, val in patch.items():
            items[key] = val
        # 展开后仍再走一遍规范化，保证输出稳定
        _normalize_style_values(items, factory, keys=STYLE_PRESET_APPLY_KEYS)
        return

    # custom 或未声明 preset：只规范化出现的键
    keys = [k for k in STYLE_PRESET_APPLY_KEYS if k in items]
    if "floating_panel_style_preset" in items:
        items["floating_panel_style_preset"] = _choice(
            items["floating_panel_style_preset"],
            STYLE_PRESET_CHOICES,
            DEFAULT_STYLE_PRESET,
        )
    _normalize_style_values(items, factory, keys=keys)


def _normalize_style_values(
    items: dict[str, str],
    factory: dict[str, str],
    *,
    keys: list[str] | tuple[str, ...],
) -> None:
    for key in keys:
        if key not in items and key not in factory:
            continue
        if key not in items:
            continue
        raw = items[key]
        fb = factory.get(key, "")

        if key == "floating_panel_style_preset":
            items[key] = _choice(raw, STYLE_PRESET_CHOICES, DEFAULT_STYLE_PRESET)
        elif key == "floating_panel_shape":
            items[key] = _choice(raw, SHAPE_CHOICES, factory.get(key, "bubble"))
        elif key == "floating_panel_tail_style":
            items[key] = _choice(raw, TAIL_STYLE_CHOICES, factory.get(key, DEFAULT_TAIL_STYLE))
        elif key in ("floating_panel_card_color_mode", "floating_panel_text_color_mode"):
            items[key] = _choice(raw, COLOR_MODE_CHOICES, DEFAULT_COLOR_MODE)
        elif key == "floating_panel_entry_animation":
            items[key] = _choice(raw, ENTRY_ANIMATION_CHOICES, DEFAULT_ENTRY_ANIMATION)
        elif key == "floating_panel_exit_animation":
            items[key] = _choice(raw, EXIT_ANIMATION_CHOICES, DEFAULT_EXIT_ANIMATION)
        elif key in PALETTE_KEYS:
            if key == "floating_panel_card_colors":
                fb_colors = WECHAT_CARD_COLORS
                try:
                    parsed = json.loads(fb) if fb else list(WECHAT_CARD_COLORS)
                    if isinstance(parsed, list) and parsed:
                        fb_colors = tuple(str(c) for c in parsed)
                except (json.JSONDecodeError, TypeError):
                    pass
            else:
                fb_colors = (WECHAT_TEXT_COLOR,)
                try:
                    parsed = json.loads(fb) if fb else [WECHAT_TEXT_COLOR]
                    if isinstance(parsed, list) and parsed:
                        fb_colors = tuple(str(c) for c in parsed)
                except (json.JSONDecodeError, TypeError):
                    pass
            items[key] = normalize_palette_json(raw, fallback_colors=fb_colors)
        elif key in WEIGHT_KEYS:
            items[key] = normalize_weights_json(raw, fallback="{}")
        elif key in BOOL_KEYS:
            items[key] = normalize_bool01(raw, default=fb or "0")
        elif key in STYLE_INT_RANGES or key in BASE_INT_RANGES:
            try:
                fb_int = int(fb) if str(fb).strip() else None
            except (TypeError, ValueError):
                fb_int = None
            items[key] = clamp_style_int(raw, key, fallback=fb_int)
        elif key in ("floating_panel_outline_color", "floating_panel_shadow_color", "floating_panel_border_color", "floating_panel_username_color"):
            items[key] = normalize_hex_color(raw, fallback=fb or "#000000")
        elif key == "floating_panel_username_text":
            v = str(raw if raw is not None else "").strip()
            items[key] = v if v else (fb or "弹幕")
        elif key == "floating_panel_username_separator":
            v = str(raw if raw is not None else "").strip()
            items[key] = v if v else (fb or "：")
        elif key == "floating_panel_font_family":
            v = str(raw or "").strip()
            items[key] = v if v else (fb or "Microsoft YaHei")
        elif key == "floating_panel_speed":
            # 速度由 ConfigService 既有逻辑处理；此处不强制
            pass
        else:
            # 未知标量：空则回退工厂
            v = str(raw if raw is not None else "").strip()
            items[key] = v if v else str(fb)


# ---------------------------------------------------------------------------
# 类型明确快照
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FloatingPanelStyleSnapshot:
    """从扁平 Config 映射得到的类型明确样式快照。"""

    style_preset: str
    shape: str
    card_colors: tuple[str, ...]
    card_color_mode: str
    card_color_weights: dict[str, float]
    text_colors: tuple[str, ...]
    text_color_mode: str
    text_color_weights: dict[str, float]
    card_opacity: int
    outline_enabled: bool
    outline_color: str
    outline_width: int
    shadow_enabled: bool
    shadow_color: str
    shadow_opacity: int
    shadow_blur: int
    shadow_offset_x: int
    shadow_offset_y: int
    border_enabled: bool
    border_color: str
    border_width: int
    border_opacity: int
    padding_x: int
    padding_y: int
    radius: int
    tail_enabled: bool
    tail_style: str
    tail_width: int
    tail_height: int
    tail_size: int
    tail_offset_y: int
    username_enabled: bool
    username_text: str
    username_color: str
    username_size: int
    username_weight: int
    username_separator: str
    content_size: int
    content_weight: int
    content_line_height: int
    gap_username_content: int
    entry_animation: str
    entry_duration_ms: int
    push_duration_ms: int
    exit_animation: str
    exit_duration_ms: int
    stack_gap: int
    font_family: str
    font_size: int
    font_bold: bool
    panel_opacity: int
    width: int
    max_items: int
    speed: str

    def to_public_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # tuples → lists for JSON
        d["card_colors"] = list(self.card_colors)
        d["text_colors"] = list(self.text_colors)
        return d


def _get_map(mapping: Mapping[str, Any], key: str, default: str = "") -> str:
    if hasattr(mapping, "get"):
        val = mapping.get(key, default)  # type: ignore[call-arg]
    else:
        val = default
    if val is None or val == "":
        return default
    return str(val)


def style_snapshot_from_mapping(mapping: Mapping[str, Any] | None) -> FloatingPanelStyleSnapshot:
    """将扁平 ConfigStore / dict 映射为类型明确快照。

    缺失字段按 wechat 工厂补齐；非法值归一化后不出现空调色板。
    """
    factory = wechat_factory_defaults()
    src: dict[str, str] = {}
    mapping = mapping or {}

    for key in STYLE_PRESET_APPLY_KEYS:
        stored = _get_map(mapping, key, "")
        src[key] = stored if stored != "" else factory.get(key, "")

    # 基础尺寸
    for key in (
        "floating_panel_width",
        "floating_panel_max_items",
        "floating_panel_opacity",
        "floating_panel_font_size",
        "floating_panel_speed",
    ):
        stored = _get_map(mapping, key, "")
        if stored != "":
            src[key] = stored

    _normalize_style_values(src, factory, keys=list(src.keys()))

    def _palette(key: str, fb: tuple[str, ...]) -> tuple[str, ...]:
        raw = normalize_palette_json(src.get(key, ""), fallback_colors=fb)
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            data = list(fb)
        return tuple(str(c) for c in data)

    def _weights(key: str) -> dict[str, float]:
        raw = normalize_weights_json(src.get(key, "{}"))
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, float] = {}
        for k, v in data.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        return out

    def _int(key: str, default: int = 0) -> int:
        try:
            return int(src.get(key, str(default)))
        except (TypeError, ValueError):
            return default

    def _bool(key: str) -> bool:
        return normalize_bool01(src.get(key, "0")) == "1"

    width_s = _get_map(mapping, "floating_panel_width", "360")
    max_items_s = _get_map(mapping, "floating_panel_max_items", "12")
    speed_s = _get_map(mapping, "floating_panel_speed", "1")
    try:
        width = int(clamp_style_int(width_s, "floating_panel_width"))
    except (TypeError, ValueError):
        width = 360
    try:
        max_items = int(clamp_style_int(max_items_s, "floating_panel_max_items"))
    except (TypeError, ValueError):
        max_items = 12

    return FloatingPanelStyleSnapshot(
        style_preset=_choice(src.get("floating_panel_style_preset"), STYLE_PRESET_CHOICES, DEFAULT_STYLE_PRESET),
        shape=_choice(src.get("floating_panel_shape"), SHAPE_CHOICES, "bubble"),
        card_colors=_palette("floating_panel_card_colors", WECHAT_CARD_COLORS),
        card_color_mode=_choice(
            src.get("floating_panel_card_color_mode"), COLOR_MODE_CHOICES, DEFAULT_COLOR_MODE
        ),
        card_color_weights=_weights("floating_panel_card_color_weights"),
        text_colors=_palette("floating_panel_text_colors", (WECHAT_TEXT_COLOR,)),
        text_color_mode=_choice(
            src.get("floating_panel_text_color_mode"), COLOR_MODE_CHOICES, DEFAULT_COLOR_MODE
        ),
        text_color_weights=_weights("floating_panel_text_color_weights"),
        card_opacity=_int("floating_panel_card_opacity", 78),
        outline_enabled=_bool("floating_panel_outline_enabled"),
        outline_color=normalize_hex_color(
            src.get("floating_panel_outline_color"), fallback="#FFFFFFC8"
        ),
        outline_width=_int("floating_panel_outline_width", 2),
        shadow_enabled=_bool("floating_panel_shadow_enabled"),
        shadow_color=normalize_hex_color(
            src.get("floating_panel_shadow_color"), fallback="#000000"
        ),
        shadow_opacity=_int("floating_panel_shadow_opacity", 30),
        shadow_blur=_int("floating_panel_shadow_blur", 12),
        shadow_offset_x=_int("floating_panel_shadow_offset_x", 2),
        shadow_offset_y=_int("floating_panel_shadow_offset_y", 2),
        border_enabled=_bool("floating_panel_border_enabled"),
        border_color=normalize_hex_color(
            src.get("floating_panel_border_color"), fallback="#FFFFFF"
        ),
        border_width=_int("floating_panel_border_width", 1),
        border_opacity=_int("floating_panel_border_opacity", 40),
        padding_x=_int("floating_panel_padding_x", 14),
        padding_y=_int("floating_panel_padding_y", 10),
        radius=_int("floating_panel_radius", 16),
        tail_enabled=_bool("floating_panel_tail_enabled"),
        tail_style=_choice(src.get("floating_panel_tail_style"), TAIL_STYLE_CHOICES, DEFAULT_TAIL_STYLE),
        tail_width=_int("floating_panel_tail_width", 8),
        tail_height=_int("floating_panel_tail_height", 10),
        tail_size=_int("floating_panel_tail_size", 10),
        tail_offset_y=_int("floating_panel_tail_offset_y", 38),
        username_enabled=_bool("floating_panel_username_enabled"),
        username_text=str(src.get("floating_panel_username_text") or "弹幕"),
        username_color=normalize_hex_color(
            src.get("floating_panel_username_color"), fallback=WECHAT_TEXT_COLOR
        ),
        username_size=_int("floating_panel_username_size", 14),
        username_weight=_int("floating_panel_username_weight", 700),
        username_separator=str(src.get("floating_panel_username_separator") or "："),
        content_size=_int("floating_panel_content_size", 16),
        content_weight=_int("floating_panel_content_weight", 400),
        content_line_height=_int("floating_panel_content_line_height", 140),
        gap_username_content=_int("floating_panel_gap_username_content", 4),
        entry_animation=_choice(
            src.get("floating_panel_entry_animation"),
            ENTRY_ANIMATION_CHOICES,
            DEFAULT_ENTRY_ANIMATION,
        ),
        entry_duration_ms=_int("floating_panel_entry_duration_ms", 200),
        push_duration_ms=_int("floating_panel_push_duration_ms", 180),
        exit_animation=_choice(
            src.get("floating_panel_exit_animation"),
            EXIT_ANIMATION_CHOICES,
            DEFAULT_EXIT_ANIMATION,
        ),
        exit_duration_ms=_int("floating_panel_exit_duration_ms", 200),
        stack_gap=_int("floating_panel_stack_gap", 8),
        font_family=str(src.get("floating_panel_font_family") or "Microsoft YaHei"),
        font_size=_int("floating_panel_font_size", 20),
        font_bold=_bool("floating_panel_font_bold"),
        panel_opacity=_int("floating_panel_opacity", 85),
        width=width,
        max_items=max_items,
        speed=str(speed_s or "1"),
    )


def style_presets_api_payload() -> dict[str, Any]:
    """GET /api/floating-panel/style-presets 只读响应（无 ConfigStore 读写）。"""
    presets: dict[str, dict[str, str]] = {}
    for pid in STYLE_PRESET_IDS:
        # 仅样式应用键 + 稳定顺序
        patch = preset_style_patch(pid)
        presets[pid] = {k: patch[k] for k in STYLE_PRESET_APPLY_KEYS if k in patch}
    return {
        "version": STYLE_CONTRACT_VERSION,
        "default_preset": DEFAULT_STYLE_PRESET,
        "presets": presets,
        "fields": list(STYLE_FIELD_KEYS),
        "restore_keys": list(STYLE_RESTORE_KEYS),
        "shape_choices": list(SHAPE_CHOICES),
        "tail_style_choices": list(TAIL_STYLE_CHOICES),
        "color_mode_choices": list(COLOR_MODE_CHOICES),
        "entry_animation_choices": list(ENTRY_ANIMATION_CHOICES),
        "exit_animation_choices": list(EXIT_ANIMATION_CHOICES),
        "int_ranges": {
            k: {"min": lo, "max": hi, "wechat_default": d}
            for k, (lo, hi, d) in STYLE_INT_RANGES.items()
        },
    }


__all__ = [
    "STYLE_CONTRACT_VERSION",
    "STYLE_PRESET_IDS",
    "STYLE_PRESET_CHOICES",
    "DEFAULT_STYLE_PRESET",
    "SHAPE_CHOICES",
    "COLOR_MODE_CHOICES",
    "TAIL_STYLE_CHOICES",
    "DEFAULT_TAIL_STYLE",
    "STYLE_FIELD_KEYS",
    "STYLE_RESTORE_KEYS",
    "STYLE_PRESET_APPLY_KEYS",
    "STYLE_PRESETS",
    "STYLE_INT_RANGES",
    "CLASSIC_CARD_COLORS",
    "WECHAT_CARD_COLORS",
    "WECHAT_TEXT_COLOR",
    "FloatingPanelStyleSnapshot",
    "wechat_factory_defaults",
    "classic_factory_defaults",
    "style_defaults_for_config",
    "preset_style_patch",
    "normalize_floating_panel_style_items",
    "normalize_hex_color",
    "normalize_palette_json",
    "normalize_weights_json",
    "normalize_bool01",
    "style_snapshot_from_mapping",
    "style_presets_api_payload",
]
