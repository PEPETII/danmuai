import time

import pytest
from app.config_store import ConfigStore
from app.danmu_engine import (
    DanmuEngine,
    DanmuItem,
    clamp_danmu_lines,
    is_persona_name_prefix_enabled,
    layout_height_ratio,
    normalize_danmu_display_text,
    normalize_layout_mode,
    resolve_danmu_display_text,
    resolve_danmu_max_chars,
)
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig


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


def test_add_text_keeps_full_text_regardless_of_max_chars(engine):
    engine.config.set("danmu_max_chars", "8")
    item = engine.add_text("一二三四五六七八九十")
    assert item is not None
    assert item.content == "一二三四五六七八九十"


def test_resolve_danmu_display_text_without_prefix(engine):
    engine.config.set("persona_name_prefix_enabled", "0")
    assert resolve_danmu_display_text("你好世界", engine.config, "吐槽型") == "你好世界"


def test_resolve_danmu_display_text_with_prefix(engine):
    engine.config.set("persona_name_prefix_enabled", "1")
    assert resolve_danmu_display_text("你好世界", engine.config, "吐槽型") == "吐槽型：你好世界"


def test_resolve_danmu_display_text_keeps_full_body_before_prefix(engine):
    engine.config.set("persona_name_prefix_enabled", "1")
    engine.config.set("danmu_max_chars", "5")
    assert resolve_danmu_display_text("一二三四五六", engine.config, "吐槽型") == "吐槽型：一二三四五六"


def test_is_persona_name_prefix_enabled_parses_truthy_values(engine):
    engine.config.set("persona_name_prefix_enabled", "on")
    assert is_persona_name_prefix_enabled(engine.config) is True
    engine.config.set("persona_name_prefix_enabled", "0")
    assert is_persona_name_prefix_enabled(engine.config) is False


def test_add_text_pre_resolved_skips_renormalize(engine):
    engine.config.set("danmu_max_chars", "4")
    prefixed = "吐槽型：这是一段很长的弹幕正文"
    item = engine.add_text(prefixed, persona="吐槽型", pre_resolved=True, skip_dedup=True)
    assert item is not None
    assert item.content == prefixed


def test_add_text_keeps_custom_pool_line_untruncated(engine):
    long_line = "这是一句保存于公式化弹幕库的超长句子应完整上屏展示"
    engine.config.set("danmu_max_chars", "8")
    engine.config.set_custom_danmu_pool([long_line])
    item = engine.add_text(long_line, skip_dedup=True)
    assert item is not None
    assert item.content == long_line


def test_add_text_keeps_meme_barrage_line_untruncated(engine):
    long_line = "瓦批的一天：查看商店，练呲水枪，打开麻麻模拟器，启动！"
    engine.config.set("danmu_max_chars", "8")
    engine.config.meme_barrage_library_insert_many(
        [(long_line, None, None)],
        collected_at=0.0,
        max_rows=10_000,
    )
    item = engine.add_text(long_line, skip_dedup=True)
    assert item is not None
    assert item.content == long_line


def test_add_text_register_exception_rolls_back_track(engine, monkeypatch):
    """BUG-P1-005: _register_item 异常时须从 track 回滚，避免计数不一致。"""
    before_count = engine._total_item_count

    def _boom(_track, _item):
        raise RuntimeError("simulated register failure")

    monkeypatch.setattr(engine, "_register_item", _boom)

    with pytest.raises(RuntimeError, match="simulated"):
        engine.add_text("rollback-test", skip_dedup=True)

    assert sum(len(t.items) for t in engine.tracks) == 0
    assert engine._total_item_count == before_count


def test_resolve_danmu_max_chars_defaults_and_clamp(engine):
    engine.config.set("danmu_max_chars", "")
    assert resolve_danmu_max_chars(engine.config, lang="zh") == 20
    assert resolve_danmu_max_chars(engine.config, lang="en") == 50
    engine.config.set("danmu_max_chars", "15")
    assert resolve_danmu_max_chars(engine.config, lang="en") == 50
    assert resolve_danmu_max_chars(engine.config, lang="zh") == 20
    engine.config.set("danmu_max_chars", "28")
    assert resolve_danmu_max_chars(engine.config, lang="en") == 28
    engine.config.set("danmu_max_chars", "99")
    assert resolve_danmu_max_chars(engine.config) == 80
    engine.config.set("danmu_max_chars", "2")
    assert resolve_danmu_max_chars(engine.config) == 5


def test_normalize_danmu_display_text_strips_only(engine):
    engine.config.set("danmu_max_chars", "")
    long_en = "This is definitely longer than fifteen chars"
    assert (
        normalize_danmu_display_text(long_en, engine.config, lang="en") == long_en
    )
    engine.config.set("danmu_max_chars", "15")
    assert (
        normalize_danmu_display_text(long_en, engine.config, lang="en") == long_en
    )
    engine.config.set("danmu_max_chars", "8")
    assert (
        normalize_danmu_display_text(long_en, engine.config, lang="en") == long_en
    )


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


