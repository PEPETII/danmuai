"""W-FP-V2-001：/api/status 悬浮窗指标与 danmu_render_mode。"""
from __future__ import annotations

import time
from types import SimpleNamespace

import pytest
from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.config_store import ConfigStore
from app.floating_panel_engine import FloatingPanelEngine
from app.floating_panel_overlay import FloatingPanelOverlay
from main import DanmuApp
from PyQt6.QtWidgets import QApplication


def _minimal_status_app(*, config, floating_panel_overlay=None, visible_overlay: int = 0, running: bool = True):
    return SimpleNamespace(
        engine=SimpleNamespace(running=running),
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: visible_overlay,
        floating_panel_overlay=floating_panel_overlay,
        stats_state=StatsState(danmu_count=0, start_time=time.monotonic()),
        web_runtime_state=WebRuntimeState(),
        personae=SimpleNamespace(get_active=lambda: []),
        config=config,
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: None,
        region_selection_state="idle",
    )


@pytest.fixture()
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_status_scrolling_mode_display_count(workspace_tmp):
    config = ConfigStore(db_path=workspace_tmp / "status_scroll.db")
    config.set("danmu_render_mode", "scrolling")
    app = _minimal_status_app(config=config, visible_overlay=3)
    status = DanmuApp.build_status_snapshot(app)
    assert status["danmu_render_mode"] == "scrolling"
    assert "display_mode" not in status
    assert status["overlay_display_count"] == 3
    assert status["floating_panel_active_count"] == 0
    assert status["display_count"] == 3


def test_status_floating_panel_mode_uses_panel_count(qapp, workspace_tmp):
    config = ConfigStore(db_path=workspace_tmp / "status_fp.db")
    config.set("danmu_render_mode", "floating_panel")
    engine = FloatingPanelEngine(config)
    overlay = FloatingPanelOverlay(config, engine)
    overlay.resize(360, 400)
    overlay.show()
    qapp.processEvents()
    overlay.add_danmu_text("status metric")
    qapp.processEvents()

    app = _minimal_status_app(config=config, floating_panel_overlay=overlay, visible_overlay=0)
    status = DanmuApp.build_status_snapshot(app)
    assert status["danmu_render_mode"] == "floating_panel"
    assert "display_mode" not in status
    assert status["overlay_display_count"] == 0
    assert status["floating_panel_active_count"] == 1
    assert status["display_count"] == 1
