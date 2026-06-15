"""Screenshot capture in normal-only mode."""

import time

from app.reply_queue import QueuedReply

from tests.conftest import make_minimal_danmu_app
from tests.fakes import FakeCapturer, FakePixmap


def test_capture_increments_screenshot_id_without_scene_bump():
    app = make_minimal_danmu_app()
    app.engine.running = True
    app.capturer = FakeCapturer(FakePixmap(0))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app._latest_screenshot_id == 1


def test_capture_always_advances_screenshot_id_even_when_in_flight():
    app = make_minimal_danmu_app()
    app.engine.running = True
    app.ai_in_flight = 1
    app._is_generating = True
    app._latest_screenshot_id = 3
    app.capturer = FakeCapturer(FakePixmap(1))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app._latest_screenshot_id == 4


def test_on_ai_reply_enqueues_despite_mismatched_scene_generation(monkeypatch):
    import main as main_mod

    app = make_minimal_danmu_app()
    app.ai_in_flight = 1
    app._scene_generation = 2
    app._register_request_meta(10, 10, 1, "visual")
    monkeypatch.setattr(main_mod, "parse_ai_reply_payload", lambda text: ["ok"])
    monkeypatch.setattr(main_mod, "normalize_reply_batch", lambda raw_items, **kwargs: raw_items)
    app._on_ai_reply = main_mod.DanmuApp._on_ai_reply.__get__(app, main_mod.DanmuApp)
    app._consume_reply_queue = lambda: None
    app._publish_live_status = lambda: None

    app._on_ai_reply('["ok"]', "persona-1", 10, 10, time.monotonic(), 1)

    assert not app.reply_buffer.is_empty()


def test_consume_does_not_drop_older_scene_generation():
    app = make_minimal_danmu_app()
    app._scene_generation = 3
    app.reply_buffer.push(
        QueuedReply("p", 1, 0, "queued old", screenshot_id=5, scene_generation=1)
    )

    app._consume_reply_queue()

    assert len(app.engine.calls) == 1
