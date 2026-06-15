"""Main flow tests: AI pipeline, in-flight, and errors."""

import time
from unittest.mock import Mock

from app.ai_client import AiWorker
from app.application.generation_pipeline_state import GenerationPipelineState
from app.runnable import AiRunnable
from main import DanmuApp
from PyQt6.QtWidgets import QApplication

from tests.conftest import make_minimal_danmu_app
from tests.fakes import FakePixmap


def test_trigger_api_call_passes_latest_screenshot_without_copy(monkeypatch):
    """W-PERF-HIGH-002: visual fire path borrows _latest_screenshot ref, no QPixmap.copy()."""
    app = make_minimal_danmu_app()
    app.engine.running = True
    pixmap = FakePixmap(0b1, width=100, height=80)
    app._latest_screenshot = pixmap
    app._latest_screenshot_id = 7
    app._latest_screenshot_time = time.monotonic()
    app.personae = Mock(
        pick_random=Mock(return_value="吐槽型"),
        get_prompt=Mock(return_value=("sys", "user")),
    )

    captured: dict[str, object] = {}

    class _Runnable:
        def __init__(self, _worker, handed_pixmap, *_args, **_kwargs):
            captured["pixmap"] = handed_pixmap

    pool = Mock()
    pool.start = Mock()
    monkeypatch.setattr("app.worker_pools.ai_worker_pool", lambda: pool)
    monkeypatch.setattr("app.runnable.AiRunnable", _Runnable)

    app._api_schedule_block_reason = Mock(return_value="")
    app._get_request_scheduler = Mock(return_value=Mock(record_trigger_time=Mock()))
    app._get_request_timing_service = Mock(return_value=Mock(mark_started=Mock()))
    app._register_request_meta = Mock()
    app._publish_live_status = Mock()
    app._log_api_schedule = Mock()
    app._trigger_api_call = DanmuApp._trigger_api_call.__get__(app, DanmuApp)

    app._trigger_api_call()

    assert captured["pixmap"] is pixmap
    assert captured["pixmap"] is app._latest_screenshot
    assert captured["pixmap"].width() == 100
    assert captured["pixmap"].height() == 80
    pool.start.assert_called_once()


def test_on_ai_reply_enqueues_despite_stale_screenshot_id(monkeypatch):
    """旧 screenshot_id / captured_at 仍入队；见 tests/test_scene_freshness.py 同族用例。"""
    import main as main_mod

    app = make_minimal_danmu_app()
    app.ai_in_flight = 1
    app._latest_screenshot_id = 100
    app._register_request_meta(10, 1, 0, "visual")
    monkeypatch.setattr(main_mod, "parse_ai_reply_payload", lambda text: ["lagged"])
    monkeypatch.setattr(main_mod, "normalize_reply_batch", lambda raw_items, **kwargs: raw_items)
    app._on_ai_reply = main_mod.DanmuApp._on_ai_reply.__get__(app, main_mod.DanmuApp)
    app._consume_reply_queue = lambda: None
    app._publish_live_status = lambda: None

    old_captured = time.monotonic() - 120.0
    app._on_ai_reply('["lagged"]', "persona-1", 10, 1, old_captured, 0)

    assert not app.reply_buffer.is_empty()


def test_runnable_request_uncaught_exception_emits_error():
    """_request 阶段未捕获异常时应 emit error（与压缩失败对称）"""
    mock_pixmap = Mock()
    mock_pixmap.width.return_value = 100
    mock_pixmap.height.return_value = 80

    import threading

    mock_worker = Mock()
    mock_worker._stopping = threading.Event()
    mock_worker._request.side_effect = ValueError("bad config")

    runnable = AiRunnable(
        worker=mock_worker,
        pixmap=mock_pixmap,
        system_pt="system",
        user_pt="user",
        persona_id="test-persona",
        request_round=2,
        screenshot_id=3,
        captured_at=2.0,
        scene_generation=1,
        compress_fn=lambda _p: "data:image/jpeg;base64,abc",
        image_quality=85,
    )
    runnable.run()

    mock_worker._emit_safe.assert_called_once()
    call_args = mock_worker._emit_safe.call_args
    assert call_args[0][0] == "error"
    assert "bad config" in call_args[0][1]


def test_request_doubao_wall_clock_skips_http_before_retry():
    """S-012：墙上时钟已过时不再发起流式请求。"""
    import time
    from unittest.mock import MagicMock

    from app.ai_client_requests import request_doubao

    worker = MagicMock()
    worker._request_deadline_at = time.monotonic() - 1.0
    worker._resolve_request_credentials.return_value = (
        "https://api.example/v1",
        "key",
        "model",
        "doubao",
    )
    worker.config.get_float.return_value = 0.8
    worker.config.get_int.return_value = 512
    worker._deliver_outcome.return_value = None

    request_doubao(
        worker,
        "data:image/jpeg;base64,abc",
        "sys",
        "user",
        "p1",
        1,
        2,
        0.0,
        0,
    )

    worker._stream_doubao.assert_not_called()
    worker._deliver_outcome.assert_called_once()
    assert worker._deliver_outcome.call_args.kwargs["signal_name"] == "error"


