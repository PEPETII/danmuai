import pytest
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine


@pytest.fixture()
def engine(workspace_tmp):
    db_path = workspace_tmp / "config.db"
    store = ConfigStore(db_path=db_path)
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")
    eng = DanmuEngine(store)
    eng.screen_width = 1000.0
    eng.screen_height = 500.0
    # Simulate a stable state where capacity has been computed
    eng._capacity_counts_stale = False
    eng._motion_tick_stale = False
    return eng


def test_set_screen_height_marks_capacity_and_motion_tick_stale(engine):
    """Changing screen_height must mark capacity and motion tick stale for rebuild."""
    assert not engine._capacity_counts_stale
    assert not engine._motion_tick_stale

    engine.set_screen_height(800.0)

    assert engine.screen_height == 800.0
    assert engine._capacity_counts_stale is True
    assert engine._motion_tick_stale is True


def test_set_screen_height_same_value_does_not_mark_stale(engine):
    """Calling set_screen_height with the same value should be a no-op."""
    engine._capacity_counts_stale = False
    engine._motion_tick_stale = False

    engine.set_screen_height(500.0)

    assert engine.screen_height == 500.0
    assert engine._capacity_counts_stale is False
    assert engine._motion_tick_stale is False


def test_tracks_fit_drawable_height_at_high_dpi(monkeypatch, workspace_tmp):
    """BUG-024: scaled line_height must keep tracks within drawable band at high DPI."""
    monkeypatch.setattr("app.danmu_engine.screen.ui_scale_factor", lambda: 2.0)

    store = ConfigStore(db_path=workspace_tmp / "dpi_tracks.db")
    store.set("layout_mode", "1/2")
    store.set("danmu_lines", "0")
    eng = DanmuEngine(store)
    eng.screen_height = 1080.0
    eng.reload_tracks()

    assert eng._track_line_height == 80.0
    assert eng._track_top_margin == 100.0
    assert eng._track_bottom_margin == 160.0
    drawable = eng.drawable_height()
    assert drawable == 540.0
    for track in eng.tracks:
        assert track.y + eng._track_line_height <= drawable + 1e-6
