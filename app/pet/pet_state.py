"""Project pet configuration from ConfigStore into typed settings."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.config_store import ConfigStore


def _truthy(value: str, *, default: bool = False) -> bool:
    raw = str(value or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _float_clamped(value: str, default: float, lo: float, hi: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(parsed, hi))


def _int_or_none(value: str) -> int | None:
    raw = str(value or "").strip().lower()
    if not raw or raw in ("null", "none"):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _int_clamped(value, default: int, lo: int, hi: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(parsed, hi))


def _json_list(value: str) -> list:
    raw = str(value or "").strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


@dataclass(frozen=True)
class PetBarrageSlot:
    slot_id: int
    asset_source: str
    asset_path: str
    position_x: int | None
    position_y: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "slot_id": self.slot_id,
            "asset_source": self.asset_source,
            "asset_path": self.asset_path,
            "position_x": self.position_x,
            "position_y": self.position_y,
        }


@dataclass(frozen=True)
class PetBarrageSettings:
    enabled: bool
    count: int
    previous_render_mode: str
    previous_reply_count: int
    slots: tuple[PetBarrageSlot, ...]

    def to_api_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "count": self.count,
            "previous_render_mode": self.previous_render_mode,
            "previous_reply_count": self.previous_reply_count,
            "slots": [slot.to_dict() for slot in self.slots],
        }


@dataclass(frozen=True)
class PetSettings:
    enabled: bool
    visible: bool
    asset_source: str
    asset_path: str
    scale: float
    opacity: float
    always_on_top: bool
    click_through: bool
    position_x: int | None
    position_y: int | None
    command_box_enabled: bool
    command_ttl_sec: int
    command_apply_count: int
    barrage: PetBarrageSettings

    @classmethod
    def from_config(cls, config: "ConfigStore") -> "PetSettings":
        try:
            ttl = int(config.get("pet_command_ttl_sec", "30") or "30")
        except (TypeError, ValueError):
            ttl = 30
        try:
            apply_count = int(config.get("pet_command_apply_count", "1") or "1")
        except (TypeError, ValueError):
            apply_count = 1
        source = str(config.get("pet_asset_source", "builtin") or "builtin").strip().lower()
        if source not in ("builtin", "local"):
            source = "builtin"
        barrage_count = _int_clamped(config.get("pet_barrage_count", "5"), 5, 5, 5)
        slots_config = _json_list(config.get("pet_barrage_slots", "[]"))
        positions_config = _json_list(config.get("pet_barrage_slot_positions", "[]"))
        barrage_slots: list[PetBarrageSlot] = []
        for slot_id in range(barrage_count):
            slot_raw = slots_config[slot_id] if slot_id < len(slots_config) and isinstance(slots_config[slot_id], dict) else {}
            pos_raw = positions_config[slot_id] if slot_id < len(positions_config) and isinstance(positions_config[slot_id], dict) else {}
            slot_source = str(slot_raw.get("asset_source", source) or source).strip().lower()
            if slot_source not in ("builtin", "local"):
                slot_source = "builtin"
            slot_path = str(slot_raw.get("asset_path", "") or "")
            barrage_slots.append(
                PetBarrageSlot(
                    slot_id=slot_id,
                    asset_source=slot_source,
                    asset_path=slot_path,
                    position_x=_int_or_none(pos_raw.get("x", slot_raw.get("position_x", ""))),
                    position_y=_int_or_none(pos_raw.get("y", slot_raw.get("position_y", ""))),
                )
            )
        previous_render_mode = str(
            config.get("pet_barrage_previous_render_mode", "scrolling") or "scrolling"
        ).strip().lower()
        if previous_render_mode not in ("scrolling", "floating_panel"):
            previous_render_mode = "scrolling"
        return cls(
            enabled=_truthy(config.get("pet_enabled", "0")),
            visible=_truthy(config.get("pet_visible", "0")),
            asset_source=source,
            asset_path=str(config.get("pet_asset_path", "") or ""),
            scale=_float_clamped(config.get("pet_scale", "0.5"), 0.5, 0.5, 2.0),
            opacity=_float_clamped(config.get("pet_opacity", "1.0"), 1.0, 0.2, 1.0),
            always_on_top=_truthy(config.get("pet_always_on_top", "1"), default=True),
            click_through=_truthy(config.get("pet_click_through", "0")),
            position_x=_int_or_none(config.get("pet_position_x", "")),
            position_y=_int_or_none(config.get("pet_position_y", "")),
            command_box_enabled=_truthy(config.get("pet_command_box_enabled", "1"), default=True),
            command_ttl_sec=max(5, min(ttl, 300)),
            command_apply_count=max(1, min(apply_count, 5)),
            barrage=PetBarrageSettings(
                enabled=_truthy(config.get("pet_barrage_mode_enabled", "0")),
                count=barrage_count,
                previous_render_mode=previous_render_mode,
                previous_reply_count=_int_clamped(
                    config.get("pet_barrage_previous_reply_count", "5"),
                    5,
                    1,
                    50,
                ),
                slots=tuple(barrage_slots),
            ),
        )

    def to_api_dict(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "visible": self.visible,
            "asset_source": self.asset_source,
            "asset_path": self.asset_path,
            "scale": self.scale,
            "opacity": self.opacity,
            "always_on_top": self.always_on_top,
            "click_through": self.click_through,
            "position_x": self.position_x,
            "position_y": self.position_y,
            "command_box_enabled": self.command_box_enabled,
            "command_ttl_sec": self.command_ttl_sec,
            "command_apply_count": self.command_apply_count,
            "pet_barrage": self.barrage.to_api_dict(),
        }
