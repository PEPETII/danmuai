"""知识包场景上下文组装与缓存失效测试（Wave 1）。

覆盖：
    - ``build_knowledge_scene_context``：live_topic / 空输入 / 关键词抽取
    - 禁止 ``round=`` / ``screenshot=`` 占位查询文本
    - ``KnowledgeRuntimeService.note_scene_generation`` / ``get_last_scene_context``
      在 scene_generation 不匹配时失效缓存

运行：``python -m pytest tests/test_knowledge_scene_context.py -q -x``
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.knowledge.models import KnowledgeSceneContext
from app.knowledge.runtime_service import (
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
