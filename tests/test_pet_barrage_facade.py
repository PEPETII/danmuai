from unittest.mock import MagicMock

import app.pet.pet_facade as pet_facade

from tests.fakes import FakeConfig


def _make_pet_app(config_values):
    app = type("StubApp", (), {})()
    app.config = FakeConfig(config_values)
    app.config_changed = MagicMock()
    return app


def _stub_pet_facade_runtime(monkeypatch):
    monkeypatch.setattr(
        pet_facade,
        "get_pet_settings_snapshot",
        lambda _app: {"ok": True},
    )
    monkeypatch.setattr(pet_facade, "sync_pet_window_visibility", lambda _app: None)


def test_apply_pet_settings_patch_enabling_pet_barrage_saves_previous_render_state(monkeypatch):
    _stub_pet_facade_runtime(monkeypatch)
    app = _make_pet_app(
        {
            "pet_enabled": "1",
            "pet_visible": "1",
            "pet_asset_source": "builtin",
            "danmu_render_mode": "floating_panel",
            "normal_reply_count": "9",
            "pet_barrage_mode_enabled": "0",
        }
    )

    pet_facade.apply_pet_settings_patch(app, {"pet_barrage_mode_enabled": True})

    assert app.config.get("pet_barrage_mode_enabled") == "1"
    assert app.config.get("pet_barrage_previous_render_mode") == "floating_panel"
    assert app.config.get("pet_barrage_previous_reply_count") == "9"
    assert app.config.get("normal_reply_count") == "5"


def test_apply_pet_settings_patch_disabling_pet_barrage_restores_previous_render_state(monkeypatch):
    _stub_pet_facade_runtime(monkeypatch)
    app = _make_pet_app(
        {
            "pet_enabled": "1",
            "pet_visible": "1",
            "pet_asset_source": "builtin",
            "danmu_render_mode": "scrolling",
            "normal_reply_count": "5",
            "pet_barrage_mode_enabled": "1",
            "pet_barrage_previous_render_mode": "floating_panel",
            "pet_barrage_previous_reply_count": "9",
        }
    )

    pet_facade.apply_pet_settings_patch(app, {"pet_barrage_mode_enabled": False})

    assert app.config.get("pet_barrage_mode_enabled") == "0"
    assert app.config.get("danmu_render_mode") == "floating_panel"
    assert app.config.get("normal_reply_count") == "9"
