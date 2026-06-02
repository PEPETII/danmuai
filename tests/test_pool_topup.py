"""Pool top-up when visible danmu count is below min_on_screen."""

from __future__ import annotations

import time

from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine, DanmuItem
from main import DanmuApp

MANY_ITEM_COUNT = 1000
DEFICIT_LOOP_COUNT = 20
# Regression ceiling only — not an absolute SLA.
DEFICIT_BUDGET_SEC = 2.0


def _seed_many_visible(engine: DanmuEngine, n: int) -> None:
    for i in range(n):
        track = engine.tracks[i % len(engine.tracks)]
        track.add(DanmuItem(content=f"d{i}", x=200.0 + (i % 40) * 35.0, width=80.0))
    engine._rebuild_visibility_counts()


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
    monkeypatch.setattr("main.sample_danmu_for_config", lambda _cfg, n: pool_lines[:n])

    app = DanmuApp.__new__(DanmuApp)
    app.engine = engine
    app.config = store
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

    monkeypatch.setattr("main.sample_danmu_for_config", lambda _cfg, n: ["x"] * n)

    app = DanmuApp.__new__(DanmuApp)
    app.engine = engine
    app.config = store
    app._scene_generation = 0

    assert app._maybe_pool_topup() == 0


def test_maybe_pool_topup_disabled_when_pool_off(tmp_path, monkeypatch):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_pool_enabled", "0")
    store.set("danmu_pool_use_custom", "0")
    store.set("min_on_screen", "5")
    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.reload_tracks()
    engine.running = True

    monkeypatch.setattr("main.sample_danmu_for_config", lambda _cfg, n: ["x"] * n)

    app = DanmuApp.__new__(DanmuApp)
    app.engine = engine
    app.config = store
    app._scene_generation = 0

    assert engine.min_on_screen() == 0
    assert app._maybe_pool_topup() == 0


def test_maybe_pool_topup_custom_only(tmp_path, monkeypatch):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "5")
    store.set("danmu_pool_enabled", "0")
    store.set("danmu_pool_use_custom", "1")
    store.set("min_on_screen", "3")
    store.set_custom_danmu_pool(["自定义1", "自定义2", "自定义3", "自定义4"])

    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()
    engine.running = True

    monkeypatch.setattr(
        "main.sample_danmu_for_config",
        lambda _cfg, n: store.get_custom_danmu_pool()[:n],
    )

    app = DanmuApp.__new__(DanmuApp)
    app.engine = engine
    app.config = store
    app._scene_generation = 0

    assert engine.min_on_screen() == 3
    added = app._maybe_pool_topup()
    assert added >= 1


def test_deficit_below_min_many_items_bounded(tmp_path, monkeypatch):
    """BUG-034: deficit_below_min with ~1000 items must not regress to multi-second scans."""
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(4, int(v)))
    store = ConfigStore(db_path=tmp_path / "deficit_bulk.db")
    store.set("danmu_pool_enabled", "1")
    store.set("min_on_screen", "5")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "8")
    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    _seed_many_visible(engine, MANY_ITEM_COUNT)

    started = time.perf_counter()
    for _ in range(DEFICIT_LOOP_COUNT):
        engine.deficit_below_min()
    elapsed = time.perf_counter() - started

    assert elapsed < DEFICIT_BUDGET_SEC
    assert engine.deficit_below_min() == 0
