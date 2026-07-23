"""Wave 5：知识包生产路径端到端测试。

调用真实生产入口（非仅 ``_inject_knowledge_prompt`` 旁路）：

- ``DanmuApp._build_visual_prompts``
- Web API：create package → import pasted_text → poll job → list items

策略：真实 KnowledgeDatabase（tmp_path）+ RuntimeService；mock AI organizer。

运行：``python -m pytest tests/test_knowledge_e2e_production.py -q -x``
"""
from __future__ import annotations

from collections import deque
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.knowledge.models import KnowledgeInjectionResult
from app.knowledge.runtime_service import KnowledgeRuntimeService
from app.web_api.routes import register_web_routes
from tests.conftest import make_minimal_danmu_app
from tests.fakes import ai_client_fake_config


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def isolated_db_path(tmp_path, monkeypatch):
    from app.knowledge import database as db_module

    db_path = tmp_path / "knowledge_e2e.db"
    monkeypatch.setattr(db_module, "KNOWLEDGE_DB_PATH", db_path)
    return db_path


@pytest.fixture
def knowledge_runtime(isolated_db_path):
    app_stub = MagicMock()
    app_stub.logger = MagicMock()
    svc = KnowledgeRuntimeService(app_stub)
    yield svc
    svc.close()


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


def _seed_boss_item(repo, *, scopes=None, package_kwargs=None):
    """插入含 boss 关键词的 fact；返回 (public_id, internal_id, package_public_id)。"""
    pkg = repo.create_package(
        name="E2E 攻略包",
        priority=10,
        **(package_kwargs or {}),
    )
    package_internal = repo.get_package(pkg["public_id"])["id"]
    source = repo.create_source(
        package_id=package_internal,
        source_type="pasted_text",
        display_name="seed",
    )
    item = repo.insert_item(
        package_id=package_internal,
        source_id=source["id"],
        chunk_id=None,
        kind="fact",
        title="葛瑞克二阶段",
        content="葛瑞克二阶段会飞天，注意龙头蓄力再滚",
        scopes=list(scopes or ["游戏"]),
        enabled=True,
        priority=10,
        confidence=0.95,
    )
    return item["public_id"], int(item["id"]), pkg["public_id"]


# ---------------------------------------------------------------------------
# 1. _build_visual_prompts + live_topic → system_pt 含知识
# ---------------------------------------------------------------------------


def test_e2e_build_visual_prompts_live_topic_injects_boss_knowledge(
    knowledge_runtime,
):
    """生产路径：live_topic 含 boss 词 + 库内有条目 → ``_build_visual_prompts`` system 含知识。"""
    _public_id, internal_id, _pkg = _seed_boss_item(knowledge_runtime.repository)
    db = knowledge_runtime._db
    assert _use_count(db, internal_id) == 0

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
    assert "二阶段" in system_pt or "龙头" in system_pt

    injection = knowledge_runtime.get_last_injection()
    assert isinstance(injection, KnowledgeInjectionResult)
    assert injection.item_ids
    assert internal_id in injection.item_ids


# ---------------------------------------------------------------------------
# 2. 注入即 mark use_count，无需 knowledge_used
# ---------------------------------------------------------------------------


def test_e2e_injection_marks_use_count_without_model_knowledge_used(
    knowledge_runtime,
):
    """``_build_visual_prompts`` 注入后 use_count+1，不依赖模型 knowledge_used。"""
    _public_id, internal_id, _pkg = _seed_boss_item(knowledge_runtime.repository)
    db = knowledge_runtime._db

    app = make_minimal_danmu_app()
    _stub_personae(app)
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)
    app.config.set("live_topic", "葛瑞克")
    app.engine.recent = deque()

    app._build_visual_prompts(request_round=2, screenshot_id=20, batch_id=2)

    assert _use_count(db, internal_id) >= 1
    injection = knowledge_runtime.get_last_injection()
    assert injection is not None
    assert injection.hit_count >= 1
    assert internal_id in injection.item_ids