def test_ai_reply_queue_uses_request_context_and_fifos_results():
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        ai_in_flight=1,
        screenshot_round=10,
        _latest_screenshot_id=10,
        config=FakeConfig({"normal_reply_count": "2"}),
    )
    app._sync_reply_batch_config = DanmuApp._sync_reply_batch_config.__get__(app, DanmuApp)
    app._on_ai_reply = DanmuApp._on_ai_reply.__get__(app, DanmuApp)
    app._register_request_meta = DanmuApp._register_request_meta.__get__(app, DanmuApp)
    app._register_request_meta(10, 10, 0, "visual")  # W-RACE-001: 需预注册 meta
    app._register_request_meta(11, 11, 0, "visual")  # W-RACE-001: 需预注册 meta
    app._sync_reply_batch_config()
    app.reply_timer.active = False

    now = time.monotonic()
    app._on_ai_reply('["A1", "A2"]', "persona-1", 10, 10, now, 0)
    app._on_ai_reply('["B1"]', "persona-2", 11, 11, now, 0)

    # 每批 2 条；每次 _on_ai_reply 消费队首 1 条 → A1、A2 上屏后 B1 留在队尾
    assert app.reply_buffer.size() == 1
    assert app.engine.calls == [
        ("A1", "persona-1"),
        ("A2", "persona-1"),
    ]
    assert any(
        item.content == "B1" and item.persona_id == "persona-2"
        for item in app.reply_buffer._items
    )
    assert app.history_writer.calls == [
        ("A1", "persona-1", 10, None),
        ("A2", "persona-1", 10, None),
    ]


def _seed_many_visible(engine: DanmuEngine, n: int) -> None:
    for i in range(n):
        track = engine.tracks[i % len(engine.tracks)]
        track.add(DanmuItem(content=f"d{i}", x=200.0 + (i % 40) * 35.0, width=80.0))
    engine._rebuild_visibility_counts()


def test_rebuild_visibility_counts_correct_after_reload_tracks(workspace_tmp):
    """BUG-034: preserve reload must keep visible / right-zone counts consistent."""
    store = ConfigStore(db_path=workspace_tmp / "reload_vis.db")
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "4")
    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks(preserve_visible=False)

    engine.tracks[0].add(DanmuItem(content="left", x=400.0, width=80.0))
    engine.tracks[1].add(DanmuItem(content="right", x=1500.0, width=80.0))
    engine.tracks[2].add(DanmuItem(content="pending", x=2000.0, width=80.0))
    engine.tracks[3].add(DanmuItem(content="fade", x=1850.0, width=80.0))
    engine._rebuild_visibility_counts()

    assert engine.visible_display_count() == 3
    assert engine.right_visible_count() == 2
    assert engine.items_in_fade_zone() is True

    engine.reload_tracks(preserve_visible=True)

    assert engine.visible_display_count() == 3
    assert engine.right_visible_count() == 2
    assert engine.items_in_fade_zone() is True
    contents = {item.content for track in engine.tracks for item in track.items}
    assert contents == {"left", "right", "pending", "fade"}


def test_visible_display_count_skips_rebuild_when_counts_fresh(engine):
    """BUG-034: fresh visibility cache must not O(n) rebuild on every read."""
    engine.tracks[0].add(DanmuItem(content="on-screen", x=400.0, width=80.0))
    engine._rebuild_visibility_counts()

    rebuild_calls: list[int] = []
    original_rebuild = engine._rebuild_visibility_counts

    def counting_rebuild() -> None:
        rebuild_calls.append(1)
        return original_rebuild()

    engine._rebuild_visibility_counts = counting_rebuild  # type: ignore[method-assign]

    for _ in range(50):
        engine.visible_display_count()

    assert rebuild_calls == []


def test_deficit_below_min_skips_rebuild_when_counts_fresh(engine):
    """BUG-034: fresh visibility cache must not O(n) rebuild on deficit_below_min."""
    engine.config.set("min_on_screen", "5")
    engine.tracks[0].add(DanmuItem(content="on-screen", x=400.0, width=80.0))
    engine._rebuild_visibility_counts()

    rebuild_calls: list[int] = []
    original_rebuild = engine._rebuild_visibility_counts

    def counting_rebuild() -> None:
        rebuild_calls.append(1)
        return original_rebuild()

    engine._rebuild_visibility_counts = counting_rebuild  # type: ignore[method-assign]

    for _ in range(50):
        engine.deficit_below_min()

    assert rebuild_calls == []


def test_needs_refill_rebuilds_when_visibility_stale(engine):
    """needs_refill() rebuilds only when visibility counts are stale (BUG-070)."""
    engine.tracks[0].add(DanmuItem(content="one", x=400.0, width=80.0))
    engine._rebuild_visibility_counts()
    assert not engine._visibility_stale

    rebuild_calls: list[int] = []
    original_rebuild = engine._rebuild_visibility_counts

    def counting_rebuild() -> None:
        rebuild_calls.append(1)
        return original_rebuild()

    engine._rebuild_visibility_counts = counting_rebuild  # type: ignore[method-assign]

    engine.config.set("danmu_pool_use_custom", "1")
    engine.config.set("min_on_screen", "5")
    engine.needs_refill()
    assert rebuild_calls == []

    engine._mark_visibility_stale()
    engine.needs_refill()
    assert len(rebuild_calls) >= 1
