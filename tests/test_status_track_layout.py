"""W-TRACK-VIS-002: /api/status 暴露 danmu_track_layout 轨道几何只读投影。

验证:
- StatusSnapshotBuilder.build() 返回 danmu_track_layout 字段
- track_count / track_ys / top_margin / bottom_margin / line_height / drawable_height
  / screen_height / screen_width / layout_mode 与 engine 实际几何一致
- WebStatusSnapshot(**snapshot) 不抛异常(dataclass 字段已同步)
- engine 为 None / 缺 tracks 时 getattr-safe 返回 {}
"""
from __future__ import annotations

import time
from types import SimpleNamespace

from app.application.stats_state import StatsState
from app.application.web_runtime_state import WebRuntimeState
from app.config_store import ConfigStore
from app.application.status_snapshot import StatusSnapshotBuilder
from app.danmu_engine_models import Track
from app.web_console_support import WebStatusSnapshot


def _track_layout_app(config, *, tracks=None, screen_h=1080.0, screen_w=1920.0):
    """构造带 tracks 的 minimal app,getattr-safe 兼容 _build_track_layout。"""
    engine = SimpleNamespace(
        running=True,
        tracks=tracks if tracks is not None else [],
        screen_height=screen_h,
        screen_width=screen_w,
        drawable_height=lambda: screen_h,
    )
    return SimpleNamespace(
        engine=engine,
        reply_buffer=SimpleNamespace(size=lambda: 0),
        visible_display_count=lambda: 0,
        floating_panel_overlay=None,
        stats_state=StatsState(danmu_count=0, start_time=time.monotonic()),
        web_runtime_state=WebRuntimeState(),
        personae=SimpleNamespace(get_active=lambda: []),
        config=config,
        lifetime_stats=SimpleNamespace(snapshot=lambda **_kwargs: {}),
        session_run_log=SimpleNamespace(list_dicts_newest_first=lambda: []),
        build_live_status_snapshot=lambda: None,
        _region_selection_state="idle",
        get_meme_barrage_status=lambda: {},
    )


def test_status_track_layout_full(workspace_tmp):
    config = ConfigStore(db_path=workspace_tmp / "track_layout_full.db")
    config.set("layout_mode", "1/2")
    tracks = [Track(y=50.0), Track(y=90.0), Track(y=130.0)]
    app = _track_layout_app(config, tracks=tracks, screen_h=1080.0, screen_w=1920.0)

    snapshot = StatusSnapshotBuilder(app).build()

    layout = snapshot["danmu_track_layout"]
    assert layout["track_count"] == 3
    assert layout["track_ys"] == [50.0, 90.0, 130.0]
    assert layout["top_margin"] == 50
    assert layout["bottom_margin"] == 80
    assert layout["line_height"] == 40
    assert layout["drawable_height"] == 1080.0
    assert layout["screen_height"] == 1080.0
    assert layout["screen_width"] == 1920.0
    assert layout["layout_mode"] == "1/2"

    # WebStatusSnapshot 字段同步,不抛 TypeError
    snap = WebStatusSnapshot(**snapshot)
    assert snap.danmu_track_layout["track_count"] == 3


def test_status_track_layout_empty_tracks(workspace_tmp):
    config = ConfigStore(db_path=workspace_tmp / "track_layout_empty.db")
    app = _track_layout_app(config, tracks=[])

    snapshot = StatusSnapshotBuilder(app).build()
    layout = snapshot["danmu_track_layout"]
    assert layout["track_count"] == 0
    assert layout["track_ys"] == []


def test_status_track_layout_reads_engine_metrics(workspace_tmp):
    """BUG-024: projection prefers engine _track_* fields over hardcoded defaults."""
    config = ConfigStore(db_path=workspace_tmp / "track_layout_metrics.db")
    engine = SimpleNamespace(
        running=True,
        tracks=[Track(y=100.0)],
        screen_height=1080.0,
        screen_width=1920.0,
        drawable_height=lambda: 540.0,
        _track_line_height=80.0,
        _track_top_margin=100.0,
        _track_bottom_margin=160.0,
    )
    app = _track_layout_app(config, tracks=engine.tracks, screen_h=1080.0, screen_w=1920.0)
    app.engine = engine

    layout = StatusSnapshotBuilder(app).build()["danmu_track_layout"]
    assert layout["line_height"] == 80.0
    assert layout["top_margin"] == 100.0
    assert layout["bottom_margin"] == 160.0


def test_status_track_layout_layout_mode_fallback(workspace_tmp):
    """未知 layout_mode 归一化为 fullscreen。"""
    config = ConfigStore(db_path=workspace_tmp / "track_layout_mode.db")
    config.set("layout_mode", "bogus")
    app = _track_layout_app(config, tracks=[Track(y=50.0)])

    snapshot = StatusSnapshotBuilder(app).build()
    assert snapshot["danmu_track_layout"]["layout_mode"] == "fullscreen"
