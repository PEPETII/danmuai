"""运行期 HWND_TOPMOST 健康检查与独占全屏风险提示。"""
from __future__ import annotations

import logging
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.config_store import ConfigStore
from app.danmu_engine import DanmuEngine
from app.floating_panel_engine import FloatingPanelEngine
from app.floating_panel_overlay import FloatingPanelOverlay
from app.overlay import DanmuOverlay
from app.win32_overlay_zorder import probe_exclusive_fullscreen_risk, reassert_hwnd_topmost
from main import DanmuApp

from tests.conftest import FakeTimer, bind_minimal_danmu_app
from tests.fakes import FakeConfig, FakeEngine, FakeLifetimeStats, FakeSessionRunLog


def _bind_display_facade(app) -> None:
    for name in (
        "_danmu_render_mode",
        "_overlay_display_enabled",
        "_floating_panel_v2_enabled",
        "_active_overlay_layer",
        "_overlay_own_hwnds",
        "_reassert_pet_above_overlays",
        "_reassert_active_overlay_topmost",
        "_update_overlay_compat_warning",
        "_on_topmost_health_tick",
        "_ensure_web_runtime_state",
        "_on_app_focus_changed",
    ):
        method = getattr(DanmuApp, name)
        object.__setattr__(app, name, method.__get__(app, DanmuApp))


@pytest.fixture()
def topmost_app(qapp, workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "topmost.db")
    engine = DanmuEngine(store)
    overlay = DanmuOverlay(store, engine)
    overlay.setGeometry(0, 0, 800, 600)
    fp_engine = FloatingPanelEngine(store)
    fp_overlay = FloatingPanelOverlay(store, fp_engine)
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(
        app,
        config=store,
        engine=engine,
        overlay=overlay,
        floating_panel_engine=fp_engine,
        floating_panel_overlay=fp_overlay,
    )
    app._topmost_health_timer = FakeTimer()
    _bind_display_facade(app)
    app._ensure_web_runtime_state = DanmuApp._ensure_web_runtime_state.__get__(app, DanmuApp)
    return app, engine, overlay, fp_overlay


def test_topmost_timer_lifecycle_on_start_stop(topmost_app):
    app, engine, overlay, _ = topmost_app
    engine.running = True
    overlay.show()
    app._sync_overlay_visibility = Mock()
    app._sync_floating_panel_visibility = Mock()
    app._reassert_active_overlay_topmost = Mock()
    app._sync_pet_window_visibility = Mock()
    app._pool_topup_timer = FakeTimer()
    app._start_meme_barrage_timers = Mock()
    app.tray = Mock()
    app.state_changed = Mock()
    app._set_error_status_safe = Mock()
    app.logger = Mock()
    app._sync_mic_service = Mock()
    app._danmu_read_service = None

    # Exercise only the timer lines from start() after overlay sync.
    app._topmost_health_timer.start()
    app._reassert_active_overlay_topmost()
    assert app._topmost_health_timer.active

    app._topmost_health_timer.stop()
    app._ensure_web_runtime_state().set_overlay_compat_warning("")
    assert not app._topmost_health_timer.active


def test_show_event_applies_win32_click_through(topmost_app, qapp):
    app, _engine, overlay, _ = topmost_app
    calls: list[bool] = []
    overlay._apply_win32_click_through = lambda: calls.append(True)
    overlay.hide()
    qapp.processEvents()
    overlay.show()
    qapp.processEvents()
    assert calls


def test_health_tick_reasserts_scrolling_overlay(topmost_app, qapp):
    app, engine, overlay, _ = topmost_app
    engine.running = True
    overlay.show()
    qapp.processEvents()
    calls: list[str] = []
    overlay.reassert_topmost_zorder = lambda: calls.append("overlay")
    app._reassert_pet_above_overlays = Mock()
    app._update_overlay_compat_warning = Mock()
    app._on_topmost_health_tick()
    assert calls == ["overlay"]


def test_health_tick_reasserts_floating_panel(topmost_app, qapp, monkeypatch):
    app, engine, _, fp_overlay = topmost_app
    app.config.set("danmu_render_mode", "floating_panel")
    engine.running = True
    fp_overlay.show()
    qapp.processEvents()
    calls: list[str] = []
    fp_overlay.reassert_topmost_zorder = lambda: calls.append("fp")
    app._reassert_pet_above_overlays = Mock()
    app._update_overlay_compat_warning = Mock()
    app._on_topmost_health_tick()
    assert calls == ["fp"]


