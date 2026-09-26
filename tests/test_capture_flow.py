"""Main flow tests: capture, backoff, and web launch."""

from unittest.mock import MagicMock, Mock, call

import pytest
from app.reply_queue import QueuedReply
from app.runnable import AiRunnable
from main import compress_screenshot

from tests.conftest import make_minimal_danmu_app, start_app_timers
from tests.fakes import (
    FakeCapturer,
    FakeConfig,
    FakeEngine,
    FakePixmap,
    FakeTimer,
)


def _startable_config() -> FakeConfig:
    """start() 的凭据/端点检查在本文件用 monkeypatch 覆盖，配置只需可读。"""
    return FakeConfig({"api_key": "test-key"})


def _build_startable_app(monkeypatch, *, real_capture_tick: bool = False):
    """构造一个能完整跑通真实 ``DanmuApp.start()`` 成功路径的最小实例。

    在 ``make_minimal_danmu_app()`` 之上补齐 start() 触达的依赖，并把与业务失败
    无关的副作用换成可断言的 Mock / FakeTimer。``real_capture_tick=True`` 时保留
    真实 ``_on_normal_capture_tick``（用于断言只投递一个 CaptureRunnable）。
    """
    from main import DanmuApp

    app = make_minimal_danmu_app()
    app.config = _startable_config()
    app.engine = FakeEngine()
    app._engine_start_spy = Mock(side_effect=app.engine.start)
    app.engine.start = app._engine_start_spy
    app.screenshot_timer = FakeTimer()
    app.reply_timer = FakeTimer()
    app._live_status_timer = FakeTimer()
    app._lifetime_flush_timer = FakeTimer()
    app._topmost_health_timer = FakeTimer()
    app._pool_topup_timer = FakeTimer()
    app.ai_worker = Mock()
    app.session_run_log = Mock()
    app.tray = Mock()
    app.overlay = Mock()
    app.state_changed = Mock()
    app.clear_problem = Mock()
    app.report_problem = Mock()
    object.__setattr__(app, "web_server", None)
    object.__setattr__(app, "knowledge_runtime", None)
    object.__setattr__(app, "virtual_host_runtime", None)
    object.__setattr__(app, "_danmu_read_service", None)

    app._ensure_knowledge_runtime = Mock(return_value=False)
    app._reset_scene_generation_baseline = Mock()
    app._sync_overlay_visibility = Mock()
    app._sync_floating_panel_visibility = Mock()
    app._reassert_active_overlay_topmost = Mock()
    app._start_meme_barrage_timers = Mock()
    app._sync_mic_service = Mock()
    if not real_capture_tick:
        app._on_normal_capture_tick = Mock()

    # 计时/调度服务的 reset 副作用计数（重复 start 必须为 0）
    timing = app._get_request_timing_service()
    app._timing_reset_spy = Mock(wraps=timing.reset_started)
    timing.reset_started = app._timing_reset_spy
    scheduler = app._get_request_scheduler()
    app._sched_reset_spy = Mock(wraps=scheduler.reset_trigger_time)
    scheduler.reset_trigger_time = app._sched_reset_spy

    app.start = DanmuApp.start.__get__(app, DanmuApp)

    monkeypatch.setattr(
        "app.ai_client_requests.visual_credentials_ready", lambda _cfg: True
    )
    monkeypatch.setattr(
        "app.model_selection.visual_api_endpoint_issue", lambda _cfg: None
    )
    return app


