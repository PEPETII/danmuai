"""Scene memory store and main integration tests."""

import time

from app.memory.types import VisualMemoryUpdate
from app.memory_prompt_builder import build_memory_prompt_block
from app.reply_queue import AIReplyFIFOBuffer, QueuedReply
from app.scene_memory import SceneMemoryStore, append_memory_to_user_pt
from main import DanmuApp

from tests.conftest import bind_minimal_danmu_app
from tests.fakes import FakeConfig
from tests.test_p0_main_flow import _make_minimal_app


def _store_with_bullets(*phrases: str, gen: int = 0) -> SceneMemoryStore:
    store = SceneMemoryStore()
    for i, phrase in enumerate(phrases):
        store.record_displayed_bullet(phrase, gen, window=10, angle=f"scene_{i}")
    store.context.tone_hint = "轻松"
    return store


def test_memory_mode_off_does_not_append_user_pt():
    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=FakeConfig(), _scene_generation=0)
    app._scene_memory = _store_with_bullets("旧弹幕")
    base = "请基于这张截图生成弹幕："
    assert app._append_scene_memory_to_user_pt(base) == base


def test_memory_mode_dedup_only_no_scene_state():
    cfg = FakeConfig()
    cfg.get = lambda key, default="": {"memory_mode": "dedup_only"}.get(key, default)
    cfg.get_int = lambda key, default=0: 10 if key == "memory_window" else default

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=cfg, _scene_generation=0)
    store = _store_with_bullets("延续语境")
    store.update_from_visual_result(
        VisualMemoryUpdate(scene_generation=0, scene_summary="应不出现", confidence=0.8)
    )
    app._scene_memory = store
    result = app._append_scene_memory_to_user_pt("请生成弹幕：")
    assert "【最近弹幕去重】" in result
    assert "【当前场景状态】" not in result
    assert "应不出现" not in result


def test_memory_mode_scene_card_appends_block():
    cfg = FakeConfig()
    cfg.get = lambda key, default="": {"memory_mode": "scene_card"}.get(key, default)
    cfg.get_int = lambda key, default=0: 10 if key == "memory_window" else default

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=cfg, _scene_generation=0)
    store = _store_with_bullets("延续语境")
    store.update_from_visual_result(
        VisualMemoryUpdate(scene_generation=0, scene_summary="团战中", confidence=0.7)
    )
    app._scene_memory = store
    result = app._append_scene_memory_to_user_pt("请生成弹幕：")
    assert "【当前场景状态】" in result
    assert "延续语境" in result
    assert "必须以当前截图" in result


def test_scene_change_strict_clears_memory():
    store = _store_with_bullets("旧场景弹幕", gen=0)
    store.update_from_visual_result(
        VisualMemoryUpdate(scene_generation=0, scene_summary="旧场景", confidence=0.8)
    )
    store.on_scene_change(1, "strict")
    block = store.format_prompt_for_generation(1, "scene_card")
    assert block == "" or "旧场景弹幕" not in block


def test_scene_change_medium_clears_volatile_keeps_stable():
    store = SceneMemoryStore()
    store.update_from_visual_result(
        VisualMemoryUpdate(
            scene_generation=0,
            scene_summary="摘要",
            stable_facts=["稳定事实"],
            volatile_facts=["易变事实"],
            confidence=0.8,
        )
    )
    store.on_scene_change(1, "medium", tone_hint="轻松自然")
    assert store.context.volatile_facts == []
    assert store.context.scene_summary == ""
    assert "稳定事实" in store.context.stable_facts
    block = store.format_prompt_for_generation(1, "scene_card")
    assert "易变事实" not in block
    assert "轻松自然" in block


def test_scene_change_loose_carries_summary():
    store = SceneMemoryStore()
    store.update_from_visual_result(
        VisualMemoryUpdate(
            scene_generation=0,
            scene_summary="第一局打得不错",
            confidence=0.5,
        )
    )
    store.record_displayed_bullet("第一局打得不错", 0, window=10, angle="scene_0")
    store.on_scene_change(1, "loose", memory_window=10)
    block = store.format_prompt_for_generation(1, "scene_card")
    assert "第一局" in block or "不错" in block


def test_record_display_ignores_wrong_generation():
    store = SceneMemoryStore()
    store.record_displayed_bullet("不应记录", 99, window=10)
    assert store.dedup.recent_bullets == []


def test_bullets_do_not_grow_beyond_window():
    store = SceneMemoryStore()
    for i in range(25):
        store.record_displayed_bullet(f"弹幕{i}", 0, window=10, angle=f"scene_{i % 3}")
    assert len(store.dedup.recent_bullets) == 10


def test_fallback_memory_eligible_false_not_recorded():
    cfg = FakeConfig()
    cfg.get = lambda key, default="": {"memory_mode": "scene_card"}.get(key, default)
    cfg.get_int = lambda key, default=0: 10 if key == "memory_window" else default

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=cfg, _scene_generation=0)
    app._scene_memory = SceneMemoryStore()

    queued = QueuedReply(
        "p1", 1, 0, "fallback text",
        scene_generation=0,
        memory_eligible=False,
        is_fallback=True,
        source="fallback",
    )
    app._record_scene_memory_display(queued)
    assert app._scene_memory.dedup.recent_bullets == []


def test_record_scene_memory_display_tolerates_invalid_memory_window():
    cfg = FakeConfig()
    cfg.get = lambda key, default="": {
        "memory_mode": "scene_card",
        "memory_window": "abc",
    }.get(key, default)

    app = DanmuApp.__new__(DanmuApp)
    bind_minimal_danmu_app(app, config=cfg, _scene_generation=0)
    app._scene_memory = SceneMemoryStore()

    queued = QueuedReply(
        "p1", 1, 0, "有效弹幕",
        scene_generation=0,
        memory_eligible=True,
        is_fallback=False,
        source="ai",
    )
    app._record_scene_memory_display(queued)
    assert len(app._scene_memory.dedup.recent_bullets) == 1
    assert app._scene_memory.dedup.recent_bullets[0].text == "有效弹幕"


