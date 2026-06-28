"""W-BILILIVE-DM-PLUGIN-MODE-005 — bililive_dm_mode_enabled 屏幕显示层 gate 测试。"""

from __future__ import annotations

from app.config_store import ConfigStore
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app


def _display_app(store: ConfigStore) -> DanmuApp:
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=store)
    app._overlay_display_enabled = DanmuApp._overlay_display_enabled.__get__(app, DanmuApp)
    app._floating_panel_v2_enabled = DanmuApp._floating_panel_v2_enabled.__get__(app, DanmuApp)
    app._bililive_dm_mode_enabled = DanmuApp._bililive_dm_mode_enabled.__get__(app, DanmuApp)
    app._danmu_render_mode = DanmuApp._danmu_render_mode.__get__(app, DanmuApp)
    return app


def test_bililive_dm_mode_disables_screen_layers_when_scrolling(tmp_path):
    store = ConfigStore(db_path=tmp_path / "bililive_dm_scrolling.db")
    store.set("danmu_render_mode", "scrolling")
    store.set("bililive_dm_mode_enabled", "1")
    app = _display_app(store)

    assert app._overlay_display_enabled() is False
    assert app._floating_panel_v2_enabled() is False
    store.close()


def test_bililive_dm_mode_disables_screen_layers_when_floating_panel(tmp_path):
    store = ConfigStore(db_path=tmp_path / "bililive_dm_fp.db")
    store.set("danmu_render_mode", "floating_panel")
    store.set("bililive_dm_mode_enabled", "1")
    app = _display_app(store)

    assert app._overlay_display_enabled() is False
    assert app._floating_panel_v2_enabled() is False
    store.close()


def test_bililive_dm_mode_off_restores_render_mode_behavior(tmp_path):
    store = ConfigStore(db_path=tmp_path / "bililive_dm_off.db")
    store.set("bililive_dm_mode_enabled", "0")

    store.set("danmu_render_mode", "scrolling")
    app = _display_app(store)
    assert app._overlay_display_enabled() is True
    assert app._floating_panel_v2_enabled() is False

    store.set("danmu_render_mode", "floating_panel")
    app = _display_app(store)
    assert app._overlay_display_enabled() is False
    assert app._floating_panel_v2_enabled() is True
    store.close()


def test_bililive_dm_mode_does_not_change_stored_render_mode(tmp_path):
    store = ConfigStore(db_path=tmp_path / "bililive_dm_preserve.db")
    store.set("danmu_render_mode", "floating_panel")
    store.set("bililive_dm_mode_enabled", "1")
    _display_app(store)

    assert store.get("danmu_render_mode") == "floating_panel"
    store.close()
