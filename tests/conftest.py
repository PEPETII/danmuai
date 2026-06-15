"""tests/conftest.py — 共享 pytest 配置与 fixture。

约定（与本仓库 AGENTS.md 测试约定一致）：
    - 临时目录：项目根 ``.pytest_tmp/``（避免 ``%TEMP%\\pytest-of-*`` 权限问题）。
      根 ``conftest.py`` 先重定向到 workspace 根，**本文件** 再细分 per-test
      子目录（``run-<pid>-<uuid>/``，每个 test session 一个）。
    - 共享假对象：在 ``tests/fakes.py``（FakeLogger / FakeEngine / FakeConfig /
      FakeTimer / FakeCapturer / FakeHistoryWriter / FakeLifetimeStats /
      FakeSessionRunLog）。本文件不重新实现，仅 import + 在 fixture / 辅助
      函数里组装。
    - 最小 DanmuApp：``bind_minimal_danmu_app(app, **overrides)``（QObject 不
      走 ``__init__``，直接 ``object.__setattr__`` 装属性）。``make_minimal_danmu_app``
      在此基础上再绑定主链路方法（``_on_screenshot_timer`` 等）方便单测。

fixture 索引：
    _isolate_log_emit_bus  autouse — Qt 析构后 ``LogEmitBus`` 引用失效，逐
                              用例重置为 ``None``（W-024 修复）
    workspace_tmp           per-test 临时目录（不走 %TEMP%）
    tmp_path                别名，给 pytest 内置 / 第三方插件用
    qapp                    PyQt6 QApplication 单例（Overlay 单测需要）
    danmu_app_minimal       ``make_minimal_danmu_app()`` 工厂封装
"""

# ruff: noqa: E402

import os
import shutil
import uuid
from pathlib import Path

# Redirect Windows temp before pytest/tmp_path_factory touches %TEMP%\\pytest-of-* .
_ROOT = Path(__file__).resolve().parent.parent
_WORKSPACE_TMP = (_ROOT / ".pytest_tmp").resolve()
_WORKSPACE_TMP.mkdir(parents=True, exist_ok=True)
_RUN_TMP = (_WORKSPACE_TMP / f"run-{os.getpid()}-{uuid.uuid4().hex[:8]}").resolve()
_RUN_TMP.mkdir(parents=True, exist_ok=True)
os.environ["TMP"] = str(_RUN_TMP)
os.environ["TEMP"] = str(_RUN_TMP)
os.environ["TMPDIR"] = str(_RUN_TMP)

_FEEDBACK_IMAGE_NAMES = (
    "qrcode_1779738450536.jpg",
    "mm_reward_qrcode_1779738306814.png",
)


def _ensure_feedback_static_images() -> None:
    """Mirror image/ QR assets into web/static/image for static UI and packaging."""
    dst_dir = _ROOT / "web" / "static" / "image"
    src_dir = _ROOT / "image"
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in _FEEDBACK_IMAGE_NAMES:
        src = src_dir / name
        dst = dst_dir / name
        if not src.is_file():
            continue
        if not dst.is_file() or src.stat().st_mtime_ns > dst.stat().st_mtime_ns:
            shutil.copy2(src, dst)


_ensure_feedback_static_images()

import pytest
from app.application.request_scheduler import RequestScheduler
from app.application.request_timing_service import RequestTimingService
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.reply_queue import AIReplyFIFOBuffer

from tests.fakes import (  # noqa: E402 — tests package (tests/__init__.py)
    FakeCapturer,
    FakeConfig,
    FakeEngine,
    FakeHistoryWriter,
    FakeLifetimeStats,
    FakeLogger,
    FakeSessionRunLog,
    FakeTimer,
)


def pytest_configure(config):
    config.option.basetemp = str(_RUN_TMP)


def _safe_node_dir(request) -> Path:
    safe = request.node.nodeid.replace("::", "_").replace("/", "_").replace("\\", "_")
    return _RUN_TMP / safe


@pytest.fixture(autouse=True)
def _isolate_log_emit_bus():
    """Reset global LogEmitBus between tests (Qt teardown may delete C++ object)."""
    import app.logger as logger_mod

    logger_mod._log_bus = None
    yield
    logger_mod._log_bus = None


@pytest.fixture
def workspace_tmp(request) -> Path:
    """Per-test directory under project .pytest_tmp (no %TEMP% access)."""
    path = _safe_node_dir(request)
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def tmp_path(workspace_tmp) -> Path:
    """Alias for pytest builtins/plugins that request tmp_path."""
    return workspace_tmp


