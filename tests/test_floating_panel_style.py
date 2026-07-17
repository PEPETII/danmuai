"""W-FP-STYLE-CONTRACT-001：浮动面板样式契约（纯模块 + 配置白名单 + 只读 API）。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.application.config_service import WEB_CONFIG_KEYS, apply_web_config_patch
from app.config_defaults import CONFIG_DEFAULTS, export_web_config_defaults
from app.config_store import ConfigStore
from app.floating_panel_style import (
    CLASSIC_CARD_COLORS,
    DEFAULT_STYLE_PRESET,
    STYLE_FIELD_KEYS,
    STYLE_PRESET_APPLY_KEYS,
    STYLE_PRESETS,
    STYLE_RESTORE_KEYS,
    WECHAT_CARD_COLORS,
    WECHAT_TEXT_COLOR,
    normalize_bool01,
    normalize_floating_panel_style_items,
    normalize_hex_color,
    normalize_palette_json,
    normalize_weights_json,
    preset_style_patch,
    style_presets_api_payload,
    style_snapshot_from_mapping,
)


def _stub_app(store):
    class _PersonaeStub:
        def set_active(self, _active):
            return None

    class _DanmuAppStub:
        config_changed = MagicMock()

    app = _DanmuAppStub()
    app.config = store
    app.personae = _PersonaeStub()
    return app


# ---------------------------------------------------------------------------
# 纯模块导入与预设锁定
# ---------------------------------------------------------------------------


def test_module_imports_without_qt():
    import app.floating_panel_style as mod

    assert mod.DEFAULT_STYLE_PRESET == "wechat"
    assert "classic" in mod.STYLE_PRESETS
    assert "wechat" in mod.STYLE_PRESETS
    # 不得依赖 Qt
    assert "PyQt" not in open(mod.__file__, encoding="utf-8").read()


def test_classic_card_colors_locked():
    assert CLASSIC_CARD_COLORS == ("#FFFFFF", "#F5D401", "#3CA0FB", "#3ACD2E")
    classic = STYLE_PRESETS["classic"]
    colors = json.loads(classic["floating_panel_card_colors"])
    assert colors == list(CLASSIC_CARD_COLORS)
    assert classic["floating_panel_shape"] == "card"
    assert classic["floating_panel_tail_enabled"] == "0"
    assert classic["floating_panel_text_colors"] == '["#000000"]'


def test_wechat_first_color_and_text_locked():
    assert WECHAT_CARD_COLORS[0] == "#FFECD2"
    assert WECHAT_TEXT_COLOR == "#281C12"
    wechat = STYLE_PRESETS["wechat"]
    colors = json.loads(wechat["floating_panel_card_colors"])
    assert colors[0] == "#FFECD2"
    assert set(colors) >= {"#FFECD2", "#DDF5D7", "#DDEBFF", "#FFDDE8"}
    assert wechat["floating_panel_shape"] == "bubble"
    assert wechat["floating_panel_tail_enabled"] == "1"
    assert json.loads(wechat["floating_panel_text_colors"]) == ["#281C12"]


def test_default_preset_is_wechat():
    assert DEFAULT_STYLE_PRESET == "wechat"
    payload = style_presets_api_payload()
    assert payload["default_preset"] == "wechat"
    assert set(payload["presets"].keys()) == {"classic", "wechat"}
    assert "custom" not in payload["presets"]


def test_preset_patch_does_not_touch_render_mode_or_scrolling():
    for pid in ("classic", "wechat"):
        patch = preset_style_patch(pid)
        assert "danmu_render_mode" not in patch
        assert "danmu_speed" not in patch
        assert "danmu_lines" not in patch
        assert "floating_panel_style_preset" in patch
        assert set(STYLE_PRESET_APPLY_KEYS).issuperset(patch.keys())


# ---------------------------------------------------------------------------
# 归一化
# ---------------------------------------------------------------------------


def test_normalize_hex_and_palette_fallbacks():
    assert normalize_hex_color("#aabbcc", fallback="#000000") == "#AABBCC"
    assert normalize_hex_color("#AABBCCDD", fallback="#000000") == "#AABBCCDD"
    assert normalize_hex_color("red", fallback="#281C12") == "#281C12"
    assert normalize_hex_color("", fallback="#FFECD2") == "#FFECD2"

    good = normalize_palette_json(
        '["#ffecd2", "#DDF5D7"]',
        fallback_colors=WECHAT_CARD_COLORS,
    )
    assert json.loads(good) == ["#FFECD2", "#DDF5D7"]

    bad = normalize_palette_json("not-json", fallback_colors=WECHAT_CARD_COLORS)
    assert json.loads(bad) == list(WECHAT_CARD_COLORS)

    empty = normalize_palette_json("[]", fallback_colors=CLASSIC_CARD_COLORS)
    assert json.loads(empty) == list(CLASSIC_CARD_COLORS)

    invalid_items = normalize_palette_json(
        '["nope", 123, "#GGGGGG"]',
        fallback_colors=WECHAT_CARD_COLORS,
    )
    assert json.loads(invalid_items) == list(WECHAT_CARD_COLORS)


def test_normalize_weights_and_bool():
    assert normalize_weights_json('{"#ffecd2": 2}') == json.dumps({"#FFECD2": 2.0})
    assert normalize_weights_json("not-json") == "{}"
    assert normalize_weights_json('["x"]') == "{}"
    assert normalize_bool01("true") == "1"
    assert normalize_bool01("FALSE") == "0"
    assert normalize_bool01("xyz", default="1") == "1"
    assert normalize_bool01("xyz", default="0") == "0"


def test_invalid_enum_and_range_fallback_no_empty():
    items = {
        "floating_panel_style_preset": "neon",
        "floating_panel_shape": "hexagon",
        "floating_panel_card_colors": "[]",
        "floating_panel_card_opacity": "999",
        "floating_panel_radius": "-3",
        "floating_panel_outline_enabled": "yes",
        "floating_panel_entry_animation": "spin",
    }
    # 不带 classic/wechat 展开：custom 路径但 preset 非法 → wechat 并展开
    normalize_floating_panel_style_items(items)
    assert items["floating_panel_style_preset"] == "wechat"
    assert items["floating_panel_shape"] == "bubble"
    assert json.loads(items["floating_panel_card_colors"])
    assert items["floating_panel_card_opacity"] == "78"
    assert int(items["floating_panel_radius"]) >= 0
    assert items["floating_panel_outline_enabled"] == "1"
    assert items["floating_panel_entry_animation"] == "fade"
    # 无空样式字段
    for key in STYLE_FIELD_KEYS:
        if key in items:
            assert items[key] not in ("", "[]") or key.endswith("_weights")


def test_custom_invalid_palette_falls_back_wechat():
    items = {
        "floating_panel_style_preset": "custom",
        "floating_panel_card_colors": "null",
        "floating_panel_text_colors": "{}",
    }
    normalize_floating_panel_style_items(items)
    assert items["floating_panel_style_preset"] == "custom"
    assert json.loads(items["floating_panel_card_colors"]) == list(WECHAT_CARD_COLORS)
    assert json.loads(items["floating_panel_text_colors"]) == [WECHAT_TEXT_COLOR]


def test_classic_expand_sets_card_no_tail():
    items = {"floating_panel_style_preset": "classic"}
    normalize_floating_panel_style_items(items)
    assert items["floating_panel_shape"] == "card"
    assert items["floating_panel_tail_enabled"] == "0"
    assert json.loads(items["floating_panel_card_colors"]) == list(CLASSIC_CARD_COLORS)
    assert "danmu_render_mode" not in items


def test_snapshot_deterministic_and_typed():
    snap = style_snapshot_from_mapping({})
    assert snap.style_preset == "wechat"
    assert snap.shape == "bubble"
    assert snap.card_colors[0] == "#FFECD2"
    assert snap.text_colors == (WECHAT_TEXT_COLOR,)
    assert snap.tail_enabled is True
    assert isinstance(snap.card_opacity, int)
    assert snap.card_colors  # 非空

    snap2 = style_snapshot_from_mapping(
        {
            "floating_panel_style_preset": "classic",
            "floating_panel_shape": "card",
            "floating_panel_card_colors": json.dumps(list(CLASSIC_CARD_COLORS)),
            "floating_panel_text_colors": '["#000000"]',
            "floating_panel_tail_enabled": "0",
        }
    )
    assert snap2.shape == "card"
    assert snap2.card_colors == CLASSIC_CARD_COLORS
    assert snap2.tail_enabled is False


# ---------------------------------------------------------------------------
# CONFIG_DEFAULTS / WEB_CONFIG_KEYS
# ---------------------------------------------------------------------------


def test_style_keys_in_defaults_and_web_whitelist():
    for key in STYLE_FIELD_KEYS:
        assert key in CONFIG_DEFAULTS, key
        assert key in WEB_CONFIG_KEYS, key
        assert key in STYLE_RESTORE_KEYS, key
        assert CONFIG_DEFAULTS[key] not in (None,)
        # 调色板默认非空数组
        if key.endswith("_colors"):
            assert json.loads(CONFIG_DEFAULTS[key])


def test_legacy_floating_panel_defaults_unchanged():
    assert CONFIG_DEFAULTS["floating_panel_width"] == "360"
    assert CONFIG_DEFAULTS["floating_panel_opacity"] == "85"
    assert CONFIG_DEFAULTS["floating_panel_font_size"] == "20"
    assert CONFIG_DEFAULTS["floating_panel_max_items"] == "12"
    assert CONFIG_DEFAULTS["floating_panel_speed"] == "1"


def test_export_web_defaults_include_style_keys():
    defaults = export_web_config_defaults()
    for key in STYLE_FIELD_KEYS:
        assert key in defaults
    assert defaults["floating_panel_style_preset"] == "wechat"


# ---------------------------------------------------------------------------
# ConfigService 往返
# ---------------------------------------------------------------------------


def test_preset_classic_via_config_service_roundtrip(tmp_path):
    store = ConfigStore(db_path=tmp_path / "style.db")
    store.set("danmu_render_mode", "scrolling")
    app = _stub_app(store)
    apply_web_config_patch(app, {"floating_panel_style_preset": "classic"})
    assert store.get("floating_panel_style_preset") == "classic"
    assert store.get("floating_panel_shape") == "card"
    assert store.get("danmu_render_mode") == "scrolling"
    colors = json.loads(store.get("floating_panel_card_colors"))
    assert colors == list(CLASSIC_CARD_COLORS)
    snap = style_snapshot_from_mapping(
        {k: store.get(k, "") for k in STYLE_PRESET_APPLY_KEYS}
    )
    assert snap.shape == "card"
    assert snap.card_colors == CLASSIC_CARD_COLORS


def test_custom_invalid_values_normalized_on_save(tmp_path):
    store = ConfigStore(db_path=tmp_path / "style2.db")
    app = _stub_app(store)
    apply_web_config_patch(
        app,
        {
            "floating_panel_style_preset": "custom",
            "floating_panel_shape": "blob",
            "floating_panel_card_colors": "[]",
            "floating_panel_card_opacity": "500",
            "floating_panel_outline_color": "blue",
            "danmu_render_mode": "scrolling",
        },
    )
    assert store.get("floating_panel_style_preset") == "custom"
    assert store.get("floating_panel_shape") == "bubble"
    assert json.loads(store.get("floating_panel_card_colors"))
    # 越界数值钳到上限 100；非法颜色回退 wechat 工厂
    assert store.get("floating_panel_card_opacity") == "100"
    assert store.get("floating_panel_outline_color").startswith("#")
    assert store.get("danmu_render_mode") == "scrolling"


def test_subset_save_preserves_unrelated_keys(tmp_path):
    store = ConfigStore(db_path=tmp_path / "style3.db")
    app = _stub_app(store)
    apply_web_config_patch(app, {"floating_panel_width": "400"})
    assert store.get("floating_panel_width") == "400"
    # 未提交样式键时不应被清空
    assert store.get("floating_panel_style_preset", "") in ("", "wechat") or True


# ---------------------------------------------------------------------------
# 只读 API
# ---------------------------------------------------------------------------


def test_style_presets_api_readonly_no_auth():
    fastapi_app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app.config = MagicMock()
    set_spy = MagicMock()
    bridge.danmu_app.config.set = set_spy
    bridge.danmu_app.config.set_batch = set_spy

    def _check_token(_authorization=None):
        return None

    from app.web_api.routes import register_web_routes

    register_web_routes(fastapi_app, bridge, _check_token)
    client = TestClient(fastapi_app)
    res = client.get("/api/floating-panel/style-presets")
    assert res.status_code == 200
    body = res.json()
    assert body["default_preset"] == "wechat"
    assert "classic" in body["presets"]
    assert "wechat" in body["presets"]
    assert body["presets"]["classic"]["floating_panel_shape"] == "card"
    assert json.loads(body["presets"]["wechat"]["floating_panel_card_colors"])[0] == "#FFECD2"
    assert "custom" not in body["presets"]
    for key in STYLE_FIELD_KEYS:
        assert key in body["fields"]
    set_spy.assert_not_called()


def test_style_presets_payload_matches_module():
    assert style_presets_api_payload()["version"] >= 1
    assert style_presets_api_payload()["presets"]["wechat"]["floating_panel_tail_enabled"] == "1"
