from app.virtual_host import (
    ActionDraft,
    DanmuBatchCreated,
    EmotionDraft,
    HostTurnResult,
    KnowledgeContextAdapter,
    SceneContext,
)


def test_danmu_batch_normalizes_limits_and_character_budget():
    batch = DanmuBatchCreated.from_lines(
        batch_id="batch-1",
        lines=["  第一条\n弹幕 ", "第一条 弹幕", "第二条", "第三条"],
        created_at=100.0,
        scene_generation=2,
        char_budget=6,
    )

    assert batch.lines == ("第一条 弹幕",)
    assert len(batch.lines) <= 10
    assert batch.char_count <= 6


def test_scene_context_requires_matching_generation_and_ttl():
    scene = SceneContext(
        scene_generation=7,
        summary="Boss 二阶段",
        keywords=("Boss", "Boss"),
        updated_at=100.0,
        ttl_seconds=5.0,
    )

    assert scene.is_fresh(scene_generation=7, now=104.9)
    assert not scene.is_fresh(scene_generation=6, now=104.0)
    assert not scene.is_fresh(scene_generation=7, now=105.1)


def test_host_result_keeps_actions_and_memory_effects_structured():
    result = HostTurnResult(
        session_id="session-1",
        turn_id=1,
        text="我看到啦",
        speak=True,
        emotion=EmotionDraft("happy", 1.5),
        actions=(ActionDraft("gesture", 0.8, 2.0),),
    )

    assert result.text == "我看到啦"
    assert result.emotion.intensity == 1.0
    assert result.actions[0].kind == "gesture"
    assert not hasattr(result.actions[0], "command")


class _Retriever:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def retrieve(self, **kwargs):
        if self.error:
            raise self.error
        return self.result


class _RetrievalResult:
    prompt_text = "[fact] 只返回的资料"
    hit_count = 3
    items = [{"id": 8, "public_id": "pub-8", "title": "来源标题"}]


class _RuntimeInjection:
    prompt_text = "[fact] runtime 资料"
    hit_count = 1
    item_ids = (9,)
    public_ids = ("pub-9",)


class _RuntimeOnly:
    retriever = None

    def build_visual_prompt_injection(self, **kwargs):
        return _RuntimeInjection()


def test_knowledge_adapter_reports_hit_with_budget_and_source_ids():
    adapter = KnowledgeContextAdapter(retriever=_Retriever(_RetrievalResult()), max_chars=8)
    result = adapter.retrieve(turn_id=1, input_text="这个 Boss 是谁")

    assert result.status == "hit"
    assert len(result.prompt_text) <= 8
    assert result.item_ids == (8,)
    assert result.public_ids == ("pub-8",)
    assert result.sources[0].source == "来源标题"


def test_knowledge_adapter_reports_no_hit_and_error_observably():
    no_hit = KnowledgeContextAdapter(retriever=_Retriever(None)).retrieve(
        turn_id=1,
        input_text="问题",
    )
    error = KnowledgeContextAdapter(retriever=_Retriever(error=RuntimeError("boom"))).retrieve(
        turn_id=2,
        input_text="问题",
    )

    assert no_hit.status == "no_hit"
    assert no_hit.diagnostic == "no_matching_items"
    assert error.status == "error"
    assert error.diagnostic == "retrieval_exception"


def test_knowledge_adapter_supports_runtime_public_injection_contract():
    result = KnowledgeContextAdapter(_RuntimeOnly()).retrieve(
        turn_id=1,
        input_text="runtime 查询",
    )

    assert result.status == "hit"
    assert result.item_ids == (9,)
    assert result.public_ids == ("pub-9",)
