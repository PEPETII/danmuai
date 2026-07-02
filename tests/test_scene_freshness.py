"""Screenshot capture in normal-only mode and scene_generation stale reply policy."""

import time
from unittest.mock import MagicMock

from app.reply_queue import QueuedReply

from tests.conftest import make_minimal_danmu_app
from tests.fakes import FakeCapturer, FakeLogger, FakePixmap


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


def test_stale_reply_dropped_when_scene_generation_lagged(monkeypatch):
    import main as main_mod

    app = make_minimal_danmu_app()
    app.logger = FakeLogger()
    app.engine.running = True
    app.ai_in_flight = 1
    app._scene_generation = 2
    app._register_request_meta(10, 10, 1, "visual")
    monkeypatch.setattr(main_mod, "parse_ai_reply_payload", lambda text: ["ok"])
    monkeypatch.setattr(main_mod, "normalize_reply_batch", lambda raw_items, **kwargs: raw_items)
    app._on_ai_reply = main_mod.DanmuApp._on_ai_reply.__get__(app, main_mod.DanmuApp)
    app._enqueue_reply_batch = MagicMock()
    app._consume_reply_queue = lambda: None
    app._publish_live_status = lambda: None
    app._scene_refresh_wanted = True
    schedule_calls = []
    app._schedule_capture = lambda: schedule_calls.append(1)

    app._on_ai_reply('["ok"]', "persona-1", 10, 10, time.monotonic(), 1)

    assert app.reply_buffer.is_empty()
    assert app._enqueue_reply_batch.call_count == 0
    assert app.ai_in_flight == 0
    assert schedule_calls == [1]
    assert any("stale_reply_dropped" in msg for msg in app.logger.warning_messages)
    assert any("scene_generation_lagged" in msg for msg in app.logger.warning_messages)


def test_fresh_reply_enqueues_when_scene_generation_matches(monkeypatch):
    import main as main_mod

    app = make_minimal_danmu_app()
    app.logger = FakeLogger()
    app.ai_in_flight = 1
    app._scene_generation = 2
    app._register_request_meta(10, 10, 2, "visual")
    monkeypatch.setattr(main_mod, "parse_ai_reply_payload", lambda text: ["ok"])
    monkeypatch.setattr(main_mod, "normalize_reply_batch", lambda raw_items, **kwargs: raw_items)
    app._on_ai_reply = main_mod.DanmuApp._on_ai_reply.__get__(app, main_mod.DanmuApp)
    app._consume_reply_queue = lambda: None
    app._publish_live_status = lambda: None
    app._notify_pet_visual_success = lambda: None

    app._on_ai_reply('["ok"]', "persona-1", 10, 10, time.monotonic(), 2)

    assert not app.reply_buffer.is_empty()
    assert not any("stale_reply_dropped" in msg for msg in app.logger.warning_messages)


def test_mic_reply_not_dropped_when_scene_generation_lagged(monkeypatch):
    import main as main_mod

    app = make_minimal_danmu_app()
    app.logger = FakeLogger()
    app.ai_in_flight = 1
    app.mic_in_flight = 1
    app._scene_generation = 2
    app._register_request_meta(-1, 10, 0, "mic")
    app._on_ai_reply = main_mod.DanmuApp._on_ai_reply.__get__(app, main_mod.DanmuApp)
    app._handle_mic_ai_reply = MagicMock()
    app._consume_reply_queue = lambda: None

    app._on_ai_reply('["m1"]', "persona-1", -1, 10, time.monotonic(), 0)

    assert app._handle_mic_ai_reply.call_count == 1
    assert not any("stale_reply_dropped" in msg for msg in app.logger.warning_messages)
    assert app.ai_in_flight == 1
    assert app.mic_in_flight == 0