def test_health_tick_skips_when_hidden(topmost_app):
    app, engine, overlay, _ = topmost_app
    engine.running = True
    assert not overlay.isVisible()
    calls: list[str] = []
    overlay.reassert_topmost_zorder = lambda: calls.append("overlay")
    app._on_topmost_health_tick()
    assert calls == []
    assert app.web_runtime_state.overlay_compat_warning == ""


def test_focus_changed_delegates_to_active_overlay(topmost_app, qapp):
    app, engine, overlay, _ = topmost_app
    engine.running = True
    overlay.show()
    qapp.processEvents()
    calls: list[str] = []
    app._reassert_active_overlay_topmost = lambda: calls.append("reassert")
    app._on_app_focus_changed(None, None)
    assert calls == ["reassert"]


def test_probe_exclusive_fullscreen_risk(monkeypatch):
    import app.win32_overlay_zorder as mod

    if mod.sys.platform != "win32":
        pytest.skip("win32 only")

    monkeypatch.setattr(mod, "_read_window_rect", lambda hwnd: (0, 0, 1920, 1080))
    monkeypatch.setattr(mod, "_GetForegroundWindow", lambda: 100)
    assert probe_exclusive_fullscreen_risk(
        overlay_hwnd=100,
        screen_x=0,
        screen_y=0,
        screen_w=1920,
        screen_h=1080,
        own_hwnds=(100,),
    ) is False
    monkeypatch.setattr(mod, "_GetForegroundWindow", lambda: 9999)
    monkeypatch.setattr(mod, "_GetWindowLong", lambda hwnd, idx: 0)
    assert probe_exclusive_fullscreen_risk(
        overlay_hwnd=100,
        screen_x=0,
        screen_y=0,
        screen_w=1920,
        screen_h=1080,
        own_hwnds=(),
    ) is True
    monkeypatch.setattr(mod, "_GetWindowLong", lambda hwnd, idx: mod._WS_CAPTION)
    assert probe_exclusive_fullscreen_risk(
        overlay_hwnd=100,
        screen_x=0,
        screen_y=0,
        screen_w=1920,
        screen_h=1080,
        own_hwnds=(),
    ) is False


def test_apply_overlay_exstyles_sets_layered_and_transparent_bits(monkeypatch):

    import app.win32_overlay_zorder as mod

    if mod.sys.platform != "win32":
        pytest.skip("win32 only")

    stored: dict[int, int] = {mod._GWL_EXSTYLE: 0}

    monkeypatch.setattr(mod, "_GetWindowLong", lambda hwnd, idx: stored.get(idx, 0))
    monkeypatch.setattr(
        mod,
        "_SetWindowLong",
        lambda hwnd, idx, value: stored.__setitem__(idx, value),
    )

    mod.apply_overlay_exstyles(12345, click_through=True)
    assert stored[mod._GWL_EXSTYLE] & mod._WS_EX_LAYERED
    assert stored[mod._GWL_EXSTYLE] & mod._WS_EX_TRANSPARENT

    mod.apply_overlay_exstyles(12345, click_through=False)
    assert stored[mod._GWL_EXSTYLE] & mod._WS_EX_LAYERED
    assert not (stored[mod._GWL_EXSTYLE] & mod._WS_EX_TRANSPARENT)


def test_reassert_hwnd_topmost_noop_on_zero(monkeypatch):
    import app.win32_overlay_zorder as mod

    called: list[int] = []
    if mod.sys.platform == "win32":
        monkeypatch.setattr(mod, "_SetWindowPos", lambda *a, **k: called.append(1))
    reassert_hwnd_topmost(0)
    assert called == []


def test_status_includes_overlay_compat_warning(monkeypatch):
    engine = FakeEngine()
    engine.running = True
    app = SimpleNamespace(
        config=FakeConfig({}),
        engine=engine,
        reply_buffer=SimpleNamespace(size=lambda: 0),
        stats_state=StatsState(),
        web_runtime_state=WebRuntimeState(),
        lifetime_stats=FakeLifetimeStats(),
        session_run_log=FakeSessionRunLog(),
        personae=SimpleNamespace(get_active=lambda: []),
        visible_display_count=lambda: 0,
        build_live_status_snapshot=lambda: None,
        _region_selection_state="idle",
    )
    app.web_runtime_state.set_overlay_compat_warning("fullscreen-risk")
    monkeypatch.setattr(
        "app.model_selection.resolve_model_status",
        lambda config: {},
    )
    monkeypatch.setattr(
        "app.web_api.capture_region.capture_region_mode",
        lambda config: "full_screen",
    )
    status = DanmuApp.build_status_snapshot(app)
    assert status["overlay_compat_warning"] == "fullscreen-risk"


