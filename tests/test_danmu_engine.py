import time

import pytest
from app.config_store import ConfigStore
from app.danmu_engine import (
    DanmuEngine,
    clamp_danmu_lines,
    layout_height_ratio,
    normalize_layout_mode,
    resolve_danmu_max_chars,
)
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app


@pytest.fixture()
def engine(workspace_tmp):
    db_path = workspace_tmp / "config.db"
    store = ConfigStore(db_path=db_path)
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "2")
    eng = DanmuEngine(store)
    eng.recent.clear()
    eng.recent_exact_set.clear()
    eng.screen_width = 1000.0
    return eng


def test_reply_fifo_buffer_preserves_completion_order():
    buffer = AIReplyFIFOBuffer()
    buffer.push(QueuedReply("persona-a", 1, 0, "first", 1, 1, 1.0, 1))
    buffer.push(QueuedReply("persona-b", 2, 0, "second", 2, 2, 2.0, 1))
    buffer.push(QueuedReply("persona-c", 3, 0, "third", 3, 3, 3.0, 1))

    assert buffer.pop().content == "first"
    assert buffer.pop().content == "second"
    assert buffer.pop().content == "third"
    assert buffer.is_empty()


def test_reply_fifo_buffer_keeps_eight_latest_items_by_default():
    buffer = AIReplyFIFOBuffer()

    for i in range(9):
        buffer.push(QueuedReply("persona", i, 0, f"msg-{i}", i))

    assert buffer.size() == 8
    assert buffer.pop().content == "msg-1"


def test_add_text_truncates_to_configured_max_chars(engine):
    engine.config.set("danmu_max_chars", "8")
    item = engine.add_text("一二三四五六七八九十")
    assert item is not None
    assert item.content == "一二三四五六七八..."


def test_resolve_danmu_max_chars_defaults_and_clamp(engine):
    engine.config.set("danmu_max_chars", "")
    assert resolve_danmu_max_chars(engine.config, lang="zh") == 15
    engine.config.set("danmu_max_chars", "99")
    assert resolve_danmu_max_chars(engine.config) == 80
    engine.config.set("danmu_max_chars", "2")
    assert resolve_danmu_max_chars(engine.config) == 5


def test_init_tracks_clamps_configured_and_auto_line_count(engine):
    engine.config.set("danmu_lines", "5")
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    assert len(engine.tracks) == 12

    engine.config.set("danmu_lines", "18")
    engine.reload_tracks()
    assert len(engine.tracks) == 18

    engine.config.set("danmu_lines", "0")
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    assert len(engine.tracks) == 20


def test_clamp_danmu_lines_bounds():
    assert clamp_danmu_lines(5) == 12
    assert clamp_danmu_lines(25) == 20
    assert clamp_danmu_lines(16) == 16


def test_layout_mode_normalization(engine):
    assert normalize_layout_mode("1/2") == "1/2"
    assert normalize_layout_mode("invalid") == "fullscreen"
    engine.config.set("layout_mode", "1/2")
    assert layout_height_ratio(engine.config) == 0.5


def test_layout_half_reduces_auto_track_count(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "layout.db")
    store.set("danmu_lines", "0")
    store.set("layout_mode", "fullscreen")
    engine = DanmuEngine(store)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    full_count = len(engine.tracks)

    store.set("layout_mode", "1/2")
    engine.reload_tracks()
    half_count = len(engine.tracks)

    assert half_count < full_count
    assert engine.tracks[-1].y < 1080 * 0.5


def test_clear_dedup_window_empties_recent(engine):
    engine._remember_content("seen")
    assert len(engine.recent) == 1
    engine.clear_dedup_window()
    assert len(engine.recent) == 0
    assert len(engine.recent_exact_set) == 0


def test_drop_pending_below_generation_removes_offscreen_old_items(engine):
    from app.danmu_engine import DanmuItem

    engine.screen_width = 1000.0
    track = engine.tracks[0]
    pending = DanmuItem("pending", scene_generation=0, x=1100.0, width=80.0)
    visible = DanmuItem("visible", scene_generation=0, x=400.0, width=80.0)
    track.items = [pending, visible]
    engine._rebuild_visibility_counts()

    dropped = engine.drop_pending_below_generation(1)

    assert dropped == 1
    assert len(track.items) == 1
    assert track.items[0].content == "visible"


def test_drop_items_below_scene_generation_removes_all_old_generation(engine):
    from app.danmu_engine import DanmuItem

    engine.screen_width = 1000.0
    track = engine.tracks[0]
    old = DanmuItem("old", scene_generation=0, x=400.0, width=80.0)
    new = DanmuItem("new", scene_generation=2, x=500.0, width=80.0)
    track.items = [old, new]

    dropped = engine.drop_items_below_scene_generation(2)

    assert dropped == 1
    assert len(track.items) == 1
    assert track.items[0].content == "new"


def test_drop_items_with_batch_id_removes_matching_track_items():
    from app.danmu_engine import DanmuEngine, DanmuItem

    from tests.fakes import FakeConfig

    engine = DanmuEngine(FakeConfig())
    engine.screen_width = 1000.0
    track = engine.tracks[0]
    keep = DanmuItem("keep", batch_id=1, x=400.0, width=80.0)
    drop = DanmuItem("drop", batch_id=9, x=500.0, width=80.0)
    track.items = [keep, drop]
    engine._rebuild_visibility_counts()

    removed = engine.drop_items_with_batch_id(9)

    assert removed == 1
    assert len(track.items) == 1
    assert track.items[0].content == "keep"


def test_drop_items_below_scene_generation_forgets_dedup(engine):
    from app.danmu_engine import DanmuItem

    engine.screen_width = 1000.0
    track = engine.tracks[0]
    old = DanmuItem("old-gen", scene_generation=0, x=400.0, width=80.0)
    track.items = [old]
    engine._remember_content("old-gen")
    engine._rebuild_visibility_counts()

    dropped = engine.drop_items_below_scene_generation(1)

    assert dropped == 1
    assert engine._is_duplicate("old-gen") is False


def test_ai_reply_queue_uses_request_context_and_fifos_results():
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        ai_in_flight=1,
        screenshot_round=10,
        _latest_screenshot_id=10,
    )
    app.reply_timer.active = False

    now = time.monotonic()
    app._on_ai_reply('["A1", "A2"]', "persona-1", 10, 10, now, 0)
    app._on_ai_reply('["B1"]', "persona-2", 11, 11, now, 0)

    assert app.reply_buffer.size() == 7

    assert app.engine.calls == [
        ("A1", "persona-1"),
        ("B1", "persona-2"),
    ]
    assert app.history_writer.calls == [
        ("A1", "persona-1", 10, None),
        ("B1", "persona-2", 11, None),
    ]
