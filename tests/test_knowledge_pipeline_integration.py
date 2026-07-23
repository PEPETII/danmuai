"""Phase B / Wave 7 集成测试：知识包运行时服务 + 主链路注入（B3）。

测试策略（mock 模式，**不**发起真实 HTTP / LLM）：
    - 用真实 ``KnowledgeDatabase``（重定向到 ``tmp_path``）+ 真实
      ``KnowledgeRepository`` + 真实 ``ImportOrchestrator`` + 真实
      ``KnowledgeRetriever``。
    - 通过 ``repo.insert_item`` 直接插入条目，绕过 ``organize_chunk`` LLM 调用。
    - ``KnowledgeRuntimeService`` 用 ``KnowledgeDatabase.open()`` 工厂装配
      （经 monkeypatch 重定向 ``KNOWLEDGE_DB_PATH``）。

覆盖场景：
    1. 生命周期：mount + close；DB 打开失败时进入降级模式（所有属性 None）
    2. ``build_visual_prompt_injection``：有命中返回 ``KnowledgeInjectionResult``；
       无命中 / 空语义查询返回 None；注入即 ``use_count+1``
    3. ``on_reply_consumed``：valid public_id → use_count 递增；invalid → 静默跳过
    4. ``_inject_knowledge_prompt``：runtime None / 无语义 / 无命中 no-op；
       scene_brief_extra 或 live_topic 命中时追加 prompt；注入即 use_count+1
    5. 全链路：``handle_reply_parsed`` 的 knowledge_used 诊断路径；
       ``_build_visual_prompts`` 经 live_topic 命中知识

约定（AGENTS.md §A.4.1）：
    - 使用 ``tmp_path`` fixture（已重定向到 ``.pytest_tmp/``）。
    - 运行：``python -m pytest tests/test_knowledge_pipeline_integration.py -q -x``
"""
from __future__ import annotations

from collections import deque
from unittest.mock import MagicMock, Mock

import pytest

from app.application.generation_pipeline import GenerationPipeline
from app.knowledge.models import KnowledgeInjectionResult
from app.knowledge.runtime_service import KnowledgeRuntimeService
from tests.conftest import make_minimal_danmu_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_db_path(tmp_path, monkeypatch):
    """重定向 ``KNOWLEDGE_DB_PATH`` 到 ``tmp_path``，返回目标路径。"""
    from app.knowledge import database as db_module

    db_path = tmp_path / "knowledge.db"
    monkeypatch.setattr(db_module, "KNOWLEDGE_DB_PATH", db_path)
    return db_path


@pytest.fixture
def knowledge_runtime(isolated_db_path):
    """挂载一个真实 ``KnowledgeRuntimeService``（DB 在 tmp_path）。

    用 ``MagicMock`` 作为 app 参数（``KnowledgeRuntimeService`` 只在异常时
    调 ``app.logger``，正常路径不访问 app）。
    """
    app_stub = MagicMock()
    app_stub.logger = MagicMock()
    svc = KnowledgeRuntimeService(app_stub)
    yield svc
    svc.close()


@pytest.fixture
def seeded_runtime(knowledge_runtime):
    """在 ``knowledge_runtime`` 的 DB 中插入 2 个 fact 条目，返回 (public_ids, internal_ids)。"""
    repo = knowledge_runtime.repository
    pkg = repo.create_package(name="集成测试包", priority=10)
    package_internal = repo.get_package(pkg["public_id"])["id"]
    source = repo.create_source(
        package_id=package_internal,
        source_type="pasted_text",
        display_name="seed",
    )
    source_id = source["id"]

    public_ids: list[str] = []
    internal_ids: list[int] = []
    for i in range(2):
        item = repo.insert_item(
            package_id=package_internal,
            source_id=source_id,
            chunk_id=None,
            kind="fact",
            title=f"事实{i}",
            content=f"葛瑞克事实{i} keyword_shared",
            scopes=["游戏"],
            enabled=True,
            priority=10 - i,
            confidence=0.9,
        )
        public_ids.append(item["public_id"])
        internal_ids.append(int(item["id"]))
    return public_ids, internal_ids


def _use_count(db, item_id: int) -> int:
    row = db.conn.execute(
        "SELECT use_count FROM knowledge_items WHERE id=?",
        (item_id,),
    ).fetchone()
    return int(row[0])


