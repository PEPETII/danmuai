from app.application.config_service import WEB_CONFIG_KEYS
from app.config_defaults import CONFIG_DEFAULTS
from app.persona_contract import DEFAULT_NORMAL_REPLY_COUNT

PET_BARRAGE_DEFAULTS = {
    "pet_barrage_mode_enabled": "0",
    "pet_barrage_count": "5",
    "pet_barrage_slots": "[]",
    "pet_barrage_slot_positions": "[]",
    "pet_barrage_previous_render_mode": "scrolling",
    "pet_barrage_previous_reply_count": str(DEFAULT_NORMAL_REPLY_COUNT),
}


def test_pet_barrage_defaults_present():
    for key, expected in PET_BARRAGE_DEFAULTS.items():
        assert CONFIG_DEFAULTS.get(key) == expected


def test_pet_barrage_keys_present_in_web_config_keys():
    for key in PET_BARRAGE_DEFAULTS:
        assert key in WEB_CONFIG_KEYS
