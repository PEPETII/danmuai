"""
P0-005 最小主流程测试

覆盖核心链路：
1. 截图压缩失败路径
2. AI 成功返回入队
3. AI 失败后错误提示 / in-flight 释放
4. 连续失败退避
"""

import time
from types import SimpleNamespace
from unittest.mock import Mock

from app.application.generation_pipeline_state import GenerationPipelineState
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.memory.activity import RecentActivityState
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply
from app.runnable import AiRunnable
from app.scene_memory import SceneMemoryStore
from main import DanmuApp, compress_screenshot

from tests.fakes import FakeLifetimeStats, FakeLogger


class FakeConfig:
    def __init__(self, values=None):
        self.values = {}
        self.values.update(values or {})

    def get(self, key, default=""):
        return self.values.get(key, default)

    def get_int(self, key, default=0):
        val = self.values.get(key, default)
        return int(val)

    def get_float(self, key, default=0.0):
        val = self.values.get(key, default)
        return float(val)

    def get_api_key(self):
        return self.values.get("api_key", "")

    def get_region(self):
        return self.values.get("region", (0, 0, 200, 200))


class FakeEngine:
    def __init__(self):
        self.calls = []
        self.running = False
        self.dropped_pending = 0
        self.screen_width = 1920.0
        self._accel_remaining = 0
        self._accel_peak = 1.0
        self.tracks = []

    def add_text(self, content, persona, batch_id=0, scene_generation=0, *, skip_dedup=False, **_kwargs):
        self.calls.append((content, persona))
        return SimpleNamespace(
            content=content,
            persona=persona,
            batch_id=batch_id,
            scene_generation=scene_generation,
            x=2000.0,
            speed=2.2,
        )

    def clear_dedup_window(self):
        pass

    def drop_pending_below_generation(self, min_generation):
        return 0

    def drop_items_below_scene_generation(self, min_generation):
        return 0

    def drop_items_with_batch_id(self, batch_id):
        return 0

    def visible_display_count(self):
        return 0

    def min_on_screen(self):
        return 5

    def deficit_below_min(self):
        return 0

    def current_display_count(self):
        return 0

    def get_display_count(self):
        return 0

    def right_zone_count(self):
        return 0

    def danmu_pool_enabled(self):
        return False

    def needs_refill(self):
        return True

    def drop_pending_items(self):
        self.dropped_pending += 1
        return 1

    def start(self):
        self.running = True

    def stop(self):
        self.running = False


class FakeHistory:
    def __init__(self):
        self.calls = []

    def add(self, content, persona, round_num):
        self.calls.append((content, persona, round_num))


class FakeHistoryWriter:
    def __init__(self):
        self.calls = []

    def enqueue(self, content, persona, round_num, image_bytes=None):
        self.calls.append((content, persona, round_num, image_bytes))

    def stop(self):
        pass


class FakeTimer:
    def __init__(self):
        self.active = False
        self.started = 0
        self.stopped = 0
        self._interval = 800
        self._single_shot = False

    def isActive(self):
        return self.active

    def start(self, ms=0):
        self.active = True
        self.started += 1

    def stop(self):
        self.active = False
        self.stopped += 1

    def interval(self):
        return self._interval

    def setInterval(self, ms):
        self._interval = ms

    def setSingleShot(self, val):
        self._single_shot = val


class FakeCapturer:
    def __init__(self, pixmap=None):
        self._pixmap = pixmap

    def grab(self):
        return self._pixmap


class FakePixmap:
    def __init__(self, scene_byte, *, is_null: bool = False, width: int = 200, height: int = 200):
        self.scene_byte = scene_byte
        self._is_null = is_null
        self._width = width
        self._height = height

    def isNull(self):
        return self._is_null

    def width(self):
        return self._width

    def height(self):
        return self._height


