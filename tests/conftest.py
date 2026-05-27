"""Shared pytest configuration."""

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
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.memory.activity import RecentActivityState
from app.reply_queue import AIReplyFIFOBuffer
from app.scene_memory import SceneMemoryStore

from tests.fakes import (  # noqa: E402 — tests package (tests/__init__.py)
    FakeConfig,
    FakeEngine,
    FakeHistory,
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
    """Attach attributes to DanmuApp.__new__ instances (QObject without __init__)."""
    defaults = {
        "logger": FakeLogger(),
        "engine": FakeEngine(),
        "history": FakeHistory(),
        "history_writer": FakeHistoryWriter(),
        "reply_buffer": AIReplyFIFOBuffer(max_items=8),
        "reply_timer": FakeTimer(),
        "ai_in_flight": 0,
        "MAX_IN_FLIGHT": 1,
        "_screenshot_scheduled": False,
        "_schedule_next_screenshot": lambda delay_ms: None,
        "_queue_low_watermark": 3,
        "_queue_fallback_keep": 3,
        "_queue_run_dry_window_ms": 2000,
        "_queue_batch_size": 5,
        "_reply_scene_count": 2,
        "_reply_filler_count": 3,
        "stats_state": StatsState(),
        "screenshot_round": 0,
        "_latest_displayed_round": 0,
        "_rtt_history": [],
        "_request_started_at_by_id": {},
        "config": FakeConfig(),
        "web_runtime_state": WebRuntimeState(),
        "_consecutive_failures": 0,
        "_failure_backoff_paused": False,
        "_last_error_message": "",
        "_scene_generation": 0,
        "_last_scene_hash": None,
        "_inflight_scene_generation": 0,
        "_stale_scene_inflight_drop_count": 0,
        "_stale_scene_consume_drop_count": 0,
        "_latest_screenshot_id": 0,
        "_latest_requested_screenshot_id": 0,
        "_latest_queued_screenshot_id": 0,
        "_latest_displayed_screenshot_id": 0,
        "_scene_rhythm_pause_until": 0.0,
        "_scene_captures_after_change": 0,
        "_scene_api_gate_active": False,
        "_latest_screenshot_time": 0.0,
        "_inflight_screenshot_id": 0,
        "_screenshot_backoff_level": 0,
        "_stale_drop_count": 0,
        "_stale_drop_times": [],
        "_local_fallback_active": False,
        "_local_fallback_for_batch": 0,
        "_publish_live_status": lambda: None,
        "web_bridge": None,
        "_is_generating": False,
        "_batch_id": 0,
        "_current_batch": None,
        "_last_api_trigger_at": 0.0,
        "_scene_memory": SceneMemoryStore(),
        "_activity_state": RecentActivityState(),
        "_last_activity_collect_at": 0.0,
        "mic_in_flight": 0,
        "MAX_MIC_IN_FLIGHT": 1,
        "_mic_request_seq": 0,
        "_mic_batch_id": 0,
        "_pending_request_meta": {},
        "_scene_generation_bumped_at": 0.0,
        "_scene_gate_prev_hash": None,
        "_active_scene_probe_size": 16,
        "session_run_log": FakeSessionRunLog(),
    }
    defaults.update(overrides)
    for key, value in defaults.items():
        object.__setattr__(app, key, value)
    object.__setattr__(app, "danmu_queue", app.reply_buffer)
    if "lifetime_stats" not in overrides:
        object.__setattr__(app, "lifetime_stats", FakeLifetimeStats())
    if "_lifetime_flush_timer" not in overrides:
        object.__setattr__(app, "_lifetime_flush_timer", FakeTimer())
