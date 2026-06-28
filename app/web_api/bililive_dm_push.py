"""W-BILILIVE-DM-PLUGIN-PUSH-004 — DanmuAI → bililive_dm 主动推送契约。"""

from __future__ import annotations

from pydantic import BaseModel, Field

PUSH_SOURCE_MAIN = "danmuai_main"
DEFAULT_PUSH_URL = "http://127.0.0.1:18766/api/plugin/danmuai/push/"


class BililiveDmPushRequest(BaseModel):
    source: str = PUSH_SOURCE_MAIN
    batch_id: int = 0
    items: list[str] = Field(default_factory=list)
    persona: str | None = None
