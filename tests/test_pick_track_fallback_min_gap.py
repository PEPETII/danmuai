"""Test _pick_track fallback boundary clamping.

验证 BUG-005：全满场景下 fallback 分支的 x 坐标越界保护。
"""

import random

import pytest

from app.danmu_engine import DanmuEngine, DanmuItem
from app.config_store import ConfigStore


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
    # 填充轨道直到 can_accept 返回 False
    item_width = 150.0
    min_gap = 80.0
    x = 0.0
    while x + item_width + min_gap < screen_width:
        item = DanmuItem(content, scene_generation=0, x=x, width=item_width)
        track.items.append(item)
        x = item.x + item_width + min_gap


def test_fallback_clamps_x_to_screen_boundary(full_engine):
    """全满轨道 + 大宽度弹幕：fallback 后 x 必须不越界。"""
    # 所有轨道填满到边缘
    for track in full_engine.tracks:
        _fill_track_to_edge(track, full_engine.screen_width)

    # 创建宽度接近屏幕宽度的大弹幕（宽度 700px，在 800px 屏幕上容易越界）
    large_item = DanmuItem("超长弹幕内容", scene_generation=0, x=0.0, width=700.0)
    min_gap = 80.0

    # 多次测试，确保随机种子覆盖各种情况
    for seed in range(10):
        random.seed(seed)
        selected_track = full_engine._pick_track(large_item)

        # 验证返回了有效轨道
        assert selected_track is not None

        # 验证 item.x 不越界：item.x + item.width + min_gap < screen_width
        item_end = large_item.x + large_item.width + min_gap
        assert item_end <= full_engine.screen_width, (
            f"[seed={seed}] item.x={large_item.x} + width={large_item.width} "
            f"+ min_gap={min_gap} = {item_end} > screen_width={full_engine.screen_width}"
        )


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


def test_fallback_with_various_widths(full_engine):
    """测试不同宽度弹幕的边界保护。"""
    for track in full_engine.tracks:
        _fill_track_to_edge(track, full_engine.screen_width)

    widths = [100.0, 300.0, 500.0, 650.0, 750.0]
    min_gap = 80.0

    for width in widths:
        item = DanmuItem("弹幕", scene_generation=0, x=0.0, width=width)
        random.seed(42)
        full_engine._pick_track(item)

        # 验证越界保护
        item_end = item.x + item.width + min_gap
        assert item_end <= full_engine.screen_width, (
            f"width={width}: item_end={item_end} > screen_width={full_engine.screen_width}"
        )