# ---------------------------------------------------------------------------
# 3. 空语义 → 不检索（无 round=/screenshot= 占位）
# ---------------------------------------------------------------------------


def test_e2e_empty_semantic_skips_retrieve_no_round_placeholder(
    knowledge_runtime, monkeypatch
):
    """空 live_topic + 无 recent + 无 extra → 不调用 retrieve，system 无 round= 查询。"""
    _seed_boss_item(knowledge_runtime.repository)
    retrieve_calls: list[dict] = []

    original_retrieve = knowledge_runtime.retriever.retrieve

    def spy_retrieve(**kwargs):
        retrieve_calls.append(dict(kwargs))
        return original_retrieve(**kwargs)

    monkeypatch.setattr(knowledge_runtime.retriever, "retrieve", spy_retrieve)

    app = make_minimal_danmu_app()
    _stub_personae(app)
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)
    app.config.set("live_topic", "")
    app.engine.recent = deque()
    # 确保 recent_sent 也为空
    object.__setattr__(app, "_recent_sent_danmu_for_prompt", lambda n=10: [])

    result = app._build_visual_prompts(request_round=99, screenshot_id=88, batch_id=1)

    assert result is not None
    system_pt, _user_pt, _persona = result
    assert retrieve_calls == []
    assert "round=" not in system_pt
    assert "screenshot=" not in system_pt
    assert knowledge_runtime.get_last_injection() is None


# ---------------------------------------------------------------------------
# 4. tagged package scope：不匹配不注入 / 匹配则注入
# ---------------------------------------------------------------------------


def test_e2e_tagged_package_scope_no_match_not_injected(knowledge_runtime):
    """scope_mode=tagged 且 scene_tags 无交集 → ``_build_visual_prompts`` 不注入。"""
    _seed_boss_item(
        knowledge_runtime.repository,
        package_kwargs={
            "scope_mode": "tagged",
            "scope_tags": ["只看这个标签"],
        },
    )

    app = make_minimal_danmu_app()
    _stub_personae(app)
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)
    # live_topic 可命中 FTS，但 package scope 标签无交集
    app.config.set("live_topic", "葛瑞克")
    app.engine.recent = deque()

    result = app._build_visual_prompts(request_round=1, screenshot_id=1, batch_id=1)

    assert result is not None
    system_pt, _user_pt, _persona = result
    assert "二阶段会飞天" not in system_pt
    assert knowledge_runtime.get_last_injection() is None


def test_e2e_tagged_package_scope_match_injected(knowledge_runtime):
    """scope_mode=tagged 且 live_topic 词落入 scene_tags 与 scope_tags 交集 → 注入。"""
    _public_id, internal_id, _pkg = _seed_boss_item(
        knowledge_runtime.repository,
        package_kwargs={
            "scope_mode": "tagged",
            "scope_tags": ["葛瑞克"],
        },
    )
    db = knowledge_runtime._db

    app = make_minimal_danmu_app()
    _stub_personae(app)
    object.__setattr__(app, "knowledge_runtime", knowledge_runtime)
    # build_knowledge_scene_context 会把 live_topic 分词进 scene_tags
    app.config.set("live_topic", "葛瑞克")
    app.engine.recent = deque()

    result = app._build_visual_prompts(request_round=1, screenshot_id=1, batch_id=1)

    assert result is not None
    system_pt, _user_pt, _persona = result
    assert "葛瑞克" in system_pt
    injection = knowledge_runtime.get_last_injection()
    assert isinstance(injection, KnowledgeInjectionResult)
    assert internal_id in injection.item_ids
    assert _use_count(db, internal_id) >= 1


# ---------------------------------------------------------------------------
# 5. API 导入路径：建包 → import → poll job → list items
# ---------------------------------------------------------------------------