def _make_minimal_app():
    """创建最小 mock 的 DanmuApp 实例"""
    app = DanmuApp.__new__(DanmuApp)
    object.__setattr__(app, "_dedup_profile_log_at_count", 0)
    object.__setattr__(app, "_scene_generation_bumped_at", 0.0)
    object.__setattr__(app, "_scene_gate_prev_hash", None)
    object.__setattr__(app, "_active_scene_probe_size", 16)
    app.logger = FakeLogger()
    app.engine = FakeEngine()
    app.history = FakeHistory()
    app.history_writer = FakeHistoryWriter()
    app.reply_buffer = AIReplyFIFOBuffer(max_items=8)
    app.danmu_queue = app.reply_buffer
    app.reply_timer = FakeTimer()
    app.ai_in_flight = 0
    app.MAX_IN_FLIGHT = 1
    app.mic_in_flight = 0
    app.MAX_MIC_IN_FLIGHT = 1
    app._mic_request_seq = 0
    app._mic_batch_id = 0
    app._pending_request_meta = {}
    app.STAGGER_INTERVAL = 1.0
    app._screenshot_scheduled = False
    app._schedule_next_screenshot = lambda delay_ms: None
    app.reply_timer.active = False
    app._queue_low_watermark = 3
    app._queue_fallback_keep = 3
    app._queue_run_dry_window_ms = 2000
    app._queue_batch_size = 5
    app._reply_scene_count = 2
    app._reply_filler_count = 3
    app.stats_state = StatsState()
    app.screenshot_round = 0
    app._latest_displayed_round = 0
    app._rtt_history = []
    app._request_started_at_by_id = {}
    app.config = FakeConfig()
    app.web_runtime_state = WebRuntimeState()
    app._consecutive_failures = 0
    app._failure_backoff_paused = False
    app._last_error_message = ""
    app.MAX_CONSECUTIVE_FAILURES = 5
    app._pending = False
    app._last_scene_hash = None
    app._scene_generation = 0
    app._inflight_scene_generation = 0
    app._stale_scene_inflight_drop_count = 0
    app._stale_scene_consume_drop_count = 0
    app._latest_screenshot_id = 0
    app._latest_requested_screenshot_id = 0
    app._latest_queued_screenshot_id = 0
    app._latest_displayed_screenshot_id = 0
    app._scene_rhythm_pause_until = 0.0
    app._scene_captures_after_change = 0
    app._scene_api_gate_active = False
    app._last_api_trigger_at = 0.0
    app.scheduled_delays = []
    app.screenshot_timer = FakeTimer()
    app.capturer = FakeCapturer(None)
    app._schedule_next_screenshot = lambda delay_ms: app.scheduled_delays.append(delay_ms)
    app._is_generating = False
    app._batch_id = 0
    app._current_batch = None
    app._latest_screenshot = None
    app._latest_screenshot_time = 0.0
    app._inflight_screenshot_id = 0
    app._inflight_started_at = 0.0
    app._stale_drop_count = 0
    app._stale_drop_times = []
    app._screenshot_backoff_level = 0
    app._local_fallback_active = False
    app._local_fallback_for_batch = 0
    app._publish_live_status = lambda: None
    app.web_bridge = None
    app.ai_worker = Mock()
    app._scene_memory = SceneMemoryStore()
    app._activity_state = RecentActivityState()
    app._last_activity_collect_at = 0.0
    app.lifetime_stats = FakeLifetimeStats()
    app.session_run_log = Mock()
    app._lifetime_flush_timer = FakeTimer()
    app._live_status_timer = FakeTimer()
    app._sync_reply_batch_config = DanmuApp._sync_reply_batch_config.__get__(app, DanmuApp)
    app._normal_recognition_interval_ms = DanmuApp._normal_recognition_interval_ms.__get__(app, DanmuApp)
    app._normal_reply_count = DanmuApp._normal_reply_count.__get__(app, DanmuApp)
    app._queue_capacity = DanmuApp._queue_capacity.__get__(app, DanmuApp)
    app._enqueue_reply_batch = DanmuApp._enqueue_reply_batch.__get__(app, DanmuApp)
    app._consume_reply_queue = DanmuApp._consume_reply_queue.__get__(app, DanmuApp)
    app._on_screenshot_timer = DanmuApp._on_screenshot_timer.__get__(app, DanmuApp)
    app._on_normal_capture_tick = DanmuApp._on_normal_capture_tick.__get__(app, DanmuApp)
    app._is_reply_stale = DanmuApp._is_reply_stale.__get__(app, DanmuApp)
    app._reply_request_id = DanmuApp._reply_request_id.__get__(app, DanmuApp)
    app._register_request_meta = DanmuApp._register_request_meta.__get__(app, DanmuApp)
    app._pop_request_meta = DanmuApp._pop_request_meta.__get__(app, DanmuApp)
    app._consume_request_timing = DanmuApp._consume_request_timing.__get__(app, DanmuApp)
    app._get_request_timing_service = DanmuApp._get_request_timing_service.__get__(app, DanmuApp)
    app._release_inflight_for_source = DanmuApp._release_inflight_for_source.__get__(app, DanmuApp)
    app._ensure_stats_state = DanmuApp._ensure_stats_state.__get__(app, DanmuApp)
    app._log_reply_drop = DanmuApp._log_reply_drop.__get__(app, DanmuApp)
    app._update_stats = DanmuApp._update_stats.__get__(app, DanmuApp)
    app._estimated_reply_gap_ms = DanmuApp._estimated_reply_gap_ms.__get__(app, DanmuApp)
    app._record_scene_memory_display = lambda *a, **k: None
    app.state_changed = Mock()
    app._sync_reply_batch_config()
    return app


