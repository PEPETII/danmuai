"""W-THEME-LAG-REFRESH-001: scene refresh after theme/scene config bump."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, Mock

import main as main_mod
from app.application import generation_pipeline as gen_pipeline_mod
from app.reply_queue import QueuedReply
from main import DanmuApp

from tests.fakes import FakeCapturer, FakePixmap
from tests.test_scene_generation_version import _scene_version_app


def _bind_scene_refresh_app(app):
    app._on_scene_generation_bumped = DanmuApp._on_scene_generation_bumped.__get__(app, DanmuApp)
    app._try_scene_refresh = DanmuApp._try_scene_refresh.__get__(app, DanmuApp)
    app._on_normal_capture_tick = DanmuApp._on_normal_capture_tick.__get__(app, DanmuApp)
    app._on_capture_completed = DanmuApp._on_capture_completed.__get__(app, DanmuApp)
    app._has_visual_request_in_flight = DanmuApp._has_visual_request_in_flight.__get__(
        app, DanmuApp
    )
    app._api_schedule_block_reason = DanmuApp._api_schedule_block_reason.__get__(app, DanmuApp)
    return app


def _immediate_single_shot(_ms, cb):
    cb()


def test_bump_purges_old_queue_and_schedules_refresh(monkeypatch):
    app = _bind_scene_refresh_app(_scene_version_app())
    app.engine.running = True
    monkeypatch.setattr("app.main_lifecycle_mixin.QTimer.singleShot", _immediate_single_shot)
    app._schedule_capture = Mock()

    app.reply_buffer.push(
        QueuedReply("p", 1, 0, "old", screenshot_id=1, scene_generation=0)
    )
    app.config.set("live_topic", "新主题")
    app._on_config_changed()

    assert app._scene_generation == 1
    assert app.reply_buffer.is_empty()
    assert app._scene_refresh_wanted is True
    app._schedule_capture.assert_called_once()
    assert app._pending_api_trigger_source == "scene_refresh"


def test_bump_with_inflight_defers_until_stale_drop(monkeypatch):
    app = _bind_scene_refresh_app(_scene_version_app())
    app.engine.running = True
    app.ai_in_flight = 1
    app._is_generating = True
    monkeypatch.setattr("app.main_lifecycle_mixin.QTimer.singleShot", _immediate_single_shot)
    app._schedule_capture = Mock()

    app.config.set("live_topic", "新主题")
    app._on_config_changed()

    assert app._scene_refresh_wanted is True
    app._schedule_capture.assert_not_called()

    app._register_request_meta(10, 10, 0, "visual")
    monkeypatch.setattr(gen_pipeline_mod, "parse_ai_reply_payload", lambda text: ["ok"])
    monkeypatch.setattr(gen_pipeline_mod, "normalize_reply_batch", lambda raw_items, **kwargs: raw_items)
    app._on_ai_reply = main_mod.DanmuApp._on_ai_reply.__get__(app, main_mod.DanmuApp)
    app._enqueue_reply_batch = MagicMock()
    app._generation_pipeline.consume_reply_queue = lambda: None
    app._publish_live_status = lambda: None

    app._on_ai_reply('["ok"]', "persona-1", 10, 10, time.monotonic(), 0)

    assert app.ai_in_flight == 0
    app._schedule_capture.assert_called_once()
    assert app._pending_api_trigger_source == "scene_refresh"


def test_unrelated_config_does_not_schedule_refresh(monkeypatch):
    app = _bind_scene_refresh_app(_scene_version_app())
    app.engine.running = True
    monkeypatch.setattr("app.main_lifecycle_mixin.QTimer.singleShot", _immediate_single_shot)
    app._schedule_capture = Mock()

    app.reply_buffer.push(
        QueuedReply("p", 1, 0, "keep", screenshot_id=1, scene_generation=0)
    )
    app.config.set("danmu_speed", "3")
    app._on_config_changed()

    assert app._scene_generation == 0
    assert app.reply_buffer.size() == 1
    assert app._scene_refresh_wanted is False
    app._schedule_capture.assert_not_called()


def test_capture_completed_passes_scene_refresh_source(monkeypatch):
    app = _bind_scene_refresh_app(_scene_version_app())
    app.engine.running = True
    triggered: list[tuple[str, bool]] = []

    def record_trigger(source="unknown", *, enforce_min_interval=True):
        triggered.append((source, enforce_min_interval))

    app._trigger_api_call = record_trigger
    app._apply_capture_result = DanmuApp._apply_capture_result.__get__(app, DanmuApp)
    app.capturer = FakeCapturer(FakePixmap(1))

    app._pending_api_trigger_source = "scene_refresh"
    app._on_capture_completed(FakePixmap(1))
    assert triggered == [("scene_refresh", False)]

    triggered.clear()
    app._pending_api_trigger_source = None
    app._on_capture_completed(FakePixmap(1))
    assert triggered == [("normal_interval", True)]


def test_trigger_api_call_clears_scene_refresh_wanted_on_fire(monkeypatch):
    app = _bind_scene_refresh_app(_scene_version_app())
    app.engine.running = True
    app._scene_refresh_wanted = True
    app._latest_screenshot = FakePixmap(1)
    app.capturer = FakeCapturer(FakePixmap(1))
    app.personae = Mock()
    app.personae.pick_random.return_value = "p1"
    app.personae.get_prompt.return_value = ("sys", "user")
    app._publish_live_status = lambda: None
    app._log_reply_pipeline = lambda *a, **k: None
    app._log_api_schedule = lambda *a, **k: None

    started = []

    class _FakePool:
        def start(self, runnable):
            started.append(runnable)

    monkeypatch.setattr("app.worker_pools.ai_worker_pool", lambda: _FakePool())
    monkeypatch.setattr(main_mod, "append_nickname_to_system_pt", lambda s, c: s)
    monkeypatch.setattr(main_mod, "append_live_topic_to_system_pt", lambda s, c: s)

    app._trigger_api_call(source="scene_refresh", enforce_min_interval=False)

    assert app._scene_refresh_wanted is False
    assert len(started) == 1


def test_scene_refresh_bypasses_min_interval_block(monkeypatch):
    app = _bind_scene_refresh_app(_scene_version_app())
    app._get_request_scheduler().last_api_trigger_at = time.monotonic()
    monkeypatch.setenv("DANMU_MIN_API_INTERVAL_MS", "800")

    assert app._api_schedule_block_reason(enforce_min_interval=True) == "min_api_interval"
    assert app._api_schedule_block_reason(enforce_min_interval=False) == ""
