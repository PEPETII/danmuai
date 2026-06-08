"""公式化弹幕库专用 API；开关与 min_on_screen 不经 PUT /api/config 全量表单。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/danmu-pool/meta``：自定义开关 + pool size。
- ``POST /api/danmu-pool/custom``：追加自定义句（去重 + 安全校验），上限 500。
- ``PUT /api/danmu-pool/settings``：写 ``danmu_pool_use_custom`` / ``min_on_screen``。
- ``DELETE /api/danmu-pool/custom``：删除自定义句。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.danmu_pool import (
    any_danmu_pool_source_enabled,
    custom_pool_size,
    danmu_pool_use_custom_from_config,
)
from app.danmu_pool_overlay import is_overlay_safe

if TYPE_CHECKING:
    from main import DanmuApp

CUSTOM_POOL_MAX = 500
APPEND_BATCH_MAX = 100
MIN_ON_SCREEN_MAX = 50

_SKIP_REASON_DUPLICATE = "duplicate"
_SKIP_REASON_EMPTY = "empty"
_SKIP_REASON_UNSAFE = "unsafe"
_SKIP_REASON_LIMIT = "limit_reached"


def get_meta(app: "DanmuApp") -> dict[str, Any]:
    config = app.config
    return {
        "custom_enabled": danmu_pool_use_custom_from_config(config),
        "min_on_screen": config.get_int("min_on_screen", 5),
        "custom_count": custom_pool_size(config),
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


def list_custom(app: "DanmuApp") -> dict[str, Any]:
    return {"items": app.config.get_custom_danmu_pool()}


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

    config = app.config
    existing = list(config.get_custom_danmu_pool())
    existing_set = set(existing)

    added: list[str] = []
    skipped_items: list[dict[str, str]] = []

    for raw in raw_lines:
        text = str(raw).strip()
        if not text:
            skipped_items.append({"text": raw, "reason": _SKIP_REASON_EMPTY})
            continue
        if text in existing_set:
            skipped_items.append({"text": text, "reason": _SKIP_REASON_DUPLICATE})
            continue
        if not is_overlay_safe(text, max_chars=None):
            skipped_items.append({"text": text, "reason": _SKIP_REASON_UNSAFE})
            continue
        if len(existing) + len(added) >= CUSTOM_POOL_MAX:
            skipped_items.append({"text": text, "reason": _SKIP_REASON_LIMIT})
            continue
        added.append(text)
        existing_set.add(text)

    if added:
        merged = existing + added
        config.set_custom_danmu_pool(merged)
        app.config_changed.emit()

    return {
        "added": len(added),
        "skipped": len(skipped_items),
        "items": config.get_custom_danmu_pool(),
        "skipped_items": skipped_items,
    }


def delete_custom(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, Any]:
    texts = payload.get("texts")
    if not isinstance(texts, list) or not texts:
        raise ValueError("请提供要删除的弹幕句")

    remove = {str(text).strip() for text in texts if str(text).strip()}
    existing = app.config.get_custom_danmu_pool()
    kept = [line for line in existing if line not in remove]
    removed = len(existing) - len(kept)
    if removed:
        app.config.set_custom_danmu_pool(kept)
        app.config_changed.emit()
    return {"removed": removed, "items": app.config.get_custom_danmu_pool()}
