"""Regression for BUG-003: PetWindow.hide_pet() must stop the animation timer."""

from main import DanmuApp
from app.pet.pet_window import PetWindow

from tests.conftest import bind_minimal_danmu_app


def test_hide_pet_stops_anim_timer(qapp):
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app)
    pet = PetWindow(app)

    pet._anim_timer.start()
    assert pet._anim_timer.isActive()

    pet.hide_pet()

    assert not pet._anim_timer.isActive()
    assert not pet.isVisible()
