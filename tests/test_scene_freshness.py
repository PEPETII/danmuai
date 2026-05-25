"""Scene generation freshness integration on DanmuApp."""

import time
from unittest.mock import Mock

from app.reply_queue import QueuedReply

from tests.test_p0_main_flow import FakeCapturer, FakePixmap, _make_minimal_app


def _patch_fingerprint(monkeypatch, values: list[int]):
    """Return successive fingerprints from fake pixmap.scene_byte."""
    seq = iter(values)

    def fake_fp(pixmap, probe_size=64):
        if hasattr(pixmap, "scene_byte"):
            return next(seq, pixmap.scene_byte)
        return next(seq, 0)

    monkeypatch.setattr("main.fingerprint_from_pixmap", fake_fp)


def test_first_capture_establishes_baseline_no_generation(monkeypatch):
    app = _make_minimal_app()
    app.engine.running = True
    _patch_fingerprint(monkeypatch, [0xAAAAAAAAAAAAAAAA])
    app.capturer = FakeCapturer(FakePixmap(0))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app._last_scene_hash == 0xAAAAAAAAAAAAAAAA


def test_scene_change_bumps_generation_and_clears_buffer(monkeypatch):
    app = _make_minimal_app()
    app.engine.running = True
    app._last_scene_hash = 0xAAAAAAAAAAAAAAAA
    app._scene_generation = 0
    app.reply_buffer.push(
        QueuedReply("p", 0, 0, "old", screenshot_id=1, scene_generation=0)
    )
    _patch_fingerprint(monkeypatch, [0x5555555555555555])
    app.capturer = FakeCapturer(FakePixmap(1))

    app._capture_screenshot()

    assert app._scene_generation == 1
    assert app.reply_buffer.is_empty()


def test_capture_during_in_flight_still_detects_scene_change(monkeypatch):
    app = _make_minimal_app()
    app.engine.running = True
    app._last_scene_hash = 0xAAAAAAAAAAAAAAAA
    app._scene_generation = 0
    app.ai_in_flight = 1
    app._is_generating = True
    app._latest_screenshot_id = 3
    _patch_fingerprint(monkeypatch, [0x5555555555555555])
    app.capturer = FakeCapturer(FakePixmap(1))

    app._capture_screenshot()

    assert app._scene_generation == 1
    assert app._latest_screenshot_id == 4


def test_on_ai_reply_stale_scene_in_flight_not_enqueued(monkeypatch):
    app = _make_minimal_app()
    app.ai_in_flight = 1
    app._scene_generation = 2

    app._on_ai_reply('["stale"]', "persona-1", 10, 10, time.monotonic(), 1)

    assert app.reply_buffer.is_empty()
    assert app._stale_scene_inflight_drop_count == 1
    assert any("stale_scene_in_flight" in m for m in app.logger.info_messages)


def test_consume_stale_scene_not_displayed():
    app = _make_minimal_app()
    app._scene_generation = 3
    app.reply_buffer.push(
        QueuedReply("p", 1, 0, "queued old", screenshot_id=5, scene_generation=1)
    )

    app._consume_reply_queue()

    assert app.engine.calls == []
    assert app._stale_scene_consume_drop_count == 1


def test_strict_scene_change_drops_on_screen_batch(monkeypatch):
    app = _make_minimal_app()
    app.config.values["freshness"] = "strict"
    app.engine.running = True
    app._current_batch = Mock(batch_id=7)
    app.engine.clear_dedup_window = Mock()
    app.engine.drop_pending_below_generation = Mock(return_value=0)
    app.engine.drop_items_below_scene_generation = Mock(return_value=2)
    app.engine.drop_items_with_batch_id = Mock(return_value=1)
    app._last_scene_hash = 0xAAAAAAAAAAAAAAAA
    _patch_fingerprint(monkeypatch, [0x5555555555555555])
    app.capturer = FakeCapturer(FakePixmap(1))

    app._capture_screenshot()

    assert app._scene_generation == 1
    app.engine.drop_items_below_scene_generation.assert_called_once_with(1)
    app.engine.drop_items_with_batch_id.assert_called_once_with(7)
    assert app._current_batch is None
    assert app._scene_api_gate_active is True


def test_medium_scene_change_clears_dedup_and_pending(monkeypatch):
    app = _make_minimal_app()
    app.config.values["freshness"] = "medium"
    app.engine.running = True
    app._current_batch = Mock(batch_id=7)
    app.engine.clear_dedup_window = Mock()
    app.engine.drop_pending_below_generation = Mock(return_value=1)
    app.engine.drop_items_with_batch_id = Mock(return_value=0)
    app._last_scene_hash = 0xAAAAAAAAAAAAAAAA
    _patch_fingerprint(monkeypatch, [0x5555555555555555])
    app.capturer = FakeCapturer(FakePixmap(1))

    app._capture_screenshot()

    assert app._scene_generation == 1
    app.engine.clear_dedup_window.assert_called_once()
    app.engine.drop_pending_below_generation.assert_called_once_with(1)
    app.engine.drop_items_with_batch_id.assert_not_called()
    assert app._current_batch is None


def test_scene_api_blocked_until_pause_and_capture(monkeypatch):
    app = _make_minimal_app()
    app.config.values["freshness"] = "medium"
    app.engine.running = True
    app._scene_generation = 1
    app._scene_rhythm_pause_until = time.monotonic() + 10.0
    app._scene_api_gate_active = True
    app._scene_captures_after_change = 0

    assert app._scene_api_blocked() is True

    app._scene_rhythm_pause_until = 0.0
    assert app._scene_api_blocked() is True

    app._scene_captures_after_change = 1
    assert app._scene_api_blocked() is False
    assert app._scene_api_gate_active is False


def test_rhythm_skips_api_while_scene_gate_active(monkeypatch):
    app = _make_minimal_app()
    app.config.values["freshness"] = "medium"
    app.engine.running = True
    app._scene_rhythm_pause_until = time.monotonic() + 10.0
    app._scene_api_gate_active = True
    app._trigger_api_call = Mock()

    app._check_rhythm_trigger()

    app._trigger_api_call.assert_not_called()


def test_loose_scene_change_does_not_clear_dedup(monkeypatch):
    app = _make_minimal_app()
    app.config.values["freshness"] = "loose"
    app.engine.running = True
    app.engine.clear_dedup_window = Mock()
    app._last_scene_hash = 0xAAAAAAAAAAAAAAAA
    _patch_fingerprint(monkeypatch, [0x5555555555555555])
    app.capturer = FakeCapturer(FakePixmap(1))

    app._capture_screenshot()

    assert app._scene_generation == 1
    app.engine.clear_dedup_window.assert_not_called()
    assert app._scene_api_gate_active is False
