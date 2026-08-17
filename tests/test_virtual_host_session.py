from app.virtual_host import (
    DanmuBatchCreated,
    HostTurnResult,
    KnowledgeContextResult,
    SceneContext,
    VirtualHostSession,
)


class _PersonaManager:
    def __init__(self):
        self.pick_count = 0

    def pick_random(self):
        self.pick_count += 1
        return "稳定主播"

    def get_prompt(self, name):
        return "人格系统设定", f"人格用户设定:{name}"


def _batch(batch_id, created_at, generation, lines=("弹幕来了",)):
    return DanmuBatchCreated.from_lines(
        batch_id=batch_id,
        lines=list(lines),
        created_at=created_at,
        scene_generation=generation,
        ttl_seconds=10,
    )


def test_session_keeps_persona_and_turn_history_across_two_rounds():
    manager = _PersonaManager()
    session = VirtualHostSession(manager, session_id="session-1")
    scene = SceneContext(scene_generation=1, summary="当前画面", updated_at=100.0)
    assert session.update_scene_context(scene)
    assert session.accept_danmu_batch(_batch("b1", 100.0, 1), now=101.0)

    turn1 = session.start_turn("第一轮问题", now=101.0)
    result1 = HostTurnResult(session.session_id, turn1.turn_id, "第一轮回答")
    session.complete_turn(turn1, result1)
    turn2 = session.start_turn("第二轮问题", now=102.0)

    assert manager.pick_count == 1
    assert session.persona_id == "稳定主播"
    assert turn1.turn_id == 1 and turn2.turn_id == 2
    assert turn2.history[0].assistant_text == "第一轮回答"
    assert turn2.recent_batches[0].batch_id == "b1"


def test_session_rejects_duplicate_expired_and_stale_batches():
    session = VirtualHostSession(session_id="session-2", clock=lambda: 100.0)
    session.update_scene_context(SceneContext(scene_generation=3, summary="画面", updated_at=100.0))

    assert session.accept_danmu_batch(_batch("same", 100.0, 3), now=100.0)
    assert not session.accept_danmu_batch(_batch("same", 100.0, 3), now=100.0)
    assert session.last_batch_acceptance.reason == "duplicate"
    assert not session.accept_danmu_batch(_batch("old", 80.0, 3), now=100.0)
    assert session.last_batch_acceptance.reason == "expired"
    assert not session.accept_danmu_batch(_batch("stale", 100.0, 2), now=100.0)
    assert session.last_batch_acceptance.reason == "scene_generation"


def test_session_retains_at_most_three_batches_and_character_budget():
    session = VirtualHostSession(session_id="session-3", batch_char_budget=6)
    for index in range(4):
        assert session.accept_danmu_batch(
            _batch(f"b{index}", 100.0 + index, 0, (f"line{index}",)),
            now=100.0 + index,
        )

    batches = session.recent_batches(now=103.0)
    assert len(batches) <= 3
    assert sum(batch.char_count for batch in batches) <= 6
    assert batches[-1].batch_id == "b3"


def test_session_remembers_accepted_batch_id_after_retention_eviction():
    session = VirtualHostSession(session_id="session-eviction", batch_char_budget=5)
    assert session.accept_danmu_batch(_batch("once", 100.0, 0, ("12345",)), now=100.0)
    assert session.accept_danmu_batch(_batch("new", 101.0, 0, ("abcde",)), now=101.0)
    assert not session.accept_danmu_batch(_batch("once", 102.0, 0, ("12345",)), now=102.0)
    assert session.last_batch_acceptance.reason == "duplicate"


def test_prompt_layers_keep_persona_scene_danmu_knowledge_and_input_separate():
    manager = _PersonaManager()
    session = VirtualHostSession(manager, session_id="session-4")
    session.update_scene_context(SceneContext(scene_generation=1, summary="画面层", updated_at=100.0))
    session.accept_danmu_batch(_batch("b1", 100.0, 1, ("弹幕层",)), now=100.0)
    turn = session.start_turn("输入层", now=100.0)
    prompt = session.compose_prompt(
        turn,
        knowledge=KnowledgeContextResult(
            status="hit",
            prompt_text="知识层",
            item_ids=(1,),
            public_ids=("public-1",),
        ),
        now=100.0,
    )
    system, user = prompt.render()

    assert "[HOST_PERSONA_SYSTEM]" in system
    assert "[HOST_KNOWLEDGE]" in system
    assert "[HOST_PERSONA_USER]" in user
    assert "[HOST_SCENE]" in user
    assert "[HOST_DANMU]" in user
    assert "[HOST_INPUT]" in user
    assert user.index("[HOST_SCENE]") < user.index("[HOST_INPUT]")
    assert "知识层" not in user


def test_expired_scene_is_not_rendered_into_new_prompt():
    session = VirtualHostSession(session_id="session-5")
    session.update_scene_context(
        SceneContext(scene_generation=4, summary="过期画面", updated_at=100.0, ttl_seconds=2)
    )
    turn = session.start_turn("继续聊天", now=103.0)
    prompt = session.compose_prompt(turn, now=103.0)

    assert turn.scene_context is None
    assert "过期画面" not in prompt.user_prompt
