from pathlib import Path

import pytest

from app.bundle_paths import resource_path
from app.pet.pet_assets import BUILTIN_PET_DIR, load_pet_assets, validate_pet_pack_dir
from tests.fakes import FakeConfig


def test_builtin_pet_pack_loads(qapp):
    pack = load_pet_assets(FakeConfig({"pet_asset_source": "builtin"}))
    assert pack.pet_id == "yuexin-miao-animated"
    assert pack.spritesheet_path.is_file()


def test_validate_pet_pack_dir_missing_json():
    with pytest.raises(ValueError, match="pet.json"):
        validate_pet_pack_dir(Path("/nonexistent/pet-pack"))


def test_validate_builtin_dimensions(qapp):
    meta, sheet, cols, rows = validate_pet_pack_dir(BUILTIN_PET_DIR)
    assert meta["id"] == "yuexin-miao-animated"
    assert sheet.name.endswith(".webp")
    assert cols >= 1 and rows >= 1


def test_local_pack_path_from_config(qapp):
    pack = load_pet_assets(
        FakeConfig(
            {
                "pet_asset_source": "local",
                "pet_asset_path": str(BUILTIN_PET_DIR),
            }
        )
    )
    assert pack.root_dir == BUILTIN_PET_DIR


def test_resource_path_pet_default_exists():
    assert resource_path("data", "pet", "default", "pet.json").is_file()
