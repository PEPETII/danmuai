"""公式化弹幕库专用 API；开关与 min_on_screen 不经 PUT /api/config 全量表单。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/danmu-pool/meta``：自定义开关 + pool size。
- ``POST /api/danmu-pool/custom``：追加自定义句（去重 + 安全校验），上限 20000。
- ``PUT /api/danmu-pool/settings``：写 ``danmu_pool_use_custom`` / ``min_on_screen``。
- ``DELETE /api/danmu-pool/custom``：删除自定义句。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.config_store import CUSTOM_DANMU_POOL_MAX
from app.danmu_pool import (
    any_danmu_pool_source_enabled,
    custom_pool_size,
    danmu_pool_use_custom_from_config,
)
from app.danmu_pool_overlay import is_overlay_safe

if TYPE_CHECKING:
    from main import DanmuApp

CUSTOM_POOL_MAX = CUSTOM_DANMU_POOL_MAX
APPEND_BATCH_MAX = 5000
MIN_ON_SCREEN_MAX = 50
DEFAULT_PAGE_SIZE = 100
MIN_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200

_SKIP_REASON_DUPLICATE = "duplicate"
_SKIP_REASON_EMPTY = "empty"
_SKIP_REASON_UNSAFE = "unsafe"
_SKIP_REASON_LIMIT = "limit_reached"


def _clamp_page_size(page_size: int) -> int:
    return max(MIN_PAGE_SIZE, min(MAX_PAGE_SIZE, int(page_size)))


def get_meta(app: "DanmuApp") -> dict[str, Any]:
    config = app.config
    manual_count = 0
    import_count = 0
    counter = getattr(config, "custom_danmu_count", None)
    if callable(counter):
        manual_count = int(counter("manual"))
        import_count = int(counter("import"))
    return {
        "custom_enabled": danmu_pool_use_custom_from_config(config),
        "min_on_screen": config.get_int("min_on_screen", 5),
        "custom_count": custom_pool_size(config),
        "manual_count": manual_count,
        "import_count": import_count,
        "custom_max": CUSTOM_POOL_MAX,
        "effective_pool_enabled": any_danmu_pool_source_enabled(config),
    }


def save_settings(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, Any]:
    items: dict[str, str] = {}
    if "custom_enabled" in payload:
        items["danmu_pool_use_custom"] = "1" if payload.get("custom_enabled") else "0"
    if "min_on_screen" in payload:
        try:
            min_n = int(payload.get("min_on_screen", 5))
        except (TypeError, ValueError):
            min_n = 5
        items["min_on_screen"] = str(max(0, min(min_n, MIN_ON_SCREEN_MAX)))
    if items:
        app.config.set_batch(items)
        app.config_changed.emit()
    return {"ok": True}


def list_custom(
    app: "DanmuApp",
    *,
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    search: str = "",
    source: str = "manual",
) -> dict[str, Any]:
    list_fn = getattr(app.config, "custom_danmu_list", None)
    if not callable(list_fn):
        return {
            "items": [],
            "total": 0,
            "page": 1,
            "page_size": _clamp_page_size(page_size),
            "source": source,
        }
    return list_fn(
        page=page,
        page_size=_clamp_page_size(page_size),
        search=search,
        source=source or None,
    )


def _parse_incoming_lines(payload: dict[str, Any]) -> list[str]:
    if isinstance(payload.get("items"), list):
        raw_lines = [str(item) for item in payload["items"]]
    else:
        text = str(payload.get("text") or "")
        raw_lines = text.splitlines()
    return raw_lines


def append_custom(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, Any]:
    raw_lines = _parse_incoming_lines(payload)
    if len(raw_lines) > APPEND_BATCH_MAX:
        raise ValueError(f"单次最多追加 {APPEND_BATCH_MAX} 条")

    source = str(payload.get("source") or "manual").strip().lower()
    if source not in ("manual", "import"):
        source = "manual"
    is_import = source == "import"

    config = app.config
    existing_set: set[str] = set()
    contains = getattr(config, "custom_danmu_contains_text", None)
    if not callable(contains):
        existing_set = set(config.get_custom_danmu_pool())

    to_insert: list[str] = []
    skipped_items: list[dict[str, str]] = []
    batch_seen: set[str] = set()
    stats = {
        "added": 0,
        "skipped_duplicate": 0,
        "skipped_empty": 0,
        "skipped_unsafe": 0,
        "skipped_limit": 0,
    }

    for raw in raw_lines:
        text = str(raw).strip()
        if not text:
            stats["skipped_empty"] += 1
            skipped_items.append({"text": raw, "reason": _SKIP_REASON_EMPTY})
            continue
        if callable(contains):
            dup = text in batch_seen or contains(text)
        else:
            dup = text in batch_seen or text in existing_set
        if dup:
            stats["skipped_duplicate"] += 1
            skipped_items.append({"text": text, "reason": _SKIP_REASON_DUPLICATE})
            continue
        if not is_overlay_safe(text, max_chars=None):
            stats["skipped_unsafe"] += 1
            skipped_items.append({"text": text, "reason": _SKIP_REASON_UNSAFE})
            continue
        room_left = CUSTOM_POOL_MAX - custom_pool_size(config) - len(to_insert)
        if room_left <= 0:
            stats["skipped_limit"] += 1
            skipped_items.append({"text": text, "reason": _SKIP_REASON_LIMIT})
            continue
        to_insert.append(text)
        batch_seen.add(text)
        if not callable(contains):
            existing_set.add(text)

    if to_insert:
        insert_fn = getattr(config, "custom_danmu_insert_many", None)
        if callable(insert_fn):
            batch_stats = insert_fn(to_insert, source=source)
            stats["added"] = int(batch_stats.get("added", 0))
            stats["skipped_duplicate"] += int(batch_stats.get("skipped_duplicate", 0))
            stats["skipped_empty"] += int(batch_stats.get("skipped_empty", 0))
            stats["skipped_limit"] += int(batch_stats.get("skipped_limit", 0))
        else:
            merged = list(config.get_custom_danmu_pool()) + to_insert
            config.set_custom_danmu_pool(merged)
            stats["added"] = len(to_insert)
        app.config_changed.emit()

    skipped_total = sum(
        stats[k]
        for k in (
            "skipped_duplicate",
            "skipped_empty",
            "skipped_unsafe",
            "skipped_limit",
        )
    )
    result: dict[str, Any] = {
        "added": stats["added"],
        "skipped": skipped_total,
        "skipped_duplicate": stats["skipped_duplicate"],
        "skipped_empty": stats["skipped_empty"],
        "skipped_unsafe": stats["skipped_unsafe"],
        "skipped_limit": stats["skipped_limit"],
        "skipped_items": skipped_items,
    }
    if not is_import:
        result["items"] = list_custom(app, page=1, page_size=DEFAULT_PAGE_SIZE, source="manual")[
            "items"
        ]
    return result


def delete_custom(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, Any]:
    ids = payload.get("ids")
    texts = payload.get("texts")
    removed = 0
    if isinstance(ids, list) and ids:
        delete_fn = getattr(app.config, "custom_danmu_delete_ids", None)
        if callable(delete_fn):
            removed = delete_fn([int(i) for i in ids])
        else:
            raise ValueError("删除接口不可用")
    elif isinstance(texts, list) and texts:
        delete_fn = getattr(app.config, "custom_danmu_delete_texts", None)
        if callable(delete_fn):
            removed = delete_fn(texts)
        else:
            existing = app.config.get_custom_danmu_pool()
            remove = {str(text).strip() for text in texts if str(text).strip()}
            kept = [line for line in existing if line not in remove]
            removed = len(existing) - len(kept)
            if removed:
                app.config.set_custom_danmu_pool(kept)
    else:
        raise ValueError("请提供要删除的弹幕句")

    if removed:
        app.config_changed.emit()
    return {"removed": removed}
