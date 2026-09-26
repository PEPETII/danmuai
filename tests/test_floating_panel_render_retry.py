"""P2-06 W-AUDIT-FP-RETRY-001: bound floating-panel render retries."""
from __future__ import annotations

from app.application.generation_pipeline import FLOATING_PANEL_RENDER_RETRY_LIMIT
from app.reply_queue import QueuedReply
from main import DanmuApp

from tests.test_floating_panel_consume import _floating_panel_app, _queued


def test_queued_reply_render_retry_metadata_defaults_to_zero():
    queued = QueuedReply("p1", 1, 0, "retry-me")

    assert queued.render_retry_count == 0


def test_floating_panel_render_failure_retries_then_advances_queue(
    workspace_tmp, qapp, monkeypatch
):
    app, _fp_engine, overlay = _floating_panel_app(workspace_tmp, qapp)

    def fail_add(*_args, **_kwargs):
        return None

    monkeypatch.setattr(overlay, "add_danmu_text", fail_add)
    app.reply_buffer.push(_queued("retry-me", 0))
    app.reply_buffer.push(_queued("after-retry", 1))

    for expected_retry_count in range(1, FLOATING_PANEL_RENDER_RETRY_LIMIT + 1):
        DanmuApp._consume_reply_queue(app)
        queued = app.reply_buffer.peek()
        assert queued is not None
        assert queued.content == "retry-me"
        assert queued.render_retry_count == expected_retry_count
        assert app.reply_buffer.size() == 2

    DanmuApp._consume_reply_queue(app)

    queued = app.reply_buffer.peek()
    assert queued is not None
    assert queued.content == "after-retry"
    assert queued.render_retry_count == 0
    assert app.reply_buffer.size() == 1
