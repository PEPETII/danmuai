"""W-PERF-TIMER-001: publish_status semantic diff and live/web timer dedupe."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.web_console import WebConsoleBridge
from app.web_console_support import status_payloads_semantically_equal
from main import DanmuApp

from tests.fakes import FakeEngine, FakeTimer
from tests.web_console_helpers import make_status_app


def _base_payload(**overrides):
    payload = {
        "running": True,
        "danmu_count": 1,
        "queue_count": 0,
        "display_count": 0,
        "runtime_sec": 10.0,
        "live_delay_sec": 1.5,
        "lifetime_runtime_sec": 100.0,
        "live_message": "ok",
    }
    payload.update(overrides)
    return payload


def test_status_payloads_semantically_equal_ignores_time_fields():
    a = _base_payload(runtime_sec=10.0, live_delay_sec=1.0, lifetime_runtime_sec=100.0)
    b = _base_payload(runtime_sec=99.0, live_delay_sec=9.9, lifetime_runtime_sec=999.0)
    assert status_payloads_semantically_equal(a, b)


def test_status_payloads_semantically_equal_detects_counter_change():
    a = _base_payload(danmu_count=1)
    b = _base_payload(danmu_count=2)
    assert not status_payloads_semantically_equal(a, b)


def test_publish_status_skips_identical_semantic_payload():
    bridge = WebConsoleBridge(make_status_app())
    bridge._broadcast_status = MagicMock()
    bridge.publish_status()
    assert bridge._broadcast_status.call_count == 1
    bridge.publish_status()
    assert bridge._broadcast_status.call_count == 1


def test_publish_status_broadcasts_on_danmu_count_change():
    app = make_status_app()
    bridge = WebConsoleBridge(app)
    bridge._broadcast_status = MagicMock()
    bridge.publish_status()
    assert bridge._broadcast_status.call_count == 1
    snap = dict(app.build_status_snapshot.return_value)
    snap["danmu_count"] = 99
    app.build_status_snapshot.return_value = snap
    bridge.publish_status()
    assert bridge._broadcast_status.call_count == 2


def test_publish_status_skips_runtime_only_drift():
    app = make_status_app()
    bridge = WebConsoleBridge(app)
    bridge._broadcast_status = MagicMock()
    bridge.publish_status()
    snap = dict(app.build_status_snapshot.return_value)
    snap["runtime_sec"] = 999.0
    snap["live_delay_sec"] = 88.0
    snap["lifetime_runtime_sec"] = 8888.0
    app.build_status_snapshot.return_value = snap
    bridge.publish_status()
    assert bridge._broadcast_status.call_count == 1


def test_publish_live_status_skips_when_web_timer_active(qapp):
    from tests.conftest import bind_minimal_danmu_app

    engine = FakeEngine()
    engine.running = True
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, engine=engine)
    web_timer = FakeTimer()
    web_timer.start()
    app._web_status_timer = web_timer
    bridge = MagicMock()
    app.web_bridge = bridge
    DanmuApp._publish_live_status(app)
    bridge.publish_status.assert_not_called()
