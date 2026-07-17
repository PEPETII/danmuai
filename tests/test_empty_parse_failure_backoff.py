"""BUG-V2-004: empty normalized visual replies must not reset failure backoff."""

import time

import pytest

from app.application import generation_pipeline as gen_pipeline_mod
from tests.conftest import make_minimal_danmu_app


def _register_visual_reply(app) -> None:
    app.ai_in_flight = 1
    app._register_request_meta(10, 10, 0, "visual")


def _deliver_visual_reply(
    app,
    text: str = "provider payload",
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
) -> None:
    app._on_ai_reply(
        text,
        "persona-1",
        request_round=10,
        screenshot_id=10,
        captured_at=time.monotonic(),
        scene_generation=0,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def test_generation_pipeline_reports_empty_normalized_result(monkeypatch):
    app = make_minimal_danmu_app()
    monkeypatch.setattr(
        gen_pipeline_mod,
        "parse_ai_reply_payload",
        lambda _text: ["raw candidate"],
    )
    monkeypatch.setattr(
        gen_pipeline_mod,
        "normalize_reply_batch",
        lambda _raw_items, **_kwargs: [],
    )

    accepted = app._generation_pipeline.handle_reply_parsed(
        text="provider payload",
        persona_id="persona-1",
        request_round=10,
        screenshot_id=10,
        captured_at=1.0,
        scene_generation=0,
        request_started_at=2.0,
        reply_received_at=3.0,
    )

    assert accepted is False
    assert app.reply_buffer.is_empty()
    assert any("empty_parse" in msg for msg in app.logger.warning_messages)


@pytest.mark.parametrize(
    ("paused", "timer_active"),
    [
        (True, False),
        (False, True),
    ],
)
def test_empty_normalized_visual_reply_preserves_failure_backoff(
    monkeypatch,
    paused,
    timer_active,
):
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._consecutive_failures = 4
    app._failure_backoff_paused = paused
    app._last_error_message = "previous error"
    app.screenshot_timer.active = timer_active
    _register_visual_reply(app)
    monkeypatch.setattr(
        gen_pipeline_mod,
        "parse_ai_reply_payload",
        lambda _text: ["raw candidate"],
    )
    monkeypatch.setattr(
        gen_pipeline_mod,
        "normalize_reply_batch",
        lambda _raw_items, **_kwargs: [],
    )

    _deliver_visual_reply(app, input_tokens=7, output_tokens=3)

    assert app._consecutive_failures == 4
    assert app._failure_backoff_paused is paused
    assert app._last_error_message == "previous error"
    assert app.screenshot_timer.active is timer_active
    assert app.reply_buffer.is_empty()
    assert app.stats_state.total_input_tokens == 7
    assert app.stats_state.total_output_tokens == 3
    assert any("empty_parse" in msg for msg in app.logger.warning_messages)


def test_nonempty_plain_text_visual_reply_resets_failure_backoff():
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._consecutive_failures = 4
    app._failure_backoff_paused = True
    app._last_error_message = "previous error"
    app.screenshot_timer.active = False
    _register_visual_reply(app)

    _deliver_visual_reply(app, text="not-json but valid plain text")

    assert app._consecutive_failures == 0
    assert app._failure_backoff_paused is False
    assert app._last_error_message == ""
    assert app.screenshot_timer.active is True
    assert app.engine.calls
    assert app.engine.calls[0][0] == "not-json but valid plain text"
