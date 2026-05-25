"""Pool top-up when visible danmu count is below min_on_screen."""

from __future__ import annotations

from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine
from main import DanmuApp


def test_maybe_pool_topup_fills_deficit(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "5")
    store.set("danmu_pool_enabled", "1")
    store.set("min_on_screen", "3")

    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()
    engine.running = True

    pool_lines = [f"pool-{i}" for i in range(8)]
    monkeypatch.setattr("main.sample_danmu", lambda n: pool_lines[:n])

    app = DanmuApp.__new__(DanmuApp)
    app.engine = engine
    app._scene_generation = 0

    assert engine.visible_display_count() == 0
    added = app._maybe_pool_topup()
    assert added >= 1
    assert engine.current_display_count() >= 1


def test_maybe_pool_topup_disabled_when_min_zero(tmp_path, monkeypatch):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("min_on_screen", "0")
    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.reload_tracks()
    engine.running = True

    monkeypatch.setattr("main.sample_danmu", lambda n: ["x"] * n)

    app = DanmuApp.__new__(DanmuApp)
    app.engine = engine
    app._scene_generation = 0

    assert app._maybe_pool_topup() == 0


def test_maybe_pool_topup_disabled_when_pool_off(tmp_path, monkeypatch):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_pool_enabled", "0")
    store.set("min_on_screen", "5")
    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.reload_tracks()
    engine.running = True

    monkeypatch.setattr("main.sample_danmu", lambda n: ["x"] * n)

    app = DanmuApp.__new__(DanmuApp)
    app.engine = engine
    app._scene_generation = 0

    assert engine.min_on_screen() == 0
    assert app._maybe_pool_topup() == 0
