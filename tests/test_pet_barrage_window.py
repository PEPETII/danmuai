from app.pet.pet_window import PetWindow
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig


def test_pet_window_only_slot_zero_supports_command_box(qapp):
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=FakeConfig(
            {
            "pet_asset_source": "builtin",
            "pet_command_box_enabled": "1",
            }
        ),
    )

    primary = PetWindow(app, slot_id=0)
    secondary = PetWindow(app, slot_id=1)

    assert primary.supports_command_box() is True
    assert secondary.supports_command_box() is False
    primary.close()
    secondary.close()
