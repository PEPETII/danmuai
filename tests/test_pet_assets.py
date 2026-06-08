from pathlib import Path

import pytest
from app.bundle_paths import resource_path
from app.pet.pet_assets import (
    BUILTIN_PET_DIR,
    PET_FRAME_H,
    PET_FRAME_W,
    PET_STATE_FRAME_COUNTS,
    PET_STATE_ROWS,
    load_pet_assets,
    validate_pet_pack_dir,
)

from tests.fakes import FakeConfig


def test_builtin_pet_pack_loads(qapp):
    pack = load_pet_assets(FakeConfig({"pet_asset_source": "builtin"}))
    assert pack.pet_id == "yuexin-miao-animated"
    assert pack.spritesheet_path.is_file()


def test_validate_pet_pack_dir_missing_json():
    with pytest.raises(ValueError, match="pet.json"):
        validate_pet_pack_dir(Path("/nonexistent/pet-pack"))


def test_frame_rect_review_on_row_8(qapp):
    pack = load_pet_assets(FakeConfig({"pet_asset_source": "builtin"}))
    _, sy, _, _ = pack.frame_rect("review", 0)
    assert sy == 8 * PET_FRAME_H


def test_frame_rect_run_on_row_7(qapp):
    pack = load_pet_assets(FakeConfig({"pet_asset_source": "builtin"}))
    _, sy, _, _ = pack.frame_rect("run", 0)
    assert sy == 7 * PET_FRAME_H


def test_frame_rect_wave_on_row_3(qapp):
    pack = load_pet_assets(FakeConfig({"pet_asset_source": "builtin"}))
    _, sy, _, _ = pack.frame_rect("wave", 0)
    assert sy == 3 * PET_FRAME_H


def test_frame_rect_jump_on_row_4(qapp):
    pack = load_pet_assets(FakeConfig({"pet_asset_source": "builtin"}))
    _, sy, _, _ = pack.frame_rect("jump", 0)
    assert sy == 4 * PET_FRAME_H


def test_state_frame_count_matches_petdex(qapp):
    pack = load_pet_assets(FakeConfig({"pet_asset_source": "builtin"}))
    assert pack.frame_count("idle") == 6
    assert pack.frame_count("wave") == 4
    assert pack.frame_count("run") == 6
    assert pack.frame_count("jump") == 5
    assert pack.frame_count("failed") == 8
    assert pack.frame_count("review") == 6
    assert PET_STATE_ROWS["idle"] == 0
    assert PET_STATE_FRAME_COUNTS["idle"] == 6
    sx, sy, sw, sh = pack.frame_rect("idle", 5)
    assert (sx, sy, sw, sh) == (5 * PET_FRAME_W, 0, PET_FRAME_W, PET_FRAME_H)


def test_state_frame_interval_sec(qapp):
    pack = load_pet_assets(FakeConfig({"pet_asset_source": "builtin"}))
    assert pack.state_frame_interval_sec("idle") == pytest.approx(1100 / 6 / 1000.0)
    assert pack.state_frame_interval_sec("wave") == pytest.approx(700 / 4 / 1000.0)
    assert pack.state_duration_ms("run") == 820


def test_validate_builtin_dimensions(qapp):
    meta, sheet, cols, rows = validate_pet_pack_dir(BUILTIN_PET_DIR)
    assert meta["id"] == "yuexin-miao-animated"
    assert sheet.name.endswith(".webp")
    assert cols == 8
    assert rows == 9


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


def _make_patch_app(config_values):
    from unittest.mock import MagicMock

    app = type("StubApp", (), {})()
    app.config = FakeConfig(config_values)
    app.config_changed = MagicMock()
    window = MagicMock()
    app.__dict__["pet_window"] = window
    return app


def test_apply_pet_settings_patch_disabling_syncs_visible(qapp):
    from app.pet.pet_facade import apply_pet_settings_patch

    app = _make_patch_app({"pet_enabled": "1", "pet_visible": "1"})
    apply_pet_settings_patch(app, {"pet_enabled": False})

    assert app.config.get("pet_enabled") == "0"
    assert app.config.get("pet_visible") == "0"


def test_apply_pet_settings_patch_enabling_syncs_visible(qapp):
    from app.pet.pet_facade import apply_pet_settings_patch

    app = _make_patch_app({"pet_enabled": "0", "pet_visible": "0"})
    apply_pet_settings_patch(app, {"pet_enabled": True})

    assert app.config.get("pet_enabled") == "1"
    assert app.config.get("pet_visible") == "1"


def test_apply_pet_settings_patch_enabled_unchanged_keeps_visible(qapp):
    from app.pet.pet_facade import apply_pet_settings_patch

    app = _make_patch_app({"pet_enabled": "1", "pet_visible": "0", "pet_scale": "1.0"})
    apply_pet_settings_patch(app, {"pet_enabled": True, "pet_scale": "1.5"})

    assert app.config.get("pet_enabled") == "1"
    assert app.config.get("pet_visible") == "0"
    assert app.config.get("pet_scale") == "1.5"


def test_sync_pet_window_visibility_noop_when_window_missing():
    """PET-009: 启动期 _init_core_subsystems 顺序保证 pet_window 已创建；
    但若缺失（如旧路径装配失败），façade 必须安全 no-op，不能抛异常。"""
    from app.pet.pet_facade import sync_pet_window_visibility

    app = type("StubApp", (), {})()
    app.config = FakeConfig({"pet_enabled": "1", "pet_visible": "1"})
    # 故意不设 pet_window
    sync_pet_window_visibility(app)  # 不应抛异常
