from unittest.mock import MagicMock

import app.pet.pet_facade as pet_facade

from tests.fakes import FakeConfig


def _make_pet_app(config_values):
    app = type("StubApp", (), {})()
    app.config = FakeConfig(config_values)
    app.config_changed = MagicMock()
    return app


class _FakeWindow:
    def __init__(self):
        self.show_calls = 0
        self.hide_calls = 0

    def show_pet(self):
        self.show_calls += 1

    def hide_pet(self):
        self.hide_calls += 1

    def apply_config(self):
        pass


class _FakeBarrage:
    def __init__(self):
        self.show_calls = 0
        self.hide_calls = 0
        self.apply_config_calls = 0

    def apply_config(self):
        self.apply_config_calls += 1

    def sync_slots_to_config(self, *, slots=None, positions=None):
        pass

    def show(self):
        self.show_calls += 1

    def hide(self):
        self.hide_calls += 1


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


def test_show_pet_disables_barrage_and_restores_render_state(monkeypatch):
    monkeypatch.setattr(
        pet_facade,
        "get_pet_settings_snapshot",
        lambda _app: {"ok": True},
    )
    app = _make_pet_app(
        {
            "pet_enabled": "1",
            "pet_visible": "0",
            "pet_asset_source": "builtin",
            "danmu_render_mode": "scrolling",
            "normal_reply_count": "5",
            "pet_barrage_mode_enabled": "1",
            "pet_barrage_previous_render_mode": "floating_panel",
            "pet_barrage_previous_reply_count": "9",
        }
    )
    window = _FakeWindow()
    barrage = _FakeBarrage()
    app.__dict__["pet_window"] = window
    app.__dict__["pet_barrage_controller"] = barrage

    result = pet_facade.show_pet(app)

    assert result == {"ok": True, "visible": True}
    assert app.config.get("pet_enabled") == "1"
    assert app.config.get("pet_visible") == "1"
    assert app.config.get("pet_barrage_mode_enabled") == "0"
    assert app.config.get("danmu_render_mode") == "floating_panel"
    assert app.config.get("normal_reply_count") == "9"
    assert window.show_calls == 1
    assert window.hide_calls == 0
    assert barrage.hide_calls == 1
    assert barrage.show_calls == 0
    app.config_changed.emit.assert_called_once()


def test_sync_pet_window_visibility_normal_mode_shows_window_hides_barrage():
    app = _make_pet_app(
        {
            "pet_enabled": "1",
            "pet_visible": "1",
            "pet_asset_source": "builtin",
            "pet_barrage_mode_enabled": "0",
        }
    )
    window = _FakeWindow()
    barrage = _FakeBarrage()
    app.__dict__["pet_window"] = window
    app.__dict__["pet_barrage_controller"] = barrage

    pet_facade.sync_pet_window_visibility(app)

    assert window.show_calls == 1
    assert window.hide_calls == 0
    assert barrage.hide_calls == 1
    assert barrage.show_calls == 0


def test_sync_pet_window_visibility_barrage_mode_hides_window_shows_barrage():
    app = _make_pet_app(
        {
            "pet_enabled": "1",
            "pet_visible": "1",
            "pet_asset_source": "builtin",
            "pet_barrage_mode_enabled": "1",
        }
    )
    window = _FakeWindow()
    barrage = _FakeBarrage()
    app.__dict__["pet_window"] = window
    app.__dict__["pet_barrage_controller"] = barrage

    pet_facade.sync_pet_window_visibility(app)

    assert window.show_calls == 0
    assert window.hide_calls == 1
    assert barrage.hide_calls == 0
    assert barrage.show_calls == 1


def test_sync_pet_window_visibility_disabled_hides_both():
    app = _make_pet_app(
        {
            "pet_enabled": "0",
            "pet_visible": "1",
            "pet_asset_source": "builtin",
            "pet_barrage_mode_enabled": "1",
        }
    )
    window = _FakeWindow()
    barrage = _FakeBarrage()
    app.__dict__["pet_window"] = window
    app.__dict__["pet_barrage_controller"] = barrage

    pet_facade.sync_pet_window_visibility(app)

    assert window.show_calls == 0
    assert window.hide_calls == 1
    assert barrage.hide_calls == 1
    assert barrage.show_calls == 0


def test_apply_pet_settings_patch_disable_barrage_shows_normal_window(monkeypatch):
    monkeypatch.setattr(
        pet_facade,
        "get_pet_settings_snapshot",
        lambda _app: {"ok": True},
    )
    app = _make_pet_app(
        {
            "pet_enabled": "1",
            "pet_visible": "1",
            "pet_asset_source": "builtin",
            "pet_barrage_mode_enabled": "1",
            "pet_barrage_previous_render_mode": "floating_panel",
            "pet_barrage_previous_reply_count": "9",
            "danmu_render_mode": "scrolling",
            "normal_reply_count": "5",
        }
    )
    window = _FakeWindow()
    barrage = _FakeBarrage()
    app.__dict__["pet_window"] = window
    app.__dict__["pet_barrage_controller"] = barrage

    pet_facade.apply_pet_settings_patch(app, {"pet_barrage_mode_enabled": False})

    assert app.config.get("pet_barrage_mode_enabled") == "0"
    assert window.show_calls == 1
    assert window.hide_calls == 0
    assert barrage.hide_calls == 1
    assert barrage.show_calls == 0


def test_barrage_show_when_disabled_does_not_call_hide_pet():
    """W-BUG-E02: barrage 未启用时调用 show() 不触发任何 hide_pet()。"""
    from app.pet.pet_barrage import PetBarrageController

    app = _make_pet_app(
        {
            "pet_enabled": "1",
            "pet_visible": "1",
            "pet_barrage_mode_enabled": "0",
        }
    )
    window = _FakeWindow()
    ctrl = PetBarrageController(app)
    ctrl.attach_windows([window])

    ctrl.show()

    assert window.hide_calls == 0
    assert window.show_calls == 0
