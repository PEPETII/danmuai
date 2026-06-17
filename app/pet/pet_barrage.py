"""Pet barrage mode: 5 pet slots + per-slot bubbles, reusing PetWindow."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt6.QtWidgets import QApplication

from app.pet.pet_assets import BUILTIN_PET_DIR, validate_pet_pack_dir
from app.pet.pet_state import PetBarrageSlot, PetSettings

if TYPE_CHECKING:
    from main import DanmuApp
    from app.pet.pet_window import PetWindow


PET_BARRAGE_COUNT = 5


@dataclass(frozen=True)
class PetBarrageDelivery:
    slot_id: int
    text: str
    persona_id: str
    batch_id: int
    scene_generation: int
    source: str


def default_slot_positions() -> list[dict[str, int]]:
    app = QApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return [{"x": 80 + idx * 220, "y": 760} for idx in range(PET_BARRAGE_COUNT)]
    geo = screen.availableGeometry()
    bottom_y = max(geo.top(), geo.bottom() - 180)
    left = geo.left() + 60
    available_w = max(1, geo.width() - 120)
    step = available_w / PET_BARRAGE_COUNT
    positions: list[dict[str, int]] = []
    for idx in range(PET_BARRAGE_COUNT):
        positions.append({"x": int(left + idx * step), "y": int(bottom_y)})
    return positions


def build_barrage_slots_payload(settings: PetSettings) -> list[dict[str, object]]:
    slots: list[dict[str, object]] = []
    defaults = default_slot_positions()
    for slot in settings.barrage.slots:
        fallback = defaults[slot.slot_id] if slot.slot_id < len(defaults) else defaults[-1]
        effective_source = slot.asset_source or settings.asset_source
        effective_path = slot.asset_path or (settings.asset_path if effective_source == settings.asset_source else "")
        slots.append(
            {
                "slot_id": slot.slot_id,
                "asset_source": effective_source,
                "asset_path": effective_path,
                "position_x": slot.position_x if slot.position_x is not None else fallback["x"],
                "position_y": slot.position_y if slot.position_y is not None else fallback["y"],
            }
        )
    return slots


def resolve_slot_asset_summary(app: "DanmuApp", slot_id: int) -> dict[str, object]:
    settings = PetSettings.from_config(app.config)
    payload = build_barrage_slots_payload(settings)
    if slot_id < 0 or slot_id >= len(payload):
        raise ValueError("无效的桌宠槽位")
    row = payload[slot_id]
    asset_source = str(row["asset_source"] or "builtin")
    asset_path = str(row["asset_path"] or "")
    try:
        if asset_source == "local" and asset_path.strip():
            meta, sheet_path, _cols, _rows = validate_pet_pack_dir(Path(asset_path))
            display_name = str(meta.get("displayName", "")) or str(meta.get("id", "")) or "自定义桌宠"
            return {
                "ok": True,
                "slot_id": slot_id,
                "asset_source": "local",
                "asset_path": asset_path,
                "display_name": display_name,
                "resource_label": "本地目录",
                "preview_path": str(sheet_path),
            }
        meta, sheet_path, _cols, _rows = validate_pet_pack_dir(BUILTIN_PET_DIR)
        return {
            "ok": True,
            "slot_id": slot_id,
            "asset_source": "builtin",
            "asset_path": "",
            "display_name": str(meta.get("displayName", "")) or str(meta.get("id", "")) or "默认桌宠",
            "resource_label": "内置默认",
            "preview_path": str(sheet_path),
        }
    except ValueError as exc:
        fallback_sheet = BUILTIN_PET_DIR / "spritesheet.webp"
        return {
            "ok": False,
            "slot_id": slot_id,
            "asset_source": asset_source,
            "asset_path": asset_path,
            "display_name": "默认桌宠" if asset_source == "builtin" else "自定义桌宠",
            "resource_label": "内置默认" if asset_source == "builtin" else "本地目录",
            "preview_path": str(fallback_sheet),
            "error": str(exc),
        }


class PetBarrageController:
    def __init__(self, app: "DanmuApp") -> None:
        self._app = app
        self._windows: list["PetWindow"] = []
        self._last_deliveries: list[PetBarrageDelivery] = []

    def attach_windows(self, windows: list["PetWindow"]) -> None:
        self._windows = list(windows)

    def is_enabled(self) -> bool:
        return PetSettings.from_config(self._app.config).barrage.enabled

    def show(self) -> None:
        if not self.is_enabled():
            self.hide()
            return
        for window in self._windows:
            window.show_pet()

    def hide(self) -> None:
        for window in self._windows:
            window.hide_pet()

    def close(self) -> None:
        self.hide()

    def apply_config(self) -> None:
        if not self._windows:
            return
        settings = PetSettings.from_config(self._app.config)
        defaults = build_barrage_slots_payload(settings)
        for window in self._windows:
            slot_data = defaults[window.slot_id] if window.slot_id < len(defaults) else defaults[0]
            window.apply_slot_config(slot_data)
        if settings.enabled and settings.visible and settings.barrage.enabled:
            self.show()
        else:
            self.hide()

    def persist_slot_position(self, slot_id: int, x: int, y: int) -> None:
        settings = PetSettings.from_config(self._app.config)
        payload = build_barrage_slots_payload(settings)
        for row in payload:
            if int(row["slot_id"]) == int(slot_id):
                row["position_x"] = int(x)
                row["position_y"] = int(y)
                break
        positions = [
            {"slot_id": int(row["slot_id"]), "x": int(row["position_x"]), "y": int(row["position_y"])}
            for row in payload
        ]
        self._app.config.set("pet_barrage_slot_positions", json.dumps(positions, ensure_ascii=False))

    def sync_slots_to_config(
        self,
        *,
        slots: list[dict[str, object]] | None = None,
        positions: list[dict[str, object]] | None = None,
    ) -> None:
        settings = PetSettings.from_config(self._app.config)
        merged = build_barrage_slots_payload(settings)
        if slots:
            for row in slots:
                try:
                    slot_id = int(row.get("slot_id", -1))
                except (TypeError, ValueError):
                    continue
                if 0 <= slot_id < len(merged):
                    merged[slot_id]["asset_source"] = str(row.get("asset_source", merged[slot_id]["asset_source"]) or "builtin")
                    merged[slot_id]["asset_path"] = str(row.get("asset_path", merged[slot_id]["asset_path"]) or "")
        if positions:
            for row in positions:
                try:
                    slot_id = int(row.get("slot_id", -1))
                except (TypeError, ValueError):
                    continue
                if 0 <= slot_id < len(merged):
                    try:
                        merged[slot_id]["position_x"] = int(row.get("x", merged[slot_id]["position_x"]))
                        merged[slot_id]["position_y"] = int(row.get("y", merged[slot_id]["position_y"]))
                    except (TypeError, ValueError):
                        continue
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
        self._app.config.set("pet_barrage_slots", json.dumps(slot_rows, ensure_ascii=False))
        self._app.config.set("pet_barrage_slot_positions", json.dumps(pos_rows, ensure_ascii=False))

    def deliver_batch(
        self,
        texts: list[str],
        *,
        persona_id: str,
        batch_id: int,
        scene_generation: int,
        source: str,
    ) -> list[PetBarrageDelivery]:
        deliveries: list[PetBarrageDelivery] = []
        for idx, window in enumerate(self._windows):
            text = texts[idx] if idx < len(texts) else ""
            delivery = PetBarrageDelivery(
                slot_id=window.slot_id,
                text=text,
                persona_id=persona_id,
                batch_id=batch_id,
                scene_generation=scene_generation,
                source=source,
            )
            deliveries.append(delivery)
            window.set_bubble_text(text)
        self._last_deliveries = deliveries
        return deliveries

    def notify_success(self) -> None:
        for window in self._windows:
            window.notify_reply_success()

    def notify_error(self) -> None:
        for window in self._windows:
            window.notify_error()

    def snapshot(self) -> dict[str, object]:
        settings = PetSettings.from_config(self._app.config)
        return {
            "enabled": settings.barrage.enabled,
            "count": PET_BARRAGE_COUNT,
            "slots": build_barrage_slots_payload(settings),
            "last_deliveries": [
                {
                    "slot_id": row.slot_id,
                    "text": row.text,
                    "persona_id": row.persona_id,
                    "batch_id": row.batch_id,
                    "scene_generation": row.scene_generation,
                    "source": row.source,
                }
                for row in self._last_deliveries
            ],
            "updated_at": time.time(),
        }
