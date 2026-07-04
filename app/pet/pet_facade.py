"""DanmuApp façade helpers for desktop pet Web API and lifecycle."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.pet.pet_animation_mapper import resolve_pet_animation_hint
from app.pet.pet_assets import (
    ALLOWED_PET_PACK_ROOT,
    is_path_within_sandbox,
    validate_pet_pack_dir,
)
from app.pet.pet_barrage import (
    PET_BARRAGE_COUNT,
    build_barrage_slots_payload,
    resolve_slot_asset_summary,
)
from app.pet.pet_state import PetSettings, _truthy
from app.translations import tr

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
    "pet_barrage_mode_enabled",
    "pet_barrage_count",
    "pet_barrage_slots",
    "pet_barrage_slot_positions",
    "pet_barrage_previous_render_mode",
    "pet_barrage_previous_reply_count",
)


def _pet_window(app: "DanmuApp"):
    return app.__dict__.get("pet_window")


def _pet_barrage_controller(app: "DanmuApp"):
    return app.__dict__.get("pet_barrage_controller")


def _pet_command_service(app: "DanmuApp"):
    return app.__dict__.get("pet_command_service")


def _maybe_ensure_pet_components(app: "DanmuApp") -> None:
    settings = PetSettings.from_config(app.config)
    if not (settings.enabled and settings.visible):
        return
    ensure = getattr(app, "_ensure_pet_components", None)
    if callable(ensure):
        ensure()


def _pet_barrage_disable_config_items(app: "DanmuApp") -> dict[str, str]:
    """Return config items to exit pet barrage mode and restore prior danmu settings."""
    if not _truthy(app.config.get("pet_barrage_mode_enabled", "0")):
        return {}
    return {
        "pet_barrage_mode_enabled": "0",
        "danmu_render_mode": str(
            app.config.get("pet_barrage_previous_render_mode", "scrolling") or "scrolling"
        ),
        "normal_reply_count": str(
            app.config.get("pet_barrage_previous_reply_count", str(PET_BARRAGE_COUNT)) or PET_BARRAGE_COUNT
        ),
    }


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
    out["pet_barrage"]["slots"] = build_barrage_slots_payload(settings)
    out["pet_barrage"]["slot_assets"] = [
        resolve_slot_asset_summary(app, slot_id)
        for slot_id in range(PET_BARRAGE_COUNT)
    ]
    ctrl = _pet_barrage_controller(app)
    if ctrl is not None:
        out["pet_barrage"]["status"] = ctrl.snapshot()
    return out


def import_pet_asset_via_dialog(app: "DanmuApp") -> dict[str, object]:
    """Open a native directory picker on the Qt main thread and bind the chosen pack."""
    from PyQt6.QtWidgets import QFileDialog

    start_dir = str(app.config.get("pet_asset_path", "") or "").strip()
    if not start_dir:
        start_dir = str(Path.home())
    selected_dir = QFileDialog.getExistingDirectory(
        None,
        tr("pet.dialog.select_folder"),
        start_dir,
        QFileDialog.Option.ShowDirsOnly,
    )
    if not selected_dir:
        snapshot = get_pet_settings_snapshot(app)
        snapshot["cancelled"] = True
        return snapshot
    return apply_pet_settings_patch(
        app,
        {
            "pet_asset_source": "local",
            "pet_asset_path": selected_dir,
        },
    )


def import_pet_barrage_slot_asset_via_dialog(app: "DanmuApp", slot_id: int) -> dict[str, object]:
    from PyQt6.QtWidgets import QFileDialog

    settings = PetSettings.from_config(app.config)
    if slot_id < 0 or slot_id >= PET_BARRAGE_COUNT:
        raise ValueError(tr("pet.error.invalid_slot"))
    current_slot = settings.barrage.slots[slot_id]
    start_dir = str(current_slot.asset_path or settings.asset_path or "").strip()
    if not start_dir:
        start_dir = str(Path.home())
    selected_dir = QFileDialog.getExistingDirectory(
        None,
        tr("pet.dialog.select_slot_folder").format(slot=slot_id + 1),
        start_dir,
        QFileDialog.Option.ShowDirsOnly,
    )
    if not selected_dir:
        snapshot = get_pet_settings_snapshot(app)
        snapshot["cancelled"] = True
        return snapshot
    return set_pet_barrage_slot_asset(
        app,
        slot_id,
        asset_source="local",
        asset_path=selected_dir,
    )


def reset_pet_asset_to_builtin(app: "DanmuApp") -> dict[str, object]:
    """Unbind any custom local pack and fall back to the builtin default pet."""
    return apply_pet_settings_patch(
        app,
        {
            "pet_asset_source": "builtin",
            "pet_asset_path": "",
        },
    )


def set_pet_barrage_slot_asset(
    app: "DanmuApp",
    slot_id: int,
    *,
    asset_source: str,
    asset_path: str,
) -> dict[str, object]:
    if slot_id < 0 or slot_id >= PET_BARRAGE_COUNT:
        raise ValueError(tr("pet.error.invalid_slot"))
    return apply_pet_settings_patch(
        app,
        {
            "pet_barrage_slots": [
                {
                    "slot_id": slot_id,
                    "asset_source": asset_source,
                    "asset_path": asset_path,
                }
            ]
        },
    )


def reset_pet_barrage_slot_asset(app: "DanmuApp", slot_id: int) -> dict[str, object]:
    settings = PetSettings.from_config(app.config)
    return set_pet_barrage_slot_asset(
        app,
        slot_id,
        asset_source=settings.asset_source,
        asset_path=settings.asset_path,
    )


def apply_pet_settings_patch(app: "DanmuApp", payload: dict[str, object]) -> dict[str, object]:
    items: dict[str, str] = {}
    slot_updates = payload.get("pet_barrage_slots")
    position_updates = payload.get("pet_barrage_slot_positions")
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
        if items["pet_asset_source"] == "builtin" and "pet_asset_path" not in items:
            items["pet_asset_path"] = ""

    if items.get("pet_asset_source") == "local" or items.get("pet_asset_path"):
        path = items.get("pet_asset_path") or app.config.get("pet_asset_path", "")
        if str(path).strip():
            path_obj = Path(str(path).strip())
            if not is_path_within_sandbox(path_obj, ALLOWED_PET_PACK_ROOT):
                raise ValueError(
                    tr("pet.error.path_out_of_range").format(
                        path=path,
                        allowed=ALLOWED_PET_PACK_ROOT,
                    )
                )
            validate_pet_pack_dir(path_obj)

    if slot_updates is not None:
        for row in slot_updates:
            if not isinstance(row, dict):
                continue
            asset_source = str(row.get("asset_source", "builtin") or "builtin").strip().lower()
            asset_path = str(row.get("asset_path", "") or "").strip()
            if asset_source == "local" and asset_path:
                path_obj = Path(asset_path)
                if not is_path_within_sandbox(path_obj, ALLOWED_PET_PACK_ROOT):
                    raise ValueError(
                        tr("pet.error.slot_path_out_of_range").format(
                            path=asset_path,
                            allowed=ALLOWED_PET_PACK_ROOT,
                        )
                    )

    if "pet_enabled" in items:
        old_enabled = _truthy(app.config.get("pet_enabled", "0"))
        new_enabled = _truthy(items["pet_enabled"])
        if new_enabled != old_enabled:
            items["pet_visible"] = items["pet_enabled"]

    if "pet_barrage_mode_enabled" in items:
        old_enabled = _truthy(app.config.get("pet_barrage_mode_enabled", "0"))
        new_enabled = _truthy(items["pet_barrage_mode_enabled"])
        if new_enabled and not old_enabled:
            from app.personae import DEFAULT_NORMAL_REPLY_COUNT

            items.setdefault(
                "pet_barrage_previous_render_mode",
                str(app.config.get("danmu_render_mode", "scrolling") or "scrolling"),
            )
            items.setdefault(
                "pet_barrage_previous_reply_count",
                str(app.config.get("normal_reply_count", str(DEFAULT_NORMAL_REPLY_COUNT)) or DEFAULT_NORMAL_REPLY_COUNT),
            )
            items["normal_reply_count"] = str(PET_BARRAGE_COUNT)
        if (not new_enabled) and old_enabled:
            items.update(_pet_barrage_disable_config_items(app))

    if items:
        app.config.set_batch(items)
    ctrl = _pet_barrage_controller(app)
    if ctrl is not None:
        ctrl.sync_slots_to_config(
            slots=slot_updates if isinstance(slot_updates, list) else None,
            positions=position_updates if isinstance(position_updates, list) else None,
        )
        ctrl.apply_config()
    elif slot_updates is not None or position_updates is not None:
        settings = PetSettings.from_config(app.config)
        merged = build_barrage_slots_payload(settings)
        if isinstance(slot_updates, list):
            for row in slot_updates:
                if not isinstance(row, dict):
                    continue
                try:
                    slot_id = int(row.get("slot_id", -1))
                except (TypeError, ValueError):
                    continue
                if 0 <= slot_id < len(merged):
                    merged[slot_id]["asset_source"] = str(row.get("asset_source", merged[slot_id]["asset_source"]) or "builtin")
                    merged[slot_id]["asset_path"] = str(row.get("asset_path", merged[slot_id]["asset_path"]) or "")
        if isinstance(position_updates, list):
            for row in position_updates:
                if not isinstance(row, dict):
                    continue
                try:
                    slot_id = int(row.get("slot_id", -1))
                    x = int(row.get("x", merged[slot_id]["position_x"]))
                    y = int(row.get("y", merged[slot_id]["position_y"]))
                except (TypeError, ValueError, IndexError):
                    continue
                if 0 <= slot_id < len(merged):
                    merged[slot_id]["position_x"] = x
                    merged[slot_id]["position_y"] = y
        slot_rows = [
            {
                "slot_id": int(row["slot_id"]),
                "asset_source": str(row["asset_source"]),
                "asset_path": str(row["asset_path"]),
            }
            for row in merged
        ]
        pos_rows = [
            {
                "slot_id": int(row["slot_id"]),
                "x": int(row["position_x"]),
                "y": int(row["position_y"]),
            }
            for row in merged
        ]
        import json

        app.config.set("pet_barrage_slots", json.dumps(slot_rows, ensure_ascii=False))
        app.config.set("pet_barrage_slot_positions", json.dumps(pos_rows, ensure_ascii=False))
        app.config_changed.emit()

    _maybe_ensure_pet_components(app)
    sync_pet_window_visibility(app)
    window = _pet_window(app)
    if window is not None:
        window.apply_config()
    return get_pet_settings_snapshot(app)


def show_pet(app: "DanmuApp") -> dict[str, object]:
    items = {"pet_enabled": "1", "pet_visible": "1"}
    items.update(_pet_barrage_disable_config_items(app))
    app.config.set_batch(items)
    app.config_changed.emit()
    ctrl = _pet_barrage_controller(app)
    if ctrl is not None:
        ctrl.apply_config()
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
        raise ValueError(tr("pet.error.service_not_initialized"))
    settings = PetSettings.from_config(app.config)
    if not settings.enabled:
        raise ValueError(tr("pet.error.enable_pet_first"))
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
    barrage = _pet_barrage_controller(app)
    animation = get_pet_animation_hint(app)
    svc = _pet_command_service(app)
    return {
        "enabled": PetSettings.from_config(app.config).enabled,
        "visible": bool(window.isVisible()) if window is not None else False,
        "animation": animation,
        "has_pending_command": svc.has_pending() if svc else False,
        "pending_command": svc.peek_summary() if svc else None,
        "pet_barrage": barrage.snapshot() if barrage is not None else {"enabled": False, "count": PET_BARRAGE_COUNT, "slots": []},
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
    barrage = _pet_barrage_controller(app)
    settings = PetSettings.from_config(app.config)
    if barrage is not None:
        barrage.apply_config()
        if settings.enabled and settings.visible and settings.barrage.enabled:
            if window is not None:
                window.hide_pet()
            barrage.show()
            return
        barrage.hide()
    if window is None:
        return
    if settings.enabled and settings.visible:
        window.show_pet()
    else:
        window.hide_pet()
