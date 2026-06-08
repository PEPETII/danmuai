"""烂梗公式化配置读取（不经 PUT /api/config）。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config_store import ConfigStore

VALID_CATEGORIES = frozenset({"random", "tagged", "local"})
VALID_DISPLAY_MODES = frozenset({"full", "ai"})

COLLECT_INTERVAL_MIN = 1
COLLECT_INTERVAL_MAX = 60
COLLECT_BATCH_MIN = 1
COLLECT_BATCH_MAX = 100
DISPLAY_INTERVAL_MIN = 1
DISPLAY_INTERVAL_MAX = 60
DISPLAY_BATCH_MIN = 1
DISPLAY_BATCH_MAX = 50


def meme_barrage_enabled(config: "ConfigStore") -> bool:
    raw = config.get("meme_barrage_enabled", "")
    if raw in ("", None):
        return False
    return str(raw).strip() != "0"


def _clamp_int(value: object, default: int, lo: int, hi: int) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(lo, min(n, hi))


def read_meme_barrage_settings(config: "ConfigStore") -> dict[str, object]:
    category = str(config.get("meme_barrage_category", "random") or "random").strip().lower()
    if category not in VALID_CATEGORIES:
        category = "random"
    display_mode = str(config.get("meme_barrage_display_mode", "full") or "full").strip().lower()
    if display_mode not in VALID_DISPLAY_MODES:
        display_mode = "full"
    tag = str(config.get("meme_barrage_tag", "06") or "06").strip() or "06"
    return {
        "enabled": meme_barrage_enabled(config),
        "category": category,
        "tag": tag,
        "display_mode": display_mode,
        "collect_interval_sec": _clamp_int(
            config.get("meme_barrage_collect_interval_sec", "5"),
            5,
            COLLECT_INTERVAL_MIN,
            COLLECT_INTERVAL_MAX,
        ),
        "collect_batch_size": _clamp_int(
            config.get("meme_barrage_collect_batch_size", "40"),
            40,
            COLLECT_BATCH_MIN,
            COLLECT_BATCH_MAX,
        ),
        "display_interval_sec": _clamp_int(
            config.get("meme_barrage_display_interval_sec", "5"),
            5,
            DISPLAY_INTERVAL_MIN,
            DISPLAY_INTERVAL_MAX,
        ),
        "display_batch_size": _clamp_int(
            config.get("meme_barrage_display_batch_size", "20"),
            20,
            DISPLAY_BATCH_MIN,
            DISPLAY_BATCH_MAX,
        ),
    }
