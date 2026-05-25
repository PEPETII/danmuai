import pytest
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine, DanmuItem
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply


@pytest.fixture()
def config_store(workspace_tmp):
    db_path = workspace_tmp / "config.db"
    store = ConfigStore(db_path=db_path)
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")
    return store


def test_add_text_uses_screen_edge_not_global_queue(config_store, monkeypatch):
    engine = DanmuEngine(config_store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="old", x=120.0, width=260.0))

    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 100.0)

    item = engine.add_text("new")

    assert item is not None
    assert item.x == pytest.approx(1100.0)


def test_pick_track_prefers_least_congested_track(config_store, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    engine = DanmuEngine(config_store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="busy1", x=100.0, width=10.0))
    engine.tracks[0].add(DanmuItem(content="busy2", x=200.0, width=10.0))
    engine.tracks[0].add(DanmuItem(content="busy3", x=300.0, width=10.0))
    engine.tracks[1].add(DanmuItem(content="free", x=100.0, width=10.0))

    def _pick_least_congested(population, weights=None, k=1):
        return [min(population, key=lambda track: len(track.items))]

    monkeypatch.setattr("app.danmu_engine.random.choices", _pick_least_congested)

    track = engine._pick_track(DanmuItem(content="incoming", width=120.0))

    assert track is engine.tracks[1]


def test_min_on_screen_default_5(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    engine = DanmuEngine(store)
    assert engine.min_on_screen() == 5


def test_deficit_below_min(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("min_on_screen", "5")
    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.reload_tracks()
    engine.tracks[0].add(DanmuItem(content="a", x=100.0, width=50.0))
    engine.tracks[1].add(DanmuItem(content="b", x=150.0, width=50.0))
    assert engine.visible_display_count() == 2
    assert engine.deficit_below_min() == 3


def test_can_accept_more_not_blocked_by_visible_cap(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "5")
    store.set("min_on_screen", "2")

    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    for i in range(5):
        engine.tracks[i % 5].add(DanmuItem(content=f"on-{i}", x=100.0 + i * 10, width=50.0))

    assert engine.visible_display_count() == 5
    assert engine._can_accept_more()
    assert engine.add_text("still accepts above min") is not None


def test_entry_zone_single_pending_still_accepts(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "5")

    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="pending-a", x=950.0, width=50.0))

    assert engine.pending_entry_count() == 1
    assert engine._can_accept_more()
    assert engine.add_text("one pending still ok") is not None


def test_min_on_screen_zero_when_pool_disabled(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_pool_enabled", "0")
    store.set("min_on_screen", "5")
    engine = DanmuEngine(store)
    assert engine.min_on_screen() == 0
    assert engine.deficit_below_min() == 0


def test_min_on_screen_zero_disables_needs_refill(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("min_on_screen", "0")
    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.reload_tracks()
    assert engine.deficit_below_min() == 0
    assert engine.needs_refill() is False


def test_acceleration_duration_wall_clock_not_tick_count(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")

    engine = DanmuEngine(store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()
    engine.tracks[0].add(DanmuItem(content="moving", x=500.0, width=100.0, speed=2.0))

    def run_accel(dt_sec: float, steps: int) -> None:
        engine.trigger_acceleration(60)
        for _ in range(steps):
            engine.update(speed_factor=1.0, dt_sec=dt_sec)

    run_accel(0.05, 20)
    assert engine._accel_remaining == 0

    run_accel(0.025, 40)
    assert engine._accel_remaining == 0

    engine.trigger_acceleration(60)
    for _ in range(10):
        engine.update(speed_factor=1.0, dt_sec=0.05)
    assert engine._accel_remaining == pytest.approx(30.0, rel=0.02)


def test_items_in_fade_zone_incremental(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")

    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()

    assert not engine.items_in_fade_zone()
    item = DanmuItem(content="fade", x=1900.0, width=100.0)
    engine.tracks[0].add(item)
    engine._refresh_item_visibility(item)
    assert engine.items_in_fade_zone()
    assert engine._fade_zone_count == 1

    item.x = 500.0
    engine._refresh_item_visibility(item)
    assert not engine.items_in_fade_zone()
    assert engine._fade_zone_count == 0


def test_acceleration_speeds_up_update(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")

    engine = DanmuEngine(store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="moving", x=500.0, width=100.0, speed=2.0))
    old_x = engine.tracks[0].items[0].x

    engine.trigger_acceleration(60)
    for _ in range(30):
        engine.update(speed_factor=1.0, dt_sec=1.0 / 60.0)

    new_x = engine.tracks[0].items[0].x
    assert new_x < old_x - 2.0


def test_reply_queue_purge_before_round():
    buf = AIReplyFIFOBuffer()
    buf.push(QueuedReply("p1", 1, 0, "old-a", screenshot_round=5))
    buf.push(QueuedReply("p1", 2, 0, "fresh", screenshot_round=10))
    buf.push(QueuedReply("p1", 3, 0, "old-b", screenshot_round=7))

    buf.purge_before_round(8)

    assert buf.size() == 1
    assert buf.pop().content == "fresh"


def test_right_zone_count(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "5")

    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="r1", x=800.0, width=50.0))
    engine.tracks[0].add(DanmuItem(content="r2", x=700.0, width=50.0))
    engine.tracks[1].add(DanmuItem(content="m1", x=400.0, width=50.0))
    engine.tracks[1].add(DanmuItem(content="l1", x=100.0, width=50.0))
    engine.tracks[2].add(DanmuItem(content="pending", x=950.0, width=50.0))

    assert engine.right_zone_count() == 3
    assert engine.right_visible_count() == 2
    assert engine.visible_display_count() == 4
    assert engine.current_display_count() == 5


def test_drop_pending_items_keeps_visible_danmu(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "3")

    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="visible-right", x=890.0, width=50.0))
    engine.tracks[1].add(DanmuItem(content="visible-mid", x=400.0, width=50.0))
    engine.tracks[2].add(DanmuItem(content="pending", x=930.0, width=50.0))

    dropped = engine.drop_pending_items()

    assert dropped == 1
    assert engine.current_display_count() == 2
    assert [item.content for track in engine.tracks for item in track.items] == [
        "visible-right",
        "visible-mid",
    ]


def test_needs_refill_when_visible_below_min(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "5")
    store.set("min_on_screen", "5")

    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="l1", x=100.0, width=50.0))
    engine.tracks[1].add(DanmuItem(content="l2", x=150.0, width=50.0))
    engine.tracks[2].add(DanmuItem(content="m1", x=400.0, width=50.0))
    engine._rebuild_visibility_counts()

    assert engine.visible_display_count() == 3
    assert engine.needs_refill() is True

    engine.tracks[3].add(DanmuItem(content="r1", x=200.0, width=50.0))
    engine.tracks[4].add(DanmuItem(content="r2", x=250.0, width=50.0))
    engine._rebuild_visibility_counts()

    assert engine.visible_display_count() == 5
    assert engine.needs_refill() is False