def test_status_clears_overlay_compat_warning_when_stopped(monkeypatch):
    engine = FakeEngine()
    engine.running = False
    app = SimpleNamespace(
        config=FakeConfig({}),
        engine=engine,
        reply_buffer=SimpleNamespace(size=lambda: 0),
        stats_state=StatsState(),
        web_runtime_state=WebRuntimeState(),
        lifetime_stats=FakeLifetimeStats(),
        session_run_log=FakeSessionRunLog(),
        personae=SimpleNamespace(get_active=lambda: []),
        visible_display_count=lambda: 0,
        build_live_status_snapshot=lambda: None,
        _region_selection_state="idle",
    )
    app.web_runtime_state.set_overlay_compat_warning("should-not-leak")
    monkeypatch.setattr(
        "app.model_selection.resolve_model_status",
        lambda config: {},
    )
    monkeypatch.setattr(
        "app.web_api.capture_region.capture_region_mode",
        lambda config: "full_screen",
    )
    status = DanmuApp.build_status_snapshot(app)
    assert status["overlay_compat_warning"] == ""


def test_reassert_hwnd_topmost_returns_false_on_setwindowpos_failure(monkeypatch):
    """BUG-004: SetWindowPos 返回 0 时 reassert_hwnd_topmost 必须返回 False；返回非 0 时 True。"""
    import app.win32_overlay_zorder as mod

    if mod.sys.platform != "win32":
        pytest.skip("win32 only: _SetWindowPos 仅在 win32 平台存在")

    monkeypatch.setattr(mod, "_SetWindowPos", lambda *a, **k: 0)
    assert reassert_hwnd_topmost(12345) is False

    monkeypatch.setattr(mod, "_SetWindowPos", lambda *a, **k: 1)
    assert reassert_hwnd_topmost(12345) is True


def test_overlay_topmost_fail_streak_accumulates_and_warns(
    topmost_app, qapp, monkeypatch, caplog
):
    """BUG-004: 连续 3 次 SetWindowPos 失败 → _topmost_fail_streak==3 且记 warning 日志。"""
    _, _, overlay, _ = topmost_app
    overlay.show()
    qapp.processEvents()

    # 模拟 SetWindowPos 始终失败
    monkeypatch.setattr("app.overlay.reassert_hwnd_topmost", lambda hwnd: False)

    with caplog.at_level(logging.WARNING, logger="danmu.overlay"):
        result1 = overlay.reassert_topmost_zorder()
        result2 = overlay.reassert_topmost_zorder()
        result3 = overlay.reassert_topmost_zorder()

    assert result1 is False
    assert result2 is False
    assert result3 is False
    assert overlay._topmost_fail_streak == 3
    assert any(
        "topmost reassert failed 3 times" in r.message for r in caplog.records
    )


def test_overlay_topmost_fail_streak_resets_on_success(topmost_app, qapp, monkeypatch):
    """BUG-004: 失败 2 次后第 3 次成功 → _topmost_fail_streak 清零。"""
    _, _, overlay, _ = topmost_app
    overlay.show()
    qapp.processEvents()

    call_count = {"n": 0}

    def fake_reassert(hwnd: int) -> bool:
        call_count["n"] += 1
        return call_count["n"] >= 3  # 前两次失败，第三次成功

    monkeypatch.setattr("app.overlay.reassert_hwnd_topmost", fake_reassert)

    overlay.reassert_topmost_zorder()
    assert overlay._topmost_fail_streak == 1
    overlay.reassert_topmost_zorder()
    assert overlay._topmost_fail_streak == 2
    overlay.reassert_topmost_zorder()
    assert overlay._topmost_fail_streak == 0


def test_update_overlay_compat_warning_uses_topmost_lost_when_fail_streak_3(
    topmost_app, qapp, monkeypatch
):
    """BUG-004: _topmost_fail_streak >= 3 时 _update_overlay_compat_warning 推送 overlay.topmost_lost。

    优先级高于独占全屏风险启发式：即使 probe_exclusive_fullscreen_risk 返回 False，
    只要连续失败达 3 次，告警即为 overlay.topmost_lost。
    """
    if sys.platform != "win32":
        pytest.skip("win32 only: _update_overlay_compat_warning 仅在 win32 处理告警")

    app, engine, overlay, _ = topmost_app
    engine.running = True
    overlay.show()
    qapp.processEvents()
    overlay._topmost_fail_streak = 3

    # 独占全屏风险探测返回 False，确保告警来源是 fail_streak 而非 at_risk
    monkeypatch.setattr(
        "app.main_display_mixin.probe_exclusive_fullscreen_risk",
        lambda **kwargs: False,
    )

    app._update_overlay_compat_warning()

    from app.translations import tr

    assert app.web_runtime_state.overlay_compat_warning == tr("overlay.topmost_lost")
