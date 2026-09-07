"""W-TEST-COVER-003: runtime hot reload for overlay-related config keys."""

from __future__ import annotations

from unittest.mock import Mock

from app.application.web_runtime_state import WebRuntimeState
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine
from app.overlay import DanmuOverlay
from app.reply_queue import AIReplyFIFOBuffer
from main import DanmuApp

from tests.fakes import FakeTimer


def _hot_reload_app(store: ConfigStore) -> tuple[DanmuApp, DanmuOverlay]:
    engine = DanmuEngine(store)
    engine.set_screen_width(1920.0)
    engine.set_screen_height(1080.0)
    engine.reload_tracks()
    overlay = DanmuOverlay(store, engine)
    engine.overlay = overlay

    app = DanmuApp.__new__(DanmuApp)
    app.config = store
    app.engine = engine
    app.overlay = overlay
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
    app._overlay_display_enabled = lambda: True
    app._on_config_changed = DanmuApp._on_config_changed.__get__(app, DanmuApp)
    return app, overlay


def test_danmu_speed_change_reflected_on_new_engine_items(workspace_tmp, qapp):
    del qapp
    store = ConfigStore(workspace_tmp / "hot_speed.db")
    store.set("danmu_speed", "2")
    store.set("danmu_lines", "4")

    app, _overlay = _hot_reload_app(store)
    app.engine.running = True
    slow = app.engine.add_text("slow", persona="p")
    assert slow is not None
    assert slow.speed == 2.0

    store.set("danmu_speed", "8")
    app._on_config_changed()
    fast = app.engine.add_text("fast", persona="p")
    assert fast is not None
    assert fast.speed == 8.0


def test_opacity_change_updates_global_factor(workspace_tmp, qapp):
    del qapp
    store = ConfigStore(workspace_tmp / "hot_opacity.db")
    store.set("danmu_speed", "2")
    store.set("danmu_lines", "4")
    store.set("opacity", "100")

    _app, overlay = _hot_reload_app(store)
    store.set("opacity", "50")
    assert overlay._global_opacity_factor() == 0.5


def test_render_mode_switch_invokes_visibility_sync(workspace_tmp, qapp):
    del qapp
    store = ConfigStore(workspace_tmp / "hot_mode.db")
    store.set("danmu_speed", "2")
    store.set("danmu_lines", "4")
    store.set("danmu_render_mode", "scrolling")

    app, _overlay = _hot_reload_app(store)
    store.set("danmu_render_mode", "floating_panel")
    app._on_config_changed()

    app._sync_overlay_visibility.assert_called()
    app._sync_floating_panel_visibility.assert_called()