def _session_state_snapshot(app) -> dict:
    """第二次 start() 调用前后用于逐字段比较的完整会话状态快照。"""
    return {
        "capture_session_epoch": app._capture_session_epoch,
        "ai_in_flight": app.ai_in_flight,
        "mic_in_flight": app.mic_in_flight,
        "capture_in_flight": app._capture_in_flight,
        "is_generating": app._is_generating,
        "local_fallback_active": app._local_fallback_active,
        "pending_request_meta": dict(app._pending_request_meta),
        "consecutive_failures": app._consecutive_failures,
        "failure_backoff_paused": app._failure_backoff_paused,
        "last_error_message": app._last_error_message,
        "scene_generation": app._scene_generation,
        "inflight_scene_generation": app._inflight_scene_generation,
        "latest_screenshot_id": app._latest_screenshot_id,
        "latest_requested_screenshot_id": app._latest_requested_screenshot_id,
        "latest_queued_screenshot_id": app._latest_queued_screenshot_id,
        "latest_displayed_screenshot_id": app._latest_displayed_screenshot_id,
        "inflight_screenshot_id": app._inflight_screenshot_id,
        "inflight_started_at": app._inflight_started_at,
        "latest_screenshot": app._latest_screenshot,
        "latest_screenshot_time": app._latest_screenshot_time,
        "batch_id": app._batch_id,
        "current_batch": app._current_batch,
        "mic_request_seq": app._mic_request_seq,
        "mic_batch_id": app._mic_batch_id,
        "scene_refresh_wanted": app._scene_refresh_wanted,
        "pending_api_trigger_source": app._pending_api_trigger_source,
        "stats_danmu_count": app.stats_state.danmu_count,
        "stats_start_time": app.stats_state.start_time,
        "reply_queue_metrics": app.reply_buffer.metrics_snapshot().to_dict(),
        "screenshot_timer_starts": app.screenshot_timer.started,
        "screenshot_timer_stops": app.screenshot_timer.stopped,
        "screenshot_timer_active": app.screenshot_timer.active,
        "screenshot_timer_interval": app.screenshot_timer.interval(),
        "reply_timer_starts": app.reply_timer.started,
        "reply_timer_active": app.reply_timer.active,
        "live_status_timer_starts": app._live_status_timer.started,
        "lifetime_flush_timer_starts": app._lifetime_flush_timer.started,
        "topmost_health_timer_starts": app._topmost_health_timer.started,
        "pool_topup_timer_starts": app._pool_topup_timer.started,
    }


def _snapshot_diff(before: dict, after: dict) -> dict:
    return {
        key: (before.get(key), after.get(key))
        for key in before.keys() | after.keys()
        if before.get(key) != after.get(key)
    }


def _start_side_effects(app) -> dict:
    """会随 start() 会话初始化变化的副作用调用次数（tick 必须是 Mock）。"""
    assert isinstance(app._on_normal_capture_tick, Mock)
    return {
        "engine_start": app._engine_start_spy.call_count,
        "reset_stopping": app.ai_worker.reset_stopping.call_count,
        "first_capture_tick": app._on_normal_capture_tick.call_count,
        "knowledge_retry": app._ensure_knowledge_runtime.call_count,
        "scene_baseline_reset": app._reset_scene_generation_baseline.call_count,
        "state_changed": app.state_changed.emit.call_count,
        "session_begin": app.session_run_log.begin.call_count,
        "timing_reset": app._timing_reset_spy.call_count,
        "scheduler_reset": app._sched_reset_spy.call_count,
        "screenshot_timer_starts": app.screenshot_timer.started,
    }


def test_normal_mode_start_uses_configured_capture_interval():
    app = make_minimal_danmu_app()
    app.config = FakeConfig(
        {
            "danmu_display_mode": "normal",
            "normal_recognition_interval_sec": "7",
            "api_key": "test-key",
        }
    )
    app._sync_reply_batch_config()
    start_app_timers(app)
    assert app.screenshot_timer._interval == 7000
    assert app.screenshot_timer.active


def test_normal_tick_skips_while_in_flight():
    app = make_minimal_danmu_app()
    app.config = FakeConfig({"danmu_display_mode": "normal"})
    app.engine.running = True
    schedule_count = 0

    def schedule():
        nonlocal schedule_count
        schedule_count += 1

    app._schedule_capture = schedule
    app.ai_in_flight = 1
    app._on_normal_capture_tick()
    assert schedule_count == 0


def test_normal_tick_captures_on_main_thread_then_queues_safe_payload(monkeypatch):
    app = make_minimal_danmu_app()
    app.config = FakeConfig({"danmu_display_mode": "normal"})
    app.engine.running = True
    grab_count = 0
    started = []

    def grab():
        nonlocal grab_count
        grab_count += 1
        return FakePixmap(0)

    app.capturer = FakeCapturer(FakePixmap(0))
    app.capturer.grab = grab

    class _FakePool:
        def start(self, runnable):
            started.append(runnable)

    monkeypatch.setattr(
        "app.worker_pools.capture_worker_pool",
        lambda: _FakePool(),
    )
    image_payload = object()
    monkeypatch.setattr("main.pixmap_to_image_snapshot", lambda _pixmap: image_payload)

    app._on_normal_capture_tick()
    assert grab_count == 1
    assert len(started) == 1
    assert started[0]._image is image_payload
    assert started[0]._session_epoch == app._capture_session_epoch