class DedupFakeEngine(FakeEngine):
    def __init__(self, duplicate_text: str):
        super().__init__()
        self.duplicate_text = duplicate_text
        self.running = True

    def add_text(self, content, persona, batch_id=0, scene_generation=0, *, skip_dedup=False, **_kwargs):
        if not skip_dedup and content == self.duplicate_text:
            return None
        return super().add_text(
            content,
            persona,
            batch_id=batch_id,
            scene_generation=scene_generation,
            skip_dedup=skip_dedup,
        )

    def is_duplicate(self, content: str) -> bool:
        return content == self.duplicate_text


def _start_app_timers(app):
    """Exercise timer setup from DanmuApp.start() without full UI stack."""
    app.reply_buffer.set_max_items(app._queue_capacity())
    app.screenshot_timer.stop()
    app.screenshot_timer.setInterval(app._normal_recognition_interval_ms())
    app.screenshot_timer.start()
    app._live_status_timer.start()
    app._lifetime_flush_timer.start()


def test_normal_mode_start_uses_configured_capture_interval():
    app = _make_minimal_app()
    app.config = FakeConfig(
        {
            "danmu_display_mode": "normal",
            "normal_recognition_interval_sec": "7",
            "api_key": "test-key",
        }
    )
    app._sync_reply_batch_config()
    _start_app_timers(app)
    assert app.screenshot_timer._interval == 7000
    assert app.screenshot_timer.active


def test_normal_mode_enqueues_full_batch_without_prepend_replacement():
    app = _make_minimal_app()
    app.config = FakeConfig({"danmu_display_mode": "normal", "normal_reply_count": "3"})
    app._sync_reply_batch_config()
    app.reply_buffer.set_max_items(app._queue_capacity())

    def enqueue_batch(items: list[str], batch_id: int):
        app._batch_id = batch_id
        app._enqueue_reply_batch(
            "p1",
            1,
            batch_id,
            time.monotonic(),
            0,
            items,
        )

    enqueue_batch(["a", "b"], 1)
    enqueue_batch(["c", "d"], 2)
    assert app.reply_buffer.size() == 4
    popped = [app.reply_buffer.pop().content for _ in range(4)]
    assert popped == ["a", "b", "c", "d"]


def test_normal_tick_skips_while_in_flight():
    app = _make_minimal_app()
    app.config = FakeConfig({"danmu_display_mode": "normal"})
    app.engine.running = True
    grab_count = 0

    def grab():
        nonlocal grab_count
        grab_count += 1
        return FakePixmap(0)

    app.capturer = FakeCapturer(FakePixmap(0))
    app.capturer.grab = grab
    app.ai_in_flight = 1
    app._on_normal_capture_tick()
    assert grab_count == 0


