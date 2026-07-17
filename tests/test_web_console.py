"""Web 控制台配置：danmu_render_mode 与悬浮窗 V2 键。"""
from __future__ import annotations

from unittest.mock import MagicMock

from app.application.config_service import WEB_CONFIG_KEYS, apply_web_config_patch
from app.config_defaults import (
    CONFIG_DEFAULTS,
    export_web_config_defaults,
    resolve_danmu_render_mode,
)
from app.config_store import ConfigStore


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


def test_danmu_render_mode_in_web_config_keys():
    assert "danmu_render_mode" in WEB_CONFIG_KEYS
    assert "display_mode" not in WEB_CONFIG_KEYS


def test_danmu_render_mode_defaults_exported():
    defaults = export_web_config_defaults()
    assert defaults["danmu_render_mode"] == "scrolling"
    assert defaults["floating_panel_width"] == "360"


def test_danmu_render_mode_persists_via_config_service(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    app = _stub_app(store)
    apply_web_config_patch(app, {"danmu_render_mode": "floating_panel"})
    assert store.get("danmu_render_mode") == "floating_panel"


def test_danmu_render_mode_invalid_falls_back_to_scrolling(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    app = _stub_app(store)
    apply_web_config_patch(app, {"danmu_render_mode": "both"})
    assert store.get("danmu_render_mode") == "scrolling"


def test_legacy_display_mode_migrates_when_render_mode_blank(tmp_path):
    import sqlite3

    db = tmp_path / "legacy_fp.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO config (key, value) VALUES ('display_mode', 'floating_panel')")
    conn.commit()
    conn.close()
    store = ConfigStore(db_path=db)
    assert store.get("danmu_render_mode") == "floating_panel"
    assert resolve_danmu_render_mode(store) == "floating_panel"


def test_legacy_both_migrates_to_scrolling(tmp_path):
    import sqlite3

    db = tmp_path / "legacy_both.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("INSERT INTO config (key, value) VALUES ('display_mode', 'both')")
    conn.commit()
    conn.close()
    store = ConfigStore(db_path=db)
    assert store.get("danmu_render_mode") == "scrolling"
    assert resolve_danmu_render_mode(store) == "scrolling"


def test_resolve_danmu_render_mode_does_not_read_display_mode(tmp_path):
    store = ConfigStore(db_path=tmp_path / "no_fallback.db")
    store.set("display_mode", "floating_panel")
    store.set("danmu_render_mode", "")
    assert resolve_danmu_render_mode(store) == "scrolling"


def test_floating_panel_v2_keys_round_trip(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    app = _stub_app(store)
    payload = {
        "floating_panel_width": "400",
        "floating_panel_max_items": "8",
        "floating_panel_x_offset": "30",
        "floating_panel_y_offset": "60",
        "floating_panel_opacity": "90",
        "floating_panel_font_size": "22",
    }
    apply_web_config_patch(app, payload)
    for key, expected in payload.items():
        assert store.get(key) == expected


def test_config_defaults_include_v2_keys():
    assert "display_mode" not in CONFIG_DEFAULTS
    for key in (
        "danmu_render_mode",
        "floating_panel_width",
    ):
        assert key in CONFIG_DEFAULTS
    assert "display_mode" not in CONFIG_DEFAULTS
    assert "bililive_dm_mode_enabled" not in CONFIG_DEFAULTS
    assert "bililive_dm_mode_enabled" not in WEB_CONFIG_KEYS
