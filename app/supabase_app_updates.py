"""Read ``app_updates`` from Supabase PostgREST (anon, enabled rows only)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Literal

import httpx

from app.supabase_config import get_supabase_credentials

_CACHE_TTL_SEC = 300.0
_APP_UPDATES_PATH = (
    "/rest/v1/app_updates"
    "?select=latest_version,release_url,enabled,message,updated_at"
    "&enabled=eq.true&order=updated_at.desc&limit=1"
)

_cache_lock = threading.Lock()
_cache: tuple[float, AppUpdateRemote | None] | None = None
AppUpdateCacheState = Literal["fresh", "cache_hit", "stale_fallback", "miss"]


@dataclass(frozen=True)
class AppUpdateRemote:
    latest_version: str
    release_url: str
    message: str


@dataclass(frozen=True)
class AppUpdateFetchResult:
    update: AppUpdateRemote | None
    cache_state: AppUpdateCacheState
    cache_age_sec: float | None = None


def clear_app_update_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = None


def _fetch_remote() -> AppUpdateRemote | None:
    creds = get_supabase_credentials()
    if creds is None:
        return None

    headers = {
        "apikey": creds.anon_key,
        "Authorization": f"Bearer {creds.anon_key}",
        "Accept": "application/json",
    }
    url = f"{creds.url}{_APP_UPDATES_PATH}"
    with httpx.Client(timeout=httpx.Timeout(8.0, connect=4.0)) as client:
        response = client.get(url, headers=headers)
        response.raise_for_status()
        rows = response.json()
    if not isinstance(rows, list) or not rows:
        return None

    row = rows[0]
    latest = str(row.get("latest_version") or "").strip()
    if not latest:
        return None
    release_url = str(row.get("release_url") or "").strip()
    message = row.get("message")
    message_text = "" if message is None else str(message).strip()
    return AppUpdateRemote(
        latest_version=latest,
        release_url=release_url,
        message=message_text,
    )


def fetch_app_update_result(*, force_refresh: bool = False) -> AppUpdateFetchResult:
    """Return latest enabled ``app_updates`` row with cache freshness metadata."""
    global _cache
    now = time.monotonic()
    with _cache_lock:
        cached = _cache
        if not force_refresh and cached is not None and now - cached[0] < _CACHE_TTL_SEC:
            cached_age = max(0.0, now - cached[0])
            if cached[1] is None:
                return AppUpdateFetchResult(update=None, cache_state="miss", cache_age_sec=cached_age)
            return AppUpdateFetchResult(
                update=cached[1],
                cache_state="cache_hit",
                cache_age_sec=cached_age,
            )

    try:
        result = _fetch_remote()
    except (httpx.HTTPError, ValueError, TypeError):
        with _cache_lock:
            cached = _cache
        if cached is not None:
            cached_age = max(0.0, time.monotonic() - cached[0])
            if cached[1] is None:
                return AppUpdateFetchResult(update=None, cache_state="miss", cache_age_sec=cached_age)
            return AppUpdateFetchResult(
                update=cached[1],
                cache_state="stale_fallback",
                cache_age_sec=cached_age,
            )
        return AppUpdateFetchResult(update=None, cache_state="miss")

    with _cache_lock:
        _cache = (now, result)
    if result is None:
        return AppUpdateFetchResult(update=None, cache_state="miss", cache_age_sec=0.0)
    return AppUpdateFetchResult(update=result, cache_state="fresh", cache_age_sec=0.0)


def fetch_app_update(*, force_refresh: bool = False) -> AppUpdateRemote | None:
    """Return latest enabled ``app_updates`` row; cache successes and reuse on transient errors."""
    return fetch_app_update_result(force_refresh=force_refresh).update