def test_runnable_request_failure_releases_in_flight():
    """_request 异常经 error 信号回主线程后应释放 ai_in_flight"""

    _ = QApplication.instance() or QApplication([])

    app = make_minimal_danmu_app()
    worker = AiWorker(app.config)
    app.ai_worker = worker
    app._on_ai_error = DanmuApp._on_ai_error.__get__(app, DanmuApp)
    worker.error.connect(lambda *args: app._on_ai_error(*args))

    app.ai_in_flight = 1
    app._is_generating = True
    app._register_request_meta(2, 3, 1, "visual")

    mock_pixmap = Mock()
    mock_pixmap.width.return_value = 100
    mock_pixmap.height.return_value = 80

    def _raise_request(*_args, **_kwargs):
        raise ValueError("bad config")

    worker._request = _raise_request

    runnable = AiRunnable(
        worker=worker,
        pixmap=mock_pixmap,
        system_pt="system",
        user_pt="user",
        persona_id="test-persona",
        request_round=2,
        screenshot_id=3,
        captured_at=2.0,
        scene_generation=1,
        compress_fn=lambda _p: "data:image/jpeg;base64,abc",
        image_quality=85,
    )
    runnable.run()
    QApplication.processEvents()

    assert app.ai_in_flight == 0
    assert app._is_generating is False


def test_ai_success_reply_enqueued():
    """测试 AI 成功返回后弹幕正确入队"""
    app = make_minimal_danmu_app()
    app.ai_in_flight = 1
    app.screenshot_round = 10
    app._register_request_meta(10, 10, 0, "visual")  # W-RACE-001: 需预注册 meta

    app._on_ai_reply('["???A", "???B"]', "persona-1", 10, 10, time.monotonic(), 0)

    assert app.ai_in_flight == 0
    assert app._is_generating is False
    assert app.reply_buffer.size() == 1
    assert len(app.engine.calls) >= 1
    assert app._consecutive_failures == 0
    assert app._failure_backoff_paused is False


def test_legacy_stat_fields_proxy_to_stats_state():
    app = make_minimal_danmu_app()

    app.danmu_count = 3
    app._total_input_tokens = 11
    app._total_output_tokens = 7
    app._start_time = 5.5

    assert app.stats_state.danmu_count == 3
    assert app.stats_state.total_input_tokens == 11
    assert app.stats_state.total_output_tokens == 7
    assert app.stats_state.start_time == 5.5


def test_legacy_web_error_fields_proxy_to_web_runtime_state():
    app = make_minimal_danmu_app()

    DanmuApp._set_error_status_safe(app, "AI timeout", True)

    assert app.web_runtime_state.error_message == "AI timeout"
    assert app.web_runtime_state.is_error is True


def test_older_reply_not_dropped_in_normal_mode():
    """普通模式不做 newer-frame supersede，旧截图回复仍会入队展示"""
    app = make_minimal_danmu_app()
    app.ai_in_flight = 1
    app._latest_requested_screenshot_id = 11
    app._register_request_meta(10, 10, 0, "visual")  # W-RACE-001: 需预注册 meta

    app._on_ai_reply('["old reply"]', "persona-1", 10, 10, time.monotonic(), 0)

    assert app.ai_in_flight == 0
    assert len(app.engine.calls) >= 1
    assert not any("superseded_by_newer_request" in msg for msg in app.logger.info_messages)


def test_ai_error_releases_in_flight():
    """测试 AI 失败后错误提示和 in-flight 释放"""
    app = make_minimal_danmu_app()
    app.ai_in_flight = 2
    app.MAX_CONSECUTIVE_FAILURES = 5  # 确保不会触发退避

    # 模拟 AI 错误
    app._on_ai_error("AI timeout", "persona-1", 5, 5, time.monotonic(), 0)

    # 验证 in-flight 减少
    assert app.ai_in_flight == 1

    # 验证错误记录
    assert app._consecutive_failures == 1
    assert app._last_error_message == "AI timeout"

    assert app._web_error_is_error is True
    assert app._web_error_message == "AI timeout"


def test_nonfatal_ai_error_schedules_next_screenshot():
    """测试非致命 AI 错误不会中断节奏定时器调度"""
    app = make_minimal_danmu_app()
    app.engine.running = True
    app.ai_in_flight = 1

    app._on_ai_error("AI timeout", "persona-1", 5, 5, time.monotonic(), 0)

    assert app._failure_backoff_paused is False
    assert app._is_generating is False


