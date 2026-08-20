"""MIC-SESSION-ISOLATION: stop→start must not let stale mic workers touch new session."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import main as main_mod
import pytest
from app.main_helpers import (
    MIC_REQUEST_EPOCH_STRIDE,
    mic_capture_epoch_from_round,
    mic_request_round,
    mic_request_seq_from_round,
    reply_request_id,
)

from tests.conftest import make_minimal_danmu_app
from tests.fakes import FakeLogger


def _bind_mic_callbacks(app) -> None:
    app._on_ai_reply = main_mod.DanmuApp._on_ai_reply.__get__(app, main_mod.DanmuApp)
    app._on_ai_error = main_mod.DanmuApp._on_ai_error.__get__(app, main_mod.DanmuApp)
    app.logger = FakeLogger()


def test_mic_request_round_encodes_capture_session_epoch():
    assert mic_request_round(1, 0) == -1
    assert mic_request_round(2, 0) == -2
    assert mic_request_round(1, 3) == -(1 + 3 * MIC_REQUEST_EPOCH_STRIDE)
    assert mic_request_seq_from_round(mic_request_round(7, 4)) == 7
    assert mic_capture_epoch_from_round(mic_request_round(7, 4)) == 4


def test_stop_start_mic_rounds_do_not_share_request_identity():
    old_epoch = 2
    new_epoch = 4
    screenshot_id = 10
    scene_generation = 0

    old_round = mic_request_round(1, old_epoch)
    new_round = mic_request_round(1, new_epoch)

    assert old_round != new_round
    assert reply_request_id(old_round, screenshot_id, scene_generation) != reply_request_id(
        new_round, screenshot_id, scene_generation
    )


@pytest.mark.parametrize(
    ("kind", "callback"),
    [
        ("reply", lambda app, rr, sid, sg: app._on_ai_reply(
            '["stale mic"]', "persona-1", rr, sid, time.monotonic(), sg
        )),
        ("error", lambda app, rr, sid, sg: app._on_ai_error(
            "mic timeout", "persona-1", rr, sid, time.monotonic(), sg
        )),
    ],
)
def test_stale_mic_callback_does_not_touch_new_session(kind, callback):
    app = make_minimal_danmu_app()
    _bind_mic_callbacks(app)

    old_epoch = 2
    new_epoch = 5
    screenshot_id = 10
    scene_generation = 0
    old_round = mic_request_round(1, old_epoch)
    new_round = mic_request_round(1, new_epoch)

    app._capture_session_epoch = new_epoch
    app.mic_in_flight = 1
    app._register_request_meta(new_round, screenshot_id, scene_generation, "mic")

    enqueue_calls: list = []
    app._enqueue_reply_batch = MagicMock(side_effect=lambda *a, **k: enqueue_calls.append((a, k)))
    app._consume_reply_queue = MagicMock()
    app._publish_live_status = MagicMock()
    app._consume_request_timing = MagicMock()
    app._release_inflight_for_source = MagicMock()

    callback(app, old_round, screenshot_id, scene_generation)

    assert app.mic_in_flight == 1
    assert app._pending_request_meta == {
        reply_request_id(new_round, screenshot_id, scene_generation): {"source": "mic"},
    }
    assert app._enqueue_reply_batch.call_count == 0
    assert app._release_inflight_for_source.call_count == 0
    assert any("stale_mic_callback_dropped" in msg for msg in app.logger.warning_messages)


def test_new_mic_callback_after_stop_start_consumes_current_session_meta():
    app = make_minimal_danmu_app()
    _bind_mic_callbacks(app)

    epoch = 6
    screenshot_id = 12
    scene_generation = 1
    request_round = mic_request_round(1, epoch)

    app._capture_session_epoch = epoch
    app.mic_in_flight = 1
    app._register_request_meta(request_round, screenshot_id, scene_generation, "mic")
    app._consume_reply_queue = MagicMock()
    app._publish_live_status = MagicMock()

    app._on_ai_reply(
        '["fresh mic"]',
        "persona-1",
        request_round,
        screenshot_id,
        time.monotonic(),
        scene_generation,
    )

    assert app.mic_in_flight == 0
    assert app._pending_request_meta == {}
    assert app.reply_buffer.size() >= 1


def test_stale_mic_error_does_not_clear_new_inflight():
    app = make_minimal_danmu_app()
    _bind_mic_callbacks(app)

    old_round = mic_request_round(1, 1)
    new_round = mic_request_round(1, 4)
    screenshot_id = 8
    scene_generation = 0

    app._capture_session_epoch = 4
    app.mic_in_flight = 1
    app._register_request_meta(new_round, screenshot_id, scene_generation, "mic")
    app._publish_live_status = MagicMock()
    app._consume_request_timing = MagicMock()

    app._on_ai_error(
        "late mic failure",
        "persona-1",
        old_round,
        screenshot_id,
        time.monotonic(),
        scene_generation,
    )

    assert app.mic_in_flight == 1
    assert app._consume_request_timing.call_count == 0
    assert any("stale_mic_callback_dropped" in msg for msg in app.logger.warning_messages)
