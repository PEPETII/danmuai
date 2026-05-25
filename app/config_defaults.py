"""Default config values for export and first-run seeding."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.personae import (
    DEFAULT_NORMAL_REPLY_COUNT,
    DEFAULT_REPLY_FILLER_COUNT,
    DEFAULT_REPLY_SCENE_COUNT,
)
from app.scene_fingerprint import DEFAULT_SCENE_PROBE_SIZE

if TYPE_CHECKING:
    from app.config_store import ConfigStore

# Numeric fallbacks when a key is missing from the store (keep in sync with CONFIG_DEFAULTS).
DEFAULT_DANMU_SPEED = 2.0
DEFAULT_FONT_SIZE = 24
DEFAULT_DEDUP_THRESHOLD = 0.5
DEFAULT_IMAGE_MAX_WIDTH = 768

# String values aligned with runtime fallbacks in main.py / danmu_engine / ai_client.
CONFIG_DEFAULTS: dict[str, str] = {
    "api_mode": "doubao",
    "temperature": "0.7",
    "max_tokens": "512",
    "screenshot_interval": "3",
    "danmu_speed": "2",
    "danmu_lines": "20",
    "danmu_max_chars": "15",
    "dedup_threshold": "0.5",
    "screen_index": "0",
    "layout_mode": "fullscreen",
    "opacity": "100",
    "font_size": "24",
    "freq_mode": "auto",
    "capture_mode": "continuous",
    "danmu_pool_enabled": "1",
    "min_on_screen": "5",
    "freshness": "medium",
    "drop_stale": "1",
    "empty_accel": "1",
    "eviction_mode": "natural",
    "image_max_width": "768",
    "image_quality": "85",
    "scene_probe_size": str(DEFAULT_SCENE_PROBE_SIZE),
    "hotkey": "Ctrl+Shift+B",
    "memory_mode": "off",
    "memory_window": "10",
    "memory_clear_policy": "medium",
    "mic_mode_enabled": "0",
    "mic_window_sec": "5",
    "reply_scene_count": str(DEFAULT_REPLY_SCENE_COUNT),
    "reply_filler_count": str(DEFAULT_REPLY_FILLER_COUNT),
    "danmu_display_mode": "realtime",
    "normal_recognition_interval_sec": "5",
    "normal_reply_count": str(DEFAULT_NORMAL_REPLY_COUNT),
}


def config_value_with_default(config, key: str) -> str:
    """Return stored value or documented default (for API export / UI)."""
    val = config.get(key, "")
    if val != "":
        return val
    return CONFIG_DEFAULTS.get(key, "")


def seed_config_defaults(config: "ConfigStore") -> None:
    """Persist defaults for keys that are missing or blank."""
    items = {
        key: default
        for key, default in CONFIG_DEFAULTS.items()
        if not config.get(key, "")
    }
    if items:
        config.set_batch(items)
