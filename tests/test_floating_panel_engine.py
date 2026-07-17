"""W-FP-STACK-ENGINE-001：FloatingPanelEngine 底部锚定堆积语义测试。

替换旧「持续上滚 / 底部空间准入阻塞」断言为聊天记录式堆积断言。
"""
from __future__ import annotations

from app.config_store import ConfigStore
from app.floating_panel_engine import FloatingPanelEngine


def _engine(tmp_path, **overrides) -> FloatingPanelEngine:
    store = ConfigStore(db_path=tmp_path / "fp_engine.db")
    store.set("dedup_threshold", "1.0")
    for key, value in overrides.items():
        store.set(key, str(value))
    engine = FloatingPanelEngine(store)
    engine.set_panel_height(400.0)
    return engine


def _pairwise_stack_gaps(engine: FloatingPanelEngine) -> list[float]:
    """活跃条目按 y 升序的相邻间距（下条顶 - 上条底）。"""
    items = sorted(
        [it for it in engine.visible_items() if not it.exiting],
        key=lambda it: it.target_y,
    )
    gaps: list[float] = []
    for idx in range(len(items) - 1):
        upper, lower = items[idx], items[idx + 1]
        gaps.append(lower.target_y - (upper.target_y + upper.height))
    return gaps


def _settle(engine: FloatingPanelEngine, *, steps: int = 40, dt: float = 0.05) -> None:
    for _ in range(steps):
        if not engine.needs_render_tick():
            break
        engine.update(dt)


def test_add_text_returns_item(workspace_tmp):
    engine = _engine(workspace_tmp)
    item = engine.add_text("hello", item_height=32.0, now=0.0)
    assert item is not None
    assert item.content == "hello"
    assert engine.visible_count() == 1
    assert hasattr(item, "style_index")
    assert hasattr(item, "target_y")


def test_new_item_starts_at_bottom(workspace_tmp):
    """新条从容器底部入场；目标底边贴面板底。"""
    engine = _engine(workspace_tmp)
    item = engine.add_text("bottom", item_height=40.0, now=0.0)
    assert item is not None
    assert item.current_y == 400.0  # 入场起点：顶边在面板底
    assert abs(item.target_y - (400.0 - 40.0)) < 0.01  # 目标底边 = 400


def test_can_accept_always_true_not_space_gated(workspace_tmp):
    """can_accept 不再表示底部空间不足；条目在场时仍可接受新条。"""
    engine = _engine(workspace_tmp)
    assert engine.can_accept_new_item(40.0) is True
    height = 40.0
    first = engine.add_text("one", item_height=height, now=0.0)
    assert first is not None
    assert engine.can_accept_new_item(height) is True
    second = engine.add_text("two", item_height=height, now=0.1)
    assert second is not None
    assert engine.visible_count() == 2


def test_second_item_joins_immediately_and_pushes_first(workspace_tmp):
    """第二个条目在第一个仍可见时可立即加入；旧条目标整体上移。"""
    engine = _engine(workspace_tmp, floating_panel_stack_gap="8")
    height = 40.0
    first = engine.add_text("one", item_height=height, now=0.0)
    assert first is not None
    y1_before = first.target_y
    second = engine.add_text("two", item_height=height, now=0.1)
    assert second is not None
    # 最新条目标底边贴底
    assert abs((second.target_y + second.height) - 400.0) < 0.01
    # 旧条被顶推到上方
    assert first.target_y < y1_before or first.target_y < second.target_y
    assert first.target_y + first.height + 8.0 <= second.target_y + 0.01
    assert engine.visible_count() == 2


def test_estimate_entry_delay_never_queues_for_space(workspace_tmp):
    """estimate_entry_delay_ms 不制造等待队列，始终就绪节奏。"""
    engine = _engine(workspace_tmp)
    height = 40.0
    assert engine.estimate_entry_delay_ms(height) == 100
    engine.add_text("one", item_height=height, now=0.0)
    assert engine.estimate_entry_delay_ms(height) == 100
    engine.add_text("two", item_height=height, now=0.1)
    assert engine.estimate_entry_delay_ms(height) == 100


def test_stack_gap_from_config(workspace_tmp):
    engine = _engine(workspace_tmp, floating_panel_stack_gap="12")
    height = 40.0
    for idx in range(3):
        item = engine.add_text(f"line-{idx}", item_height=height, now=float(idx), skip_dedup=True)
        assert item is not None
    for gap in _pairwise_stack_gaps(engine):
        assert abs(gap - 12.0) < 0.01