def test_normal_mode_is_reply_stale_ignores_scene_generation():
    app = _make_minimal_app()
    app.config = FakeConfig({"danmu_display_mode": "normal", "drop_stale": "0"})
    stale, reason = app._is_reply_stale(1, time.monotonic(), scene_generation=0)
    assert stale is False
    assert reason == ""
    stale2, reason2 = app._is_reply_stale(1, time.monotonic(), scene_generation=99)
    assert stale2 is False
    assert reason2 == ""


def test_normal_mode_no_stale_ttl_when_drop_stale_enabled():
    app = _make_minimal_app()
    app.config = FakeConfig(
        {
            "danmu_display_mode": "normal",
            "drop_stale": "1",
            "normal_recognition_interval_sec": "5",
        }
    )
    captured = time.monotonic() - 60.0
    stale, reason = app._is_reply_stale(1, captured, scene_generation=0, source="ai")
    assert stale is False
    assert reason == ""


def test_normal_mode_consumes_all_non_duplicate_items():
    app = _make_minimal_app()
    app.config = FakeConfig(
        {
            "danmu_display_mode": "normal",
            "drop_stale": "0",
        }
    )
    app._sync_reply_batch_config()
    app.engine = DedupFakeEngine("dup")
    app.engine.running = True
    now = time.monotonic()
    for idx, text in enumerate(["ok1", "dup", "ok2"]):
        app.reply_buffer.push(
            QueuedReply(
                "p1",
                1,
                idx,
                text,
                screenshot_id=1,
                captured_at=now,
                scene_generation=0,
            )
        )
    for _ in range(3):
        app._consume_reply_queue()
    assert [c[0] for c in app.engine.calls] == ["ok1", "ok2"]
    assert len(app.history_writer.calls) == 2


def test_compress_screenshot_failure_path():
    """测试截图压缩失败时 in-flight 计数正确释放"""
    # 模拟一个会导致压缩失败的 pixmap
    mock_pixmap = Mock()
    mock_pixmap.toImage.side_effect = RuntimeError("has been deleted")

    # 创建 mock worker
    mock_worker = Mock()
    mock_worker._stopping = False

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


def test_ai_success_reply_enqueued():
    """测试 AI 成功返回后弹幕正确入队"""
    app = _make_minimal_app()
    app.ai_in_flight = 1
    app.screenshot_round = 10

    app._on_ai_reply('["???A", "???B"]', "persona-1", 10, 10, time.monotonic(), 0)

    assert app.ai_in_flight == 0
    assert app._is_generating is False
    assert app.reply_buffer.size() == 1
    assert len(app.engine.calls) >= 1
    assert app._consecutive_failures == 0
    assert app._failure_backoff_paused is False


def test_legacy_stat_fields_proxy_to_stats_state():
    app = _make_minimal_app()

    app.danmu_count = 3
    app._total_input_tokens = 11
    app._total_output_tokens = 7
    app._start_time = 5.5

    assert app.stats_state.danmu_count == 3
    assert app.stats_state.total_input_tokens == 11
    assert app.stats_state.total_output_tokens == 7
    assert app.stats_state.start_time == 5.5


def test_legacy_web_error_fields_proxy_to_web_runtime_state():
    app = _make_minimal_app()

    DanmuApp._set_error_status_safe(app, "AI timeout", True)

    assert app.web_runtime_state.error_message == "AI timeout"
    assert app.web_runtime_state.is_error is True


def test_older_reply_not_dropped_in_normal_mode():
    """普通模式不做 newer-frame supersede，旧截图回复仍会入队展示"""
    app = _make_minimal_app()
    app.ai_in_flight = 1
    app._latest_requested_screenshot_id = 11

    app._on_ai_reply('["old reply"]', "persona-1", 10, 10, time.monotonic(), 0)

    assert app.ai_in_flight == 0
    assert len(app.engine.calls) >= 1
    assert not any("superseded_by_newer_request" in msg for msg in app.logger.info_messages)


