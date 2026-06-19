"""烂梗公式化 Web API；配置不经 PUT /api/config。"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from app.meme_barrage.client import FALLBACK_TAGS, MemeBarrageApiClient
from app.meme_barrage.config import (
    COLLECT_BATCH_MAX,
    COLLECT_BATCH_MIN,
    COLLECT_INTERVAL_MAX,
    COLLECT_INTERVAL_MIN,
    DISPLAY_BATCH_MAX,
    DISPLAY_BATCH_MIN,
    DISPLAY_INTERVAL_MAX,
    DISPLAY_INTERVAL_MIN,
    VALID_CATEGORIES,
    VALID_DISPLAY_MODES,
    normalize_meme_barrage_tags,
    read_meme_barrage_settings,
)

if TYPE_CHECKING:
    from main import DanmuApp

_tags_cache: list[dict[str, str]] | None = None


def _status_fields(app: "DanmuApp") -> dict[str, object]:
    getter = getattr(app, "get_meme_barrage_status", None)
    if callable(getter):
        return getter()
    settings = read_meme_barrage_settings(app.config)
    if getattr(app.config, "conn", None) is None:
        return {
            "enabled": settings["enabled"],
            "library_count": 0,
            "display_queue_size": 0,
        }
    from app.meme_barrage.store import MemeBarrageStore

    store = MemeBarrageStore(app.config)
    return {
        "enabled": settings["enabled"],
        "library_count": store.count(),
        "display_queue_size": 0,
    }


def get_meta(app: "DanmuApp") -> dict[str, Any]:
    settings = read_meme_barrage_settings(app.config)
    status = _status_fields(app)
    return {
        **settings,
        "library_count": status.get("library_count", 0),
        "display_queue_size": status.get("display_queue_size", 0),
    }


def save_settings(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, Any]:
    items: dict[str, str] = {}
    reset_cursors = False
    clamped_fields: dict[str, dict[str, int]] = {}

    if "enabled" in payload:
        items["meme_barrage_enabled"] = "1" if payload.get("enabled") else "0"
    if "category" in payload:
        category = str(payload.get("category") or "random").strip().lower()
        if category in VALID_CATEGORIES:
            items["meme_barrage_category"] = category
            reset_cursors = True
    if "tag" in payload:
        raw = payload.get("tag")
        if isinstance(raw, list):
            tags_list = [str(t).strip() for t in raw if str(t).strip()]
        elif raw is None:
            tags_list = []
        else:
            # 兼容旧字符串 / 逗号字符串
            tags_list = [t.strip() for t in str(raw).split(",") if t.strip()]
        tags_list = normalize_meme_barrage_tags(tags_list)
        items["meme_barrage_tag"] = json.dumps(tags_list, ensure_ascii=False)
        reset_cursors = True
    if "display_mode" in payload:
        mode = str(payload.get("display_mode") or "full").strip().lower()
        if mode in VALID_DISPLAY_MODES:
            items["meme_barrage_display_mode"] = mode
    if "collect_interval_sec" in payload:
        try:
            sec = int(payload.get("collect_interval_sec", 5))
        except (TypeError, ValueError):
            sec = 5
        actual = max(COLLECT_INTERVAL_MIN, min(sec, COLLECT_INTERVAL_MAX))
        if actual != sec:
            clamped_fields["collect_interval_sec"] = {"requested": sec, "actual": actual}
        items["meme_barrage_collect_interval_sec"] = str(actual)
    if "collect_batch_size" in payload:
        try:
            n = int(payload.get("collect_batch_size", 2))
        except (TypeError, ValueError):
            n = 2
        actual = max(COLLECT_BATCH_MIN, min(n, COLLECT_BATCH_MAX))
        if actual != n:
            clamped_fields["collect_batch_size"] = {"requested": n, "actual": actual}
        items["meme_barrage_collect_batch_size"] = str(actual)
    if "display_interval_sec" in payload:
        try:
            sec = int(payload.get("display_interval_sec", 5))
        except (TypeError, ValueError):
            sec = 5
        actual = max(DISPLAY_INTERVAL_MIN, min(sec, DISPLAY_INTERVAL_MAX))
        if actual != sec:
            clamped_fields["display_interval_sec"] = {"requested": sec, "actual": actual}
        items["meme_barrage_display_interval_sec"] = str(actual)
    if "display_batch_size" in payload:
        try:
            n = int(payload.get("display_batch_size", 2))
        except (TypeError, ValueError):
            n = 2
        actual = max(DISPLAY_BATCH_MIN, min(n, DISPLAY_BATCH_MAX))
        if actual != n:
            clamped_fields["display_batch_size"] = {"requested": n, "actual": actual}
        items["meme_barrage_display_batch_size"] = str(actual)

    if items:
        app.config.set_batch(items)
        app.config_changed.emit()
        apply = getattr(app, "apply_meme_barrage_settings", None)
        if callable(apply):
            apply(reset_cursors=reset_cursors)

    result = get_meta(app)
    if clamped_fields:
        result["clamped_fields"] = clamped_fields
    return result


def get_tags() -> dict[str, Any]:
    global _tags_cache
    if _tags_cache:
        return {"tags": _tags_cache}
    try:
        client = MemeBarrageApiClient()
        _tags_cache = client.dict_list()
    except Exception:
        _tags_cache = list(FALLBACK_TAGS)
    return {"tags": _tags_cache}


def clear_library(app: "DanmuApp") -> dict[str, Any]:
    clearer = getattr(app, "clear_meme_barrage_library", None)
    if callable(clearer):
        return clearer()
    from app.meme_barrage.service import MemeBarrageService

    MemeBarrageService(app.config).clear_all()
    return {"ok": True, "library_count": 0, "display_queue_size": 0}