def test_capture_in_flight_skips_second_schedule(monkeypatch):
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._capture_in_flight = True
    started = []

    class _FakePool:
        def start(self, runnable):
            started.append(runnable)

    monkeypatch.setattr(
        "app.worker_pools.capture_worker_pool",
        lambda: _FakePool(),
    )

    app._schedule_capture()
    assert started == []


def test_start_resets_capture_in_flight(monkeypatch):
    """BUG-A02: stop→start 后 start() 应重置 _capture_in_flight，避免截图管道卡死。

    P1-04 之后“运行中重复 start”是 no-op，因此这里把前置状态建模为 stop() 之后：
    截图 worker 在途残留（``_capture_in_flight=True``）但引擎已停止
    （``engine.running=False``）。
    """
    app = _build_startable_app(monkeypatch)
    app._capture_in_flight = True
    app.engine.running = False
    initial_epoch = app._capture_session_epoch

    app.start()

    assert app._capture_in_flight is False, (
        "start() 应将 _capture_in_flight 重置为 False"
    )
    assert app._capture_session_epoch == initial_epoch + 1


def test_first_start_starts_timers_and_first_capture_tick(monkeypatch):
    """首次 start 仍启动定时器、首 tick 并发一次 state_changed(True)。"""
    app = _build_startable_app(monkeypatch)
    assert app.engine.running is False

    app.start()

    assert app.engine.running is True
    assert app._engine_start_spy.call_count == 1
    assert app.screenshot_timer.started == 1
    assert app._live_status_timer.started == 1
    assert app._lifetime_flush_timer.started == 1
    assert app._topmost_health_timer.started == 1
    assert app._pool_topup_timer.started == 1
    assert app._on_normal_capture_tick.call_count == 1
    assert app._capture_session_epoch == 1
    assert app.state_changed.emit.call_args_list == [call(True)]


def test_repeated_start_while_running_preserves_session_state(monkeypatch):
    """P1-04 核心：运行中第二次 start() 必须对会话状态零副作用（逐字段快照比较）。"""
    app = _build_startable_app(monkeypatch)
    app.start()

    # 运行中：存在在途视觉请求、request meta、失败计数与已累计统计。
    app.ai_in_flight = 1
    app._capture_in_flight = False
    app._pending_request_meta[(4, 9, 0)] = {"source": "visual"}
    app._latest_requested_screenshot_id = 9
    app._consecutive_failures = 2
    app._scene_generation = 3
    app.stats_state.add_danmu(5)

    effects_before = _start_side_effects(app)
    before = _session_state_snapshot(app)

    app.start()  # 运行中重复调用 → 必须 no-op

    after = _session_state_snapshot(app)
    assert after == before, f"重复 start 改动了会话状态: {_snapshot_diff(before, after)}"
    assert _start_side_effects(app) == effects_before
    assert any(
        "reason=already_running" in msg for msg in app.logger.info_messages
    ), "重复 start 应记录 already_running 诊断"


def test_repeated_start_does_not_create_second_capture_runnable(monkeypatch):
    """重复 start 不得再次调用 _on_normal_capture_tick，也不创建第二个 runnable。"""
    app = _build_startable_app(monkeypatch, real_capture_tick=True)
    app.capturer = FakeCapturer(FakePixmap(0b1))
    monkeypatch.setattr("main.pixmap_to_image_snapshot", lambda _pixmap: object())
    started: list[object] = []

    class _FakePool:
        def start(self, runnable):
            started.append(runnable)

    monkeypatch.setattr("app.worker_pools.capture_worker_pool", lambda: _FakePool())

    app.start()
    assert len(started) == 1
    first_epoch = app._capture_session_epoch
    assert started[0]._session_epoch == first_epoch

    app.start()  # 运行中重复 start

    assert len(started) == 1, "重复 start 不得投递第二个 capture runnable"
    assert app._capture_session_epoch == first_epoch