def _stub_personae(app, *, persona: str = "persona-1") -> None:
    app.personae = Mock(
        pick_random=Mock(return_value=persona),
        get_prompt=Mock(return_value=("system_prompt_base", "user_prompt_base")),
    )


# ---------------------------------------------------------------------------
# 1. 生命周期 + 降级模式
# ---------------------------------------------------------------------------


def test_knowledge_runtime_lifecycle_mount_and_close(isolated_db_path):
    """``KnowledgeRuntimeService(app)`` 装配成功 → 所有属性非 None → close() 释放。"""
    app_stub = MagicMock()
    svc = KnowledgeRuntimeService(app_stub)

    assert svc.repository is not None
    assert svc.import_orchestrator is not None
    assert svc.retriever is not None
    # close 不抛异常
    svc.close()
    # close 后属性清空
    assert svc.repository is None
    assert svc.import_orchestrator is None
    assert svc.retriever is None


def test_knowledge_runtime_degraded_mode_when_db_open_fails(monkeypatch):
    """``KnowledgeDatabase.open()`` 失败 → 降级模式：所有属性 None，方法 no-op。"""
    from app.knowledge import database as db_module

    def _raise_oserror(_path):
        raise OSError("simulated db open failure")

    monkeypatch.setattr(db_module.KnowledgeDatabase, "_open_at", _raise_oserror)

    app_stub = MagicMock()
    svc = KnowledgeRuntimeService(app_stub)

    # 降级模式：所有属性 None
    assert svc.repository is None
    assert svc.import_orchestrator is None
    assert svc.retriever is None

    # 方法 no-op（不抛异常，返回 None / 空）
    assert svc.build_visual_prompt_injection(
        scene_brief="x", keywords=[], request_round=1, screenshot_id=1
    ) is None
    svc.on_reply_consumed(["kid_1"])  # 不抛异常
    svc.close()  # 不抛异常


# ---------------------------------------------------------------------------
# 2. build_visual_prompt_injection
# ---------------------------------------------------------------------------


def test_build_visual_prompt_injection_with_hits_returns_prompt(
    knowledge_runtime, seeded_runtime
):
    """有命中 → ``KnowledgeInjectionResult``；注入后 use_count 递增（无需 on_reply_consumed）。"""
    _public_ids, internal_ids = seeded_runtime
    db = knowledge_runtime._db

    assert _use_count(db, internal_ids[0]) == 0
    assert _use_count(db, internal_ids[1]) == 0

    injection = knowledge_runtime.build_visual_prompt_injection(
        scene_brief="葛瑞克战斗",
        keywords=["葛瑞克"],
        request_round=1,
        screenshot_id=10,
    )
    assert injection is not None
    assert isinstance(injection, KnowledgeInjectionResult)
    assert isinstance(injection.prompt_text, str) and injection.prompt_text != ""
    assert injection.item_ids  # non-empty
    assert injection.hit_count > 0
    assert "葛瑞克" in injection.prompt_text

    # 方案 A：注入即 mark_items_used，不依赖 knowledge_used
    for item_id in injection.item_ids:
        assert _use_count(db, item_id) >= 1


def test_build_visual_prompt_injection_returns_none_when_no_hits(knowledge_runtime):
    """空库（无条目）→ ``build_visual_prompt_injection`` 返回 None。"""
    injection = knowledge_runtime.build_visual_prompt_injection(
        scene_brief="不存在的场景",
        keywords=["不存在的关键词"],
        request_round=1,
        screenshot_id=10,
    )
    assert injection is None


def test_build_visual_prompt_injection_returns_none_for_empty_query(knowledge_runtime):
    """空 scene_brief + 空 keywords → 不发起检索，直接返回 None。"""
    injection = knowledge_runtime.build_visual_prompt_injection(
        scene_brief="",
        keywords=[],
        request_round=1,
        screenshot_id=10,
    )
    assert injection is None


def test_build_visual_prompt_injection_increments_use_count_without_knowledge_used(
    knowledge_runtime, seeded_runtime
):
    """注入命中 → use_count +1，无需 knowledge_used / on_reply_consumed。"""
    _public_ids, internal_ids = seeded_runtime
    db = knowledge_runtime._db

    before = [_use_count(db, iid) for iid in internal_ids]
    assert before == [0, 0]

    injection = knowledge_runtime.build_visual_prompt_injection(
        scene_brief="葛瑞克",
        keywords=["葛瑞克"],
        request_round=2,
        screenshot_id=20,
    )
    assert isinstance(injection, KnowledgeInjectionResult)
    assert injection.item_ids

    for item_id in injection.item_ids:
        assert _use_count(db, item_id) == 1