def test_duplicate_rejected(workspace_tmp):
    engine = _engine(workspace_tmp)
    assert engine.add_text("dup", item_height=32.0) is not None
    assert engine.add_text("dup", item_height=32.0) is None


def test_similar_duplicate_rejected(workspace_tmp):
    store = ConfigStore(db_path=workspace_tmp / "fp_lev.db")
    store.set("dedup_threshold", "0.5")
    engine = FloatingPanelEngine(store)
    engine.set_panel_height(400.0)
    assert engine.add_text("哈哈哈哈", item_height=32.0) is not None
    assert engine.add_text("哈哈哈哈啊", item_height=32.0) is None


def test_idle_update_does_not_move_settled_items(workspace_tmp):
    """无新消息且动画结束后，连续 update 不改变 current_y；needs_render_tick false。"""
    engine = _engine(
        workspace_tmp,
        floating_panel_entry_duration_ms="50",
        floating_panel_push_duration_ms="50",
    )
    item = engine.add_text("idle", item_height=40.0, now=0.0)
    assert item is not None
    _settle(engine)
    assert engine.needs_render_tick() is False
    y_snap = item.current_y
    for _ in range(10):
        engine.update(0.05, now=99.0)
        assert item.current_y == y_snap
    assert engine.needs_render_tick() is False
    assert engine.visible_count() == 1


def test_height_update_recomputes_targets_without_clear(workspace_tmp):
    engine = _engine(workspace_tmp, floating_panel_stack_gap="8")
    height = 40.0
    first = engine.add_text("one", item_height=height, skip_dedup=True, now=0.0)
    second = engine.add_text("two", item_height=height, skip_dedup=True, now=0.1)
    assert first is not None and second is not None
    engine.update_item_height(first, 80.0)
    assert engine.visible_count() == 2
    assert first.height == 80.0
    # 最新条仍贴底
    assert abs((second.target_y + second.height) - 400.0) < 0.01
    gap = second.target_y - (first.target_y + first.height)
    assert abs(gap - 8.0) < 0.01


def test_max_items_new_joins_oldest_exits(workspace_tmp):
    """达到 max_items 后新消息仍进入，最旧条目进入顶部退出流程。"""
    engine = _engine(
        workspace_tmp,
        floating_panel_max_items="3",
        floating_panel_exit_duration_ms="100",
        floating_panel_entry_duration_ms="0",
        floating_panel_push_duration_ms="0",
    )
    height = 30.0
    for i in range(4):
        item = engine.add_text(f"line-{i}", item_height=height, now=float(i))
        assert item is not None
    # 新消息不被拒绝；最旧应处于退出或已进入退出动画
    contents = [it.content for it in engine.visible_items()]
    assert "line-3" in contents
    exiting = [it for it in engine.visible_items() if it.exiting]
    active = [it for it in engine.visible_items() if not it.exiting]
    assert len(active) <= 3
    # 推进退出直至最旧移除
    for _ in range(40):
        engine.update(0.05)
    remaining = [it.content for it in engine.visible_items()]
    assert "line-3" in remaining
    assert "line-0" not in remaining or any(
        it.exiting and it.content == "line-0" for it in engine.visible_items()
    )
    # 最终活跃不超过 3
    assert engine.active_count() <= 3


def test_overflow_height_exits_top_not_bottom_queue(workspace_tmp):
    """总高度超出容器时顶部条目退出；底部无隐藏等待项。"""
    engine = _engine(
        workspace_tmp,
        floating_panel_stack_gap="0",
        floating_panel_max_items="50",
        floating_panel_entry_duration_ms="0",
        floating_panel_push_duration_ms="0",
        floating_panel_exit_duration_ms="50",
    )
    # 400px 面板，每条 120 → 约 4 条就超出
    for i in range(5):
        item = engine.add_text(f"tall-{i}", item_height=120.0, now=float(i), skip_dedup=True)
        assert item is not None  # 无底部拒绝
    # 无「等待队列」隐藏项：所有 _items 都是可见状态机条目
    for it in engine.visible_items():
        assert it.current_y is not None
    _settle(engine, steps=80)
    # 完全越顶后移除；存活条目目标应主要在面板内
    for it in engine.visible_items():
        if not it.exiting:
            assert it.target_y + it.height > 0.0


def test_engine_default_speed_is_one(workspace_tmp):
    """floating_panel_speed 仍可读（兼容），不驱动堆积位移。"""
    engine = _engine(workspace_tmp)
    assert engine.pixels_per_second == 120.0


