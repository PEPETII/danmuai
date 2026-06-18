"""P2-04: DanmuEngine incremental counts, track cache, and capacity eviction tests."""

import time

from app.config_store import ConfigStore
from app.danmu_engine import ENTRY_ZONE_PX, DanmuEngine, DanmuItem
from app.danmu_engine_models import Track


def _make_engine(tmp_path, *, lines: int = 8, width: float = 1920.0) -> DanmuEngine:
    store = ConfigStore(db_path=tmp_path / "perf.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", str(lines))
    engine = DanmuEngine(store)
    engine.set_screen_width(width)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    engine.recent.clear()
    engine.recent_exact_set.clear()
    return engine


def _assert_counts_match_scan(engine: DanmuEngine) -> None:
    sw = engine.screen_width
    assert engine.pending_entry_count() == DanmuEngine._scan_pending_entry_count(
        engine.tracks, sw
    )
    assert engine.offscreen_pending_count() == DanmuEngine._scan_offscreen_pending_count(
        engine.tracks, sw
    )
    assert engine.current_display_count() == DanmuEngine._scan_current_display_count(
        engine.tracks
    )


def _assert_track_cache_matches_scan(engine: DanmuEngine) -> None:
    sw = engine.screen_width
    zone_left = sw - ENTRY_ZONE_PX
    for track in engine.tracks:
        expected_entry = sum(
            1 for it in track.items if it.x + it.width > zone_left and it.x < sw
        )
        expected_tail = (
            max((Track.item_right_edge(it) for it in track.items), default=float("-inf"))
            if track.items
            else float("-inf")
        )
        assert track.entry_zone_count(sw) == expected_entry
        assert track.rightmost_edge() == expected_tail


def test_capacity_counts_match_scan_after_seeded_adds(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(4, int(v)))
    engine = _make_engine(tmp_path, lines=6, width=1000.0)

    for i in range(40):
        track = engine.tracks[i % len(engine.tracks)]
        x = 700.0 + (i % 12) * 30.0 if i % 3 else 200.0 + i * 5.0
        item = DanmuItem(content=f"c{i}", x=x, width=60.0)
        track.add(item)
        engine._register_item(track, item)

    _assert_counts_match_scan(engine)
    _assert_track_cache_matches_scan(engine)


def test_capacity_counts_match_scan_after_add_text_burst(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(4, int(v)))
    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: (a + b) / 2)
    engine = _make_engine(tmp_path, lines=6, width=1000.0)

    for i in range(30):
        engine.add_text(f"burst-{i}", skip_dedup=True)

    _assert_counts_match_scan(engine)
    _assert_track_cache_matches_scan(engine)


def test_capacity_counts_match_scan_after_motion_and_eviction(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(4, int(v)))
    store = ConfigStore(db_path=tmp_path / "motion.db")
    store.set("danmu_speed", "8.0")
    store.set("danmu_lines", "6")
    store.set("danmu_pending_entry_cap", "4")
    store.set("danmu_track_retention_cap", "12")
    engine = DanmuEngine(store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()
    engine.recent.clear()
    engine.recent_exact_set.clear()

    for i in range(20):
        engine.add_text(f"m{i}", skip_dedup=True)

    for _ in range(120):
        engine.update(speed_factor=1.0, dt_sec=1.0 / 60.0)

    _assert_counts_match_scan(engine)
    _assert_track_cache_matches_scan(engine)


def test_eviction_still_drops_furthest_offscreen(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "evict.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")
    store.set("danmu_pending_entry_cap", "2")
    engine = DanmuEngine(store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="far-a", x=1100.0, width=50.0))
    engine.tracks[1].add(DanmuItem(content="far-b", x=1200.0, width=50.0))
    engine._rebuild_capacity_counts()

    item = engine.add_text("new-after-evict", skip_dedup=True)
    assert item is not None
    contents = [it.content for track in engine.tracks for it in track.items]
    assert "far-b" not in contents
    assert "new-after-evict" in contents
    _assert_counts_match_scan(engine)


