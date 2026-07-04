"""Desktop pet Web API helpers (delegates to DanmuApp façade)."""

from __future__ import annotations

import mimetypes
from typing import TYPE_CHECKING, Any

from app.translations import tr
from fastapi import HTTPException
from fastapi.responses import FileResponse

if TYPE_CHECKING:
    from main import DanmuApp


def get_settings(app: "DanmuApp") -> dict[str, object]:
    return app.get_pet_settings_snapshot()


def save_settings(app: "DanmuApp", payload: dict[str, Any]) -> dict[str, object]:
    try:
        return app.apply_pet_settings_patch(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def import_asset_via_dialog(app: "DanmuApp") -> dict[str, object]:
    try:
        return app.import_pet_asset_via_dialog()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def import_barrage_slot_asset_via_dialog(app: "DanmuApp", slot_id: int) -> dict[str, object]:
    try:
        return app.import_pet_barrage_slot_asset_via_dialog(slot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def reset_asset_to_builtin(app: "DanmuApp") -> dict[str, object]:
    try:
        return app.reset_pet_asset_to_builtin()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def set_barrage_slot_asset(
    app: "DanmuApp",
    slot_id: int,
    *,
    asset_source: str,
    asset_path: str,
) -> dict[str, object]:
    try:
        return app.set_pet_barrage_slot_asset(
            slot_id,
            asset_source=asset_source,
            asset_path=asset_path,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def reset_barrage_slot_asset(app: "DanmuApp", slot_id: int) -> dict[str, object]:
    try:
        return app.reset_pet_barrage_slot_asset(slot_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def get_barrage_slot_preview(app: "DanmuApp", slot_id: int):
    settings = app.get_pet_settings_snapshot()
    barrage = settings.get("pet_barrage") if isinstance(settings, dict) else {}
    assets = barrage.get("slot_assets") if isinstance(barrage, dict) else []
    if not isinstance(assets, list) or slot_id < 0 or slot_id >= len(assets):
        raise HTTPException(status_code=404, detail=tr("pet.slotNotFound"))
    preview_path = str((assets[slot_id] or {}).get("preview_path") or "").strip()
    if not preview_path:
        raise HTTPException(status_code=404, detail=tr("pet.previewNotFound"))
    media_type = mimetypes.guess_type(preview_path)[0] or "application/octet-stream"
    return FileResponse(preview_path, media_type=media_type)


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