def test_engine_uses_floating_panel_speed_for_pixels_per_second(workspace_tmp):
    engine = _engine(workspace_tmp, floating_panel_speed="3.0")
    assert engine.pixels_per_second == 360.0


def test_stack_animation_uses_duration_not_speed(workspace_tmp):
    """堆积位移由 duration 控制，与 floating_panel_speed 无关。"""
    slow = _engine(
        workspace_tmp,
        floating_panel_speed="0.5",
        floating_panel_entry_duration_ms="200",
        floating_panel_push_duration_ms="200",
    )
    fast_speed = _engine(
        workspace_tmp,
        floating_panel_speed="5.0",
        floating_panel_entry_duration_ms="200",
        floating_panel_push_duration_ms="200",
    )
    a = slow.add_text("a", item_height=40.0, now=0.0)
    b = fast_speed.add_text("b", item_height=40.0, now=0.0)
    assert a is not None and b is not None
    start_a, start_b = a.current_y, b.current_y
    slow.update(0.1, now=0.1)
    fast_speed.update(0.1, now=0.1)
    # 相同 duration → 相同进度比例
    progress_a = (start_a - a.current_y) / max(1e-6, start_a - a.target_y)
    progress_b = (start_b - b.current_y) / max(1e-6, start_b - b.target_y)
    assert abs(progress_a - progress_b) < 0.05


def test_style_index_fixed_at_creation(workspace_tmp):
    engine = _engine(workspace_tmp)
    a = engine.add_text("a", item_height=30.0, now=0.0, style_index=2)
    b = engine.add_text("b", item_height=30.0, now=0.1, style_index=7)
    assert a is not None and b is not None
    assert a.style_index == 2
    assert b.style_index == 7
    _settle(engine)
    assert a.style_index == 2
    assert b.style_index == 7


def test_exit_removes_only_when_fully_past_top(workspace_tmp):
    engine = _engine(
        workspace_tmp,
        floating_panel_max_items="1",
        floating_panel_entry_duration_ms="0",
        floating_panel_push_duration_ms="0",
        floating_panel_exit_duration_ms="200",
    )
    first = engine.add_text("old", item_height=40.0, now=0.0)
    second = engine.add_text("new", item_height=40.0, now=1.0)
    assert first is not None and second is not None
    assert first.exiting is True
    # 退出动画中途：仍在列表中（未瞬删）
    engine.update(0.05)
    assert first in engine.visible_items() or any(
        it.content == "old" for it in engine.visible_items()
    )
    # 推完退出
    for _ in range(20):
        engine.update(0.05)
    assert all(it.content != "old" for it in engine.visible_items())
    assert any(it.content == "new" for it in engine.visible_items())


def test_clear_resets_state(workspace_tmp):
    engine = _engine(workspace_tmp)
    engine.add_text("x", item_height=30.0)
    engine.clear()
    assert engine.visible_count() == 0
    assert engine.is_duplicate("x") is False


def test_empty_text_rejected(workspace_tmp):
    engine = _engine(workspace_tmp)
    assert engine.add_text("   ", item_height=30.0) is None
    assert engine.add_text("", item_height=30.0) is None


def test_batch_order_preserved(workspace_tmp):
    engine = _engine(workspace_tmp, floating_panel_entry_duration_ms="0", floating_panel_push_duration_ms="0")
    texts = ["a", "b", "c"]
    for i, t in enumerate(texts):
        engine.add_text(t, item_height=30.0, now=float(i), batch_id=1, skip_dedup=True)
    # 活跃条目从旧到新；最新在底部（target_y 最大）
    active = [it for it in engine.visible_items() if not it.exiting]
    by_y = sorted(active, key=lambda it: it.target_y)
    assert [it.content for it in by_y] == texts


def test_apply_config_recomputes_without_clearing(workspace_tmp):
    engine = _engine(workspace_tmp, floating_panel_stack_gap="8")
    engine.add_text("keep", item_height=40.0, now=0.0)
    engine.config.set("floating_panel_stack_gap", "16")
    engine.apply_config()
    assert engine.visible_count() == 1
    assert engine.stack_gap == 16.0


def test_scrolling_mode_uses_danmu_engine_not_fp_engine(workspace_tmp):
    """配置 scrolling 时不应误用 FloatingPanelEngine（由 main 路由保证；此处测 resolve）。"""
    from app.config_defaults import resolve_danmu_render_mode

    store = ConfigStore(db_path=workspace_tmp / "mode.db")
    store.set("danmu_render_mode", "scrolling")
    assert resolve_danmu_render_mode(store) == "scrolling"