def test_two_duplicate_start_requests_start_engine_once(monkeypatch):
    """两个 /api/start 信号在主线程顺序处理 → 只产生一次真实启动。

    Qt 主线程串行处理排队的 ``start_requested``，等价于这里连续两次调用 ``start()``。
    """
    app = _build_startable_app(monkeypatch)

    app.start()
    app.start()

    assert app._engine_start_spy.call_count == 1
    assert app._capture_session_epoch == 1
    assert app.state_changed.emit.call_count == 1


def test_stop_then_start_opens_new_session(monkeypatch):
    """完整 stop→start 仍递增新会话 epoch、重置 capture gate 并允许新请求。"""
    app = _build_startable_app(monkeypatch)
    app.start()
    first_epoch = app._capture_session_epoch

    app.engine.stop()  # 模拟 stop() 结束当前会话（running=False）
    app._capture_in_flight = False
    app.start()

    assert app._capture_session_epoch == first_epoch + 1
    assert app._engine_start_spy.call_count == 2
    assert app._on_normal_capture_tick.call_count == 2
    assert app._capture_in_flight is False


def test_start_without_credentials_still_prompts_when_not_running(monkeypatch):
    """凭据缺失时首次 start 仍走现有提示路径，guard 不得误拦截。"""
    app = _build_startable_app(monkeypatch)
    monkeypatch.setattr(
        "app.ai_client_requests.visual_credentials_ready", lambda _cfg: False
    )

    app.start()

    assert app.engine.running is False
    assert app._engine_start_spy.call_count == 0
    assert app.report_problem.call_count == 1
    app.tray.show_api_key_missing_hint.assert_called_once()
    app.tray.update_state.assert_called_once_with(running=False)


def test_duplicate_start_after_transient_credential_loss_is_noop(monkeypatch):
    """已经运行后配置瞬时变化不得让重复 start 破坏当前会话或弹出缺失提示。"""
    app = _build_startable_app(monkeypatch)
    app.start()
    monkeypatch.setattr(
        "app.ai_client_requests.visual_credentials_ready", lambda _cfg: False
    )

    before = _session_state_snapshot(app)
    app.start()

    assert app.report_problem.call_count == 0
    app.tray.show_api_key_missing_hint.assert_not_called()
    assert app._ensure_knowledge_runtime.call_count == 1
    assert _session_state_snapshot(app) == before


def test_duplicate_start_diagnostic_is_rate_limited(monkeypatch):
    """重复 start 的 already_running 诊断按间隔限频，不随每次调用刷屏。"""
    app = _build_startable_app(monkeypatch)
    app.start()
    app.logger.info_messages.clear()

    app.start()
    app.start()
    app.start()

    duplicates = [
        msg for msg in app.logger.info_messages if "reason=already_running" in msg
    ]
    assert len(duplicates) == 1


def test_web_start_request_signal_is_guarded_on_main_thread(monkeypatch, qapp):
    """WebConsoleBridge.start_requested 直连 danmu_app.start；两次 emit 只启动一次。

    ``/api/start`` 路由 emit 的正是 ``bridge.start_requested`` → ``danmu_app.start``
    这条路径，因此主线程 guard 就是该 HTTP 接口的幂等保证。这里用 MagicMock 承载
    bridge 的接线要求，并让它的 ``start`` 指向真实 ``DanmuApp.start``。
    """
    from app.web_console import WebConsoleBridge

    app = _build_startable_app(monkeypatch)
    mock_app = MagicMock()
    # 用普通 callable 转发，避免 __new__ 构造的 QObject 线程亲和性导致 Qt 丢弃信号。
    mock_app.start = lambda: app.start()

    bridge = WebConsoleBridge(mock_app)
    bridge.start_requested.emit()
    bridge.start_requested.emit()
    qapp.processEvents()

    assert app._engine_start_spy.call_count == 1
    assert app._capture_session_epoch == 1
    assert app.state_changed.emit.call_count == 1


def test_api_start_route_reaches_danmu_app_start():
    """锁定 /api/start → bridge.start_requested → danmu_app.start 的幂等主线程路径。"""
    from pathlib import Path

    web_console = Path("app/web_console.py").read_text(encoding="utf-8")
    runtime = Path("app/web_console_runtime.py").read_text(encoding="utf-8")

    assert "self.start_requested.connect(danmu_app.start)" in web_console
    assert "bridge.start_requested.emit()" in runtime