# ---------------------------------------------------------------------------
# 3. on_reply_consumed
# ---------------------------------------------------------------------------


def test_on_reply_consumed_increments_use_count(seeded_runtime, knowledge_runtime):
    """valid public_id → ``use_count`` 递增 + ``last_used_at`` 更新。"""
    public_ids, internal_ids = seeded_runtime
    repo = knowledge_runtime.repository
    db = knowledge_runtime._db  # 内部 db（供验证 use_count）

    # 初始 use_count 应为 0，last_used_at 应为 None（未使用）
    row_before = db.conn.execute(
        "SELECT use_count, last_used_at FROM knowledge_items WHERE id=?",
        (internal_ids[0],),
    ).fetchone()
    assert row_before[0] == 0
    assert row_before[1] is None or row_before[1] == ""

    # 调用 on_reply_consumed
    knowledge_runtime.on_reply_consumed(public_ids)

    # 验证 use_count 已递增
    row_after = db.conn.execute(
        "SELECT use_count, last_used_at FROM knowledge_items WHERE id=?",
        (internal_ids[0],),
    ).fetchone()
    assert row_after[0] >= 1
    # last_used_at 是 ISO 字符串（time.strftime 格式）
    assert row_after[1] is not None and isinstance(row_after[1], str) and row_after[1] != ""


def test_on_reply_consumed_ignores_invalid_public_ids(
    seeded_runtime, knowledge_runtime
):
    """invalid public_id（不存在 / 空字符串 / None）被静默跳过，不抛异常。"""
    _public_ids, internal_ids = seeded_runtime
    db = knowledge_runtime._db

    # 全部无效 → no-op，不抛异常
    knowledge_runtime.on_reply_consumed(
        ["nonexistent_public_id", "", None, "kid_does_not_exist"]  # type: ignore[list-item]
    )

    # 既有条目 use_count 不变
    row = db.conn.execute(
        "SELECT use_count FROM knowledge_items WHERE id=?", (internal_ids[0],)
    ).fetchone()
    assert row[0] == 0


def test_on_reply_consumed_empty_list_is_noop(knowledge_runtime):
    """空列表 → 立即 return，不访问 repository。"""
    # 不抛异常即可
    knowledge_runtime.on_reply_consumed([])


# ---------------------------------------------------------------------------
# 4. _inject_knowledge_prompt
# ---------------------------------------------------------------------------


def test_inject_knowledge_prompt_noop_when_runtime_none():
    """``knowledge_runtime=None`` → ``_inject_knowledge_prompt`` 原样返回 system_pt。"""
    app = make_minimal_danmu_app()
    # 显式置 None（模拟 _init_startup_services 装配失败时的降级状态）
    object.__setattr__(app, "knowledge_runtime", None)
    assert app.__dict__.get("knowledge_runtime") is None

    original_pt = "你是一名弹幕主播。"
    result = app._inject_knowledge_prompt(
        original_pt,
        request_round=1,
        screenshot_id=10,
    )
    assert result == original_pt


def test_inject_knowledge_prompt_skips_without_semantic_query(
    knowledge_runtime, seeded_runtime
):
    """无 live_topic / scene_brief_extra / recent / mic → 无语义查询，不注入（禁止 round 占位）。"""
    app = make_minimal_danmu_app()
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)
    # FakeConfig 默认 live_topic 空；engine.recent 空
    app.engine.recent = deque()

    original_pt = "你是一名弹幕主播。"
    result = app._inject_knowledge_prompt(
        original_pt,
        request_round=99,
        screenshot_id=88,
    )
    assert result == original_pt
    # 未注入 → use_count 仍为 0
    _public_ids, internal_ids = seeded_runtime
    db = knowledge_runtime._db
    assert _use_count(db, internal_ids[0]) == 0


