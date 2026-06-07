"""Project pet configuration from ConfigStore into typed settings."""

from __future__ import annotations

from dataclasses import dataclass
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
        return cls(
            enabled=_truthy(config.get("pet_enabled", "0")),
            visible=_truthy(config.get("pet_visible", "0")),
            asset_source=source,
            asset_path=str(config.get("pet_asset_path", "") or ""),
            scale=_float_clamped(config.get("pet_scale", "1.0"), 1.0, 0.5, 2.0),
            opacity=_float_clamped(config.get("pet_opacity", "1.0"), 1.0, 0.2, 1.0),
            always_on_top=_truthy(config.get("pet_always_on_top", "1"), default=True),
            click_through=_truthy(config.get("pet_click_through", "0")),
            position_x=_int_or_none(config.get("pet_position_x", "")),
            position_y=_int_or_none(config.get("pet_position_y", "")),
            command_box_enabled=_truthy(config.get("pet_command_box_enabled", "1"), default=True),
            command_ttl_sec=max(5, min(ttl, 300)),
            command_apply_count=max(1, min(apply_count, 5)),
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
        }
