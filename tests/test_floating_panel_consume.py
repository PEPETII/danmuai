"""W-FP-STACK-PIPELINE-001：floating_panel 堆积消费与 reply 节奏集成测试。"""
from __future__ import annotations

import time

from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine
from app.floating_panel_engine import FloatingPanelEngine
from app.floating_panel_overlay import FloatingPanelOverlay
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply
from main import DanmuApp

from tests.conftest import FakeTimer, bind_minimal_danmu_app


def _floating_panel_app(workspace_tmp, qapp, **config_overrides):
    store = ConfigStore(db_path=workspace_tmp / "fp_consume.db")
    store.set("danmu_render_mode", "floating_panel")
    store.set("dedup_threshold", "1.0")
    for key, value in config_overrides.items():
        store.set(key, str(value))
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


def test_consume_joins_while_old_items_visible(workspace_tmp, qapp):
    """旧条目仍可见时新消息立即消费，不因空间回插/延迟。"""
    app, fp_engine, _overlay = _floating_panel_app(workspace_tmp, qapp)
    fp_engine.add_text("already-on-screen", item_height=40.0, skip_dedup=True)

    app.reply_buffer.push(_queued("queued-one", 0))
    app.reply_buffer.push(_queued("queued-two", 1))
    assert app.reply_buffer.size() == 2

    DanmuApp._consume_reply_queue(app)

    assert app.reply_buffer.size() == 1
    assert fp_engine.visible_count() == 2
    contents = [it.content for it in fp_engine.visible_items()]
    assert "already-on-screen" in contents
    assert "queued-one" in contents


def test_consume_drains_queue_without_space_wait(workspace_tmp, qapp):
    """连续批次在旧消息未越顶时逐条进入，无需推进滚动腾空间。"""
    app, fp_engine, _overlay = _floating_panel_app(workspace_tmp, qapp)
    height = 40.0
    stack_gap = float(app.config.get("floating_panel_stack_gap", "8") or 8)

    for idx, content in enumerate(("queue-alpha", "queue-beta", "queue-gamma")):
        app.reply_buffer.push(_queued(content, idx))

    for _ in range(5):
        if app.reply_buffer.is_empty():
            break
        DanmuApp._consume_reply_queue(app)

    assert app.reply_buffer.is_empty()
    assert fp_engine.visible_count() == 3
    for gap in _pairwise_stack_gaps(fp_engine):
        assert abs(gap - stack_gap) < 0.01


def test_consume_discards_duplicate_before_display(workspace_tmp, qapp):
    """peek 去重丢弃重复文本；旧条仍可见时也不再入场。"""
    app, fp_engine, _overlay = _floating_panel_app(workspace_tmp, qapp)
    assert fp_engine.add_text("dup-line", item_height=40.0) is not None
    assert fp_engine.visible_count() == 1

    app.reply_buffer.push(_queued("dup-line", 0))
    DanmuApp._consume_reply_queue(app)

    assert app.reply_buffer.is_empty()
    assert fp_engine.visible_count() == 1


def test_consume_discards_empty_text(workspace_tmp, qapp):
    app, fp_engine, _overlay = _floating_panel_app(workspace_tmp, qapp)
    app.reply_buffer.push(_queued("   ", 0))
    app.reply_buffer.push(_queued("keep-me", 1))

    DanmuApp._consume_reply_queue(app)

    assert app.reply_buffer.size() == 1
    assert app.reply_buffer.peek().content == "keep-me"
    assert fp_engine.visible_count() == 0


def test_consume_requeues_on_unexpected_display_failure(workspace_tmp, qapp, monkeypatch):
    """真实渲染失败仍可回插重试；非 spacing 拒因。"""
    app, fp_engine, overlay = _floating_panel_app(workspace_tmp, qapp)
    reasons: list[str] = []
    object.__setattr__(app, "_record_undisplayed", lambda reason, persona_id="": reasons.append(reason))

    def fail_add(*_a, **_k):
        return None

    monkeypatch.setattr(overlay, "add_danmu_text", fail_add)
    app.reply_buffer.push(_queued("retry-me", 0))

    DanmuApp._consume_reply_queue(app)

    assert app.reply_buffer.size() == 1
    assert app.reply_buffer.peek().content == "retry-me"
    assert fp_engine.visible_count() == 0
    assert "floating_panel_spacing" not in reasons
    assert "floating_panel_render" in reasons


def test_estimated_reply_gap_ms_floating_panel_uses_push_pace_not_spacing(
    workspace_tmp, qapp
):
    """floating gap 跟 push duration，不读 can_accept / 横向密度。"""
    app, fp_engine, _overlay = _floating_panel_app(
        workspace_tmp,
        qapp,
        floating_panel_push_duration_ms="180",
    )
    app.engine.visibility_counts = lambda: (999, 999)

    gap = app._estimated_reply_gap_ms()
    assert gap == 180
    assert gap >= 100
    assert gap <= 1000

    # 占位旧条后仍同一节奏，不切换到空间等待
    fp_engine.add_text("blocker", item_height=40.0, skip_dedup=True)
    gap_after = app._estimated_reply_gap_ms()
    assert gap_after == gap


def test_estimated_reply_gap_ms_floating_panel_floor_when_push_zero(workspace_tmp, qapp):
    app, _fp_engine, _overlay = _floating_panel_app(
        workspace_tmp,
        qapp,
        floating_panel_push_duration_ms="0",
    )
    assert app._estimated_reply_gap_ms() == 100


def _pairwise_stack_gaps(engine: FloatingPanelEngine) -> list[float]:
    items = sorted(
        [it for it in engine.visible_items() if not it.exiting],
        key=lambda it: it.target_y,
    )
    gaps: list[float] = []
    for idx in range(len(items) - 1):
        upper, lower = items[idx], items[idx + 1]
        gaps.append(lower.target_y - (upper.target_y + upper.height))
    return gaps