def test_consume_reply_queue_records_ai_display():
    cfg = FakeConfig()
    cfg.get = lambda key, default="": {
        "memory_mode": "scene_card",
        "drop_stale": "0",
    }.get(key, default)
    cfg.get_int = lambda key, default=0: 10 if key == "memory_window" else default

    app = _make_minimal_app()
    app.config = cfg
    app._scene_memory = SceneMemoryStore()
    app._record_scene_memory_display = DanmuApp._record_scene_memory_display.__get__(app, DanmuApp)
    app._memory_tone_hint = DanmuApp._memory_tone_hint.__get__(app, DanmuApp)
    app._memory_mode = DanmuApp._memory_mode.__get__(app, DanmuApp)
    app._memory_enabled = DanmuApp._memory_enabled.__get__(app, DanmuApp)
    app._scene_generation = 0
    app._latest_screenshot_id = 5
    app._latest_requested_screenshot_id = 5
    app._latest_queued_screenshot_id = 5
    app.reply_buffer.push(
        QueuedReply(
            "p1", 1, 0, "真实 AI 弹幕",
            screenshot_id=5,
            captured_at=time.monotonic(),
            scene_generation=0,
            memory_eligible=True,
            source="ai",
        )
    )

    app._consume_reply_queue()

    assert len(app._scene_memory.dedup.recent_bullets) == 1
    assert app._scene_memory.dedup.recent_bullets[0].text == "真实 AI 弹幕"


def test_consume_reply_queue_stale_does_not_record():
    cfg = FakeConfig()
    cfg.get = lambda key, default="": {
        "memory_mode": "scene_card",
        "drop_stale": "0",
    }.get(key, default)
    cfg.get_int = lambda key, default=0: 10 if key == "memory_window" else default

    app = _make_minimal_app()
    app.config = cfg
    app._scene_memory = SceneMemoryStore()
    app._scene_generation = 2
    app._latest_screenshot_id = 5
    app.reply_buffer.push(
        QueuedReply(
            "p1", 1, 0, "过期弹幕",
            screenshot_id=5,
            captured_at=time.monotonic(),
            scene_generation=1,
            memory_eligible=True,
            source="ai",
        )
    )

    app._consume_reply_queue()

    assert app._scene_memory.dedup.recent_bullets == []


def test_consume_reply_queue_fallback_not_recorded():
    cfg = FakeConfig()
    cfg.get = lambda key, default="": {
        "memory_mode": "scene_card",
        "drop_stale": "0",
    }.get(key, default)
    cfg.get_int = lambda key, default=0: 10 if key == "memory_window" else default

    app = _make_minimal_app()
    app.config = cfg
    app._scene_memory = SceneMemoryStore()
    app._scene_generation = 0
    app._latest_screenshot_id = 5
    app._latest_requested_screenshot_id = 5
    app._latest_queued_screenshot_id = 5
    app.reply_buffer.push(
        QueuedReply(
            "p1", 1, 0, "轻量 fallback",
            screenshot_id=5,
            captured_at=time.monotonic(),
            scene_generation=0,
            memory_eligible=False,
            is_fallback=True,
            source="fallback",
        )
    )

    app._consume_reply_queue()

    assert app._scene_memory.dedup.recent_bullets == []


def test_append_memory_to_user_pt_no_block_unchanged():
    assert append_memory_to_user_pt("prompt", "") == "prompt"


def test_on_scene_generation_advanced_resets_memory_when_enabled():
    cfg = FakeConfig()
    cfg.get = lambda key, default="": {
        "memory_mode": "scene_card",
        "memory_clear_policy": "strict",
        "freshness": "loose",
    }.get(key, default)

    app = _make_minimal_app()
    app.config = cfg
    app._scene_memory = _store_with_bullets("旧内容", gen=0)
    app._scene_generation = 1
    app.engine.running = True
    app.reply_buffer = AIReplyFIFOBuffer(max_items=8)
    app._current_persona = "p1"

    app._on_scene_generation_advanced(prev_hash=0xAAAA)

    assert app._scene_memory.context.scene_generation == 1
    assert app._scene_memory.dedup.recent_bullets == []


def test_enqueue_reply_batch_sets_memory_eligible():
    app = _make_minimal_app()
    app._batch_id = 1
    app._scene_generation = 0
    app._latest_screenshot_id = 1
    app._latest_screenshot_time = time.monotonic()

    app._enqueue_reply_batch(
        "p1", 1, 1, time.monotonic(), 0, ["a", "b"],
        from_local_fallback=True,
    )
    item = app.reply_buffer.peek()
    assert item is not None
    assert item.memory_eligible is False
    assert item.is_fallback is True

    app.reply_buffer.clear()
    app._enqueue_reply_batch(
        "p1", 2, 2, time.monotonic(), 0, ["c", "d"],
        from_local_fallback=False,
    )
    item = app.reply_buffer.peek()
    assert item.memory_eligible is True
    assert item.is_fallback is False


def test_update_from_visual_result_merges_context():
    store = SceneMemoryStore()
    store.update_from_visual_result(
        VisualMemoryUpdate(
            scene_generation=0,
            scene_type="desktop",
            scene_summary="写代码",
            confidence=0.75,
        )
    )
    block = build_memory_prompt_block(store.context, store.dedup, "scene_card")
    assert "desktop" in block or "写代码" in block
