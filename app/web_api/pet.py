"""Desktop pet Web API helpers (delegates to DanmuApp façade)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import HTTPException

if TYPE_CHECKING:
    from main import DanmuApp


def get_settings(app: "DanmuApp") -> dict[str, object]:
    return app.get_pet_settings_snapshot()


def save_settings(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, object]:
    try:
        return app.apply_pet_settings_patch(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def show_pet(app: "DanmuApp") -> dict[str, object]:
    return app.show_pet()


def hide_pet(app: "DanmuApp") -> dict[str, object]:
    return app.hide_pet()


def close_pet(app: "DanmuApp") -> dict[str, object]:
    return app.close_pet()


def submit_command(app: "DanmuApp", text: str) -> dict[str, object]:
    try:
        return app.submit_pet_command(text, source="web_api")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_status(app: "DanmuApp") -> dict[str, object]:
    return app.get_pet_status_snapshot()
