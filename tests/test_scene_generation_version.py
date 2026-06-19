"""W-THEME-LAG-SCENE-VERSION-001: scene_generation bumps on scene config changes."""

from __future__ import annotations

from unittest.mock import Mock

import main as main_mod
from app.application.config_service import apply_web_config_patch, scene_version_fingerprint
from app.config_store import ConfigStore
from main import DanmuApp

from tests.conftest import make_minimal_danmu_app
from tests.fakes import FakeCapturer, FakePixmap


def _scene_version_app():
    app = make_minimal_danmu_app()
    app.engine.reload_tracks = Mock()
    app.hotkey = Mock()
    app.overlay = Mock()
    app.overlay.display_settings_dirty = Mock(return_value=False)
    app._sync_overlay_visibility = Mock()
    app._sync_floating_panel_visibility = Mock()
    app._sync_pet_window_visibility = Mock()
    app._sync_mic_service = Mock()
    app._overlay_display_enabled = lambda: False
    app._ensure_web_runtime_state = DanmuApp._ensure_web_runtime_state.__get__(app, DanmuApp)
    app._reset_scene_generation_baseline = DanmuApp._reset_scene_generation_baseline.__get__(
        app, DanmuApp
    )
    app._maybe_bump_scene_generation_on_config = (
        DanmuApp._maybe_bump_scene_generation_on_config.__get__(app, DanmuApp)
    )
    app._on_config_changed = DanmuApp._on_config_changed.__get__(app, DanmuApp)
    app._reset_scene_generation_baseline()
    return app


def test_baseline_stays_zero_until_scene_key_changes():
    app = _scene_version_app()
    assert app._scene_generation == 0
    assert app._scene_version_fingerprint == scene_version_fingerprint(app.config)


def test_live_topic_change_bumps_once():
    app = _scene_version_app()
    app.config.set("live_topic", "艾尔登法环")
    app._on_config_changed()
    assert app._scene_generation == 1

    app._on_config_changed()
    assert app._scene_generation == 1


def test_user_nickname_and_screen_index_bump():
    app = _scene_version_app()

    app.config.set("user_nickname", "小明")
    app._on_config_changed()
    assert app._scene_generation == 1

    app.config.set("screen_index", "1")
    app._on_config_changed()
    assert app._scene_generation == 2


def test_region_change_bumps():
    app = _scene_version_app()
    app.config.set_region(10, 20, 100, 80)
    app._on_config_changed()
    assert app._scene_generation == 1


def test_unrelated_config_no_bump():
    app = _scene_version_app()
    app.config.set("danmu_speed", "3")
    app._on_config_changed()
    assert app._scene_generation == 0

    app.config.set("opacity", "50")
    app._on_config_changed()
    assert app._scene_generation == 0


def test_capture_still_does_not_bump():
    app = _scene_version_app()
    app.engine.running = True
    app.capturer = FakeCapturer(FakePixmap(0))
    app._capture_screenshot = DanmuApp._capture_screenshot.__get__(app, DanmuApp)

    app._capture_screenshot()

    assert app._scene_generation == 0


def test_acquire_visual_inflight_uses_bumped_generation():
    app = _scene_version_app()
    app.config.set("live_topic", "新主题")
    app._on_config_changed()
    assert app._scene_generation == 1

    app._acquire_visual_inflight(42, app._scene_generation)
    assert app._inflight_scene_generation == 1
    assert app._inflight_screenshot_id == 42


def test_on_ai_reply_carries_bumped_scene_generation(monkeypatch):
    app = _scene_version_app()
    app.config.set("live_topic", "主题A")
    app._on_config_changed()
    scene_generation = app._scene_generation
    assert scene_generation == 1

    app._on_ai_reply = main_mod.DanmuApp._on_ai_reply.__get__(app, main_mod.DanmuApp)
    app._register_request_meta(1, 5, scene_generation, "visual")
    app.ai_in_flight = 1
    monkeypatch.setattr(main_mod, "parse_ai_reply_payload", lambda text: ["ok"])
    monkeypatch.setattr(main_mod, "normalize_reply_batch", lambda raw_items, **kwargs: raw_items)
    app._consume_reply_queue = lambda: None
    app._publish_live_status = lambda: None

    app._on_ai_reply('["ok"]', "persona-1", 1, 5, 0.0, scene_generation)

    assert not app.reply_buffer.is_empty()
    item = app.reply_buffer.peek()
    assert item.scene_generation == scene_generation


def test_apply_web_config_patch_bumps_via_config_changed(workspace_tmp):
    store = ConfigStore(workspace_tmp / "scene_version.db")
    store.set("_api_key", "sk-test")
    app = _scene_version_app()
    app.config = store
    app._reset_scene_generation_baseline()

    def _emit_config_changed():
        app._on_config_changed()

    app.config_changed = Mock()
    app.config_changed.emit = _emit_config_changed

    apply_web_config_patch(app, {"live_topic": "黑神话"})
    assert app._scene_generation == 1

    apply_web_config_patch(app, {"danmu_speed": "2.5"})
    assert app._scene_generation == 1


def test_reset_baseline_after_bump_clears_generation():
    app = _scene_version_app()
    app.config.set("live_topic", "主题")
    app._on_config_changed()
    assert app._scene_generation == 1

    app._reset_scene_generation_baseline()
    assert app._scene_generation == 0
    assert app._scene_version_fingerprint == scene_version_fingerprint(app.config)