def _ok_item(
    kind: str = "fact",
    title: str = "E2E 事实",
    content: str = "端到端整理出的知识内容",
    confidence: float = 0.9,
) -> dict:
    return {
        "kind": kind,
        "title": title,
        "content": content,
        "examples": [],
        "triggers": [],
        "tones": [],
        "scopes": [],
        "entities": [],
        "confidence": confidence,
        "evidence": "",
    }


def _ok_result(items=None, input_tokens: int = 100, output_tokens: int = 50) -> dict:
    return {
        "ok": True,
        "items": items or [],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "error": "",
    }


def _wait_for_job_done(repo, job_id: str, timeout: float = 15.0) -> dict:
    import sqlite3
    import time

    deadline = time.time() + timeout
    last_err: Exception | None = None
    while time.time() < deadline:
        try:
            job = repo.get_job(job_id)
        except sqlite3.InterfaceError as exc:
            last_err = exc
            time.sleep(0.1)
            continue
        if job and job["status"] in (
            "completed",
            "completed_with_errors",
            "failed",
            "cancelled",
            "interrupted",
        ):
            return job
        time.sleep(0.05)
    if last_err is not None:
        raise last_err
    raise TimeoutError(f"job {job_id} didn't finish within {timeout}s")


def test_e2e_api_import_pasted_text_poll_job_list_items(tmp_path):
    """API：create package → import pasted_text（mock organizer）→ poll job → list items。"""
    from app.knowledge.database import KnowledgeDatabase
    from app.knowledge.import_service import ImportOrchestrator
    from app.knowledge.repository import KnowledgeRepository
    from app.knowledge.retriever import KnowledgeRetriever

    db = KnowledgeDatabase._open_at(tmp_path / "api_e2e.db")
    repo = KnowledgeRepository(db)
    orch = ImportOrchestrator(db, repo)
    retriever = KnowledgeRetriever(db)
    knowledge_runtime = SimpleNamespace(
        repository=repo,
        import_orchestrator=orch,
        retriever=retriever,
    )
    config = ai_client_fake_config()

    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    bridge.danmu_app = SimpleNamespace(
        knowledge_runtime=knowledge_runtime,
        config=config,
        config_changed=MagicMock(),
    )

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    try:
        create = client.post(
            "/api/knowledge/packages",
            json={"name": "E2E API 包", "description": "wave5"},
        )
        assert create.status_code == 200
        pid = create.json()["package_id"]
        assert pid

        item = _ok_item(
            kind="fact",
            title="葛瑞克攻略要点",
            content="葛瑞克二阶段注意龙头蓄力",
        )
        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[item]),
        ):
            imp = client.post(
                f"/api/knowledge/packages/{pid}/imports",
                json={
                    "source_type": "pasted_text",
                    "display_name": "粘贴攻略",
                    "pasted_text": "# 葛瑞克\n\n二阶段会飞天，注意龙头蓄力再滚。",
                },
            )
            assert imp.status_code == 200
            body = imp.json()
            assert body["ok"] is True
            job_id = body["job_id"]
            assert job_id.startswith("kj_")

            final = _wait_for_job_done(repo, job_id, timeout=15.0)

        assert final["status"] in ("completed", "completed_with_errors")
        assert int(final.get("generated_items") or 0) >= 1

        job_resp = client.get(f"/api/knowledge/jobs/{job_id}")
        assert job_resp.status_code == 200
        assert job_resp.json()["status"] in (
            "completed",
            "completed_with_errors",
        )

        items_resp = client.get(f"/api/knowledge/items?package_id={pid}")
        assert items_resp.status_code == 200
        items_body = items_resp.json()
        assert items_body["total"] >= 1
        assert any(
            "葛瑞克" in (it.get("title") or "") or "葛瑞克" in (it.get("content") or "")
            for it in items_body["items"]
        )
    finally:
        orch.close()
        db.close()
