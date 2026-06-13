"""W-TEST-COVER-010: parameterized config key round-trip via ConfigService."""

from __future__ import annotations

import pytest
from app.application.config_service import WEB_CONFIG_KEYS, apply_web_config_patch
from app.config_store import ConfigStore

from tests.helpers.config_payload import make_config_app_stub

# Keys covered elsewhere in dedicated tests (reference only).
_COVERED_ELSEWHERE = frozenset(
    {
        "user_nickname",
        "live_topic",
        "danmu_render_mode",
        "floating_panel_width",
        "floating_panel_max_items",
        "floating_panel_lifetime_sec",
        "floating_panel_x_offset",
        "floating_panel_y_offset",
        "floating_panel_opacity",
        "floating_panel_font_size",
        "floating_panel_speed",
        "danmu_font_family",
        "danmu_font_bold",
        "font_size",
    }
)

_ROUND_TRIP_CASES = [
    ("temperature", "0.9", "0.9"),
    ("max_tokens", "600", "600"),
    ("danmu_lines", "12", "12"),
    ("danmu_max_chars", "20", "20"),
    ("dedup_threshold", "0.7", "0.7"),
    ("screen_index", "1", "1"),
    ("layout_mode", "1/2", "1/2"),
    ("opacity", "80", "80"),
    ("empty_accel", "0", "0"),
    ("eviction_mode", "accelerate", "accelerate"),
    ("danmu_pending_entry_cap", "100", "100"),
    ("danmu_track_retention_cap", "50", "50"),
    ("reply_queue_max_items", "4", "4"),
    ("image_max_width", "640", "640"),
    ("image_quality", "75", "75"),
    ("hotkey", "Ctrl+Alt+B", "Ctrl+Alt+B"),
    ("mic_mode_enabled", "1", "1"),
    ("mic_window_sec", "8", "8"),
    ("normal_recognition_interval_sec", "10", "10"),
    ("normal_reply_count", "6", "6"),
    ("floating_panel_font_family", "SimHei", "SimHei"),
    ("floating_panel_font_bold", "1", "1"),
    ("pet_enabled", "1", "1"),
    ("pet_visible", "1", "1"),
    ("pet_asset_source", "builtin", "builtin"),
    ("pet_scale", "1.0", "1.0"),
    ("pet_opacity", "0.8", "0.8"),
    ("pet_always_on_top", "1", "1"),
    ("pet_click_through", "0", "0"),
    ("pet_command_box_enabled", "1", "1"),
    ("pet_command_ttl_sec", "60", "60"),
    ("pet_command_apply_count", "2", "2"),
    ("danmu_speed", "0", "0.5"),
]


@pytest.mark.parametrize("key,write_value,expected", _ROUND_TRIP_CASES)
def test_config_key_round_trip(tmp_path, key, write_value, expected):
    assert key in WEB_CONFIG_KEYS
    assert key not in _COVERED_ELSEWHERE or key == "danmu_speed"
    store = ConfigStore(tmp_path / f"rt_{key}.db")
    app = make_config_app_stub(store)
    apply_web_config_patch(app, {key: write_value})
    assert store.get(key) == expected
    store2 = ConfigStore(tmp_path / f"rt_{key}.db")
    assert store2.get(key) == expected
    store2.close()