def test_ai_error_does_not_crash_on_missing_ui():
    """测试 AI 错误处理在 UI 缺失时安全降级"""
    app = make_minimal_danmu_app()
    app.window = None  # 模拟 UI 未初始化

    app._on_ai_error("test error", "persona-1", 1, 1, 1.0, 0)

    assert app._consecutive_failures == 1
    assert app._last_error_message == "test error"


def test_empty_ai_reply_logs_warning(monkeypatch):
    """AI 解析结果为空时应记录 warning 便于排障"""
    app = make_minimal_danmu_app()
    app.ai_in_flight = 1
    app._register_request_meta(10, 10, 0, "visual")
    monkeypatch.setattr(
        "main.parse_ai_reply_payload",
        lambda _text: [],
    )
    monkeypatch.setattr(
        "main.normalize_reply_batch",
        lambda raw_items, **_kwargs: raw_items,
    )

    app._on_ai_reply("not-json", "persona-1", 10, 10, time.monotonic(), 0)

    assert any("empty_parse" in msg for msg in app.logger.warning_messages)


def test_legacy_overlay_cache_fields_proxy_to_web_runtime_state():
    app = make_minimal_danmu_app()

    app._cached_danmu_lines = 14
    app._cached_layout_mode = "windowed"

    assert app.web_runtime_state.cached_danmu_lines == 14
    assert app.web_runtime_state.cached_layout_mode == "windowed"


def test_generation_pipeline_state_is_read_only_projection():
    app = make_minimal_danmu_app()
    app._latest_displayed_round = 6
    app._latest_requested_screenshot_id = 12
    app._latest_queued_screenshot_id = 11
    app._latest_displayed_screenshot_id = 10

    state = GenerationPipelineState.from_app(app)

    assert state.latest_displayed_round == 6
    assert state.latest_requested_screenshot_id == 12
    assert state.latest_queued_screenshot_id == 11
    assert state.latest_displayed_screenshot_id == 10

def test_consecutive_failures_triggers_backoff_at_production_threshold():
    """W-TEST-AI-ERROR-001：连续 5 次失败（生产默认）后暂停并停截图定时器。"""
    app = make_minimal_danmu_app()
    app.ai_in_flight = 1
    app._on_ai_error = DanmuApp._on_ai_error.__get__(app, DanmuApp)
    app.screenshot_timer.active = True

    for i in range(4):
        app._on_ai_error(f"AI timeout: error {i}", "persona-1", i, i, 1.0 + i, 0)
        assert app._failure_backoff_paused is False

    app._on_ai_error("AI timeout: error 4", "persona-1", 4, 4, 5.0, 0)

    assert app._consecutive_failures == 5
    assert app._failure_backoff_paused is True
    assert app.screenshot_timer.active is False


def test_fatal_error_immediate_backoff():
    """测试致命错误（如 401）立即暂停截图"""
    app = make_minimal_danmu_app()
    app.ai_in_flight = 1
    app._on_ai_error = DanmuApp._on_ai_error.__get__(app, DanmuApp)
    app.screenshot_timer.active = True

    app._on_ai_error("401 API Key failure", "persona-1", 1, 1, time.monotonic(), 0)

    assert app._failure_backoff_paused is True
    assert app._consecutive_failures == 1
    assert app.screenshot_timer.active is False


def test_fatal_403_and_402_immediate_backoff():
    """W-TEST-AI-ERROR-001：403 与 402 状态码立即暂停。"""
    app = make_minimal_danmu_app()
    app._on_ai_error = DanmuApp._on_ai_error.__get__(app, DanmuApp)

    app.ai_in_flight = 1
    app.screenshot_timer.active = True
    app._on_ai_error("403 Forbidden", "persona-1", 1, 1, time.monotonic(), 0)
    assert app._failure_backoff_paused is True
    assert app.screenshot_timer.active is False

    app._failure_backoff_paused = False
    app._consecutive_failures = 0
    app.screenshot_timer.active = True
    app.ai_in_flight = 1
    app._on_ai_error("HTTP 402 Payment Required", "persona-1", 2, 2, time.monotonic(), 0)
    assert app._failure_backoff_paused is True
    assert app.screenshot_timer.active is False


def test_success_resets_failure_count():
    """测试成功请求后重置失败计数"""
    app = make_minimal_danmu_app()
    app.ai_in_flight = 1
    app._consecutive_failures = 3
    app._failure_backoff_paused = True
    app._last_error_message = "previous error"
    app._register_request_meta(10, 10, 0, "visual")  # W-RACE-001: 需预注册 meta

    app._on_ai_reply('["??????"]', "persona-1", 10, 10, time.monotonic(), 0)

    assert app._consecutive_failures == 0
    assert app._failure_backoff_paused is False
    assert app._last_error_message == ""


def test_screenshot_loop_respects_backoff():
    """测试截图循环在退避状态下不执行截图"""
    app = make_minimal_danmu_app()
    app.engine.running = True
    app._failure_backoff_paused = True

    app._capture_screenshot()

    assert app.screenshot_round == 0
    assert app._latest_screenshot is None

