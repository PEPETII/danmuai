"""W-FP-V3-003：floating_panel 主链路 consume 与 reply 节奏集成测试。"""
from __future__ import annotations

import time

from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine
from app.floating_panel_engine import FloatingPanelEngine
from app.floating_panel_overlay import FloatingPanelOverlay
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply
from main import DanmuApp

from tests.conftest import FakeTimer, bind_minimal_danmu_app


def _floating_panel_app(workspace_tmp, qapp):
    store = ConfigStore(db_path=workspace_tmp / "fp_consume.db")
    store.set("danmu_render_mode", "floating_panel")
    store.set("dedup_threshold", "1.0")
    fp_engine = FloatingPanelEngine(store)
    fp_engine.set_panel_height(400.0)
    overlay = FloatingPanelOverlay(store, fp_engine)
    overlay.resize(360, 400)
    qapp.processEvents()

    horiz = DanmuEngine(store)
    horiz.set_screen_width(1000.0)

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=store,
        engine=horiz,
        reply_buffer=AIReplyFIFOBuffer(max_items=8),
        reply_timer=FakeTimer(),
    )
    object.__setattr__(app, "floating_panel_engine", fp_engine)
    object.__setattr__(app, "floating_panel_overlay", overlay)
    object.__setattr__(app, "_maybe_pool_topup", lambda: 0)
    object.__setattr__(app, "_current_batch", None)
    app._danmu_render_mode = DanmuApp._danmu_render_mode.__get__(app, DanmuApp)
    app._display_danmu_text = DanmuApp._display_danmu_text.__get__(app, DanmuApp)
    app._consume_reply_queue = DanmuApp._consume_reply_queue.__get__(app, DanmuApp)
    app._estimated_reply_gap_ms = DanmuApp._estimated_reply_gap_ms.__get__(app, DanmuApp)
    return app, fp_engine, overlay


def _queued(content: str, index: int) -> QueuedReply:
    return QueuedReply(
        "p1",
        1,
        index,
        content,
        screenshot_round=1,
        screenshot_id=1,
        captured_at=time.monotonic(),
        scene_generation=0,
    )


def test_consume_defers_when_spacing_blocked(workspace_tmp, qapp):
    app, fp_engine, _overlay = _floating_panel_app(workspace_tmp, qapp)
    fp_engine.add_text("already-on-screen", item_height=40.0, skip_dedup=True)

    app.reply_buffer.push(_queued("queued-one", 0))
    app.reply_buffer.push(_queued("queued-two", 1))
    assert app.reply_buffer.size() == 2

    DanmuApp._consume_reply_queue(app)

    assert app.reply_buffer.size() == 2
    assert fp_engine.visible_count() == 1


def test_consume_drains_queue_with_scroll_ticks(workspace_tmp, qapp):
    app, fp_engine, _overlay = _floating_panel_app(workspace_tmp, qapp)
    height = 40.0
    min_gap = fp_engine.min_vertical_gap(height)

    for content in ("queue-alpha", "queue-beta", "queue-gamma"):
        app.reply_buffer.push(_queued(content, 0))

    for _ in range(300):
        if app.reply_buffer.is_empty():
            break
        before = app.reply_buffer.size()
        DanmuApp._consume_reply_queue(app)
        if app.reply_buffer.size() == before:
            fp_engine.update(0.05)

    assert app.reply_buffer.is_empty()
    assert fp_engine.visible_count() == 3
    for gap in _pairwise_vertical_gaps(fp_engine):
        assert gap >= min_gap - 0.01


def test_consume_discards_duplicate_before_display(workspace_tmp, qapp):
    app, fp_engine, _overlay = _floating_panel_app(workspace_tmp, qapp)
    fp_engine.add_text("dup-line", item_height=40.0)
    for _ in range(200):
        fp_engine.update(0.1)
        if fp_engine.visible_count() == 0:
            break

    app.reply_buffer.push(_queued("dup-line", 0))
    DanmuApp._consume_reply_queue(app)

    assert app.reply_buffer.is_empty()
    assert fp_engine.visible_count() == 0


def test_consume_requeues_on_unexpected_display_failure(workspace_tmp, qapp, monkeypatch):
    app, fp_engine, overlay = _floating_panel_app(workspace_tmp, qapp)

    def fail_add(*_a, **_k):
        return None

    monkeypatch.setattr(overlay, "add_danmu_text", fail_add)
    app.reply_buffer.push(_queued("retry-me", 0))

    DanmuApp._consume_reply_queue(app)

    assert app.reply_buffer.size() == 1
    assert app.reply_buffer.peek().content == "retry-me"
    assert fp_engine.visible_count() == 0


def test_estimated_reply_gap_ms_floating_panel_independent_of_horizontal_density(
    workspace_tmp, qapp
):
    app, fp_engine, _overlay = _floating_panel_app(workspace_tmp, qapp)
    app.engine.visibility_counts = lambda: (999, 999)

    assert app._estimated_reply_gap_ms() == 120

    fp_engine.add_text("blocker", item_height=40.0, skip_dedup=True)
    blocked_gap = app._estimated_reply_gap_ms()
    assert blocked_gap > 50
    assert blocked_gap < 1000


def _pairwise_vertical_gaps(engine: FloatingPanelEngine) -> list[float]:
    items = sorted(engine.visible_items(), key=lambda it: it.current_y)
    gaps: list[float] = []
    for idx in range(len(items) - 1):
        upper, lower = items[idx], items[idx + 1]
        gaps.append(lower.current_y - (upper.current_y + upper.height))
    return gaps
