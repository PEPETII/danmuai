import time
from unittest.mock import Mock

import pytest
from app.mic_prompt import mic_insert_reply_count
from main import BatchTracker, DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig


def _bind_main_methods(app):
    for name in (
        "_reply_request_id",
        "_register_request_meta",
        "_pop_request_meta",
        "_release_inflight_for_source",
        "_enqueue_reply_batch",
        "_handle_mic_ai_reply",
        "_on_ai_reply",
        "_on_ai_error",
        "_default_batch_interval",
        "_consume_request_timing",
        "_publish_live_status",
        "_consume_reply_queue",
    ):
        setattr(app, name, getattr(DanmuApp, name).__get__(app, DanmuApp))
    app.logger = Mock()
    app.personae = Mock()
    app.personae.pick_random = Mock(return_value="persona-1")
    app._queue_capacity = lambda: 8


@pytest.fixture
def app():
    instance = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(instance)
    _bind_main_methods(instance)
    instance._latest_screenshot_id = 10
    instance._latest_requested_screenshot_id = 10
    instance._latest_queued_screenshot_id = 0
    instance._scene_generation = 0
    return instance


def test_mic_enqueue_does_not_reset_batch_tracker(app):
    batch = BatchTracker(99)
    batch.next_generation_time = 12345.0
    app._current_batch = batch
    app._batch_id = 7

    app._enqueue_reply_batch(
        "persona-1",
        -1,
        10,
        time.monotonic(),
        0,
        ["接话1", "接话2", "a", "b", "c"],
        from_mic_insert=True,
    )

    assert app._current_batch is batch
    assert app._current_batch.next_generation_time == 12345.0
    queued = list(app.reply_buffer._items)
    assert queued
    assert all(item.source == "mic" for item in queued)
    assert all(item.replaceable is False for item in queued)


def test_on_ai_reply_mic_does_not_decrement_visual_inflight(app):
    app.ai_in_flight = 1
    app.mic_in_flight = 1
    app._register_request_meta(-1, 10, 0, "mic")
    app._consume_reply_queue = lambda: None
    app._on_ai_reply('["m1","m2","m3","m4","m5"]', "persona-1", -1, 10, time.monotonic(), 0)
    assert app.ai_in_flight == 1
    assert app.mic_in_flight == 0
    assert app.reply_buffer.size() == 5
    assert mic_insert_reply_count(app.config) == 5


def test_on_ai_error_mic_does_not_increment_failures(app):
    app._consecutive_failures = 0
    app._register_request_meta(-2, 10, 0, "mic")
    app._on_ai_error("mic failed", "persona-1", -2, 10, time.monotonic(), 0)
    assert app._consecutive_failures == 0


def test_visual_on_ai_reply_still_decrements_ai_inflight(app):
    app.ai_in_flight = 1
    app._is_generating = True
    app._register_request_meta(5, 10, 0, "visual")
    app._on_ai_reply('["v1","v2","v3","v4","v5"]', "persona-1", 5, 10, time.monotonic(), 0)
    assert app.ai_in_flight == 0
    assert app._is_generating is False


def test_mic_ai_reply_parses_object_envelope(app):
    app.config = FakeConfig({})
    app._consume_reply_queue = lambda: None

    raw = (
        '{"scene_brief": "用户在说话", '
        '"comments": ["mic1", "mic2", "mic3", "mic4", "mic5"]}'
    )
    app._handle_mic_ai_reply(raw, "persona-1", -1, 10, time.monotonic(), 0)

    assert app.reply_buffer.size() == 5


def test_mic_ai_reply_shortfall_pads_to_five(app, monkeypatch):
    app.config = FakeConfig({})
    app._consume_reply_queue = lambda: None
    monkeypatch.setattr("app.reply_parser._scene_fillers", lambda config=None: ["scene-a", "scene-b"])
    monkeypatch.setattr(
        "app.reply_parser._generic_fillers",
        lambda config=None: ["generic-a", "generic-b", "generic-c"],
    )

    app._handle_mic_ai_reply('["mic1", "mic2"]', "persona-1", -1, 10, time.monotonic(), 0)

    queued = [item.content for item in app.reply_buffer._items]
    assert len(queued) == mic_insert_reply_count(app.config)
    assert queued[:2] == ["mic1", "mic2"]
    assert len(queued) == len(set(queued))