@pytest.mark.parametrize(
    "invalid_pixmap",
    [None, FakePixmap(0, width=0), FakePixmap(0, height=0)],
)
def test_capture_completed_invalid_frame_does_not_reuse_previous_frame(invalid_pixmap):
    app = make_minimal_danmu_app()
    app.engine.running = True
    previous = FakePixmap(0b1)
    app._latest_screenshot = previous
    app._latest_screenshot_id = 5
    app._capture_in_flight = True
    triggered = []
    app._trigger_api_call = lambda **kwargs: triggered.append(kwargs)

    app._on_capture_completed(invalid_pixmap, session_epoch=app._capture_session_epoch)
    assert app._capture_in_flight is False
    assert app._latest_screenshot is previous
    assert app._latest_screenshot_id == 5
    assert triggered == []


def test_capture_completed_success_triggers_api():
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._capture_in_flight = True
    triggered = []
    app._trigger_api_call = lambda source="unknown", **kwargs: triggered.append(source)

    app._on_capture_completed(
        FakePixmap(0b1),
        session_epoch=app._capture_session_epoch,
    )
    assert app._capture_in_flight is False
    assert app._latest_screenshot is not None
    assert triggered == ["normal_interval"]


def test_capture_completed_from_previous_session_is_ignored_after_restart():
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._capture_session_epoch = 2
    previous = FakePixmap(0b1)
    app._latest_screenshot = previous
    app._latest_screenshot_id = 7
    app._capture_in_flight = True
    triggered = []
    app._trigger_api_call = lambda **kwargs: triggered.append(kwargs)

    app._on_capture_completed(FakePixmap(0b10), session_epoch=1)

    assert app._capture_in_flight is True
    assert app._latest_screenshot is previous
    assert app._latest_screenshot_id == 7
    assert triggered == []


def test_stop_ignores_late_capture_completed():
    app = make_minimal_danmu_app()
    app.engine.running = False
    app._latest_screenshot_id = 2
    triggered = []
    app._trigger_api_call = lambda source="unknown", **kwargs: triggered.append(source)

    app._on_capture_completed(FakePixmap(0b1))
    assert app._latest_screenshot_id == 2
    assert triggered == []


def test_compress_screenshot_failure_path():
    """测试截图压缩失败时 in-flight 计数正确释放"""
    # 模拟一个会导致压缩失败的 pixmap
    mock_pixmap = Mock()
    mock_pixmap.toImage.side_effect = RuntimeError("has been deleted")

    # 创建 mock worker
    import threading

    mock_worker = Mock()
    mock_worker._stopping = threading.Event()

    # 创建 runnable 并执行
    runnable = AiRunnable(
        worker=mock_worker,
        pixmap=mock_pixmap,
        system_pt="system",
        user_pt="user",
        persona_id="test-persona",
        request_round=1,
        screenshot_id=1,
        captured_at=1.0,
        scene_generation=0,
        compress_fn=compress_screenshot
    )

    # 执行 run 方法（会捕获异常并发射错误信号）
    runnable.run()

    # 验证错误信号被发射
    mock_worker._emit_safe.assert_called_once()
    call_args = mock_worker._emit_safe.call_args
    assert call_args[0][0] == "error"
    assert "压缩失败" in call_args[0][1]










def test_capture_does_not_advance_scene_generation(monkeypatch):
    """普通模式截图不探测场景跳变，代际保持不变"""
    app = make_minimal_danmu_app()
    app.engine.running = True
    app.reply_buffer.push(QueuedReply("p", 0, 0, "old", scene_generation=0))
    app.capturer = FakeCapturer(FakePixmap(0b1))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app.reply_buffer.size() == 1
    assert app._latest_screenshot is not None


def test_capture_while_in_flight_still_updates_frame(monkeypatch):
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._latest_screenshot_id = 3
    app.ai_in_flight = 1
    app.capturer = FakeCapturer(FakePixmap((1 << 16) - 1))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app._latest_screenshot_id == 4
    assert app._latest_screenshot is not None


def test_repeated_capture_keeps_scene_generation(monkeypatch):
    app = make_minimal_danmu_app()
    app.engine.running = True
    app.capturer = FakeCapturer(FakePixmap(0b1))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app._latest_screenshot is not None


