"""Velopack update HTTP API (frozen installs)."""

from __future__ import annotations

from app import release_channels, update_service
from app.velopack_config import UPDATE_FEED_URL
from app.supabase_app_updates import fetch_app_update_result
from app.version import __version__
from app.version_compare import is_version_newer, normalize_version


def get_update_status() -> dict:
    return update_service.get_status().to_dict()


def post_update_check() -> dict:
    return update_service.check_for_updates().to_dict()


def post_update_download() -> dict:
    return update_service.download_updates().to_dict()


def post_update_restart() -> dict:
    return update_service.apply_updates_and_restart().to_dict()


def get_update_channels() -> dict:
    """Read-only channel metadata; does not contact the Velopack update feed."""
    current = normalize_version(__version__)
    result = fetch_app_update_result()
    row = result.update

    if row is not None and row.latest_version:
        latest = normalize_version(row.latest_version)
        release_url = row.release_url or release_channels.R2_LATEST_INSTALLER_URL
        message = row.message
    else:
        latest = current
        release_url = release_channels.R2_LATEST_INSTALLER_URL
        message = ""

    metadata: dict[str, str | bool | float | None] = {
        "current_version": current,
        "latest_version": latest,
        "update_available": is_version_newer(latest, current),
        "release_url": release_url,
        "feed_url": UPDATE_FEED_URL,
        "message": message,
        "cache_state": result.cache_state,
        "from_cache": result.cache_state in {"cache_hit", "stale_fallback"},
        "stale": result.cache_state == "stale_fallback",
        "cache_age_sec": result.cache_age_sec,
    }
    metadata.update(release_channels.to_dict())
    return metadata


def get_release_channels() -> dict:
    """Backward-compatible alias for channel metadata endpoint."""
    return get_update_channels()
