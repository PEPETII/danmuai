"""W-PET-LAZY-INIT-VISIBILITY-001: pet lazy init on cold start and Web save."""

from unittest.mock import MagicMock

from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig


def _bind_pet_lifecycle_methods(app: DanmuApp) -> None:
    app._ensure_pet_components = DanmuApp._ensure_pet_components.__get__(app, DanmuApp)
    app._sync_pet_window_visibility = DanmuApp._sync_pet_window_visibility.__get__(app, DanmuApp)


def test_sync_pet_window_visibility_ensures_when_enabled_visible(qapp):
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig(
            {
                "pet_enabled": "1",
                "pet_visible": "1",
                "pet_asset_source": "builtin",
            }
        ),
    )
    _bind_pet_lifecycle_methods(app)

    assert app.__dict__.get("pet_window") is None

    app._sync_pet_window_visibility()

    assert app.__dict__.get("pet_window") is not None
    assert app.pet_window.isVisible()


def test_sync_pet_window_visibility_skips_ensure_when_disabled(qapp):
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig({"pet_enabled": "0", "pet_visible": "1"}),
    )
    _bind_pet_lifecycle_methods(app)
    ensure_calls = {"n": 0}
    original_ensure = app._ensure_pet_components

    def counting_ensure():
        ensure_calls["n"] += 1
        return original_ensure()

    app._ensure_pet_components = counting_ensure

    app._sync_pet_window_visibility()

    assert ensure_calls["n"] == 0
    assert app.__dict__.get("pet_window") is None


def test_sync_pet_window_visibility_skips_ensure_when_not_visible(qapp):
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig({"pet_enabled": "1", "pet_visible": "0"}),
    )
    _bind_pet_lifecycle_methods(app)
    ensure_calls = {"n": 0}
    original_ensure = app._ensure_pet_components

    def counting_ensure():
        ensure_calls["n"] += 1
        return original_ensure()

    app._ensure_pet_components = counting_ensure

    app._sync_pet_window_visibility()

    assert ensure_calls["n"] == 0
    assert app.__dict__.get("pet_window") is None


def test_apply_pet_settings_patch_ensures_on_enable(qapp):
    from app.pet.pet_facade import apply_pet_settings_patch

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig(
            {
                "pet_enabled": "0",
                "pet_visible": "0",
                "pet_asset_source": "builtin",
            }
        ),
    )
    app.config_changed = MagicMock()
    _bind_pet_lifecycle_methods(app)

    assert app.__dict__.get("pet_window") is None

    apply_pet_settings_patch(app, {"pet_enabled": True})

    assert app.config.get("pet_enabled") == "1"
    assert app.config.get("pet_visible") == "1"
    assert app.__dict__.get("pet_window") is not None
    assert app.pet_window.isVisible()


def test_facade_sync_noop_without_ensure_helper():
    from app.pet.pet_facade import sync_pet_window_visibility

    app = type("StubApp", (), {})()
    app.config = FakeConfig({"pet_enabled": "1", "pet_visible": "1"})
    sync_pet_window_visibility(app)


def test_startup_sync_guard_calls_visibility_when_enabled_visible(qapp, monkeypatch):
    """_init_startup_services 在 enabled+visible 时走 _sync_pet_window_visibility。"""
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig(
            {
                "pet_enabled": "1",
                "pet_visible": "1",
                "pet_asset_source": "builtin",
            }
        ),
    )
    _bind_pet_lifecycle_methods(app)
    sync_calls = {"n": 0}
    original_sync = app._sync_pet_window_visibility

    def counting_sync():
        sync_calls["n"] += 1
        return original_sync()

    app._sync_pet_window_visibility = counting_sync

    if (
        app.config.get("pet_enabled", "0") == "1"
        and app.config.get("pet_visible", "0") == "1"
    ):
        app._sync_pet_window_visibility()

    assert sync_calls["n"] == 1
    assert app.__dict__.get("pet_window") is not None


def test_startup_sync_guard_skips_when_disabled(qapp):
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig({"pet_enabled": "0", "pet_visible": "0"}),
    )
    _bind_pet_lifecycle_methods(app)
    sync_calls = {"n": 0}

    def counting_sync():
        sync_calls["n"] += 1

    app._sync_pet_window_visibility = counting_sync

    if (
        app.config.get("pet_enabled", "0") == "1"
        and app.config.get("pet_visible", "0") == "1"
    ):
        app._sync_pet_window_visibility()

    assert sync_calls["n"] == 0
    assert app.__dict__.get("pet_window") is None
