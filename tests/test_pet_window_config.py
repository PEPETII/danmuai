"""PetWindow.apply_slot_config — incremental asset reload contracts."""

from unittest.mock import MagicMock, patch

from app.pet.pet_window import PetWindow
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig


def _make_app(**overrides) -> DanmuApp:
    app = DanmuApp.__new__(DanmuApp)
    cfg = FakeConfig()
    bind_minimal_danmu_app(app, config=cfg, **overrides)
    return app


def _make_window(app: DanmuApp, slot_id: int = 0) -> PetWindow:
    """Create a PetWindow with mocked reload_assets to track calls."""
    w = PetWindow.__new__(PetWindow)
    w._app = app
    w.slot_id = slot_id
    w._slot_asset_source = "builtin"
    w._slot_asset_path = ""
    w._slot_position_x = None
    w._slot_position_y = None
    w._settings = MagicMock()
    w._settings.asset_source = "builtin"
    w._settings.asset_path = ""
    return w


# ── apply_slot_config: incremental reload ──────────────────────────


def test_apply_slot_config_no_reload_when_assets_unchanged():
    """When asset_source and asset_path are unchanged, reload_assets() must NOT be called."""
    app = _make_app()
    w = _make_window(app, slot_id=0)

    with patch.object(w, "reload_assets") as mock_reload, \
         patch.object(w, "_apply_window_geometry"), \
         patch.object(w, "update"):
        w.apply_slot_config({"asset_source": "builtin", "asset_path": ""})
        mock_reload.assert_not_called()


def test_apply_slot_config_reload_when_source_changes():
    """When asset_source changes, reload_assets() must be called."""
    app = _make_app()
    w = _make_window(app, slot_id=0)

    with patch.object(w, "reload_assets") as mock_reload, \
         patch.object(w, "_apply_window_geometry"), \
         patch.object(w, "update"):
        w.apply_slot_config({"asset_source": "local", "asset_path": "C:/pets/custom"})
        mock_reload.assert_called_once()


def test_apply_slot_config_reload_when_path_changes():
    """When asset_path changes (same source), reload_assets() must be called."""
    app = _make_app()
    w = _make_window(app, slot_id=0)
    # Pre-set to a different path
    w._slot_asset_path = "C:/pets/old"

    with patch.object(w, "reload_assets") as mock_reload, \
         patch.object(w, "_apply_window_geometry"), \
         patch.object(w, "update"):
        w.apply_slot_config({"asset_source": "local", "asset_path": "C:/pets/new"})
        mock_reload.assert_called_once()


def test_apply_slot_config_first_call_loads_assets():
    """On first call (old_source/old_path are defaults), reload_assets() must be called
    if the new config differs from defaults."""
    app = _make_app()
    w = _make_window(app, slot_id=0)
    # Defaults are "builtin" / "" — requesting "local" triggers reload
    with patch.object(w, "reload_assets") as mock_reload, \
         patch.object(w, "_apply_window_geometry"), \
         patch.object(w, "update"):
        w.apply_slot_config({"asset_source": "local", "asset_path": "C:/pets/custom"})
        mock_reload.assert_called_once()


def test_apply_slot_config_position_update_without_reload():
    """Position changes alone must NOT trigger reload_assets()."""
    app = _make_app()
    w = _make_window(app, slot_id=0)

    with patch.object(w, "reload_assets") as mock_reload, \
         patch.object(w, "_apply_window_geometry"), \
         patch.object(w, "update"):
        w.apply_slot_config({"asset_source": "builtin", "asset_path": "", "position_x": 100, "position_y": 200})
        mock_reload.assert_not_called()


# ── _persist_position: atomic batch write ──────────────────────────


def test_persist_position_uses_set_batch():
    """W-BUG-E03: _persist_position must use set_batch for atomic x/y write."""
    app = _make_app()
    w = _make_window(app, slot_id=0)
    w._settings.barrage = MagicMock()
    w._settings.barrage.enabled = False

    with patch.object(w, "pos", return_value=MagicMock(x=lambda: 42, y=lambda: 99)), \
         patch.object(app.config, "set_batch") as mock_batch, \
         patch("app.pet.pet_window.PetSettings") as mock_settings_cls:
        mock_settings_cls.from_config.return_value = w._settings
        w._persist_position()

    mock_batch.assert_called_once_with({
        "pet_position_x": "42",
        "pet_position_y": "99",
    })