def test_inject_knowledge_prompt_noop_when_runtime_returns_none(
    knowledge_runtime, seeded_runtime
):
    """``knowledge_runtime`` 已挂载但检索无命中 → 原样返回 system_pt。"""
    app = make_minimal_danmu_app()
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)

    original_pt = "你是一名弹幕主播。"
    # 有语义但与 seed 无关 → 检索无命中
    result = app._inject_knowledge_prompt(
        original_pt,
        request_round=1,
        screenshot_id=10,
        scene_brief_extra="完全无关的场景描述 xyz123",
    )
    assert result == original_pt


def test_inject_knowledge_prompt_appends_when_runtime_returns_prompt(
    knowledge_runtime, seeded_runtime
):
    """scene_brief_extra=葛瑞克 → 检索命中 → 追加 prompt。"""
    app = make_minimal_danmu_app()
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)

    original_pt = "你是一名弹幕主播。"
    result = app._inject_knowledge_prompt(
        original_pt,
        request_round=1,
        screenshot_id=10,
        scene_brief_extra="葛瑞克",
    )
    assert result.startswith(original_pt)
    assert result != original_pt
    assert "\n\n" in result
    assert "葛瑞克" in result


def test_inject_knowledge_prompt_hits_with_live_topic(
    knowledge_runtime, seeded_runtime
):
    """config live_topic 含命中词 → 注入成功。"""
    app = make_minimal_danmu_app()
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)
    # 与 seed content「葛瑞克事实…」对齐的短主题词（整句「…攻略」可能整段成词导致 FTS 不命中）
    app.config.set("live_topic", "葛瑞克")

    original_pt = "你是一名弹幕主播。"
    result = app._inject_knowledge_prompt(
        original_pt,
        request_round=3,
        screenshot_id=30,
    )
    assert result != original_pt
    assert "葛瑞克" in result


def test_inject_with_hits_increments_use_count_without_knowledge_used(
    knowledge_runtime, seeded_runtime
):
    """inject 命中 → use_count +1，无需 knowledge_used。"""
    _public_ids, internal_ids = seeded_runtime
    db = knowledge_runtime._db
    assert _use_count(db, internal_ids[0]) == 0

    app = make_minimal_danmu_app()
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)

    result = app._inject_knowledge_prompt(
        "system_base",
        request_round=1,
        screenshot_id=10,
        scene_brief_extra="葛瑞克",
    )
    assert result != "system_base"

    injection = knowledge_runtime.get_last_injection()
    assert isinstance(injection, KnowledgeInjectionResult)
    assert injection.item_ids
    for item_id in injection.item_ids:
        assert _use_count(db, item_id) >= 1


# ---------------------------------------------------------------------------
# 5. 全链路：handle_reply_parsed / _build_visual_prompts
# ---------------------------------------------------------------------------


def test_handle_reply_parsed_invokes_on_reply_consumed_with_knowledge_used(
    knowledge_runtime, seeded_runtime
):
    """``handle_reply_parsed`` 收到含 ``knowledge_used`` 的 envelope → 调
    ``on_reply_consumed`` → 条目 use_count 递增。
    """
    public_ids, internal_ids = seeded_runtime
    db = knowledge_runtime._db

    app = make_minimal_danmu_app()
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)
    # 重建 GenerationPipeline 以使用新 app
    object.__setattr__(app, "_generation_pipeline", GenerationPipeline(app))

    # 构造 AI 回复 envelope：comments + knowledge_used
    reply_text = (
        '{"comments": ["葛瑞克二阶段接龙头", "这波操作可以"], '
        '"knowledge_used": ["' + public_ids[0] + '"]}'
    )

    # 预注册 request meta（handle_reply_parsed 不释放 in-flight，但 enqueue 需要回复队列）
    app._register_request_meta(10, 10, 0, "visual")

    accepted = app._generation_pipeline.handle_reply_parsed(
        text=reply_text,
        persona_id="persona-1",
        request_round=10,
        screenshot_id=10,
        captured_at=1.0,
        scene_generation=0,
        request_started_at=2.0,
        reply_received_at=3.0,
    )

    # 1. handle_reply_parsed 应接受该回复（envelope.items 解析出 2 条弹幕）
    assert accepted is True

    # 2. knowledge_used 中的 public_id 对应的条目 use_count 应递增
    row = db.conn.execute(
        "SELECT use_count FROM knowledge_items WHERE id=?", (internal_ids[0],)
    ).fetchone()
    assert row[0] >= 1

    # 3. 另一个未在 knowledge_used 中的条目 use_count 仍为 0
    row2 = db.conn.execute(
        "SELECT use_count FROM knowledge_items WHERE id=?", (internal_ids[1],)
    ).fetchone()
    assert row2[0] == 0


