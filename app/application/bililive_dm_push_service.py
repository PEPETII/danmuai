"""W-BILILIVE-DM-PLUGIN-PUSH-004 — 主链路旁路推送到 bililive_dm 插件。"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import httpx

from app.bililive_dm_plugin_auth import plugin_secret_headers
from app.env_config import get as get_env
from app.web_api.bililive_dm_push import (
    DEFAULT_PUSH_URL,
    PUSH_SOURCE_MAIN,
    BililiveDmPushRequest,
)

logger = logging.getLogger(__name__)

MAX_ITEMS = 5
MAX_ITEM_CHARS = 60
_PUSH_TIMEOUT_SEC = 3.0


@dataclass(frozen=True)
class PushBatchResult:
    ok: bool
    error: str | None = None
    displayed: int = 0


def sanitize_push_items(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in items:
        text = str(raw).replace("\r", "").strip()
        if not text:
            continue
        if len(text) > MAX_ITEM_CHARS:
            text = text[: MAX_ITEM_CHARS - 1] + "…"
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
        if len(out) >= MAX_ITEMS:
            break
    return out


def push_batch_to_bililive_dm(
    request: BililiveDmPushRequest,
    *,
    url: str | None = None,
) -> PushBatchResult:
    items = sanitize_push_items(request.items)
    if not items:
        return PushBatchResult(ok=False, error="empty_items", displayed=0)

    payload = {
        "source": request.source or PUSH_SOURCE_MAIN,
        "batch_id": request.batch_id,
        "items": items,
        "persona": request.persona or "",
    }
    target = (url or get_env("DANMU_BILILIVE_DM_PUSH_URL") or DEFAULT_PUSH_URL).strip()
    timeout = httpx.Timeout(_PUSH_TIMEOUT_SEC, connect=_PUSH_TIMEOUT_SEC)

    headers = {
        "Content-Type": "application/json; charset=utf-8",
        **plugin_secret_headers(),
    }

    try:
        client = httpx.Client(timeout=timeout)
        try:
            resp = client.post(
                target,
                json=payload,
                headers=headers,
            )
        finally:
            client.close()
    except httpx.ConnectError:
        return PushBatchResult(ok=False, error="connection_refused", displayed=0)
    except httpx.TimeoutException:
        return PushBatchResult(ok=False, error="timeout", displayed=0)

    if resp.status_code < 200 or resp.status_code >= 300:
        return PushBatchResult(ok=False, error=f"http_{resp.status_code}", displayed=0)

    try:
        data = resp.json()
    except ValueError:
        return PushBatchResult(ok=False, error="invalid_json", displayed=0)

    if not data.get("ok"):
        return PushBatchResult(
            ok=False,
            error=str(data.get("error") or "push_failed"),
            displayed=int(data.get("displayed") or 0),
        )
    return PushBatchResult(ok=True, error=None, displayed=int(data.get("displayed") or len(items)))


def _push_worker(*, batch_id: int, items: list[str], persona: str | None) -> None:
    result = push_batch_to_bililive_dm(
        BililiveDmPushRequest(batch_id=batch_id, items=items, persona=persona),
    )
    if result.ok:
        logger.info(
            "bililive_dm_push: ok batch_id=%s displayed=%s",
            batch_id,
            result.displayed,
        )
    else:
        logger.warning(
            "bililive_dm_push: failed batch_id=%s error=%s",
            batch_id,
            result.error,
        )


def schedule_push_batch(
    *,
    batch_id: int,
    items: list[str],
    persona: str | None = None,
) -> None:
    if get_env("DANMU_BILILIVE_DM_PUSH", "1").strip() == "0":
        return
    display_items = sanitize_push_items(items)
    if not display_items:
        return
    thread = threading.Thread(
        target=_push_worker,
        kwargs={
            "batch_id": batch_id,
            "items": display_items,
            "persona": persona,
        },
        name=f"bililive-dm-push-{batch_id}",
        daemon=True,
    )
    thread.start()