def test_null_pixmap_does_not_increment_screenshot_id():
    """无效 pixmap 不应递增 screenshot_id 或缓存帧"""
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._latest_screenshot_id = 5
    app.capturer = FakeCapturer(FakePixmap(0, is_null=True))

    app._capture_screenshot()

    assert app._latest_screenshot_id == 5
    assert app._latest_screenshot is None
    assert any("null_pixmap" in msg for msg in app.logger.warning_messages)


def test_repeated_capture_failure_sets_web_error_status():
    """S-009: third consecutive capture failure surfaces structured capture problem."""
    app = make_minimal_danmu_app()
    app.engine.running = True
    app.capturer = FakeCapturer(None)
    reported: list[str] = []
    app.report_problem = lambda code, **kwargs: reported.append(code) or {}

    for _ in range(3):
        app._capture_screenshot()

    assert app._capture_fail_streak == 3
    assert reported == ["CAPTURE-001"]


def test_capture_success_clears_capture_error_status():
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._capture_fail_streak = 3
    app._capture_error_active = True
    cleared: list[str | None] = []
    app.clear_problem = lambda *, code=None: cleared.append(code)
    app.capturer = FakeCapturer(FakePixmap(0b1))

    app._capture_screenshot()

    assert app._capture_fail_streak == 0
    assert app._capture_error_active is False
    assert cleared == ["CAPTURE-001"]


def test_capture_failure_reschedules_next_screenshot():
    """测试截图失败不会让主循环卡死（普通模式由 screenshot_timer 驱动）"""
    app = make_minimal_danmu_app()
    app.engine.running = True

    app._capture_screenshot()

    assert app._latest_screenshot is None

def test_open_web_console_when_ready_skips_attach_on_terminal_failure(monkeypatch):

    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    object.__setattr__(app, "webview_shell", None)
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._bind_failed.set()
    object.__setattr__(app, "web_server", server)

    attach_calls = []
    notified = []
    monkeypatch.setattr(
        "app.webview_shell.attach_webview_shell",
        lambda *args, **kwargs: attach_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure",
        lambda danmu, key, **kw: notified.append(key),
    )
    monkeypatch.setattr(
        "app.webview_shell.wait_for_http_server",
        lambda url, timeout: False,
    )

    app._open_web_console_when_ready("/")
    assert attach_calls == []
    assert notified == ["web_console.startup_failed"]
    assert server._startup_failure_user_notified is True

    app._open_web_console_when_ready("/")
    assert notified == ["web_console.startup_failed"]


def test_open_web_console_after_handshake_failed_auto_browser(monkeypatch):
    """W-OPEN-CONSOLE-RECOVERY-002: tray click after handshake failure opens browser."""

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server._browser_launch_opened = False
    object.__setattr__(app, "web_server", server)

    shell = MagicMock()
    shell.is_running.return_value = False
    shell.is_handshake_pending.return_value = False
    shell.handshake_failed = True
    object.__setattr__(app, "webview_shell", shell)

    message_boxes = []
    monkeypatch.setattr(
        "PyQt6.QtWidgets.QMessageBox",
        lambda *a, **k: message_boxes.append(1),
    )
    browser_calls = []
    attach_calls = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )
    monkeypatch.setattr(
        "app.webview_shell.attach_webview_shell",
        lambda *args, **kwargs: attach_calls.append(1),
    )

    app._open_web_console("/#settings")
    assert message_boxes == []
    assert browser_calls == ["/#settings"]
    assert server._browser_launch_opened is True
    assert attach_calls == []


def test_open_web_console_after_handshake_failed_no_browser_when_already_opened(
    monkeypatch,
):
    """W-OPEN-CONSOLE-RECOVERY-002: dedupe — skip browser when already fallback once."""

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    server = MagicMock()
    server.base_url = "http://127.0.0.1:18765"
    server._browser_launch_opened = True
    object.__setattr__(app, "web_server", server)

    shell = MagicMock()
    shell.is_running.return_value = False
    shell.is_handshake_pending.return_value = False
    shell.handshake_failed = True
    object.__setattr__(app, "webview_shell", shell)

    browser_calls = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )

    app._open_web_console("/#settings")
    assert browser_calls == []


