"""W-TEST-COVER-002: _on_config_changed multi-field combo side effects."""

from __future__ import annotations

from unittest.mock import Mock

from app.application.web_runtime_state import WebRuntimeState
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine
from app.overlay import DanmuOverlay
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply
from main import DanmuApp

from tests.fakes import FakeTimer


def _bind_config_changed_app(store: ConfigStore) -> DanmuApp:
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
    app._sync_pet_window_visibility = Mock()
    app._sync_reply_batch_config = DanmuApp._sync_reply_batch_config.__get__(app, DanmuApp)
    app._normal_recognition_interval_ms = DanmuApp._normal_recognition_interval_ms.__get__(
        app, DanmuApp
    )
    app._queue_capacity = DanmuApp._queue_capacity.__get__(app, DanmuApp)
    app._ensure_web_runtime_state = DanmuApp._ensure_web_runtime_state.__get__(app, DanmuApp)
    app._overlay_display_enabled = DanmuApp._overlay_display_enabled.__get__(app, DanmuApp)
    app._on_config_changed = DanmuApp._on_config_changed.__get__(app, DanmuApp)
    return app


def test_combo_render_mode_and_font_size_updates_overlay(workspace_tmp, qapp):
    del qapp
    store = ConfigStore(workspace_tmp / "combo_font.db")
    store.set("font_size", "24")
    store.set("danmu_speed", "2")
    store.set("danmu_lines", "4")
    store.set("danmu_render_mode", "scrolling")

    app = _bind_config_changed_app(store)
    assert app.overlay.font.pointSize() == 24

    store.set("danmu_render_mode", "floating_panel")
    store.set("font_size", "36")
    app._on_config_changed()

    assert app.overlay.font.pointSize() == 36
    app._sync_floating_panel_visibility.assert_called()
    app._sync_overlay_visibility.assert_called()


def test_combo_font_family_and_bold_apply_together(workspace_tmp, qapp):
    del qapp
    store = ConfigStore(workspace_tmp / "combo_family.db")
    store.set("danmu_speed", "2")
    store.set("danmu_lines", "4")
    store.set("danmu_font_family", "Microsoft YaHei")
    store.set("danmu_font_bold", "0")
    store.set("danmu_render_mode", "scrolling")

    app = _bind_config_changed_app(store)
    store.set("danmu_font_family", "SimHei")
    store.set("danmu_font_bold", "1")
    store.set("danmu_render_mode", "floating_panel")
    app._on_config_changed()

    assert app.overlay.font.family() == "SimHei"
    assert app.overlay.font.bold() is True


def test_combo_reply_queue_resize_on_config_change(workspace_tmp, qapp):
    del qapp
    store = ConfigStore(workspace_tmp / "combo_queue.db")
    store.set("danmu_speed", "2")
    store.set("danmu_lines", "4")
    store.set("reply_queue_max_items", "8")

    app = _bind_config_changed_app(store)
    for i in range(6):
        app.reply_buffer.push(QueuedReply("p", 1, i, f"t{i}", screenshot_round=1))

    store.set("reply_queue_max_items", "2")
    app._on_config_changed()

    assert app.reply_buffer.size() == 2
