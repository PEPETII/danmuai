"""Test _pick_track fallback offscreen queue semantics.

验证 B-001：全满场景下 fallback 应在 tail 后方离屏排队，不得钳回屏幕内可见区。
"""

import heapq
import random

import pytest

from app.danmu_engine import DanmuEngine, DanmuItem
from app.config_store import ConfigStore
from app.danmu_engine_models import Track


@pytest.fixture()
def full_engine(workspace_tmp):
    """创建弹幕引擎，所有轨道均满。"""
    db_path = workspace_tmp / "fallback_test.db"
    store = ConfigStore(db_path=db_path)
    store.set("danmu_speed", "2.0")
    store.set("danmu_lines", "3")
    eng = DanmuEngine(store)
    eng.screen_width = 800.0
    eng.reload_tracks()
    return eng


def _fill_track_to_edge(track, screen_width: float, content: str = "示例弹幕"):
    """填满轨道到屏幕最右侧边缘。"""
    item_width = 150.0
    min_gap = 80.0
    x = 0.0
    while x + item_width + min_gap < screen_width:
        item = DanmuItem(content, scene_generation=0, x=x, width=item_width)
        track.items.append(item)
        x = item.x + item_width + min_gap


def _tail_edge(engine: DanmuEngine) -> float:
    return max(track.rightmost_edge() for track in engine.tracks)


def test_fallback_queues_offscreen_behind_tail(full_engine, monkeypatch):
    """全满轨道 + 大宽度弹幕：fallback 后 x 应在 tail 后方，不得钳回屏内。"""
    for track in full_engine.tracks:
        _fill_track_to_edge(track, full_engine.screen_width)

    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 100.0)
    large_item = DanmuItem("超长弹幕内容", scene_generation=0, x=900.0, width=700.0)
    min_gap = full_engine._calc_min_gap(large_item)
    tail_edge = _tail_edge(full_engine)
    old_max_allowed_x = full_engine.screen_width - large_item.width - min_gap

    selected_track = full_engine._pick_track(large_item)

    assert selected_track is not None
    assert large_item.x >= tail_edge + min_gap
    assert large_item.x > old_max_allowed_x


def test_fallback_picks_from_smallest_rightmost_edges(full_engine, monkeypatch):
    """满载 fallback 应从 rightmost_edge 最小的 3 条轨道中选取。"""
    track_count = len(full_engine.tracks)
    assert track_count >= 3

    for index, track in enumerate(full_engine.tracks):
        edge = float((index + 1) * 100)
        track.items.append(
            DanmuItem("fill", scene_generation=0, x=edge - 50.0, width=50.0)
        )

    monkeypatch.setattr(Track, "can_accept", lambda self, item, sw, gap: False)

    allowed = {
        track
        for track in heapq.nsmallest(3, full_engine.tracks, key=lambda t: t.rightmost_edge())
    }
    item = DanmuItem("incoming", scene_generation=0, x=0.0, width=120.0)
    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 100.0)

    for seed in range(30):
        random.seed(seed)
        selected = full_engine._pick_track(item)
        assert selected in allowed


def test_fallback_returns_valid_track(full_engine):
    """验证 fallback 始终返回有效 track。"""
    for track in full_engine.tracks:
        _fill_track_to_edge(track, full_engine.screen_width)

    item = DanmuItem("测试", scene_generation=0, x=0.0, width=100.0)

    for seed in range(20):
        random.seed(seed)
        selected = full_engine._pick_track(item)
        assert selected is not None
        assert selected in full_engine.tracks


def test_fallback_with_various_widths_stays_behind_tail(full_engine, monkeypatch):
    """不同宽度弹幕均应排在 tail 后方，不得回夹至屏内 max_allowed_x。"""
    for track in full_engine.tracks:
        _fill_track_to_edge(track, full_engine.screen_width)

    monkeypatch.setattr("app.danmu_engine.random.uniform", lambda a, b: 100.0)
    widths = [100.0, 300.0, 500.0, 650.0, 750.0]
    tail_edge = _tail_edge(full_engine)

    for width in widths:
        item = DanmuItem("弹幕", scene_generation=0, x=900.0, width=width)
        min_gap = full_engine._calc_min_gap(item)
        old_max_allowed_x = full_engine.screen_width - item.width - min_gap
        full_engine._pick_track(item)

        assert item.x >= tail_edge + min_gap
        if old_max_allowed_x < tail_edge + min_gap:
            assert item.x > old_max_allowed_x, (
                f"width={width}: item.x={item.x} clamped to visible zone "
                f"(max_allowed_x={old_max_allowed_x})"
            )