def bind_minimal_danmu_app(app, **overrides):
    """给 ``DanmuApp.__new__(DanmuApp)`` 出来的 QObject 实例装一批默认属性。

    不调用 ``__init__``，避免触发 Qt / 屏幕 / 网络初始化；所有 attribute 用
    ``object.__setattr__`` 写入（绕开某些 ``__slots__`` / property 限制）。

    默认绑定（按需 ``overrides`` 覆盖）：
        logger / engine / history_writer / reply_buffer / reply_timer /
        ai_in_flight / mic_in_flight / stats_state / config /
        web_runtime_state / _pending_request_meta / session_run_log /
        _request_scheduler / _request_timing_service / lifetime_stats /
        _lifetime_flush_timer

    典型用法：
        app = DanmuApp.__new__(DanmuApp)
        bind_minimal_danmu_app(app, ai_in_flight=1)
        app._consume_reply_queue()  # 走真实主链路方法
    """
    """Attach attributes to DanmuApp.__new__ instances (QObject without __init__)."""
    defaults = {
        "logger": FakeLogger(),
        "engine": FakeEngine(),
        "history_writer": FakeHistoryWriter(),
        "reply_buffer": AIReplyFIFOBuffer(max_items=8),
        "reply_timer": FakeTimer(),
        "_topmost_health_timer": FakeTimer(),
        "ai_in_flight": 0,
        "_local_fallback_active": False,
        "_queue_low_watermark": 3,
        "_queue_fallback_keep": 3,
        "_queue_batch_size": 5,
        "_reply_scene_count": 2,
        "_reply_filler_count": 3,
        "stats_state": StatsState(),
        "screenshot_round": 0,
        "_latest_displayed_round": 0,
        "config": FakeConfig(),
        "web_runtime_state": WebRuntimeState(),
        "_consecutive_failures": 0,
        "_capture_fail_streak": 0,
        "_capture_error_active": False,
        "_capture_in_flight": False,
        "_failure_backoff_paused": False,
        "_last_error_message": "",
        "_scene_generation": 0,
        "_inflight_scene_generation": 0,
        "_latest_screenshot_id": 0,
        "_latest_requested_screenshot_id": 0,
        "_latest_queued_screenshot_id": 0,
        "_latest_displayed_screenshot_id": 0,
        "_latest_screenshot_time": 0.0,
        "_inflight_screenshot_id": 0,
        "_publish_live_status": lambda: None,
        "web_bridge": None,
        "_is_generating": False,
        "_batch_id": 0,
        "_current_batch": None,
        "mic_in_flight": 0,
        "_mic_request_seq": 0,
        "_mic_batch_id": 0,
        "_pending_request_meta": {},
        "session_run_log": FakeSessionRunLog(),
        "_mic_orchestrator": None,
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        object.__setattr__(app, key, value)
    if "lifetime_stats" not in overrides:
        object.__setattr__(app, "lifetime_stats", FakeLifetimeStats())
    if "_lifetime_flush_timer" not in overrides:
        object.__setattr__(app, "_lifetime_flush_timer", FakeTimer())
    if "_request_scheduler" not in overrides:
        object.__setattr__(app, "_request_scheduler", RequestScheduler())
    if "_request_timing_service" not in overrides:
        object.__setattr__(app, "_request_timing_service", RequestTimingService())


@pytest.fixture
def qapp():
    from PyQt6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
    app.processEvents()


@pytest.fixture()
def floating_panel_setup(qapp, workspace_tmp):
    """Create V2 floating panel overlay with stable defaults for focused tests."""
    from app.config_store import ConfigStore
    from app.floating_panel_engine import FloatingPanelEngine
    from app.floating_panel_overlay import FloatingPanelOverlay

    store = ConfigStore(db_path=workspace_tmp / "config.db")
    store.set("danmu_render_mode", "floating_panel")
    store.set("floating_panel_max_items", "12")
    store.set("floating_panel_font_size", "20")
    store.set("floating_panel_opacity", "85")
    engine = FloatingPanelEngine(store)
    overlay = FloatingPanelOverlay(store, engine)
    overlay.resize(360, 400)
    overlay.show()
    qapp.processEvents()
    return store, overlay


def make_minimal_floating_panel_app(store, panel):
    """Construct a minimal DanmuApp shell for FloatingPanel tests."""
    from main import DanmuApp

    app = DanmuApp.__new__(DanmuApp)
    object.__setattr__(app, "config", store)
    object.__setattr__(app, "floating_panel_overlay", panel)
    object.__setattr__(
        app,
        "logger",
        type(
            "L",
            (),
            {
                "debug": lambda *a, **k: None,
                "info": lambda *a, **k: None,
                "warning": lambda *a, **k: None,
                "error": lambda *a, **k: None,
            },
        )(),
    )
    return app


def bind_floating_panel_app_methods(app):
    """Bind display-related DanmuApp methods onto a __new__ instance."""
    from main import DanmuApp

    app._overlay_display_enabled = DanmuApp._overlay_display_enabled.__get__(app, DanmuApp)
    app._sync_overlay_visibility = DanmuApp._sync_overlay_visibility.__get__(app, DanmuApp)
    app._floating_panel_v2_enabled = DanmuApp._floating_panel_v2_enabled.__get__(app, DanmuApp)
    app._sync_floating_panel_visibility = DanmuApp._sync_floating_panel_visibility.__get__(app, DanmuApp)
    app._display_danmu_text = DanmuApp._display_danmu_text.__get__(app, DanmuApp)
    app._danmu_render_mode = DanmuApp._danmu_render_mode.__get__(app, DanmuApp)
    app._consume_reply_queue = DanmuApp._consume_reply_queue.__get__(app, DanmuApp)
    app._on_config_changed = DanmuApp._on_config_changed.__get__(app, DanmuApp)


class SpyOverlay:
    """Record overlay visibility interactions for FloatingPanel integration tests."""

    def __init__(self):
        self.show_calls = 0
        self.hide_calls = 0
        self.stop_render_calls = 0
        self.ensure_render_calls = 0
        self._dirty = False

    def show_for_screen(self, *_a, **_k):
        self.show_calls += 1

    def ensure_render_loop(self):
        self.ensure_render_calls += 1

    def stop_render_loop(self):
        self.stop_render_calls += 1

    def hide(self):
        self.hide_calls += 1

    def display_settings_dirty(self):
        return self._dirty

    def apply_display_settings(self):
        self._dirty = False


def make_minimal_danmu_app():
    """造一个**绑了主链路方法**的最小 DanmuApp（主链路单测专用）。

    与 ``bind_minimal_danmu_app`` 的差别：本函数会从 ``DanmuApp`` 类上把
    关键方法（``_on_screenshot_timer`` / ``_consume_reply_queue`` /
    ``_enqueue_reply_batch`` / ``_normal_recognition_interval_ms`` 等）通过
    ``__get__`` 绑到实例上，使单测可以**真实地**走主链路逻辑而不需要起
    Qt event loop。

    Returns:
        DanmuApp 实例（attribute 已装、主链路方法已绑，ai_worker 是 Mock）。
    """
    from unittest.mock import Mock

    from main import DanmuApp

    app = DanmuApp.__new__(DanmuApp)
    object.__setattr__(app, "_dedup_profile_log_at_count", 0)
    app.logger = FakeLogger()
    app.engine = FakeEngine()
    app.history_writer = FakeHistoryWriter()
    app.reply_buffer = AIReplyFIFOBuffer(max_items=8)
    app.reply_timer = FakeTimer()
    app.ai_in_flight = 0
    app.mic_in_flight = 0
    app._local_fallback_active = False
    app._mic_request_seq = 0
    app._mic_batch_id = 0
    app._pending_request_meta = {}
    app.reply_timer.active = False
    app._queue_low_watermark = 3
    app._queue_fallback_keep = 3
    app._queue_batch_size = 5
    app._reply_scene_count = 2
    app._reply_filler_count = 3
    app.stats_state = StatsState()
    app.screenshot_round = 0
    app._latest_displayed_round = 0
    app.config = FakeConfig()
    object.__setattr__(app, "_request_scheduler", RequestScheduler())
    object.__setattr__(app, "_request_timing_service", RequestTimingService())
    app.web_runtime_state = WebRuntimeState()
    app._consecutive_failures = 0
    app._capture_fail_streak = 0
    app._capture_error_active = False
    app._failure_backoff_paused = False
    app._last_error_message = ""
    app.MAX_CONSECUTIVE_FAILURES = 5
    app._pending = False
    app._scene_generation = 0
    app._inflight_scene_generation = 0
    app._mic_orchestrator = None
    app._latest_screenshot_id = 0
    app._latest_requested_screenshot_id = 0
    app._latest_queued_screenshot_id = 0
    app._latest_displayed_screenshot_id = 0
    app.screenshot_timer = FakeTimer()
    app._topmost_health_timer = FakeTimer()
    app.capturer = FakeCapturer(None)
    app._capture_in_flight = False
    app._capture_coordinator = Mock()
    app._capture_coordinator.completed = Mock()
    app.ai_worker = Mock()
    app.ai_worker._stopping = __import__("threading").Event()
    app._is_generating = False
    app._batch_id = 0
    app._current_batch = None
    app._latest_screenshot = None
    app._latest_screenshot_time = 0.0
    app._inflight_screenshot_id = 0
    app._inflight_started_at = 0.0
    app._publish_live_status = lambda: None
    app.web_bridge = None
    app.lifetime_stats = FakeLifetimeStats()
    app.session_run_log = Mock()
    app._lifetime_flush_timer = FakeTimer()
    app._live_status_timer = FakeTimer()
    app._sync_reply_batch_config = DanmuApp._sync_reply_batch_config.__get__(app, DanmuApp)
    app._normal_recognition_interval_ms = DanmuApp._normal_recognition_interval_ms.__get__(
        app, DanmuApp
    )
    app._normal_reply_count = DanmuApp._normal_reply_count.__get__(app, DanmuApp)
    app._queue_capacity = DanmuApp._queue_capacity.__get__(app, DanmuApp)
    app._enqueue_reply_batch = DanmuApp._enqueue_reply_batch.__get__(app, DanmuApp)
    app._consume_reply_queue = DanmuApp._consume_reply_queue.__get__(app, DanmuApp)
    app._on_screenshot_timer = DanmuApp._on_screenshot_timer.__get__(app, DanmuApp)
    app._on_normal_capture_tick = DanmuApp._on_normal_capture_tick.__get__(app, DanmuApp)
    app._schedule_capture = DanmuApp._schedule_capture.__get__(app, DanmuApp)
    app._apply_capture_result = DanmuApp._apply_capture_result.__get__(app, DanmuApp)
    app._on_capture_completed = DanmuApp._on_capture_completed.__get__(app, DanmuApp)
    app._has_visual_request_in_flight = DanmuApp._has_visual_request_in_flight.__get__(
        app, DanmuApp
    )
    app._capture_screenshot = DanmuApp._capture_screenshot.__get__(app, DanmuApp)
    app._note_capture_failure = DanmuApp._note_capture_failure.__get__(app, DanmuApp)
    app._note_capture_success = DanmuApp._note_capture_success.__get__(app, DanmuApp)
    app._set_error_status_safe = DanmuApp._set_error_status_safe.__get__(app, DanmuApp)
    app._reply_request_id = DanmuApp._reply_request_id.__get__(app, DanmuApp)
    app._register_request_meta = DanmuApp._register_request_meta.__get__(app, DanmuApp)
    app._pop_request_meta = DanmuApp._pop_request_meta.__get__(app, DanmuApp)
    app._consume_request_timing = DanmuApp._consume_request_timing.__get__(app, DanmuApp)
    app._get_request_scheduler = DanmuApp._get_request_scheduler.__get__(app, DanmuApp)
    app._get_request_timing_service = DanmuApp._get_request_timing_service.__get__(app, DanmuApp)
    app.get_request_scheduler = DanmuApp.get_request_scheduler.__get__(app, DanmuApp)
    app.get_request_timing_service = DanmuApp.get_request_timing_service.__get__(app, DanmuApp)
    app._release_inflight_for_source = DanmuApp._release_inflight_for_source.__get__(app, DanmuApp)
    app._acquire_visual_inflight = DanmuApp._acquire_visual_inflight.__get__(app, DanmuApp)
    app._ensure_stats_state = DanmuApp._ensure_stats_state.__get__(app, DanmuApp)
    app._update_stats = DanmuApp._update_stats.__get__(app, DanmuApp)
    app._estimated_reply_gap_ms = DanmuApp._estimated_reply_gap_ms.__get__(app, DanmuApp)
    app.state_changed = Mock()
    app._sync_reply_batch_config()
    return app


def start_app_timers(app):
    """Timer setup from DanmuApp.start() without full UI stack."""
    app.reply_buffer.set_max_items(app._queue_capacity())
    app.screenshot_timer.stop()
    app.screenshot_timer.setInterval(app._normal_recognition_interval_ms())
    app.screenshot_timer.start()
    app._live_status_timer.start()
    app._lifetime_flush_timer.start()


def make_app_for_start_without_api_key(monkeypatch):
    """Minimal DanmuApp stub for BUG-009 start() API-key guard tests."""
    from unittest.mock import MagicMock

    from main import DanmuApp

    app = DanmuApp.__new__(DanmuApp)
    engine = FakeEngine()
    engine_start_called: list[bool] = []

    def fake_engine_start():
        engine_start_called.append(True)
        engine.running = True

    monkeypatch.setattr(engine, "start", fake_engine_start)

    screenshot_timer = FakeTimer()
    tray = MagicMock()

    object.__setattr__(app, "config", FakeConfig({}))
    object.__setattr__(app, "engine", engine)
    object.__setattr__(app, "logger", FakeLogger())
    object.__setattr__(app, "web_runtime_state", WebRuntimeState())
    object.__setattr__(app, "tray", tray)
    object.__setattr__(app, "web_server", None)
    object.__setattr__(app, "screenshot_timer", screenshot_timer)
    object.__setattr__(app, "web_bridge", None)
    object.__setattr__(
        app,
        "_ensure_web_runtime_state",
        DanmuApp._ensure_web_runtime_state.__get__(app, DanmuApp),
    )
    object.__setattr__(
        app,
        "_set_error_status_safe",
        DanmuApp._set_error_status_safe.__get__(app, DanmuApp),
    )

    return app, engine_start_called, screenshot_timer, tray
