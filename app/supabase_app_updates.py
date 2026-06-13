"""Read ``app_updates`` from Supabase PostgREST (anon, enabled rows only)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

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


@dataclass(frozen=True)
class AppUpdateRemote:
    latest_version: str
    release_url: str
    message: str


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


def fetch_app_update(*, force_refresh: bool = False) -> AppUpdateRemote | None:
    """Return latest enabled ``app_updates`` row; cache successes and reuse on transient errors."""
    global _cache
    now = time.monotonic()
    with _cache_lock:
        if (
            not force_refresh
            and _cache is not None
            and now - _cache[0] < _CACHE_TTL_SEC
        ):
            return _cache[1]

    try:
        result = _fetch_remote()
    except (httpx.HTTPError, ValueError, TypeError):
        with _cache_lock:
            if _cache is not None:
                return _cache[1]
        return None

    with _cache_lock:
        _cache = (now, result)
    return result
