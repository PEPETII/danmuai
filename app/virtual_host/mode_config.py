"""虚拟主播互斥模式配置：对话模式与弹幕适配模式。"""

from __future__ import annotations

from typing import Any

DIALOGUE_ENABLED_KEY = "virtual_host_dialogue_enabled"
DANMU_ADAPTER_ENABLED_KEY = "virtual_host_danmu_adapter_enabled"

DEFAULT_DIALOGUE_ENABLED = "0"
DEFAULT_DANMU_ADAPTER_ENABLED = "1"

ALLOWED_PATCH_KEYS = frozenset({"dialogue_enabled", "danmu_adapter_enabled"})


def _read_bool(config, key: str, *, default: str) -> bool:
    return str(config.get(key, default) or default).strip() == "1"


def _write_bool(enabled: bool) -> str:
    return "1" if enabled else "0"


def sanitize_virtual_host_mode_settings(config, *, persist: bool = False) -> dict[str, str]:
    """读取并规范化互斥模式；存储同时开启时优先保留弹幕适配模式。"""

    dialogue = _read_bool(config, DIALOGUE_ENABLED_KEY, default=DEFAULT_DIALOGUE_ENABLED)
    danmu_adapter = _read_bool(
        config,
        DANMU_ADAPTER_ENABLED_KEY,
        default=DEFAULT_DANMU_ADAPTER_ENABLED,
    )
    if dialogue and danmu_adapter:
        dialogue = False
    normalized = {
        DIALOGUE_ENABLED_KEY: _write_bool(dialogue),
        DANMU_ADAPTER_ENABLED_KEY: _write_bool(danmu_adapter),
    }
    if persist:
        current = {
            DIALOGUE_ENABLED_KEY: str(config.get(DIALOGUE_ENABLED_KEY, "") or ""),
            DANMU_ADAPTER_ENABLED_KEY: str(config.get(DANMU_ADAPTER_ENABLED_KEY, "") or ""),
        }
        if current != normalized:
            setter = getattr(config, "set_batch", None)
            if callable(setter):
                setter(normalized)
    return normalized


def export_virtual_host_mode_settings(config) -> dict[str, bool]:
    normalized = sanitize_virtual_host_mode_settings(config)
    return {
        "dialogue_enabled": normalized[DIALOGUE_ENABLED_KEY] == "1",
        "danmu_adapter_enabled": normalized[DANMU_ADAPTER_ENABLED_KEY] == "1",
    }


def apply_virtual_host_mode_settings(config, patch: dict[str, Any]) -> dict[str, bool]:
    if not isinstance(patch, dict):
        raise ValueError("payload must be an object")

    unknown = set(patch.keys()) - ALLOWED_PATCH_KEYS
    if unknown:
        raise ValueError("invalid_payload")

    if not patch:
        return export_virtual_host_mode_settings(config)

    for key in ALLOWED_PATCH_KEYS:
        if key not in patch or patch[key] is None:
            continue
        if not isinstance(patch[key], bool):
            raise ValueError("invalid_payload")

    if patch.get("dialogue_enabled") is True and patch.get("danmu_adapter_enabled") is True:
        raise ValueError("virtual_host_modes_mutually_exclusive")

    current = export_virtual_host_mode_settings(config)
    dialogue = current["dialogue_enabled"]
    danmu_adapter = current["danmu_adapter_enabled"]

    if "dialogue_enabled" in patch and patch["dialogue_enabled"] is not None:
        dialogue = bool(patch["dialogue_enabled"])
    if "danmu_adapter_enabled" in patch and patch["danmu_adapter_enabled"] is not None:
        danmu_adapter = bool(patch["danmu_adapter_enabled"])

    if patch.get("dialogue_enabled") is True:
        dialogue = True
        danmu_adapter = False
    elif patch.get("danmu_adapter_enabled") is True:
        danmu_adapter = True
        dialogue = False

    if dialogue and danmu_adapter:
        raise ValueError("virtual_host_modes_mutually_exclusive")

    setter = getattr(config, "set_batch", None)
    if not callable(setter):
        raise RuntimeError("config store unavailable")
    setter(
        {
            DIALOGUE_ENABLED_KEY: _write_bool(dialogue),
            DANMU_ADAPTER_ENABLED_KEY: _write_bool(danmu_adapter),
        }
    )
    return export_virtual_host_mode_settings(config)


__all__ = [
    "ALLOWED_PATCH_KEYS",
    "DANMU_ADAPTER_ENABLED_KEY",
    "DEFAULT_DANMU_ADAPTER_ENABLED",
    "DEFAULT_DIALOGUE_ENABLED",
    "DIALOGUE_ENABLED_KEY",
    "apply_virtual_host_mode_settings",
    "export_virtual_host_mode_settings",
    "sanitize_virtual_host_mode_settings",
]
