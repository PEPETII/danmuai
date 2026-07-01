"""公告已读状态：config.db JSON 归一化、校验与读写（不经 PUT /api/config）。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/announcements-read-state``：返回 ``{readIds, lastSeenMs, overviewBannerDismissedId}``。
- ``PUT /api/announcements-read-state``：批量追加已读 id（去重 + 截断到 200 条）。

数据存于 ``ConfigStore`` 的 ``announcements_read_state`` 键（JSON 字符串）；归一化逻辑见
``empty_state`` / ``_normalize_*`` 助手。**不**进 ``PUT /api/config`` 全量表单；本模块
``validate_payload`` / ``get_from_config`` / ``save_to_config`` 在 ``app.web_api.routes`` 中调用。
"""

from __future__ import annotations

import re

from fastapi import HTTPException

ANNOUNCEMENTS_READ_STATE_KEY = "announcements_read_state"
ANNOUNCEMENTS_READ_IDS_MAX = 200
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def empty_state() -> dict[str, object]:
    return {"readIds": [], "lastSeenMs": 0, "overviewBannerDismissedId": ""}


def _normalize_overview_banner_dismissed_id(raw: object) -> str:
    if not isinstance(raw, str):
        return ""
    item = raw.strip()
    if not item:
        return ""
    if not _UUID_RE.match(item):
        return ""
    return item


def normalize_state(raw: object) -> dict[str, object]:
    if not isinstance(raw, dict):
        return empty_state()
    read_ids = raw.get("readIds")
    if not isinstance(read_ids, list):
        read_ids = []
    cleaned: list[str] = []
    for item in read_ids:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if item and item not in cleaned:
            cleaned.append(item)
    last_seen_ms = raw.get("lastSeenMs", 0)
    try:
        last_seen_ms = int(last_seen_ms)
    except (TypeError, ValueError):
        last_seen_ms = 0
    if last_seen_ms < 0:
        last_seen_ms = 0
    overview_banner_dismissed_id = _normalize_overview_banner_dismissed_id(
        raw.get("overviewBannerDismissedId", "")
    )
    return {
        "readIds": cleaned[:ANNOUNCEMENTS_READ_IDS_MAX],
        "lastSeenMs": last_seen_ms,
        "overviewBannerDismissedId": overview_banner_dismissed_id,
    }


def get_from_config(config) -> dict[str, object]:
    raw = config.get_json(ANNOUNCEMENTS_READ_STATE_KEY, default=empty_state())
    return normalize_state(raw)


def save_to_config(config, state: dict[str, object]) -> None:
    config.set_json(ANNOUNCEMENTS_READ_STATE_KEY, state)


def validate_payload(body: dict) -> dict[str, object]:
    read_ids = body.get("readIds")
    if read_ids is None:
        read_ids = []
    if not isinstance(read_ids, list):
        raise HTTPException(status_code=400, detail="readIds 必须为数组")
    cleaned: list[str] = []
    for item in read_ids:
        if not isinstance(item, str):
            raise HTTPException(status_code=400, detail="readIds 元素必须为字符串")
        item = item.strip()
        if not item:
            continue
        if not _UUID_RE.match(item):
            raise HTTPException(status_code=400, detail="readIds 包含无效的公告 ID")
        if item not in cleaned:
            cleaned.append(item)
    if len(cleaned) > ANNOUNCEMENTS_READ_IDS_MAX:
        cleaned = cleaned[-ANNOUNCEMENTS_READ_IDS_MAX:]
    last_seen_ms = body.get("lastSeenMs", 0)
    try:
        last_seen_ms = int(last_seen_ms)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="lastSeenMs 必须为整数") from exc
    if last_seen_ms < 0:
        raise HTTPException(status_code=400, detail="lastSeenMs 不能为负数")
    overview_banner_dismissed_id = body.get("overviewBannerDismissedId", "")
    if overview_banner_dismissed_id is None:
        overview_banner_dismissed_id = ""
    if not isinstance(overview_banner_dismissed_id, str):
        raise HTTPException(
            status_code=400, detail="overviewBannerDismissedId 必须为字符串"
        )
    overview_banner_dismissed_id = overview_banner_dismissed_id.strip()
    if overview_banner_dismissed_id and not _UUID_RE.match(overview_banner_dismissed_id):
        raise HTTPException(
            status_code=400, detail="overviewBannerDismissedId 无效的公告 ID"
        )
    return {
        "readIds": cleaned,
        "lastSeenMs": last_seen_ms,
        "overviewBannerDismissedId": overview_banner_dismissed_id,
    }
