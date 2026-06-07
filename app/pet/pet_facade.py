"""DanmuApp façade helpers for desktop pet Web API and lifecycle."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.pet.pet_animation_mapper import resolve_pet_animation_hint
from app.pet.pet_assets import validate_pet_pack_dir
from app.pet.pet_state import PetSettings

if TYPE_CHECKING:
    from main import DanmuApp

PET_CONFIG_KEYS = (
    "pet_enabled",
    "pet_visible",
    "pet_asset_source",
    "pet_asset_path",
    "pet_scale",
    "pet_opacity",
    "pet_always_on_top",
    "pet_click_through",
    "pet_position_x",
    "pet_position_y",
    "pet_command_box_enabled",
    "pet_command_ttl_sec",
    "pet_command_apply_count",
)


def _pet_window(app: "DanmuApp"):
    return app.__dict__.get("pet_window")


def _pet_command_service(app: "DanmuApp"):
    return app.__dict__.get("pet_command_service")


def get_pet_settings_snapshot(app: "DanmuApp") -> dict[str, object]:
    settings = PetSettings.from_config(app.config)
    svc = _pet_command_service(app)
    pending = svc.peek_summary() if svc else None
    pack_info: dict[str, Any] = {"ok": False}
    try:
        from app.pet.pet_assets import load_pet_assets

        pack = load_pet_assets(app.config)
        pack_info = {
            "ok": True,
            "id": pack.pet_id,
            "display_name": pack.display_name,
            "description": pack.description,
        }
    except ValueError as exc:
        pack_info = {"ok": False, "error": str(exc)}
    out = settings.to_api_dict()
    out["asset"] = pack_info
    out["has_pending_command"] = pending is not None
    out["pending_command"] = pending
    return out


def apply_pet_settings_patch(app: "DanmuApp", payload: dict[str, object]) -> dict[str, object]:
    items: dict[str, str] = {}
    for key in PET_CONFIG_KEYS:
        if key not in payload or payload[key] is None:
            continue
        value = payload[key]
        if key in ("pet_position_x", "pet_position_y") and value in ("", None):
            items[key] = ""
        elif isinstance(value, bool):
            items[key] = "1" if value else "0"
        else:
            items[key] = str(value)

    if "pet_asset_source" in items:
        src = items["pet_asset_source"].strip().lower()
        items["pet_asset_source"] = src if src in ("builtin", "local") else "builtin"

    if items.get("pet_asset_source") == "local" or items.get("pet_asset_path"):
        path = items.get("pet_asset_path") or app.config.get("pet_asset_path", "")
        if str(path).strip():
            from pathlib import Path

            validate_pet_pack_dir(Path(str(path).strip()))

    if items:
        app.config.set_batch(items)
        app.config_changed.emit()

    sync_pet_window_visibility(app)
    window = _pet_window(app)
    if window is not None:
        window.apply_config()
    return get_pet_settings_snapshot(app)


def show_pet(app: "DanmuApp") -> dict[str, object]:
    app.config.set_batch({"pet_enabled": "1", "pet_visible": "1"})
    app.config_changed.emit()
    sync_pet_window_visibility(app)
    return {"ok": True, "visible": True}


def hide_pet(app: "DanmuApp") -> dict[str, object]:
    app.config.set("pet_visible", "0")
    app.config_changed.emit()
    sync_pet_window_visibility(app)
    return {"ok": True, "visible": False}


def close_pet(app: "DanmuApp") -> dict[str, object]:
    app.config.set_batch({"pet_enabled": "0", "pet_visible": "0"})
    app.config_changed.emit()
    sync_pet_window_visibility(app)
    return {"ok": True, "enabled": False}


def submit_pet_command(
    app: "DanmuApp",
    text: str,
    *,
    source: str = "web_api",
) -> dict[str, object]:
    svc = _pet_command_service(app)
    if svc is None:
        raise ValueError("桌宠指令服务未初始化")
    settings = PetSettings.from_config(app.config)
    if not settings.enabled:
        raise ValueError("请先启用桌宠")
    result = svc.submit(
        text,
        ttl_sec=settings.command_ttl_sec,
        apply_count=settings.command_apply_count,
        source=source,
    )
    window = _pet_window(app)
    if window is not None:
        window.notify_command_submitted()
    return result


def get_pet_status_snapshot(app: "DanmuApp") -> dict[str, object]:
    window = _pet_window(app)
    animation = get_pet_animation_hint(app)
    svc = _pet_command_service(app)
    return {
        "enabled": PetSettings.from_config(app.config).enabled,
        "visible": bool(window.isVisible()) if window is not None else False,
        "animation": animation,
        "has_pending_command": svc.has_pending() if svc else False,
        "pending_command": svc.peek_summary() if svc else None,
    }


def get_pet_animation_hint(app: "DanmuApp") -> str:
    window = _pet_window(app)
    if window is not None:
        return resolve_pet_animation_hint(
            app,
            one_shot=window._one_shot,
            one_shot_until=window._one_shot_until,
        )
    return resolve_pet_animation_hint(app)


def sync_pet_window_visibility(app: "DanmuApp") -> None:
    window = _pet_window(app)
    if window is None:
        return
    settings = PetSettings.from_config(app.config)
    if settings.enabled and settings.visible:
        window.show_pet()
    else:
        window.hide_pet()