def test_handle_reply_parsed_without_knowledge_used_does_not_call_on_reply_consumed(
    knowledge_runtime, seeded_runtime
):
    """``handle_reply_parsed`` 收到不含 ``knowledge_used`` 的回复 → 不调
    ``on_reply_consumed``（即使 knowledge_runtime 已挂载）。
    """
    _public_ids, internal_ids = seeded_runtime
    db = knowledge_runtime._db

    app = make_minimal_danmu_app()
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)
    object.__setattr__(app, "_generation_pipeline", GenerationPipeline(app))

    # Spy: 把 on_reply_consumed 替换为记录调用的 mock
    on_reply_calls: list[list[str]] = []
    original = app.knowledge_runtime.on_reply_consumed

    def spy(knowledge_used_item_ids):
        on_reply_calls.append(list(knowledge_used_item_ids))
        return original(knowledge_used_item_ids)

    object.__setattr__(app.knowledge_runtime, "on_reply_consumed", spy)

    # 构造 AI 回复（纯 JSON 数组，无 knowledge_used）
    reply_text = '["葛瑞克二阶段接龙头", "这波操作可以"]'

    app._register_request_meta(10, 10, 0, "visual")
    accepted = app._generation_pipeline.handle_reply_parsed(
        text=reply_text,
        persona_id="persona-1",
        request_round=10,
        screenshot_id=10,
        captured_at=1.0,
        scene_generation=0,
        request_started_at=2.0,
        reply_received_at=3.0,
    )

    assert accepted is True
    # on_reply_consumed 不应被调用（knowledge_used 为空）
    assert on_reply_calls == []

    # 条目 use_count 不变
    row = db.conn.execute(
        "SELECT use_count FROM knowledge_items WHERE id=?", (internal_ids[0],)
    ).fetchone()
    assert row[0] == 0


def test_handle_reply_parsed_isolates_knowledge_runtime_exception(
    knowledge_runtime, seeded_runtime
):
    """``on_reply_consumed`` 抛异常时 ``handle_reply_parsed`` 不被打断（异常隔离）。"""
    public_ids, _internal_ids = seeded_runtime

    app = make_minimal_danmu_app()
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)
    object.__setattr__(app, "_generation_pipeline", GenerationPipeline(app))

    # 让 on_reply_consumed 抛异常
    def raise_on_call(_ids):
        raise RuntimeError("simulated knowledge runtime failure")

    object.__setattr__(app.knowledge_runtime, "on_reply_consumed", raise_on_call)

    reply_text = (
        '{"comments": ["葛瑞克二阶段接龙头"], '
        '"knowledge_used": ["' + public_ids[0] + '"]}'
    )

    app._register_request_meta(10, 10, 0, "visual")
    # 不应抛异常
    accepted = app._generation_pipeline.handle_reply_parsed(
        text=reply_text,
        persona_id="persona-1",
        request_round=10,
        screenshot_id=10,
        captured_at=1.0,
        scene_generation=0,
        request_started_at=2.0,
        reply_received_at=3.0,
    )

    # 主链路仍应接受该回复
    assert accepted is True
    # 异常应被记录到 debug 日志
    assert any(
        "on_reply_consumed" in msg or "knowledge" in msg.lower()
        for msg in app.logger.debug_messages
    )


def test_build_visual_prompts_with_live_topic_hits_knowledge(
    knowledge_runtime, seeded_runtime
):
    """生产路径 ``_build_visual_prompts`` + live_topic → system_pt 含知识注入。"""
    app = make_minimal_danmu_app()
    _stub_personae(app)
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)
    app.config.set("live_topic", "葛瑞克")
    app.engine.recent = deque()

    result = app._build_visual_prompts(request_round=1, screenshot_id=1, batch_id=1)

    assert result is not None
    system_pt, _user_pt, _persona = result
    assert system_pt.startswith("system_prompt_base")
    assert "葛瑞克" in system_pt
    # 注入即 use_count 更新
    injection = knowledge_runtime.get_last_injection()
    assert isinstance(injection, KnowledgeInjectionResult)
    assert injection.item_ids
    db = knowledge_runtime._db
    for item_id in injection.item_ids:
        assert _use_count(db, item_id) >= 1
