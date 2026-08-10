"""公式化弹幕库专用 API；开关与 min_on_screen 不经 PUT /api/config 全量表单。

自定义句库数据来源为 ``%APPDATA%/DanmuAI/custom_formula_pool/*.txt``（见
``app.custom_formula_txt_pool``），不再提供应用内逐条追加或文件导入接口。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.custom_formula_txt_pool import (
    get_txt_pool_status,
    open_txt_pool_directory,
    refresh_txt_pool,
)
from app.danmu_pool import (
    CUSTOM_DANMU_POOL_MAX,
    any_danmu_pool_source_enabled,
    custom_pool_size,
    danmu_pool_use_custom_from_config,
)

if TYPE_CHECKING:
    from main import DanmuApp

CUSTOM_POOL_MAX = CUSTOM_DANMU_POOL_MAX
MIN_ON_SCREEN_MAX = 50


def get_meta(app: "DanmuApp") -> dict[str, Any]:
    config = app.config
    txt_status = get_txt_pool_status(config)
    return {
        "custom_enabled": danmu_pool_use_custom_from_config(config),
        "min_on_screen": config.get_int("min_on_screen", 5),
        "custom_count": custom_pool_size(config),
        "custom_max": CUSTOM_POOL_MAX,
        "effective_pool_enabled": any_danmu_pool_source_enabled(config),
        **txt_status,
    }


def save_settings(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, Any]:
    items: dict[str, str] = {}
    clamped_fields: dict[str, dict[str, int]] = {}
    if "custom_enabled" in payload:
        items["danmu_pool_use_custom"] = "1" if payload.get("custom_enabled") else "0"
    if "min_on_screen" in payload:
        try:
            min_n = int(payload.get("min_on_screen", 5))
        except (TypeError, ValueError):
            min_n = 5
        actual = max(0, min(min_n, MIN_ON_SCREEN_MAX))
        if actual != min_n:
            clamped_fields["min_on_screen"] = {"requested": min_n, "actual": actual}
        items["min_on_screen"] = str(actual)
    if items:
        app.config.set_batch(items)
        app.config_changed.emit()
    result: dict[str, Any] = {"ok": True}
    if clamped_fields:
        result["clamped_fields"] = clamped_fields
    return result


def refresh_custom_txt_pool(app: "DanmuApp") -> dict[str, Any]:
    status = refresh_txt_pool(app.config)
    app.config_changed.emit()
    return {"ok": True, **status}


def open_custom_txt_folder(app: "DanmuApp") -> dict[str, Any]:
    return open_txt_pool_directory(app.config)
