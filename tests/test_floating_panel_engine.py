"""W-FP-V2-001：FloatingPanelEngine 单元测试。"""
from __future__ import annotations

from app.config_store import ConfigStore
from app.floating_panel_engine import FloatingPanelEngine


def _engine(tmp_path, **overrides) -> FloatingPanelEngine:
    store = ConfigStore(db_path=tmp_path / "fp_engine.db")
    for key, value in overrides.items():
        store.set(key, str(value))
    engine = FloatingPanelEngine(store)
    engine.set_panel_height(400.0)
    return engine


def test_add_text_returns_item(workspace_tmp):
    engine = _engine(workspace_tmp)
    item = engine.add_text("hello", item_height=32.0, now=0.0)
    assert item is not None
    assert item.content == "hello"
    assert engine.visible_count() == 1


def test_new_item_starts_at_bottom(workspace_tmp):
    engine = _engine(workspace_tmp)
    item = engine.add_text("bottom", item_height=40.0, now=0.0)
    assert item is not None
    assert item.current_y == 400.0


def test_second_item_shifts_targets_upward(workspace_tmp):
    engine = _engine(workspace_tmp)
    first = engine.add_text("one", item_height=40.0, now=0.0)
    second = engine.add_text("two", item_height=40.0, now=0.1)
    assert first is not None and second is not None
    # 新条目在底部（target_y 更大），旧条目被顶上去（target_y 更小）
    assert first.target_y < second.target_y


def test_duplicate_rejected(workspace_tmp):
    engine = _engine(workspace_tmp)
    assert engine.add_text("dup", item_height=32.0) is not None
    assert engine.add_text("dup", item_height=32.0) is None


def test_max_items_forces_oldest_exit(workspace_tmp):
    engine = _engine(workspace_tmp, floating_panel_max_items="3", floating_panel_lifetime_sec="60")
    for i in range(4):
        engine.add_text(f"line-{i}", item_height=30.0, now=0.0)
    assert engine.visible_count() == 3
    assert engine.visible_items()[-1].content == "line-3"
    assert engine.visible_items()[0].content != "line-0"


def test_lifetime_triggers_exit_and_removal(workspace_tmp):
    engine = _engine(workspace_tmp, floating_panel_lifetime_sec="1")
    engine.add_text("fade-me", item_height=30.0, now=0.0)
    engine.update(0.5, now=0.5)
    assert engine.visible_count() == 1
    for _ in range(40):
        engine.update(0.1, now=2.0)
    assert engine.visible_count() == 0


def test_clear_resets_state(workspace_tmp):
    engine = _engine(workspace_tmp)
    engine.add_text("x", item_height=30.0)
    engine.clear()
    assert engine.visible_count() == 0
    assert engine.is_duplicate("x") is False


def test_scrolling_mode_uses_danmu_engine_not_fp_engine(workspace_tmp):
    """配置 scrolling 时不应误用 FloatingPanelEngine（由 main 路由保证；此处测 resolve）。"""
    from app.config_defaults import resolve_danmu_render_mode

    store = ConfigStore(db_path=workspace_tmp / "mode.db")
    store.set("danmu_render_mode", "scrolling")
    assert resolve_danmu_render_mode(store) == "scrolling"
