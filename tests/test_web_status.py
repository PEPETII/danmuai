"""Web console tests: status snapshot and refresh."""

import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.application.generation_pipeline_state import GenerationPipelineState
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.web_console import WebConsoleBridge
from main import DanmuApp

from tests.fakes import FakeConfig
from tests.web_console_helpers import make_status_app


def test_refresh_status_uses_public_status_snapshot():
    bridge = WebConsoleBridge(make_status_app())
    status = bridge.refresh_status()

    assert status.dedup_profile is None
    assert len(status.session_runs) == 1
    assert status.session_runs[0]["model"] == "gpt-test"
    bridge.danmu_app.build_status_snapshot.assert_called_once()


def test_build_status_snapshot_delegates_to_builder(monkeypatch):
    calls = []

    class FakeBuilder:
        def __init__(self, app):
            calls.append(app)

        def build(self):
            return {"running": True}

    monkeypatch.setattr("main.StatusSnapshotBuilder", FakeBuilder)
    app = SimpleNamespace()

    status = DanmuApp.build_status_snapshot(app)

    assert status == {"running": True}
    assert calls == [app]


def test_build_status_snapshot_omits_dedup_profile_when_disabled(monkeypatch):
    from app.danmu_engine import reset_dedup_profile_for_tests

    app = SimpleNamespace(
        engine=SimpleNamespace(running=False, get_dedup_profile_snapshot=MagicMock(return_value={"enabled": True})),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: 0,
        _total_input_tokens=0,
        _total_output_tokens=0,
        _start_time=0.0,
        _web_error_message="",
        _web_error_is_error=False,
        danmu_count=0,
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig({"screen_index": "0", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: None,
    )

    monkeypatch.delenv("DANMU_DEDUP_PROFILE", raising=False)
    reset_dedup_profile_for_tests()

    status = DanmuApp.build_status_snapshot(app)

    assert status["dedup_profile"] is None
    app.engine.get_dedup_profile_snapshot.assert_not_called()


def test_build_status_snapshot_includes_dedup_profile_when_enabled(monkeypatch):
    from app.danmu_engine import reset_dedup_profile_for_tests

    app = SimpleNamespace(
        engine=SimpleNamespace(
            running=True,
            get_dedup_profile_snapshot=MagicMock(
                return_value={"enabled": True, "duplicate_checks": 3}
            ),
        ),
        reply_buffer=SimpleNamespace(size=lambda: 2),
        visible_display_count=lambda: 1,
        _total_input_tokens=7,
        _total_output_tokens=5,
        _start_time=time.monotonic() - 3.0,
        _web_error_message="",
        _web_error_is_error=False,
        danmu_count=4,
        personae=SimpleNamespace(get_active=lambda: ["吐槽型"]),
        config=FakeConfig({"screen_index": "1", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {"lifetime_total_tokens": 12}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: SimpleNamespace(
            analyzing=True,
            local_fallback=False,
            delay_sec=1.2,
            primary_message=lambda: "analyzing",
        ),
    )

    monkeypatch.setenv("DANMU_DEDUP_PROFILE", "1")
    reset_dedup_profile_for_tests()

    status = DanmuApp.build_status_snapshot(app)

    assert status["dedup_profile"] == {"enabled": True, "duplicate_checks": 3}
    assert status["live_message"] == "analyzing"
    assert "live_stale_drops" not in status
    app.engine.get_dedup_profile_snapshot.assert_called_once()


def test_build_status_snapshot_uses_stopped_live_message_when_not_running():
    from app.translations import tr

    app = SimpleNamespace(
        engine=SimpleNamespace(running=False),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: 0,
        stats_state=StatsState(),
        web_runtime_state=WebRuntimeState(),
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig({"screen_index": "0", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: SimpleNamespace(
            analyzing=False,
            local_fallback=False,
            delay_sec=0.0,
            primary_message=lambda: "should-not-leak-running-copy",
        ),
    )

    status = DanmuApp.build_status_snapshot(app)

    assert status["live_message"] == tr("control.status_stopped_desc")


def test_build_status_snapshot_prefers_web_runtime_state_cache_and_keeps_output_compatible():
    app = SimpleNamespace(
        engine=SimpleNamespace(running=False),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: 0,
        stats_state=StatsState(danmu_count=2, total_input_tokens=5, total_output_tokens=4),
        web_runtime_state=WebRuntimeState(
            error_message="warn",
            is_error=True,
            cached_danmu_lines=18,
            cached_layout_mode="windowed",
        ),
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig({"screen_index": "0", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: None,
    )

    status = DanmuApp.build_status_snapshot(app)

    assert status["error_message"] == "warn"
    assert status["is_error"] is True
    assert status["total_tokens"] == 9
    assert "cached_danmu_lines" not in status
    assert "cached_layout_mode" not in status


def test_build_status_snapshot_collects_generation_projection_without_exposing_new_fields():
    app = SimpleNamespace(
        engine=SimpleNamespace(running=False),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: 0,
        stats_state=StatsState(),
        web_runtime_state=WebRuntimeState(),
        latest_displayed_round=9,
        latest_requested_screenshot_id=11,
        latest_queued_screenshot_id=10,
        latest_displayed_screenshot_id=8,
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig({"screen_index": "0", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: None,
    )

    runtime_state = GenerationPipelineState.from_app(app)
    status = DanmuApp.build_status_snapshot(app)

    assert runtime_state.latest_displayed_round == 9
    assert runtime_state.latest_requested_screenshot_id == 11
    assert runtime_state.latest_queued_screenshot_id == 10
    assert runtime_state.latest_displayed_screenshot_id == 8
    assert "latest_displayed_round" not in status
    assert "latest_requested_screenshot_id" not in status
    assert "latest_queued_screenshot_id" not in status
    assert "latest_displayed_screenshot_id" not in status


def test_build_status_snapshot_display_count_when_engine_visible():
    """BUG-003: display_count in status must reflect engine visible_display_count."""
    engine = SimpleNamespace(running=True)

    app = SimpleNamespace(
        engine=engine,
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: 2,
        stats_state=StatsState(danmu_count=0, start_time=time.monotonic()),
        web_runtime_state=WebRuntimeState(),
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig({"screen_index": "0", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: None,
        _region_selection_state="idle",
    )

    status = DanmuApp.build_status_snapshot(app)

    assert status["display_count"] == 2


def test_build_status_snapshot_prefers_state_objects_when_present():
    app = SimpleNamespace(
        engine=SimpleNamespace(running=False),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: 0,
        stats_state=StatsState(
            danmu_count=9,
            total_input_tokens=13,
            total_output_tokens=8,
            start_time=0.0,
        ),
        web_runtime_state=WebRuntimeState(error_message="web failed", is_error=True),
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig({"screen_index": "2", "_api_key": "sk-test"}),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: None,
    )

    status = DanmuApp.build_status_snapshot(app)

    assert status["danmu_count"] == 9
    assert status["input_tokens"] == 13
    assert status["output_tokens"] == 8
    assert status["total_tokens"] == 21
    assert status["error_message"] == "web failed"
    assert status["is_error"] is True


def test_build_status_snapshot_includes_model_projection():
    from app.model_catalog import default_catalog_model_id

    dash_model = default_catalog_model_id("dashscope")
    app = SimpleNamespace(
        engine=SimpleNamespace(running=False, get_dedup_profile_snapshot=MagicMock()),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: 0,
        stats_state=StatsState(),
        _start_time=0.0,
        _web_error_message="",
        _web_error_is_error=False,
        danmu_count=0,
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig(
            {
                "api_endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_mode": "openai",
                "model": dash_model,
                "default_model_id": dash_model,
                "_api_key": "sk-test",
            }
        ),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: None,
    )

    status = DanmuApp.build_status_snapshot(app)

    assert status["active_model_id"] == dash_model
    assert status["inferred_provider_id"] == "dashscope"
    assert status["model_source"] == "catalog"
    assert status["uses_custom_credentials"] is False


def test_build_status_snapshot_includes_capture_region():
    app = SimpleNamespace(
        engine=SimpleNamespace(running=False, get_dedup_profile_snapshot=MagicMock()),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: 0,
        stats_state=StatsState(),
        _start_time=0.0,
        _web_error_message="",
        _web_error_is_error=False,
        danmu_count=0,
        personae=SimpleNamespace(get_active=lambda: []),
        config=FakeConfig(
            {
                "screen_index": "0",
                "region_x": "12",
                "region_y": "34",
                "region_w": "320",
                "region_h": "180",
                "_api_key": "sk-test",
            }
        ),
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: None,
        _region_selection_state="idle",
    )

    status = DanmuApp.build_status_snapshot(app)

    assert status["capture_region_mode"] == "custom"
    assert status["region_x"] == 12
    assert status["region_w"] == 320
    assert status["region_selection_state"] == "idle"
    assert status["provider_model_mismatch"] is False

def test_classify_web_console_startup_ready():
    from app.web_console import WebConsoleBridge, WebConsoleServer, classify_web_console_startup

    server = WebConsoleServer(WebConsoleBridge(MagicMock()))
    server.startup_ok = True
    assert classify_web_console_startup(server) == "ready"


def test_classify_web_console_startup_failed_bind():
    from app.web_console import WebConsoleBridge, WebConsoleServer, classify_web_console_startup

    server = WebConsoleServer(WebConsoleBridge(MagicMock()))
    server._bind_failed.set()
    assert classify_web_console_startup(server) == "failed"


def test_classify_web_console_startup_failed_dead_thread():
    from app.web_console import WebConsoleBridge, WebConsoleServer, classify_web_console_startup

    server = WebConsoleServer(WebConsoleBridge(MagicMock()))
    server._thread = None
    assert classify_web_console_startup(server) == "failed"


def test_classify_web_console_startup_slow():
    import threading

    from app.web_console import WebConsoleBridge, WebConsoleServer, classify_web_console_startup

    server = WebConsoleServer(WebConsoleBridge(MagicMock()))

    def _sleep() -> None:
        time.sleep(5.0)

    server._thread = threading.Thread(target=_sleep, daemon=True)
    server._thread.start()
    try:
        assert classify_web_console_startup(server) == "slow"
    finally:
        server._bind_failed.set()
        server._thread.join(timeout=1.0)


def test_web_console_server_stop_schedules_shutdown_callback():
    from app.web_console import WebConsoleBridge, WebConsoleServer

    class _FakeUvicornServer:
        should_exit = False

    danmu_app = MagicMock()
    bridge = WebConsoleBridge(danmu_app)
    server = WebConsoleServer(bridge)
    server._server = _FakeUvicornServer()
    loop = MagicMock()
    server._loop = loop

    server.stop()

    danmu_app.stop_web_status_timer.assert_called_once_with()
    danmu_app.detach_web_status_timer.assert_called_once_with()
    loop.call_soon_threadsafe.assert_called_once()
    callback = loop.call_soon_threadsafe.call_args[0][0]
    assert callable(callback)
    callback()
    assert server._server.should_exit is True
    assert server._shutdown_requested.is_set() is True


def test_web_console_server_wait_shutdown_complete_uses_event():
    from app.web_console import WebConsoleBridge, WebConsoleServer

    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    fake_thread = MagicMock()
    fake_thread.is_alive.return_value = True
    server._thread = fake_thread

    assert server.wait_shutdown_complete(timeout=0.01) is False
    server._shutdown_complete.set()
    assert server.wait_shutdown_complete(timeout=0.01) is True


def test_broadcast_log_skips_closed_event_loop():
    import asyncio
    import time

    from app.web_console import WebConsoleBridge

    danmu_app = MagicMock()
    bridge = WebConsoleBridge(danmu_app)
    loop = asyncio.new_event_loop()
    bridge.set_event_loop(loop)
    loop.close()

    bridge._broadcast_log("INFO", "late log", time.time())

    assert bridge._pending_log_items == []
    assert bridge._log_flush_scheduled is False