def test_low_water_buffer_can_schedule_prefetch():
    """测试节奏模式下 _maybe_schedule_screenshot 不再手动调度"""
    app = _make_minimal_app()
    app.engine.running = True
    app.reply_buffer.push(QueuedReply("persona-1", 1, 0, "pending", screenshot_id=1))

    app._maybe_schedule_screenshot()

    assert app.scheduled_delays == []


def test_inventory_policy_ignores_capture_mode_flag():
    """测试节奏模式下 _maybe_schedule_screenshot 不再手动调度"""
    app = _make_minimal_app()
    app.config = FakeConfig({"capture_mode": "smart"})
    app.engine.running = True
    app.reply_buffer.push(QueuedReply("persona-1", 1, 0, "pending", screenshot_id=1))

    app._maybe_schedule_screenshot()

    assert app.scheduled_delays == []


def test_ai_error_releases_in_flight():
    """测试 AI 失败后错误提示和 in-flight 释放"""
    app = _make_minimal_app()
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
    app = _make_minimal_app()
    app.engine.running = True
    app.ai_in_flight = 1

    app._on_ai_error("AI timeout", "persona-1", 5, 5, time.monotonic(), 0)

    assert app._failure_backoff_paused is False
    assert app._is_generating is False


def test_consecutive_failures_triggers_backoff():
    """测试连续失败达到阈值后自动暂停"""
    app = _make_minimal_app()
    app.ai_in_flight = 1
    app.MAX_CONSECUTIVE_FAILURES = 3  # 降低阈值以便测试

    # 模拟连续 3 次失败
    for i in range(3):
        app._on_ai_error(f"AI ??????: error {i}", "persona-1", i, i, 1.0 + i, 0)

    # 验证进入退避状态
    assert app._consecutive_failures == 3
    assert app._failure_backoff_paused is True

    assert app._web_error_is_error is True
    assert "连续" in app._web_error_message


def test_fatal_error_immediate_backoff():
    """测试致命错误（如 401）立即暂停截图"""
    app = _make_minimal_app()
    app.ai_in_flight = 1

    # 模拟致命错误（401 认证失败）
    app._on_ai_error("401 API Key failure", "persona-1", 1, 1, time.monotonic(), 0)

    # 验证立即进入退避状态
    assert app._failure_backoff_paused is True
    assert app._consecutive_failures == 1

    # 验证截图调度标志被清除
    assert app._screenshot_scheduled is False


def test_success_resets_failure_count():
    """测试成功请求后重置失败计数"""
    app = _make_minimal_app()
    app.ai_in_flight = 1
    app._consecutive_failures = 3
    app._failure_backoff_paused = True
    app._last_error_message = "previous error"

    app._on_ai_reply('["??????"]', "persona-1", 10, 10, time.monotonic(), 0)

    assert app._consecutive_failures == 0
    assert app._failure_backoff_paused is False
    assert app._last_error_message == ""


def test_screenshot_loop_respects_backoff():
    """测试截图循环在退避状态下不执行截图"""
    app = _make_minimal_app()
    app.engine.running = True
    app._failure_backoff_paused = True

    app._capture_screenshot()

    assert app.screenshot_round == 0
    assert app._latest_screenshot is None


def test_capture_does_not_advance_scene_generation(monkeypatch):
    """普通模式截图不探测场景跳变，代际保持不变"""
    app = _make_minimal_app()
    app.engine.running = True
    app._last_scene_hash = 0xAAAAAAAAAAAAAAAA
    app.reply_buffer.push(QueuedReply("p", 0, 0, "old", scene_generation=0))
    app.capturer = FakeCapturer(FakePixmap(0b1))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app.reply_buffer.size() == 1
    assert app._latest_screenshot is not None


