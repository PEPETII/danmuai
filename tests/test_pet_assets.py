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


def test_sync_pet_window_visibility_shows_pet_when_enabled_and_visible():
    """PET-009: 启动期一次性同步应把 enabled=1 + visible=1 的桌宠调出 show_pet。"""
    from app.pet.pet_facade import sync_pet_window_visibility

    class _FakeWindow:
        def __init__(self):
            self.show_calls = 0
            self.hide_calls = 0

        def show_pet(self):
            self.show_calls += 1

        def hide_pet(self):
            self.hide_calls += 1

    app = type("StubApp", (), {})()
    app.config = FakeConfig({"pet_enabled": "1", "pet_visible": "1"})
    window = _FakeWindow()
    app.__dict__["pet_window"] = window

    sync_pet_window_visibility(app)

    assert window.show_calls == 1
    assert window.hide_calls == 0


def test_sync_pet_window_visibility_hides_pet_when_disabled():
    """PET-009: enabled=0 时启动期同步必须 hide，不应误显。"""
    from app.pet.pet_facade import sync_pet_window_visibility

    class _FakeWindow:
        def __init__(self):
            self.show_calls = 0
            self.hide_calls = 0

        def show_pet(self):
            self.show_calls += 1

        def hide_pet(self):
            self.hide_calls += 1

    app = type("StubApp", (), {})()
    app.config = FakeConfig({"pet_enabled": "0", "pet_visible": "1"})
    window = _FakeWindow()
    app.__dict__["pet_window"] = window

    sync_pet_window_visibility(app)

    assert window.show_calls == 0
    assert window.hide_calls == 1


def test_sync_pet_window_visibility_hides_pet_when_visible_zero():
    """PET-009: enabled=1 + visible=0 时启动期同步必须 hide（不展开桌宠）。"""
    from app.pet.pet_facade import sync_pet_window_visibility

    class _FakeWindow:
        def __init__(self):
            self.show_calls = 0
            self.hide_calls = 0

        def show_pet(self):
            self.show_calls += 1

        def hide_pet(self):
            self.hide_calls += 1

    app = type("StubApp", (), {})()
    app.config = FakeConfig({"pet_enabled": "1", "pet_visible": "0"})
    window = _FakeWindow()
    app.__dict__["pet_window"] = window

    sync_pet_window_visibility(app)

    assert window.show_calls == 0
    assert window.hide_calls == 1


def test_sync_pet_window_visibility_noop_when_window_missing():
    """PET-009: 启动期 _init_core_subsystems 顺序保证 pet_window 已创建；
    但若缺失（如旧路径装配失败），façade 必须安全 no-op，不能抛异常。"""
    from app.pet.pet_facade import sync_pet_window_visibility

    app = type("StubApp", (), {})()
    app.config = FakeConfig({"pet_enabled": "1", "pet_visible": "1"})
    # 故意不设 pet_window
    sync_pet_window_visibility(app)  # 不应抛异常