def test_pick_track_weights_use_cached_entry_density(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    engine = _make_engine(tmp_path, lines=2, width=1000.0)

    engine.tracks[0].add(DanmuItem(content="busy1", x=850.0, width=10.0))
    engine.tracks[0].add(DanmuItem(content="busy2", x=880.0, width=10.0))
    engine.tracks[0].add(DanmuItem(content="busy3", x=910.0, width=10.0))
    engine.tracks[1].add(DanmuItem(content="free", x=100.0, width=10.0))
    engine._rebuild_capacity_counts()

    def _pick_least_entry_density(population, weights=None, k=1):
        return [min(population, key=lambda track: track.entry_zone_count_cached)]

    monkeypatch.setattr("app.danmu_engine.random.choices", _pick_least_entry_density)
    track = engine._pick_track(DanmuItem(content="incoming", width=120.0))
    assert track is engine.tracks[1]


def test_incremental_counts_skip_full_scan_when_fresh(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(4, int(v)))
    engine = _make_engine(tmp_path, lines=4, width=1000.0)
    for i in range(20):
        track = engine.tracks[i % len(engine.tracks)]
        item = DanmuItem(content=f"x{i}", x=950.0 + i, width=40.0)
        track.add(item)
        engine._register_item(track, item)

    rebuild_calls: list[int] = []
    original = engine._rebuild_capacity_counts

    def counting_rebuild() -> None:
        rebuild_calls.append(1)
        return original()

    engine._rebuild_capacity_counts = counting_rebuild  # type: ignore[method-assign]

    for _ in range(50):
        engine.pending_entry_count()
        engine.offscreen_pending_count()
        engine.current_display_count()

    assert rebuild_calls == []


ADD_TEXT_BUDGET_SEC = 2.5
PREPARE_CAPACITY_BUDGET_SEC = 1.5
UPDATE_BUDGET_SEC = 3.0


def test_add_text_high_density_within_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(8, int(v)))
    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: (a + b) / 2)
    engine = _make_engine(tmp_path, lines=10, width=1920.0)

    started = time.perf_counter()
    for i in range(80):
        engine.add_text(f"dense-{i}", skip_dedup=True)
    elapsed = time.perf_counter() - started

    assert elapsed < ADD_TEXT_BUDGET_SEC
    _assert_counts_match_scan(engine)


def test_prepare_capacity_high_density_within_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(6, int(v)))
    store = ConfigStore(db_path=tmp_path / "cap.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "8")
    store.set("danmu_pending_entry_cap", "8")
    store.set("danmu_track_retention_cap", "24")
    engine = DanmuEngine(store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    engine.recent.clear()
    engine.recent_exact_set.clear()

    for i in range(30):
        track = engine.tracks[i % len(engine.tracks)]
        item = DanmuItem(content=f"off-{i}", x=1050.0 + i * 8, width=40.0)
        track.add(item)
        engine._register_item(track, item)

    started = time.perf_counter()
    for _ in range(40):
        assert engine._prepare_capacity_for_new_item()
    elapsed = time.perf_counter() - started

    assert elapsed < PREPARE_CAPACITY_BUDGET_SEC
    _assert_counts_match_scan(engine)


def test_update_many_items_still_within_budget(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(8, int(v)))
    engine = _make_engine(tmp_path, lines=8, width=1920.0)

    for i in range(500):
        track = engine.tracks[i % len(engine.tracks)]
        item = DanmuItem(content=f"d{i}", x=200.0 + (i % 40) * 35.0, width=80.0, speed=2.0)
        track.add(item)
        engine._register_item(track, item)
    engine._rebuild_visibility_counts()

    started = time.perf_counter()
    for _ in range(60):
        engine.update(speed_factor=1.0, dt_sec=1.0 / 60.0)
    elapsed = time.perf_counter() - started

    assert elapsed < UPDATE_BUDGET_SEC
    _assert_counts_match_scan(engine)
    _assert_track_cache_matches_scan(engine)