def test_needs_render_tick_spawn_pending(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.reload_tracks()
    engine.tracks[0].add(DanmuItem(content="pending", x=1950.0, width=80.0))
    assert engine.visible_display_count() == 0
    assert engine.needs_render_tick()


def test_needs_render_tick_false_when_far_off_right(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.reload_tracks()
    engine.tracks[0].add(DanmuItem(content="far", x=2500.0, width=80.0))
    assert not engine.needs_render_tick()


def test_needs_refill_blocks_when_entry_zone_pending_full(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "5")
    store.set("min_on_screen", "5")

    engine = DanmuEngine(store)
    engine.set_screen_width(900.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="pending-a", x=950.0, width=50.0))
    engine.tracks[1].add(DanmuItem(content="pending-b", x=980.0, width=50.0))
    engine.tracks[2].add(DanmuItem(content="visible", x=100.0, width=50.0))
    engine._rebuild_visibility_counts()

    assert engine.current_display_count() == 3
    assert engine.right_zone_count() == 2
    assert engine.right_visible_count() == 0
    assert engine.visible_display_count() == 1
    assert engine.pending_entry_count() == 2
    assert engine.offscreen_pending_count() == 2
    assert engine.needs_refill() is False


def test_can_accept_more_false_when_pending_entry_overloaded(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "3")

    engine = DanmuEngine(store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="p1", x=980.0, width=40.0))
    engine.tracks[0].add(DanmuItem(content="p2", x=990.0, width=40.0))
    engine.tracks[1].add(DanmuItem(content="p3", x=985.0, width=40.0))
    engine.tracks[2].add(DanmuItem(content="p4", x=982.0, width=40.0))
    engine.tracks[0].add(DanmuItem(content="p5", x=988.0, width=40.0))
    engine.tracks[1].add(DanmuItem(content="p6", x=986.0, width=40.0))

    assert engine.max_pending_entry() == 6
    assert engine.pending_entry_count() == 6
    assert not engine._can_accept_more()


def test_pick_track_fallback_rejects_entry_tail_past_limit(config_store, monkeypatch):
    engine = DanmuEngine(config_store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    for track in engine.tracks:
        track.add(DanmuItem(content="blocked", x=1300.0, width=50.0))

    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 100.0)

    incoming = DanmuItem(content="incoming", x=1100.0, width=120.0)
    assert engine._pick_track(incoming) is None


def test_add_text_pick_failure_does_not_pollute_dedup(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")
    engine = DanmuEngine(store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    for track in engine.tracks:
        track.add(DanmuItem(content="blocked", x=1300.0, width=50.0))

    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 100.0)

    text = "retry-after-entry-reject"
    assert engine.add_text(text) is None
    assert not engine.is_duplicate(text)
    engine.tracks[0].items.clear()
    engine.tracks[1].items.clear()
    assert engine.add_text(text) is not None


def test_pick_track_fallback_still_accepts_when_tail_within_limit(config_store, monkeypatch):
    engine = DanmuEngine(config_store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="tail", x=900.0, width=50.0))
    engine.tracks[1].add(DanmuItem(content="far", x=100.0, width=50.0))

    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 80.0)

    incoming = DanmuItem(content="incoming", x=1100.0, width=120.0)
    track = engine._pick_track(incoming)
    assert track is not None
    assert incoming.x > engine.tracks[0].items[0].x


def test_reload_tracks_preserves_visible_items(config_store):
    engine = DanmuEngine(config_store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks(preserve_visible=False)
    engine.tracks[0].add(DanmuItem(content="stay", x=500.0, width=100.0))
    engine.reload_tracks(preserve_visible=True)
    assert engine.current_display_count() == 1
    assert engine.tracks[0].items[0].content == "stay"
    assert engine.needs_render_tick()


def test_reload_tracks_drops_offscreen_items(config_store):
    engine = DanmuEngine(config_store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks(preserve_visible=False)
    engine.tracks[0].add(DanmuItem(content="gone", x=-200.0, width=100.0))
    engine.reload_tracks(preserve_visible=True)
    assert engine.current_display_count() == 0
    assert not engine.needs_render_tick()