def test_open_web_console_failed_restarts_via_maybe_restart(monkeypatch):
    """W-OPEN-CONSOLE-RECOVERY-002: failed server uses maybe_restart then when_ready."""
    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    object.__setattr__(app, "webview_shell", None)
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._bind_failed.set()
    object.__setattr__(app, "web_server", server)

    restart_calls = []
    when_ready_calls = []
    monkeypatch.setattr(
        "app.web_console.maybe_restart_web_console",
        lambda srv: restart_calls.append(1) or True,
    )
    monkeypatch.setattr(
        "app.webview_shell.wait_for_http_server",
        lambda url, timeout: True,
    )
    monkeypatch.setattr(
        app,
        "_open_web_console_when_ready",
        lambda path, **kw: when_ready_calls.append(path),
    )

    app._open_web_console("/#settings")
    assert restart_calls == [1]
    assert when_ready_calls == ["/#settings"]


def test_open_web_console_failed_recovery_falls_back_to_browser(monkeypatch):
    """W-OPEN-CONSOLE-RECOVERY-002: recovery probe fails → browser + notify once."""
    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    object.__setattr__(app, "webview_shell", None)
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._bind_failed.set()
    object.__setattr__(app, "web_server", server)

    browser_calls = []
    notified = []
    when_ready_calls = []
    monkeypatch.setattr(
        "app.web_console.maybe_restart_web_console",
        lambda srv: False,
    )
    monkeypatch.setattr(
        "app.webview_shell.wait_for_http_server",
        lambda url, timeout: False,
    )
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )
    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure",
        lambda danmu, key, **kw: notified.append(key),
    )
    monkeypatch.setattr(
        app,
        "_open_web_console_when_ready",
        lambda path, **kw: when_ready_calls.append(path),
    )

    app._open_web_console("/#settings")
    assert browser_calls == ["/#settings"]
    assert notified == ["web_console.startup_failed"]
    assert server._browser_launch_opened is True
    assert when_ready_calls == []


def test_open_web_console_failed_recovery_dedupes_browser_and_notify(monkeypatch):
    """W-OPEN-CONSOLE-RECOVERY-002: repeated open does not re-notify or re-open browser."""
    from app.web_console import WebConsoleBridge, WebConsoleServer

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    object.__setattr__(app, "webview_shell", None)
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._bind_failed.set()
    object.__setattr__(app, "web_server", server)

    browser_calls = []
    notified = []
    monkeypatch.setattr(
        "app.web_console.maybe_restart_web_console",
        lambda srv: False,
    )
    monkeypatch.setattr(
        "app.webview_shell.wait_for_http_server",
        lambda url, timeout: False,
    )
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )
    monkeypatch.setattr(
        "app.webview_shell.notify_web_console_failure",
        lambda danmu, key, **kw: notified.append(key),
    )

    app._open_web_console("/#settings")
    app._open_web_console("/#settings")
    assert browser_calls == ["/#settings"]
    assert notified == ["web_console.startup_failed"]


def test_open_web_console_failed_respects_restart_cap(monkeypatch):
    """W-OPEN-CONSOLE-RECOVERY-002: at restart cap, user open does not call server.start."""
    from app.web_console import (
        WEB_CONSOLE_MAX_RESTART_ATTEMPTS,
        WebConsoleBridge,
        WebConsoleServer,
        maybe_restart_web_console,
    )

    app = make_minimal_danmu_app()
    object.__setattr__(app, "web_launch_mode", "webview")
    object.__setattr__(app, "webview_shell", None)
    bridge = WebConsoleBridge(MagicMock())
    server = WebConsoleServer(bridge)
    server._bind_failed.set()
    server._thread = None
    server._restart_attempts = WEB_CONSOLE_MAX_RESTART_ATTEMPTS
    object.__setattr__(app, "web_server", server)

    start_calls = []
    monkeypatch.setattr(server, "start", lambda: start_calls.append(1))
    browser_calls = []
    monkeypatch.setattr(
        "app.web_console.open_web_console_browser",
        lambda srv, p: browser_calls.append(p),
    )
    monkeypatch.setattr(
        "app.webview_shell.wait_for_http_server",
        lambda url, timeout: False,
    )

    assert maybe_restart_web_console(server) is False
    assert start_calls == []

    app._open_web_console("/#settings")
    assert start_calls == []
    assert browser_calls == ["/#settings"]

