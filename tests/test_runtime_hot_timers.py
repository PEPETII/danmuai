"""W-TEST-COVER-012: runtime timer interval updates on config change."""

from __future__ import annotations

from unittest.mock import Mock

from app.application.web_runtime_state import WebRuntimeState
from app.config_store import ConfigStore
from app.reply_queue import AIReplyFIFOBuffer
from main import DanmuApp

from tests.fakes import FakeEngine, FakeTimer


def _timer_app(store: ConfigStore) -> DanmuApp:
    app = DanmuApp.__new__(DanmuApp)
    app.config = store
    app.engine = FakeEngine()
    app.overlay = Mock()
    app.overlay.display_settings_dirty = Mock(return_value=False)
    app.web_runtime_state = WebRuntimeState(
        cached_danmu_lines=store.get_int("danmu_lines", 4),
        cached_layout_mode=store.get("layout_mode", "fullscreen"),
    )
    app.screenshot_timer = FakeTimer()
    app.reply_buffer = AIReplyFIFOBuffer(max_items=8)
    app.hotkey = Mock()
    app._sync_mic_service = lambda: None
    app._sync_overlay_visibility = Mock()
    app._sync_floating_panel_visibility = Mock()
    app._sync_reply_batch_config = DanmuApp._sync_reply_batch_config.__get__(app, DanmuApp)
    app._normal_recognition_interval_ms = DanmuApp._normal_recognition_interval_ms.__get__(
        app, DanmuApp
    )
    app._queue_capacity = DanmuApp._queue_capacity.__get__(app, DanmuApp)
    app._ensure_web_runtime_state = DanmuApp._ensure_web_runtime_state.__get__(app, DanmuApp)
    app._overlay_display_enabled = lambda: False
    app._on_config_changed = DanmuApp._on_config_changed.__get__(app, DanmuApp)
    return app


def test_on_config_changed_updates_screenshot_timer_interval(workspace_tmp):
    store = ConfigStore(workspace_tmp / "timer_hot.db")
    store.set("normal_recognition_interval_sec", "5")
    app = _timer_app(store)
    app._on_config_changed()
    assert app.screenshot_timer._interval == 5000

    store.set("normal_recognition_interval_sec", "12")
    app._on_config_changed()
    assert app.screenshot_timer._interval == 12000
