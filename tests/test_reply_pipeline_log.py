"""W-THEME-LAG-LOG-001: reply_pipeline structured observability logs."""

import time
from unittest.mock import Mock

import main as main_mod
import pytest
from main import DanmuApp

from tests.conftest import make_minimal_danmu_app
from tests.fakes import DedupFakeEngine, FakeLogger, FakePixmap


def _pipeline_messages(logger: FakeLogger) -> list[str]:
    return [msg for msg in logger.debug_messages if "reply_pipeline" in msg]


def _bind_trigger(app) -> None:
    app._trigger_api_call = DanmuApp._trigger_api_call.__get__(app, DanmuApp)


def _bind_on_ai_reply(app) -> None:
    app._on_ai_reply = DanmuApp._on_ai_reply.__get__(app, DanmuApp)


@pytest.fixture
def pipeline_log_env(monkeypatch):
    monkeypatch.setenv("DANMU_REPLY_PIPELINE_LOG", "1")


def test_request_started_logs_all_ids(pipeline_log_env, monkeypatch):
    app = make_minimal_danmu_app()
    app.logger = FakeLogger()
    app.engine.running = True
    captured_at = time.monotonic()
    app._latest_screenshot = FakePixmap(0b1, width=100, height=80)
    app._latest_screenshot_id = 7
    app._latest_screenshot_time = captured_at
    app.personae = Mock(
        pick_random=Mock(return_value="吐槽型"),
        get_prompt=Mock(return_value=("sys", "user")),
    )

    pool = Mock()
    pool.start = Mock()
    monkeypatch.setattr("app.worker_pools.ai_worker_pool", lambda: pool)
    monkeypatch.setattr(
        "app.runnable.AiRunnable",
        lambda *_args, **_kwargs: object(),
    )

    app._api_schedule_block_reason = Mock(return_value="")
    app._log_api_schedule = Mock()
    app._publish_live_status = Mock()
    _bind_trigger(app)

    app._trigger_api_call()

    messages = _pipeline_messages(app.logger)
    assert len(messages) == 1
    msg = messages[0]
    assert "event=request_started" in msg
    assert "request_id=1:7:0" in msg
    assert "request_round=1" in msg
    assert "screenshot_id=7" in msg
    assert f"captured_at={captured_at}" in msg
    assert "request_started_at=" in msg
    assert "scene_generation=0" in msg
    assert "dropped_as_stale=False" in msg
    assert "enqueued=False" in msg
    assert "displayed=False" in msg


def test_stale_reply_logs_dropped_as_stale(pipeline_log_env):
    app = make_minimal_danmu_app()
    app.logger = FakeLogger()
    _bind_on_ai_reply(app)
    app._pending_request_meta = {}
    app.ai_in_flight = 1

    app._on_ai_reply(
        '["stale"]',
        "persona-stale",
        request_round=1,
        screenshot_id=1,
        captured_at=time.monotonic(),
        scene_generation=0,
    )

    messages = _pipeline_messages(app.logger)
    assert len(messages) == 1
    msg = messages[0]
    assert "event=reply_received" in msg
    assert "dropped_as_stale=True" in msg
    assert "enqueued=False" in msg
    assert "displayed=False" in msg
    assert "reply_received_at=" in msg


def test_enqueue_logs_queue_sizes(pipeline_log_env, monkeypatch):
    app = make_minimal_danmu_app()
    app.logger = FakeLogger()
    _bind_on_ai_reply(app)
    app.ai_in_flight = 1
    app._register_request_meta(3, 9, 0, "visual")
    app._get_request_timing_service().mark_started(request_id=(3, 9, 0), now=time.monotonic())
    monkeypatch.setattr(main_mod, "parse_ai_reply_payload", lambda text: ["a", "b"])
    monkeypatch.setattr(main_mod, "normalize_reply_batch", lambda raw_items, **kwargs: raw_items)
    app._consume_reply_queue = Mock()
    app._publish_live_status = Mock()
    app._notify_pet_visual_success = Mock()

    app._on_ai_reply('["a", "b"]', "persona-1", 3, 9, time.monotonic(), 0)

    messages = _pipeline_messages(app.logger)
    enqueued = [m for m in messages if "event=reply_enqueued" in m]
    assert len(enqueued) == 1
    msg = enqueued[0]
    assert "queue_size_before_enqueue=0" in msg
    assert "queue_size_after_enqueue=2" in msg
    assert "enqueued=True" in msg
    assert "request_started_at=" in msg
    assert "reply_received_at=" in msg


def test_consume_logs_displayed_true(pipeline_log_env, monkeypatch):
    app = make_minimal_danmu_app()
    app.logger = FakeLogger()
    app.engine.running = True
    _bind_on_ai_reply(app)
    app._register_request_meta(2, 5, 0, "visual")
    app.ai_in_flight = 1
    monkeypatch.setattr(main_mod, "parse_ai_reply_payload", lambda text: ["弹幕一"])
    monkeypatch.setattr(main_mod, "normalize_reply_batch", lambda raw_items, **kwargs: raw_items)
    app._notify_pet_visual_success = lambda: None

    app._on_ai_reply('["弹幕一"]', "persona-1", 2, 5, time.monotonic(), 0)
    app._consume_reply_queue()

    displayed = [m for m in _pipeline_messages(app.logger) if "event=reply_displayed" in m]
    assert len(displayed) == 1
    assert "displayed=True" in displayed[0]
    assert "request_id=2:5:0" in displayed[0]
    assert "captured_at=" in displayed[0]


def test_consume_logs_displayed_false_on_duplicate(pipeline_log_env):
    app = make_minimal_danmu_app()
    app.logger = FakeLogger()
    app.engine = DedupFakeEngine("dup")
    app.engine.running = True
    app.config = app.config.__class__({"danmu_display_mode": "normal", "drop_stale": "0"})
    app._sync_reply_batch_config()

    from app.reply_queue import QueuedReply

    now = time.monotonic()
    app.reply_buffer.push(
        QueuedReply(
            "p1",
            1,
            0,
            "dup",
            screenshot_round=1,
            screenshot_id=3,
            captured_at=now,
            scene_generation=0,
            request_id=(1, 3, 0),
        )
    )
    app._consume_reply_queue()

    displayed = [m for m in _pipeline_messages(app.logger) if "event=reply_displayed" in m]
    assert len(displayed) == 1
    assert "displayed=False" in displayed[0]
    assert "screenshot_id=3" in displayed[0]
    assert "duplicate_match_type=" in displayed[0]
    assert "duplicate_loss=1" in displayed[0]
    assert "duplicate_loss_total=1" in displayed[0]


def test_pipeline_log_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DANMU_REPLY_PIPELINE_LOG", raising=False)
    app = make_minimal_danmu_app()
    app.logger = FakeLogger()
    app.engine.running = True
    app._latest_screenshot = FakePixmap(0b1, width=10, height=10)
    app._latest_screenshot_id = 1
    app._latest_screenshot_time = time.monotonic()
    app.personae = Mock(
        pick_random=Mock(return_value="吐槽型"),
        get_prompt=Mock(return_value=("sys", "user")),
    )
    app._api_schedule_block_reason = Mock(return_value="")
    app._log_api_schedule = Mock()
    app._publish_live_status = Mock()
    pool = Mock()
    monkeypatch.setattr("app.worker_pools.ai_worker_pool", lambda: pool)
    monkeypatch.setattr("app.runnable.AiRunnable", lambda *_a, **_k: object())
    _bind_trigger(app)

    app._trigger_api_call()

    assert _pipeline_messages(app.logger) == []
