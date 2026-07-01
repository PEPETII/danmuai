"""应用更新弹窗忽略状态：config.db JSON 校验与读写。

路由（由 ``app.web_api.routes`` 注册）：
- ``GET /api/app-update-state``：返回 ``{dismissedLatestVersion: str}``。
- ``PUT /api/app-update-state``：写入用户已忽略的版本号（点过「暂不更新」后不再提示）。

数据存于 ``ConfigStore`` 的 ``app_update_state`` 键（JSON 字符串）；字段名是
``dismissedLatestVersion``，对齐 Supabase ``app_updates.latest_version``。
"""

from __future__ import annotations

from fastapi import HTTPException

APP_UPDATE_STATE_KEY = "app_update_state"


def empty_state() -> dict[str, str]:
    return {"dismissedLatestVersion": ""}


def get_from_config(config) -> dict[str, str]:
    raw = config.get_json(APP_UPDATE_STATE_KEY, default=empty_state())
    if not isinstance(raw, dict):
        return empty_state()
    dismissed = raw.get("dismissedLatestVersion", "")
    if not isinstance(dismissed, str):
        dismissed = ""
    return {"dismissedLatestVersion": dismissed.strip()}


def save_to_config(config, state: dict[str, str]) -> None:
    config.set_json(APP_UPDATE_STATE_KEY, state)


def validate_payload(body: dict) -> dict[str, str]:
    dismissed = body.get("dismissedLatestVersion", "")
    if dismissed is None:
        dismissed = ""
    if not isinstance(dismissed, str):
        raise HTTPException(
            status_code=400, detail="dismissedLatestVersion 必须为字符串"
        )
    dismissed = dismissed.strip()
    if dismissed:
        from app.version_compare import normalize_version, parse_version

        try:
            parse_version(dismissed)
        except ValueError as exc:
            raise HTTPException(
                status_code=400, detail="dismissedLatestVersion 版本格式无效"
            ) from exc
        dismissed = normalize_version(dismissed)
    return {"dismissedLatestVersion": dismissed}