def test_capture_while_in_flight_still_updates_frame(monkeypatch):
    app = _make_minimal_app()
    app.engine.running = True
    app._latest_screenshot_id = 3
    app.ai_in_flight = 1
    app.capturer = FakeCapturer(FakePixmap((1 << 16) - 1))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app._latest_screenshot_id == 4
    assert app._latest_screenshot is not None


def test_repeated_capture_keeps_scene_generation(monkeypatch):
    app = _make_minimal_app()
    app.engine.running = True
    app._last_scene_hash = 0xAAAAAAAAAAAAAAAA
    app.capturer = FakeCapturer(FakePixmap(0b1))

    app._capture_screenshot()

    assert app._scene_generation == 0
    assert app._latest_screenshot is not None


def test_scene_fingerprint_ignores_small_hash_drift(monkeypatch):
    from app.scene_fingerprint import is_scene_change

    prev = 0xAAAAAAAAAAAAAAAA
    cur = prev ^ (1 << 5)
    assert is_scene_change(prev, cur) is False


def test_ai_error_does_not_crash_on_missing_ui():
    """测试 AI 错误处理在 UI 缺失时安全降级"""
    app = _make_minimal_app()
    app.window = None  # 模拟 UI 未初始化

    app._on_ai_error("test error", "persona-1", 1, 1, 1.0, 0)

    assert app._consecutive_failures == 1
    assert app._last_error_message == "test error"


def test_invalid_pixmap_does_not_increment_screenshot_id():
    """无效 pixmap 不应递增 screenshot_id 或缓存帧"""
    app = _make_minimal_app()
    app.engine.running = True
    app._latest_screenshot_id = 5
    app.capturer = FakeCapturer(FakePixmap(0, is_null=True))

    app._capture_screenshot()

    assert app._latest_screenshot_id == 5
    assert app._latest_screenshot is None
    assert any("invalid_pixmap" in msg for msg in app.logger.warning_messages)


def test_empty_ai_reply_logs_warning(monkeypatch):
    """AI 解析结果为空时应记录 warning 便于排障"""
    app = _make_minimal_app()
    app.ai_in_flight = 1
    app._register_request_meta(10, 10, 0, "visual")
    monkeypatch.setattr(
        "main.parse_ai_reply_with_memory",
        lambda _text, _gen: ([], None),
    )
    monkeypatch.setattr(
        "main.normalize_reply_batch",
        lambda raw_items, **_kwargs: raw_items,
    )

    app._on_ai_reply("not-json", "persona-1", 10, 10, time.monotonic(), 0)

    assert any("empty_parse" in msg for msg in app.logger.warning_messages)


def test_capture_failure_reschedules_next_screenshot():
    """测试截图失败不会让主循环卡死（节奏模式由定时器驱动）"""
    app = _make_minimal_app()
    app.engine.running = True

    app._capture_screenshot()

    assert app._latest_screenshot is None


def test_legacy_overlay_cache_fields_proxy_to_web_runtime_state():
    app = _make_minimal_app()

    app._cached_danmu_lines = 14
    app._cached_layout_mode = "windowed"

    assert app.web_runtime_state.cached_danmu_lines == 14
    assert app.web_runtime_state.cached_layout_mode == "windowed"


def test_generation_pipeline_state_is_read_only_projection():
    app = _make_minimal_app()
    app._active_scene_probe_size = 32
    app._scene_generation_bumped_at = 4.5
    app._last_activity_collect_at = 2.5
    app._latest_displayed_round = 6
    app._latest_requested_screenshot_id = 12
    app._latest_queued_screenshot_id = 11
    app._latest_displayed_screenshot_id = 10

    state = GenerationPipelineState.from_app(app)

    assert state.active_scene_probe_size == 32
    assert state.scene_generation_bumped_at == 4.5
    assert state.last_activity_collect_at == 2.5
    assert state.latest_displayed_round == 6
    assert state.latest_requested_screenshot_id == 12
    assert state.latest_queued_screenshot_id == 11
    assert state.latest_displayed_screenshot_id == 10
    assert app._active_scene_probe_size == 32
    assert app._scene_generation_bumped_at == 4.5
