"""Velopack update HTTP API (frozen installs)."""

from __future__ import annotations

from app import update_service


def get_update_status() -> dict:
    return update_service.get_status().to_dict()


def post_update_check() -> dict:
    return update_service.check_for_updates().to_dict()


def post_update_download() -> dict:
    return update_service.download_updates().to_dict()


def post_update_restart() -> dict:
    return update_service.apply_updates_and_restart().to_dict()
