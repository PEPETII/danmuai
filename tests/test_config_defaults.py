from app.application.config_service import (
    WEB_CONFIG_KEYS,
    _clamp_choice,
    _clamp_int_key,
)
from app.config_defaults import (
    CONFIG_DEFAULTS,
    DEFAULT_LANGUAGE,
    seed_config_defaults,
)
from app.config_store import ConfigStore


def test_seed_includes_language_field_when_added(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("language", "")

    seed_config_defaults(store)

    assert store.get("language") == DEFAULT_LANGUAGE
    store.close()


# W-FP-V2-001：danmu_render_mode 与侧边悬浮窗配置字段
FP_KEYS = (
    "danmu_render_mode",
    "floating_panel_width",
    "floating_panel_max_items",
    "floating_panel_lifetime_sec",
    "floating_panel_x_offset",
    "floating_panel_y_offset",
    "floating_panel_opacity",
    "floating_panel_font_size",
)


def test_fp_keys_present_in_defaults():
    """W-FP-V2-001 字段在 CONFIG_DEFAULTS 中均有默认值。"""
    assert "display_mode" not in CONFIG_DEFAULTS
    for key in FP_KEYS:
        assert key in CONFIG_DEFAULTS, f"missing default for {key}"
        assert CONFIG_DEFAULTS[key] != ""


def test_fp_keys_present_in_web_config_keys():
    """W-FP-V2-001 字段在 WEB_CONFIG_KEYS 元组中可被 Web 端读写。"""
    for key in FP_KEYS:
        assert key in WEB_CONFIG_KEYS, f"missing web key for {key}"


def test_seed_writes_fp_defaults_on_blank_db(tmp_path):
    """空 DB seed 后 V2 键均落库为默认值。"""
    store = ConfigStore(db_path=tmp_path / "config.db")
    for key in FP_KEYS:
        store.set(key, "")
    seed_config_defaults(store)
    for key in FP_KEYS:
        assert store.get(key) == CONFIG_DEFAULTS[key], key
    store.close()


def test_danmu_render_mode_invalid_falls_back_to_scrolling():
    items = {"danmu_render_mode": "weird-mode"}
    _clamp_choice(items, "danmu_render_mode", ("scrolling", "floating_panel"), "scrolling")
    assert items["danmu_render_mode"] == "scrolling"


def test_floating_panel_max_items_clamped():
    """floating_panel_max_items=9999 被钳到 50。"""
    items = {"floating_panel_max_items": "9999"}
    _clamp_int_key(items, "floating_panel_max_items", 12, 1, 50)
    assert items["floating_panel_max_items"] == "50"


def test_floating_panel_font_size_clamped_min():
    items = {"floating_panel_font_size": "1"}
    _clamp_int_key(items, "floating_panel_font_size", 20, 12, 48)
    assert items["floating_panel_font_size"] == "12"


def test_floating_panel_opacity_zero_allowed():
    items = {"floating_panel_opacity": "0"}
    _clamp_int_key(items, "floating_panel_opacity", 85, 0, 100)
    assert items["floating_panel_opacity"] == "0"


# W-FONT-001：字体设置字段
FONT_KEYS = (
    "danmu_font_family",
    "danmu_font_bold",
    "floating_panel_font_family",
    "floating_panel_font_bold",
)


def test_font_keys_present_in_defaults():
    for key in FONT_KEYS:
        assert key in CONFIG_DEFAULTS, f"missing default for {key}"
        assert CONFIG_DEFAULTS[key] != ""


def test_font_keys_present_in_web_config_keys():
    for key in FONT_KEYS:
        assert key in WEB_CONFIG_KEYS, f"missing web key for {key}"


def test_seed_writes_font_defaults_on_blank_db(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    for key in FONT_KEYS:
        store.set(key, "")
    seed_config_defaults(store)
    for key in FONT_KEYS:
        assert store.get(key) == CONFIG_DEFAULTS[key], key
    store.close()


def test_font_size_clamps_to_72():
    items = {"font_size": "9999"}
    _clamp_int_key(items, "font_size", 24, 12, 72)
    assert items["font_size"] == "72"


def test_imported_fonts_default_is_empty_list():
    import json

    assert CONFIG_DEFAULTS["imported_fonts"] == "[]"
    assert json.loads(CONFIG_DEFAULTS["imported_fonts"]) == []
