"""烂梗公式化配置读取（不经 PUT /api/config）。"""

from __future__ import annotations

import json
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

DISPLAY_QUEUE_MAX = 500

DEFAULT_TAG = "06"
MAX_SELECTED_TAGS = 3

# 采集游标（不经 PUT /api/config；仅 MemeBarrageService 读写）
CURSOR_KEY_LOCAL_OFFSET = "meme_barrage_local_read_offset"
CURSOR_KEY_REMOTE_PAGE = "meme_barrage_remote_page_num"
DEFAULT_LOCAL_READ_OFFSET = 0
DEFAULT_REMOTE_PAGE_NUM = 1


def normalize_meme_barrage_tags(tags: list[str]) -> list[str]:
    """Keep at most ``MAX_SELECTED_TAGS`` ids; remote API rejects four or more."""
    cleaned = [str(t).strip() for t in tags if str(t).strip()]
    if not cleaned:
        return [DEFAULT_TAG]
    return cleaned[:MAX_SELECTED_TAGS]


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


def _parse_tag(raw: object) -> list[str]:
    """向后兼容解析 ``meme_barrage_tag`` 为 ``list[str]``。

    1. 优先 ``json.loads`` → 若为 list 则直接使用；
    2. 解析失败 / 结果非 list → 视为旧的「单字符串或逗号分隔字符串」，
       按 ``,`` split → 过滤空 → 至少保留 1 个；
    3. 解析失败且为空 → 回退默认值 ``["06"]``。
    """
    out: list[str] = []
    if isinstance(raw, list):
        out = [str(t).strip() for t in raw if str(t).strip()]
    else:
        s = str(raw or "").strip()
        if s:
            parsed_as_json_list = False
            try:
                parsed = json.loads(s)
                if isinstance(parsed, list):
                    parsed_as_json_list = True
                    out = [str(t).strip() for t in parsed if str(t).strip()]
            except (ValueError, TypeError):
                pass
            if not out and not parsed_as_json_list:
                out = [t.strip() for t in s.split(",") if t.strip()]
    return normalize_meme_barrage_tags(out)


def load_meme_barrage_cursors(config: "ConfigStore") -> tuple[int, int]:
    """Load persisted local-library offset and remote API page number."""
    local_offset = _clamp_int(
        config.get(CURSOR_KEY_LOCAL_OFFSET, str(DEFAULT_LOCAL_READ_OFFSET)),
        DEFAULT_LOCAL_READ_OFFSET,
        0,
        10_000_000,
    )
    page_num = _clamp_int(
        config.get(CURSOR_KEY_REMOTE_PAGE, str(DEFAULT_REMOTE_PAGE_NUM)),
        DEFAULT_REMOTE_PAGE_NUM,
        1,
        10_000_000,
    )
    return local_offset, page_num


def persist_meme_barrage_cursors(
    config: "ConfigStore",
    *,
    local_offset: int,
    page_num: int,
) -> None:
    """Persist cursors to config.db; not exposed via Web PUT /api/config."""
    local_offset = max(0, int(local_offset))
    page_num = max(1, int(page_num))
    config.set_batch(
        {
            CURSOR_KEY_LOCAL_OFFSET: str(local_offset),
            CURSOR_KEY_REMOTE_PAGE: str(page_num),
        }
    )


def read_meme_barrage_settings(config: "ConfigStore") -> dict[str, object]:
    category = str(config.get("meme_barrage_category", "random") or "random").strip().lower()
    if category not in VALID_CATEGORIES:
        category = "random"
    display_mode = str(config.get("meme_barrage_display_mode", "full") or "full").strip().lower()
    if display_mode not in VALID_DISPLAY_MODES:
        display_mode = "full"
    tag = _parse_tag(config.get("meme_barrage_tag", DEFAULT_TAG))
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
            config.get("meme_barrage_collect_batch_size", "2"),
            2,
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
            config.get("meme_barrage_display_batch_size", "2"),
            2,
            DISPLAY_BATCH_MIN,
            DISPLAY_BATCH_MAX,
        ),
    }
