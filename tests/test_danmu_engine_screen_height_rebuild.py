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
