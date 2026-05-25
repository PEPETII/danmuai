"""Tests for memory prompt builder."""

from app.memory.store import SceneMemoryStore
from app.memory.types import VisualMemoryUpdate
from app.memory_prompt_builder import (
    BUDGET_SCENE_CARD,
    BUDGET_STRONG,
    append_memory_to_user_pt,
    build_constraints_section,
    build_memory_prompt_block,
)


def _store_with_context_and_bullets() -> SceneMemoryStore:
    store = SceneMemoryStore()
    store.update_from_visual_result(
        VisualMemoryUpdate(
            scene_generation=0,
            scene_type="game",
            scene_summary="团战中",
            volatile_facts=["血量偏低"],
            confidence=0.7,
        )
    )
    store.record_displayed_bullet("这波可以", 0, window=10, angle="scene_0")
    store.context.tone_hint = "轻松"
    return store


def test_build_off_returns_empty():
    store = _store_with_context_and_bullets()
    assert build_memory_prompt_block(store.context, store.dedup, "off") == ""


def test_dedup_only_has_dedup_not_scene_state():
    store = _store_with_context_and_bullets()
    block = build_memory_prompt_block(store.context, store.dedup, "dedup_only")
    assert "【最近弹幕去重】" in block
    assert "【生成约束】" in block
    assert "【当前场景状态】" not in block
    assert "团战" not in block


def test_scene_card_has_all_sections():
    store = _store_with_context_and_bullets()
    block = build_memory_prompt_block(store.context, store.dedup, "scene_card")
    assert "【当前场景状态】" in block
    assert "【最近弹幕去重】" in block
    assert "【生成约束】" in block
    assert "团战" in block
    assert "必须以当前截图" in block


def test_strong_budget_larger_than_standard():
    store = _store_with_context_and_bullets()
    for i in range(8):
        store.record_displayed_bullet(f"弹幕{i}", 0, window=20, angle=f"filler_{i}")
    store.context.stable_facts = [f"事实{i}" for i in range(5)]
    store.context.volatile_facts = [f"易变{i}" for i in range(6)]
    standard = build_memory_prompt_block(store.context, store.dedup, "scene_card")
    strong = build_memory_prompt_block(store.context, store.dedup, "strong")
    assert len(strong) <= BUDGET_STRONG
    assert len(standard) <= BUDGET_SCENE_CARD
    assert BUDGET_STRONG > BUDGET_SCENE_CARD


def test_append_memory_to_user_pt_no_block_unchanged():
    assert append_memory_to_user_pt("prompt", "") == "prompt"


def test_constraints_section_present():
    assert "必须以当前截图" in build_constraints_section()