def test_bump_purges_queued_older_scene_generation(monkeypatch):
    from main import DanmuApp

    from tests.test_scene_generation_version import _scene_version_app

    app = _scene_version_app()
    app.logger = FakeLogger()
    app._on_scene_generation_bumped = DanmuApp._on_scene_generation_bumped.__get__(app, DanmuApp)
    monkeypatch.setattr("app.main_lifecycle_mixin.QTimer.singleShot", lambda _ms, cb: None)
    app._try_scene_refresh = lambda: None
    app.reply_buffer.push(
        QueuedReply("p", 1, 0, "queued old", screenshot_id=5, scene_generation=0)
    )

    app.config.set("live_topic", "新主题")
    app._on_config_changed()

    assert app._scene_generation == 1
    assert app.reply_buffer.is_empty()
    assert any("scene_queue_purged" in msg for msg in app.logger.info_messages)


def test_bump_purges_offscreen_engine_items(monkeypatch):
    from app.danmu_engine import DanmuEngine, DanmuItem
    from main import DanmuApp

    from tests.fakes import FakeConfig
    from tests.test_scene_generation_version import _scene_version_app

    app = _scene_version_app()
    app.logger = FakeLogger()
    app.engine = DanmuEngine(FakeConfig())
    app._on_scene_generation_bumped = DanmuApp._on_scene_generation_bumped.__get__(app, DanmuApp)
    monkeypatch.setattr("app.main_lifecycle_mixin.QTimer.singleShot", lambda _ms, cb: None)
    app._try_scene_refresh = lambda: None

    app.engine.screen_width = 1000.0
    track = app.engine.tracks[0]
    pending = DanmuItem("pending-old", scene_generation=0, x=1100.0, width=80.0)
    visible = DanmuItem("visible-old", scene_generation=0, x=400.0, width=80.0)
    track.items = [pending, visible]
    app.engine._rebuild_visibility_counts()

    app.config.set("live_topic", "新主题")
    app._on_config_changed()

    assert app._scene_generation == 1
    assert len(track.items) == 1
    assert track.items[0].content == "visible-old"
    assert any("scene_engine_purged" in msg for msg in app.logger.info_messages)


def test_bump_purges_ai_and_fallback_keeps_mic(monkeypatch):
    from main import DanmuApp

    from tests.test_scene_generation_version import _scene_version_app

    app = _scene_version_app()
    app.logger = FakeLogger()
    app._on_scene_generation_bumped = DanmuApp._on_scene_generation_bumped.__get__(app, DanmuApp)
    monkeypatch.setattr("app.main_lifecycle_mixin.QTimer.singleShot", lambda _ms, cb: None)
    app._try_scene_refresh = lambda: None
    app.reply_buffer.push(
        QueuedReply("p", 1, 0, "old-ai", source="ai", scene_generation=0)
    )
    app.reply_buffer.push(
        QueuedReply(
            "p",
            1,
            0,
            "old-fb",
            source="fallback",
            is_fallback=True,
            replaceable=True,
            scene_generation=0,
        )
    )
    app.reply_buffer.push(
        QueuedReply("p", 1, 0, "keep-mic", source="mic", scene_generation=0)
    )

    app.config.set("live_topic", "新主题")
    app._on_config_changed()

    assert app._scene_generation == 1
    assert app.reply_buffer.size() == 1
    assert app.reply_buffer.peek().content == "keep-mic"
    assert app.reply_buffer.peek().source == "mic"
    assert any("scene_queue_purged" in msg for msg in app.logger.info_messages)


def test_bump_purge_prevents_old_ai_from_displaying(monkeypatch):
    from main import DanmuApp

    from tests.test_scene_generation_version import _scene_version_app

    app = _scene_version_app()
    app._on_scene_generation_bumped = DanmuApp._on_scene_generation_bumped.__get__(app, DanmuApp)
    monkeypatch.setattr("app.main_lifecycle_mixin.QTimer.singleShot", lambda _ms, cb: None)
    app._try_scene_refresh = lambda: None
    app._consume_reply_queue = DanmuApp._consume_reply_queue.__get__(app, DanmuApp)
    app.reply_buffer.push(
        QueuedReply("p", 1, 0, "old-theme-ai", source="ai", scene_generation=0)
    )

    app.config.set("live_topic", "新主题")
    app._on_config_changed()

    assert app.reply_buffer.is_empty()
    app._consume_reply_queue()
    assert not app.engine.calls
