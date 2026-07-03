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

包结构（从原 app/danmu_engine.py 拆分，零业务逻辑变更）：
  - track.py  — DanmuEngine 类主定义与核心方法（轨道/去重/容量）
  - screen.py — 屏幕适配模块级函数/常量 + 屏幕适配方法（挂载到 DanmuEngine）
  - render.py — 渲染常量 + 渲染/可见性方法（挂载到 DanmuEngine）
"""

import json  # noqa: F401 — 保留 app.danmu_engine.json 属性路径（如有测试 patch 依赖）
import random  # noqa: F401 — 保留 app.danmu_engine.random 属性路径（测试 monkeypatch 依赖）

# Step 1: 加载 screen 模块（模块级函数 + 常量，无 DanmuEngine 依赖）
from . import screen  # noqa: F401

# Step 2: 加载 render 模块（常量，无 DanmuEngine 依赖）
from . import render  # noqa: F401

# Step 3: 加载 track 模块 — DanmuEngine 类主定义
# track.py 从 .screen / .render 导入模块级函数/常量（已加载），不触发循环
from .track import DanmuEngine

# Step 4: 挂载 screen / render 方法到 DanmuEngine 类
screen._mount_methods(DanmuEngine)
render._mount_methods(DanmuEngine)

# Step 5: 重新导出全部公开+被外部引用的私有符号（保持向后兼容）
from app.danmu_engine_models import (  # noqa: F401 — re-exported
    DanmuItem,
    Track,
    _DANMU_FALLBACK_CHAR_WIDTH,
)
from app.danmu_engine_dedup import (  # noqa: F401 — re-exported for app.danmu_engine callers
    DedupProfileStats,
    dedup_profile_enabled,
    get_last_duplicate_observation,
    is_duplicate_in_recent,
    log_dedup_profile_summary,
    reset_dedup_profile_for_tests,
    snapshot_dedup_profile,
)
from .track import (  # noqa: F401 — re-exported
    _LEVENSHTEIN_RATIO,
    _LEVENSHTEIN_UNAVAILABLE,
    _get_levenshtein_ratio,
)
from .screen import (
    DEFAULT_DANMU_LINES,
    DEFAULT_DANMU_MAX_CHARS_EN,
    DEFAULT_DANMU_MAX_CHARS_ZH,
    DEFAULT_LAYOUT_MODE,
    DANMU_LINES_MAX,
    DANMU_LINES_MIN,
    DANMU_MAX_CHARS_MAX,
    DANMU_MAX_CHARS_MIN,
    DANMU_PENDING_ENTRY_CAP_MAX,
    DANMU_TRACK_RETENTION_CAP_MAX,
    LAYOUT_MODE_RATIOS,
    MAX_EVICT_ITERATIONS,
    _DEFAULT_DANMU_PENDING_ENTRY_CAP,
    _DEFAULT_DANMU_TRACK_RETENTION_CAP,
    clamp_danmu_lines,
    is_persona_name_prefix_enabled,
    layout_height_ratio,
    normalize_danmu_display_text,
    normalize_layout_mode,
    resolve_danmu_color,
    resolve_danmu_display_text,
    resolve_danmu_max_chars,
    resolve_danmu_pending_entry_cap,
    resolve_danmu_track_retention_cap,
)
from .render import (  # noqa: F401 — re-exported
    ENTRY_ZONE_PX,
    FADE_IN_PX,
    FADE_OUT_PX,
)

__all__ = [
    "DanmuEngine",
    "DanmuItem",
    "Track",
    "DedupProfileStats",
    "dedup_profile_enabled",
    "get_last_duplicate_observation",
    "is_duplicate_in_recent",
    "log_dedup_profile_summary",
    "reset_dedup_profile_for_tests",
    "snapshot_dedup_profile",
    "_LEVENSHTEIN_UNAVAILABLE",
    "_LEVENSHTEIN_RATIO",
    "_get_levenshtein_ratio",
    "_DANMU_FALLBACK_CHAR_WIDTH",
    "DEFAULT_DANMU_LINES",
    "DEFAULT_DANMU_MAX_CHARS_EN",
    "DEFAULT_DANMU_MAX_CHARS_ZH",
    "DEFAULT_LAYOUT_MODE",
    "DANMU_LINES_MAX",
    "DANMU_LINES_MIN",
    "DANMU_MAX_CHARS_MAX",
    "DANMU_MAX_CHARS_MIN",
    "DANMU_PENDING_ENTRY_CAP_MAX",
    "DANMU_TRACK_RETENTION_CAP_MAX",
    "LAYOUT_MODE_RATIOS",
    "MAX_EVICT_ITERATIONS",
    "_DEFAULT_DANMU_PENDING_ENTRY_CAP",
    "_DEFAULT_DANMU_TRACK_RETENTION_CAP",
    "clamp_danmu_lines",
    "is_persona_name_prefix_enabled",
    "layout_height_ratio",
    "normalize_danmu_display_text",
    "normalize_layout_mode",
    "resolve_danmu_color",
    "resolve_danmu_display_text",
    "resolve_danmu_max_chars",
    "resolve_danmu_pending_entry_cap",
    "resolve_danmu_track_retention_cap",
    "ENTRY_ZONE_PX",
    "FADE_IN_PX",
    "FADE_OUT_PX",
]
