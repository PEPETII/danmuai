"""Phase 4-B scheduling and timing regression tests."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import app.api_schedule as api_schedule
import main
import pytest
from app.application.request_scheduler import RequestScheduler
from app.application.request_timing_service import RequestTimingService
from app.main_helpers import MAX_IN_FLIGHT, density_right_target, reply_request_id
from main import DanmuApp
from PyQt6.QtCore import QObject

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import (
    FakeConfig,
    FakeEngine,
    FakeHistoryWriter,
    FakeLifetimeStats,
    FakeLogger,
    FakeTimer,
)


def _make_request_app(**overrides):
    app = DanmuApp.__new__(DanmuApp)
    defaults = {
        "logger": FakeLogger(),
        "engine": FakeEngine(),
        "config": FakeConfig(),
        "history_writer": FakeHistoryWriter(),
        "lifetime_stats": FakeLifetimeStats(),
        "MAX_CONSECUTIVE_FAILURES": 5,
    }
    defaults.update(overrides)
    bind_minimal_danmu_app(app, **defaults)

    object.__setattr__(app, "screenshot_timer", FakeTimer())
    object.__setattr__(app, "_live_status_timer", FakeTimer())
    object.__setattr__(app, "_mic_service", SimpleNamespace(stop=lambda: None))
    object.__setattr__(app, "overlay", SimpleNamespace(stop_render_loop=lambda: None, hide=lambda: None))
    object.__setattr__(app, "tray", SimpleNamespace(update_state=lambda running: None))
    object.__setattr__(app, "state_changed", SimpleNamespace(emit=lambda running: None))
    object.__setattr__(app, "ai_worker", Mock(mark_stopping=lambda: None))
    object.__setattr__(app, "personae", SimpleNamespace(pick_random=lambda: "p1", get_prompt=lambda _p: ("sys", "user")))
    object.__setattr__(app, "capturer", SimpleNamespace(grab=lambda: None))

    for name in (
        "_get_request_scheduler",
        "get_request_scheduler",
        "get_request_timing_service",
        "_has_visual_request_in_flight",
        "api_schedule_block_reason",
        "_consume_request_timing",
        "_rtt_avg",
        "_smart_cooldown_ms",
        "_reply_request_id",
        "_register_request_meta",
        "_pop_request_meta",
        "_release_inflight_for_source",
        "_ensure_stats_state",
        "_on_ai_reply",
        "_on_ai_error",
    ):
        object.__setattr__(app, name, getattr(DanmuApp, name).__get__(app, DanmuApp))

    object.__setattr__(app, "_log_api_schedule", lambda **_kwargs: None)
    object.__setattr__(app, "_publish_live_status", lambda: None)
    object.__setattr__(app, "_set_error_status_safe", lambda *_args, **_kwargs: None)
    object.__setattr__(app, "_current_persona", "p1")
    object.__setattr__(app, "visible_display_count", lambda: 0)
    app.engine.running = True
    return app


def test_lifecycle_init_creates_scheduler_and_timing_once(qapp, monkeypatch):
    """W-LIFECYCLE-STATE-DEDUP-001: pipeline + tracking init must not recreate scheduler/timing."""
    scheduler_calls: list[RequestScheduler] = []
    timing_calls: list[RequestTimingService] = []

    original_scheduler = RequestScheduler
    original_timing = RequestTimingService

    def tracking_scheduler(*args, **kwargs):
        inst = original_scheduler(*args, **kwargs)
        scheduler_calls.append(inst)
        return inst

    def tracking_timing(*args, **kwargs):
        inst = original_timing(*args, **kwargs)
        timing_calls.append(inst)
        return inst

    monkeypatch.setattr("app.main_lifecycle_mixin.RequestScheduler", tracking_scheduler)
    monkeypatch.setattr("app.main_lifecycle_mixin.RequestTimingService", tracking_timing)

    app = DanmuApp.__new__(DanmuApp)
    QObject.__init__(app)
    app.config = FakeConfig()
    app.logger = FakeLogger()
    for name in ("_on_ai_reply", "_on_ai_error", "_on_mic_utterance_end", "_publish_live_status"):
        object.__setattr__(app, name, getattr(DanmuApp, name).__get__(app, DanmuApp))

    DanmuApp._init_request_pipeline_state(app)
    scheduler_ref = app._request_scheduler
    timing_ref = app._request_timing_service

    DanmuApp._init_runtime_tracking_state(app)

    assert len(scheduler_calls) == 1
    assert len(timing_calls) == 1
    assert app._request_scheduler is scheduler_ref
    assert app._request_timing_service is timing_ref


def test_reply_request_id_format():
    assert reply_request_id(2, 7, 0) == (2, 7, 0)
    assert reply_request_id(-1, 5, 0) != reply_request_id(3, 5, 0)


def test_reply_request_id_injective_across_ranges():
    """BUG-073: colon-separated ids must be unique across visual/mic integer domains."""
    keys: set[str] = set()
    triple_count = 0
    for request_round in range(-20, 201):
        for screenshot_id in range(0, 201):
            for scene_generation in range(0, 31):
                key = reply_request_id(request_round, screenshot_id, scene_generation)
                assert key not in keys, (
                    request_round,
                    screenshot_id,
                    scene_generation,
                    key,
                )
                keys.add(key)
                triple_count += 1
    assert triple_count > 0
    assert reply_request_id(5, 0, 0) in keys
    assert reply_request_id(-3, 0, 2) in keys


_META_CONCURRENT_WORKERS = 8
_META_ENTRIES_PER_WORKER = 50


def test_pending_meta_unique_keys_under_concurrent_calls():
    """BUG-073: concurrent register/pop must not lose or overwrite distinct request triples."""
    app = _make_request_app()
    logger = app.logger
    assert isinstance(logger, FakeLogger)

    triples: list[tuple[int, int, int, str]] = []
    for worker_id in range(_META_CONCURRENT_WORKERS):
        base = worker_id * 10_000
        for index in range(_META_ENTRIES_PER_WORKER):
            request_round = base + index
            screenshot_id = base + index + 1
            scene_generation = worker_id % 5
            source = f"w{worker_id}-i{index}"
            triples.append((request_round, screenshot_id, scene_generation, source))

    expected_count = _META_CONCURRENT_WORKERS * _META_ENTRIES_PER_WORKER
    register_errors: list[str] = []
    register_lock = threading.Lock()

    def register_batch(worker_id: int) -> None:
        try:
            for request_round, screenshot_id, scene_generation, source in triples:
                if request_round // 10_000 != worker_id:
                    continue
                key = app._register_request_meta(
                    request_round,
                    screenshot_id,
                    scene_generation,
                    source,
                )
                expected_key = app._reply_request_id(
                    request_round,
                    screenshot_id,
                    scene_generation,
                )
                if key != expected_key:
                    with register_lock:
                        register_errors.append(f"key_mismatch:{key}")
                    return
                stored = app._pending_request_meta.get(key)
                if stored is None or stored.get("source") != source:
                    with register_lock:
                        register_errors.append(f"overwrite:{key}")
        except Exception as exc:
            with register_lock:
                register_errors.append(f"register_exc:{exc!r}")

    register_barrier = threading.Barrier(_META_CONCURRENT_WORKERS + 1)
    register_threads = [
        threading.Thread(
            target=lambda wid=worker_id: (
                register_barrier.wait(),
                register_batch(wid),
            ),
            daemon=True,
        )
        for worker_id in range(_META_CONCURRENT_WORKERS)
    ]
    for thread in register_threads:
        thread.start()
    register_barrier.wait()
    for thread in register_threads:
        thread.join(timeout=5.0)
        assert not thread.is_alive()

    assert register_errors == []
    assert len(app._pending_request_meta) == expected_count

    sample_round, sample_sid, sample_gen, sample_source = triples[0]
    sample_key = app._reply_request_id(sample_round, sample_sid, sample_gen)
    assert app._pending_request_meta[sample_key]["source"] == sample_source

    pop_errors: list[str] = []
    pop_lock = threading.Lock()

    def pop_batch(worker_id: int) -> None:
        try:
            for request_round, screenshot_id, scene_generation, source in triples:
                if request_round // 10_000 != worker_id:
                    continue
                meta = app._pop_request_meta(request_round, screenshot_id, scene_generation)
                if meta.get("source") != source:
                    with pop_lock:
                        pop_errors.append(
                            f"pop_source_mismatch:{request_round}:{screenshot_id}:{scene_generation}"
                        )
        except Exception as exc:
            with pop_lock:
                pop_errors.append(f"pop_exc:{exc!r}")

    pop_barrier = threading.Barrier(_META_CONCURRENT_WORKERS + 1)
    pop_threads = [
        threading.Thread(
            target=lambda wid=worker_id: (
                pop_barrier.wait(),
                pop_batch(wid),
            ),
            daemon=True,
        )
        for worker_id in range(_META_CONCURRENT_WORKERS)
    ]
    for thread in pop_threads:
        thread.start()
    pop_barrier.wait()
    for thread in pop_threads:
        thread.join(timeout=5.0)
        assert not thread.is_alive()

    assert pop_errors == []
    assert app._pending_request_meta == {}
    assert not any(
        "request_meta_missing" in msg or "pop_before_reply" in msg
        for msg in logger.warning_messages
    )


def test_density_right_target():
    assert density_right_target(0) == 2
    assert density_right_target(9) == 3


def test_min_api_interval_blocks_and_then_allows(monkeypatch):
    app = _make_request_app()
    app.get_request_scheduler().last_api_trigger_at = 100.0

    monkeypatch.setenv("DANMU_MIN_API_INTERVAL_MS", "800")
    monkeypatch.setattr(api_schedule.time, "monotonic", lambda: 100.5)
    assert app.api_schedule_block_reason(enforce_min_interval=True) == "min_api_interval"

    monkeypatch.setattr(api_schedule.time, "monotonic", lambda: 100.81)
    assert app.api_schedule_block_reason(enforce_min_interval=True) == ""


def test_consume_request_timing_updates_history_and_clears_id(monkeypatch):
    app = _make_request_app()
    request_id = app._reply_request_id(2, 7, 0)
    timing = app.get_request_timing_service()
    timing.request_started_at_by_id[request_id] = 10.0
    app._register_request_meta(2, 7, 0, "visual")
    monkeypatch.setattr(main.time, "monotonic", lambda: 11.5)

    app._consume_request_timing(2, 7, 0)

    assert request_id not in timing.request_started_at_by_id
    assert timing.rtt_history == pytest.approx([1.5])


def test_request_timing_keys_do_not_collide_for_mic_and_visual(monkeypatch):
    app = _make_request_app()
    visual_id = app._reply_request_id(3, 5, 0)
    mic_id = app._reply_request_id(-1, 5, 0)
    assert visual_id != mic_id

    app._get_request_timing_service().mark_started(request_id=visual_id, now=10.0)
    app._get_request_timing_service().mark_started(request_id=mic_id, now=20.0)
    monkeypatch.setattr(main.time, "monotonic", lambda: 21.5)

    visual_rtt = app._get_request_timing_service().consume_timing(request_id=visual_id, now=21.5)
    assert visual_rtt == pytest.approx(11.5)
    assert mic_id in app.get_request_timing_service().request_started_at_by_id


def test_get_request_scheduler_public_facade():
    app = _make_request_app()
    scheduler = app.get_request_scheduler()
    assert scheduler is app._get_request_scheduler()


def test_request_scheduler_records_trigger_time():
    app = _make_request_app()
    scheduler = RequestScheduler()
    object.__setattr__(app, "_request_scheduler", scheduler)

    scheduler.record_trigger_time(now=42.0)
    assert scheduler.last_api_trigger_at == 42.0


def test_request_timing_service_avg_rtt():
    service = RequestTimingService()
    service.rtt_history = [1.0, 2.0, 3.0]
    assert service.avg_rtt() == pytest.approx(2.0)


def test_consume_request_timing_updates_rtt_history(monkeypatch):
    app = _make_request_app()
    request_id = app._reply_request_id(1, 1, 0)
    timing = app.get_request_timing_service()
    timing.request_started_at_by_id[request_id] = 0.0
    monkeypatch.setattr(main.time, "monotonic", lambda: 1.0)

    app._consume_request_timing(1, 1, 0)

    assert timing.rtt_history == [1.0]


def test_on_ai_reply_consumes_timing_on_success_path(monkeypatch):
    app = _make_request_app()
    app.ai_in_flight = 1
    app._is_generating = True
    request_id = app._reply_request_id(3, 5, 0)
    timing = app.get_request_timing_service()
    timing.request_started_at_by_id[request_id] = 10.0
    app._register_request_meta(3, 5, 0, "visual")
    app._enqueue_reply_batch = Mock()
    app._consume_reply_queue = Mock()
    app.reply_timer.active = False
    monkeypatch.setattr(main.time, "monotonic", lambda: 11.2)
    monkeypatch.setattr(main, "parse_ai_reply_payload", lambda text: ["A"])
    monkeypatch.setattr(main, "normalize_reply_batch", lambda raw_items, **_kwargs: raw_items)

    app._on_ai_reply('["A"]', "p1", 3, 5, 10.0, 0)

    assert request_id not in timing.request_started_at_by_id
    assert timing.rtt_history == pytest.approx([1.2])
    assert app._enqueue_reply_batch.called
    app._consume_reply_queue.assert_called_once_with()


def test_mic_probe_does_not_touch_pending_request_meta(monkeypatch):
    from app.ai_client import AiProbeResult
    from app.mic_test_send import send_mic_probe

    app = _make_request_app()
    app.ai_worker = MagicMock()
    app.ai_worker.resolve_mic_request_credentials = lambda: (
        "https://ark.cn-beijing.volces.com/api/v3",
        "sk-test",
        "doubao-seed-2-0-mini-260428",
        "doubao",
    )
    app.run_mic_probe_in_pool = lambda *_args, **_kwargs: AiProbeResult(
        signal="finished",
        message="ok",
    )

    before = dict(app._pending_request_meta)
    send_mic_probe(app, "data:image/jpeg;base64,abc", "hi", "data:audio/wav;base64,x")
    assert app._pending_request_meta == before


def test_on_ai_error_consumes_timing_on_error_path(monkeypatch):
    app = _make_request_app()
    app.ai_in_flight = 1
    app._is_generating = True
    request_id = app._reply_request_id(4, 8, 0)
    timing = app.get_request_timing_service()
    timing.request_started_at_by_id[request_id] = 20.0
    app._register_request_meta(4, 8, 0, "visual")
    monkeypatch.setattr(main.time, "monotonic", lambda: 21.5)

    app._on_ai_error("boom", "p1", 4, 8, 20.0, 0)

    assert request_id not in timing.request_started_at_by_id
    assert timing.rtt_history == pytest.approx([1.5])


def test_max_in_flight_module_constant_gates_trigger(monkeypatch):
    """BUG-011: MAX_IN_FLIGHT is a module constant; at-cap visual requests do not fire again."""
    from tests.conftest import make_minimal_danmu_app

    app = make_minimal_danmu_app()
    app.engine.running = True
    app._latest_screenshot = object()
    app._latest_screenshot_id = 3
    app._latest_screenshot_time = __import__("time").monotonic()
    app.ai_in_flight = MAX_IN_FLIGHT
    app._is_generating = True
    app.personae = SimpleNamespace(
        pick_random=lambda: "p1",
        get_prompt=lambda _p: ("sys", "user"),
    )
    app._log_api_schedule = lambda **_kwargs: None
    app._trigger_api_call = DanmuApp._trigger_api_call.__get__(app, DanmuApp)

    pool = Mock()
    pool.start = Mock()
    monkeypatch.setattr(
        "PyQt6.QtCore.QThreadPool",
        Mock(globalInstance=Mock(return_value=pool)),
    )
    monkeypatch.setattr("app.runnable.AiRunnable", lambda *a, **k: Mock())

    app._trigger_api_call()
    assert app.ai_in_flight == MAX_IN_FLIGHT
    pool.start.assert_not_called()
    assert "MAX_IN_FLIGHT" not in app.__dict__
