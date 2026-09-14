"""知识包场景上下文组装与缓存失效测试（Wave 1）。

覆盖：
    - ``build_knowledge_scene_context``：live_topic / 空输入 / 关键词抽取
    - 禁止 ``round=`` / ``screenshot=`` 占位查询文本
    - ``KnowledgeRuntimeService.note_scene_generation`` / ``get_last_scene_context``
      在 scene_generation 不匹配时失效缓存

运行：``python -m pytest tests/test_knowledge_scene_context.py -q -x``
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from app.knowledge.models import KnowledgeSceneContext
from app.knowledge.runtime_service import (
    _SCENE_CONTEXT_TTL_SEC,
    SCENE_CONTEXT_REUSE_MAX_AGE_SEC,
    KnowledgeRuntimeService,
    build_knowledge_scene_context,
)

# ---------------------------------------------------------------------------
# build_knowledge_scene_context
# ---------------------------------------------------------------------------


def test_build_knowledge_scene_context_live_topic_only():
    """仅 live_topic → has_semantic_query True，brief/keywords 来自主题。"""
    ctx = build_knowledge_scene_context(
        live_topic="葛瑞克攻略",
        request_round=5,
        screenshot_id=9,
        scene_generation=2,
        now=1000.0,
    )
    assert isinstance(ctx, KnowledgeSceneContext)
    assert ctx.has_semantic_query is True
    assert "葛瑞克" in ctx.scene_brief or "葛瑞克" in " ".join(ctx.keywords)
    assert ctx.source_request_round == 5
    assert ctx.source_screenshot_id == 9
    assert ctx.scene_generation == 2
    assert ctx.updated_at == 1000.0
    # 不得把 round/screenshot 编号拼进查询文本
    assert "round=" not in ctx.scene_brief
    assert "screenshot=" not in ctx.scene_brief
    for kw in ctx.keywords:
        assert "round=" not in kw
        assert "screenshot=" not in kw


def test_build_knowledge_scene_context_empty_inputs_no_semantic_query():
    """全部空输入 → has_semantic_query False，brief/keywords 为空。"""
    ctx = build_knowledge_scene_context(
        live_topic="",
        recent_danmu=[],
        mic_text="",
        user_nickname="",
        extra_brief="",
        extra_keywords=[],
        request_round=99,
        screenshot_id=88,
    )
    assert ctx.has_semantic_query is False
    assert ctx.scene_brief == ""
    assert ctx.keywords == ()
    # 元数据仍可记录，但不得成为查询文本
    assert ctx.source_request_round == 99
    assert "round=" not in ctx.scene_brief
    assert "screenshot=" not in ctx.scene_brief


def test_build_knowledge_scene_context_never_produces_round_screenshot_text():
    """任意 round/screenshot 数值都不得出现在 brief/keywords 文本中。"""
    ctx = build_knowledge_scene_context(
        live_topic="",
        recent_danmu=None,
        mic_text="",
        extra_brief="",
        request_round=12345,
        screenshot_id=67890,
        scene_generation=3,
    )
    blob = f"{ctx.scene_brief}|{'|'.join(ctx.keywords)}|{'|'.join(ctx.scene_tags)}"
    assert "round=" not in blob
    assert "screenshot=" not in blob
    assert "12345" not in blob
    assert "67890" not in blob


def test_build_knowledge_scene_context_keywords_chinese_and_english():
    """中文 2–8 字与英文词均可抽取为 keywords。"""
    ctx = build_knowledge_scene_context(
        live_topic="葛瑞克 boss fight guide",
        recent_danmu=["这波操作可以", "nice play"],
        mic_text="注意二阶段",
        extra_keywords=["自定义标签"],
    )
    assert ctx.has_semantic_query is True
    joined = " ".join(ctx.keywords).lower()
    # 中文实体
    assert "葛瑞克" in joined or "葛瑞克" in ctx.scene_brief
    # 英文 token（长度 ≥2 且非 stopword）
    assert "boss" in joined or "fight" in joined or "guide" in joined
    # extra_keywords 原样进入
    assert "自定义标签" in ctx.keywords
    # stopword 不应主导
    assert "的" not in ctx.keywords
    assert "the" not in {k.lower() for k in ctx.keywords}


def test_build_knowledge_scene_context_recent_danmu_only_builds_brief():
    """仅 recent_danmu 有语义 → keywords 非空，必要时用 keywords 拼 brief。"""
    ctx = build_knowledge_scene_context(
        recent_danmu=["葛瑞克二阶段", "龙头连招"],
    )
    assert ctx.has_semantic_query is True
    assert ctx.keywords or ctx.scene_brief
    assert "round=" not in ctx.scene_brief


# ---------------------------------------------------------------------------
# runtime scene_generation cache invalidation
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_runtime(tmp_path, monkeypatch):
    """挂载真实 runtime（DB 在 tmp），供缓存 API 测试。"""
    from app.knowledge import database as db_module

    monkeypatch.setattr(db_module, "KNOWLEDGE_DB_PATH", tmp_path / "knowledge.db")
    app_stub = MagicMock()
    app_stub.logger = MagicMock()
    svc = KnowledgeRuntimeService(app_stub)
    yield svc
    svc.close()


def test_scene_generation_mismatch_invalidates_cached_context(isolated_runtime):
    """scene_generation 变化 → get_last_scene_context 返回 None。"""
    svc = isolated_runtime
    ctx = build_knowledge_scene_context(
        live_topic="葛瑞克",
        request_round=1,
        screenshot_id=1,
        scene_generation=1,
        now=2000.0,
    )
    assert ctx.has_semantic_query
    svc.remember_scene_context(ctx)

    # generation 匹配 → 可读
    got = svc.get_last_scene_context(scene_generation=1, now=2001.0)
    assert got is not None
    assert got.scene_generation == 1
    assert "葛瑞克" in got.scene_brief or "葛瑞克" in " ".join(got.keywords)

    # note 到新 generation → 清空缓存
    svc.note_scene_generation(2)
    assert svc.get_last_scene_context(scene_generation=1, now=2002.0) is None
    assert svc.get_last_scene_context(scene_generation=2, now=2002.0) is None


def test_get_last_scene_context_rejects_mismatched_generation_without_note(
    isolated_runtime,
):
    """未调用 note 时，查询参数 scene_generation 不匹配也返回 None。"""
    svc = isolated_runtime
    ctx = build_knowledge_scene_context(
        live_topic="葛瑞克",
        scene_generation=5,
        now=3000.0,
    )
    svc.remember_scene_context(ctx)

    assert svc.get_last_scene_context(scene_generation=5, now=3001.0) is not None
    assert svc.get_last_scene_context(scene_generation=6, now=3001.0) is None


def test_note_scene_generation_same_value_keeps_cache(isolated_runtime):
    """相同 scene_generation 重复 note → 缓存保留。"""
    svc = isolated_runtime
    ctx = build_knowledge_scene_context(
        live_topic="葛瑞克",
        scene_generation=3,
        now=4000.0,
    )
    svc.remember_scene_context(ctx)
    svc.note_scene_generation(3)
    got = svc.get_last_scene_context(scene_generation=3, now=4001.0)
    assert got is not None
    assert got.has_semantic_query


# ---------------------------------------------------------------------------
# Case H：普通视觉链路的真实语义 —— 检索诊断 + 复用窗口
# ---------------------------------------------------------------------------


class _FakeRetrieveResult:
    def __init__(self, prompt_text: str, items: list[dict]):
        self.prompt_text = prompt_text
        self.items = items
        self.hit_count = len(items)
        self.retrieval_ms = 3


class _StubRetriever:
    """只实现 runtime 注入路径用到的三个方法的最小替身。"""

    def __init__(self, hit: bool = True):
        self.hit = hit
        self.last_injected = None
        self.used_batches: list[list[int]] = []
        self.calls: list[dict] = []

    def retrieve(self, **kwargs):
        self.calls.append(kwargs)
        if not self.hit:
            return None
        return _FakeRetrieveResult(
            prompt_text="知识：葛瑞克弱点是龙头",
            items=[{"id": 11, "public_id": "ki_11", "content": "葛瑞克弱点是龙头"}],
        )

    def set_last_injected(self, contents):
        self.last_injected = list(contents)

    def mark_items_used(self, ids):
        self.used_batches.append(list(ids))


def test_visual_injection_uses_real_semantics_and_reports_injected(isolated_runtime):
    """真实场景语义 → 检索命中 → 诊断 injected，并记录使用次数。"""
    svc = isolated_runtime
    stub = _StubRetriever()
    svc.retriever = stub

    injection = svc.build_visual_prompt_injection(
        "葛瑞克二阶段", ["葛瑞克"], request_round=4, screenshot_id=7
    )

    assert injection is not None
    assert injection.hit_count == 1
    assert "葛瑞克" in injection.prompt_text
    assert svc.get_retrieval_diagnostic() == "injected"
    assert stub.used_batches == [[11]]
    # 传给检索器的是真实语义，不是 round/screenshot 编号占位
    assert stub.calls and stub.calls[0]["scene_brief"] == "葛瑞克二阶段"
    assert "round=" not in stub.calls[0]["scene_brief"]


def test_empty_scene_semantics_never_fabricates_query(isolated_runtime):
    """无真实语义时不得检索、不得伪造查询，诊断标记 empty_query。"""
    svc = isolated_runtime
    stub = _StubRetriever()
    svc.retriever = stub

    assert (
        svc.build_visual_prompt_injection(
            "", [], request_round=9, screenshot_id=9
        )
        is None
    )
    assert svc.get_retrieval_diagnostic() == "empty_query"
    assert stub.calls == []
    assert svc.get_last_injection() is None


def test_retriever_none_reports_knowledge_disabled(isolated_runtime):
    svc = isolated_runtime
    svc.retriever = None

    assert (
        svc.build_visual_prompt_injection(
            "葛瑞克", ["葛瑞克"], request_round=1, screenshot_id=1
        )
        is None
    )
    assert svc.get_retrieval_diagnostic() == "knowledge_disabled"


def test_retriever_exception_reports_retriever_error(isolated_runtime):
    svc = isolated_runtime

    class _Boom(_StubRetriever):
        def retrieve(self, **kwargs):
            raise RuntimeError("db gone")

    svc.retriever = _Boom()

    assert (
        svc.build_visual_prompt_injection(
            "葛瑞克", ["葛瑞克"], request_round=1, screenshot_id=1
        )
        is None
    )
    assert svc.get_retrieval_diagnostic() == "retriever_error"


def test_retriever_miss_reports_no_hit(isolated_runtime):
    svc = isolated_runtime
    svc.retriever = _StubRetriever(hit=False)

    assert (
        svc.build_visual_prompt_injection(
            "葛瑞克", ["葛瑞克"], request_round=1, screenshot_id=1
        )
        is None
    )
    assert svc.get_retrieval_diagnostic() == "no_hit"


def test_reuse_window_is_strictly_narrower_than_default_ttl():
    """复用窗口必须是收紧的硬上限，否则陈旧语义会持续污染检索。"""
    assert 0 < SCENE_CONTEXT_REUSE_MAX_AGE_SEC < _SCENE_CONTEXT_TTL_SEC


def test_max_age_override_narrows_reuse_window(isolated_runtime):
    """普通视觉链路复用上一轮语义时，窗口由 max_age_sec 收紧。"""
    svc = isolated_runtime
    ctx = build_knowledge_scene_context(
        live_topic="葛瑞克", scene_generation=7, now=5000.0
    )
    svc.remember_scene_context(ctx)

    reuse = SCENE_CONTEXT_REUSE_MAX_AGE_SEC
    # 窗口内可读
    assert (
        svc.get_last_scene_context(
            scene_generation=7,
            now=5000.0 + reuse - 1.0,
            max_age_sec=reuse,
        )
        is not None
    )
    # 超出复用窗口 → 拒绝
    assert (
        svc.get_last_scene_context(
            scene_generation=7,
            now=5000.0 + reuse + 1.0,
            max_age_sec=reuse,
        )
        is None
    )
    # 同一时刻不传 max_age_sec 时仍在默认 TTL 内 → 证明是窗口在收紧
    assert (
        svc.get_last_scene_context(
            scene_generation=7, now=5000.0 + reuse + 1.0
        )
        is not None
    )


def test_repeated_identical_semantics_do_not_slide_reuse_window(isolated_runtime):
    """同一批语义重复注入时复用窗口起点不变；新语义才重置窗口。"""
    svc = isolated_runtime
    svc.retriever = _StubRetriever()

    first = svc.build_visual_prompt_injection(
        "葛瑞克", ["葛瑞克"], request_round=1, screenshot_id=1
    )
    assert first is not None
    ctx1 = svc.get_last_scene_context(scene_generation=0)
    assert ctx1 is not None
    recorded_at = ctx1.updated_at

    # 留出可观测的时间差，确保 time.time() 确实前进
    time.sleep(0.05)

    again = svc.build_visual_prompt_injection(
        "葛瑞克", ["葛瑞克"], request_round=2, screenshot_id=2
    )
    assert again is not None
    ctx2 = svc.get_last_scene_context(scene_generation=0)
    assert ctx2 is not None
    assert ctx2.updated_at == recorded_at, "同语义重复注入不得把复用窗口起点往后推"

    # 换一批新语义 → 窗口重置
    time.sleep(0.05)
    fresh = svc.build_visual_prompt_injection(
        "女武神玛莲妮亚", ["玛莲妮亚"], request_round=3, screenshot_id=3
    )
    assert fresh is not None
    ctx3 = svc.get_last_scene_context(scene_generation=0)
    assert ctx3 is not None
    assert ctx3.updated_at > recorded_at, "新语义应当重置复用窗口起点"

