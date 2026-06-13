"""Velopack update HTTP API (frozen installs)."""

from __future__ import annotations

from app import release_channels, update_service


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
    from app.version import __version__

    return release_channels.build_update_metadata(current_version=__version__)


def get_release_channels() -> dict:
    """Backward-compatible alias for channel metadata endpoint."""
    return get_update_channels()
