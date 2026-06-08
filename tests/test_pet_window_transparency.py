"""PET-014: PetWindow geometry and transparency contracts."""

from app.pet.pet_assets import PET_FRAME_H, PET_FRAME_W
from app.pet.pet_window import (
    _COMMAND_BAND_HEIGHT,
    command_band_height,
    sprite_y_offset,
)
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig


def test_command_band_height_hidden_vs_visible():
    assert command_band_height(False) == 0
    assert command_band_height(True) == _COMMAND_BAND_HEIGHT


def test_sprite_y_offset_matches_command_band():
    assert sprite_y_offset(False) == 0
    assert sprite_y_offset(True) == _COMMAND_BAND_HEIGHT


def test_pet_window_height_fits_sprite_when_command_hidden(qapp):
    from app.pet.pet_window import PetWindow

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=FakeConfig({"pet_asset_source": "builtin", "pet_scale": "1.0"}))
    window = PetWindow(app)
    expected_h = int(PET_FRAME_H * 1.0)
    assert window.height() == expected_h
    assert window.width() == int(PET_FRAME_W * 1.0)


def test_pet_window_height_expands_when_command_visible(qapp):
    from app.pet.pet_window import PetWindow

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=FakeConfig({"pet_asset_source": "builtin", "pet_scale": "1.0"}))
    window = PetWindow(app)
    window._show_command_box()
    expected_h = int(PET_FRAME_H * 1.0) + _COMMAND_BAND_HEIGHT
    assert window.height() == expected_h


def test_pet_window_shrinks_after_command_hidden(qapp):
    from app.pet.pet_window import PetWindow

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=FakeConfig({"pet_asset_source": "builtin", "pet_scale": "1.0"}))
    window = PetWindow(app)
    window._show_command_box()
    window._hide_command_box()
    assert window.height() == int(PET_FRAME_H * 1.0)
