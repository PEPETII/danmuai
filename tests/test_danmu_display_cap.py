"""Configurable danmu display caps: safe defaults, optional unlimited via 0."""

from app.config_defaults import (
    DEFAULT_DANMU_PENDING_ENTRY_CAP,
    DEFAULT_DANMU_TRACK_RETENTION_CAP,
)
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine, DanmuItem
from app.main_helpers import queue_capacity
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply


def test_explicit_zero_pending_cap_accepts_many_entry_zone_items(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "3")
    store.set("danmu_pending_entry_cap", "0")

    engine = DanmuEngine(store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    for i in range(8):
        engine.tracks[i % 3].add(DanmuItem(content=f"p{i}", x=1010.0 + i * 5, width=40.0))

    assert engine.max_pending_entry() == 0
    assert engine.entry_zone_overloaded() is False
    assert engine.add_text("still-accepts") is not None


def test_default_pending_cap_is_300(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "3")

    engine = DanmuEngine(store)
    assert engine.max_pending_entry() == DEFAULT_DANMU_PENDING_ENTRY_CAP
    assert DEFAULT_DANMU_PENDING_ENTRY_CAP == 300


def test_default_track_retention_cap_is_600(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "3")

    engine = DanmuEngine(store)
    assert engine._track_retention_cap() == DEFAULT_DANMU_TRACK_RETENTION_CAP
    assert DEFAULT_DANMU_TRACK_RETENTION_CAP == 600


def test_pending_cap_evicts_furthest_offscreen_before_accept(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")
    store.set("danmu_pending_entry_cap", "2")

    engine = DanmuEngine(store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="far-a", x=1100.0, width=50.0))
    engine.tracks[1].add(DanmuItem(content="far-b", x=1200.0, width=50.0))

    assert engine.pending_entry_count() == 2
    item = engine.add_text("new-after-evict")
    assert item is not None
    contents = [it.content for track in engine.tracks for it in track.items]
    assert "far-b" not in contents
    assert "new-after-evict" in contents


def test_track_retention_cap_evicts_offscreen(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")
    store.set("danmu_track_retention_cap", "3")

    engine = DanmuEngine(store)
    engine.set_screen_width(1000.0)
    engine.set_screen_height(400.0)
    engine.reload_tracks()

    engine.tracks[0].add(DanmuItem(content="on-screen", x=200.0, width=50.0))
    engine.tracks[0].add(DanmuItem(content="off-1", x=1100.0, width=50.0))
    engine.tracks[1].add(DanmuItem(content="off-2", x=1200.0, width=50.0))
    engine.tracks[1].add(DanmuItem(content="off-3", x=1300.0, width=50.0))

    assert engine.add_text("incoming") is not None
    assert engine.current_display_count() <= 3
    contents = [it.content for track in engine.tracks for it in track.items]
    assert "on-screen" in contents
    assert "off-3" not in contents


def test_offscreen_item_released_after_scroll(tmp_path, monkeypatch):
    monkeypatch.setattr("app.danmu_engine.clamp_danmu_lines", lambda v: max(2, int(v)))
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("danmu_speed", "10.0")
    store.set("danmu_lines", "2")

    engine = DanmuEngine(store)
    engine.set_screen_width(400.0)
    engine.set_screen_height(200.0)
    engine.reload_tracks()

    item = DanmuItem(content="scroll-away", x=100.0, width=80.0, speed=10.0)
    item._pixmap = object()
    engine.tracks[0].add(item)

    for _ in range(20):
        engine.update(speed_factor=1.0, dt_sec=1.0 / 60.0)

    assert engine.current_display_count() == 0


def test_queue_capacity_zero_means_unlimited(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    assert queue_capacity(store, 5) == 0

    buf = AIReplyFIFOBuffer(max_items=0)
    for i in range(25):
        buf.push(QueuedReply("p1", 1, i, f"item-{i}"))
    assert buf.size() == 25


def test_queue_capacity_honors_configured_limit(tmp_path):
    store = ConfigStore(db_path=tmp_path / "config.db")
    store.set("reply_queue_max_items", "4")
    assert queue_capacity(store, 5) == 4

    buf = AIReplyFIFOBuffer(max_items=4)
    for i in range(6):
        buf.push(QueuedReply("p1", 1, i, f"item-{i}"))
    assert buf.size() == 4
    assert buf.pop().content == "item-2"
