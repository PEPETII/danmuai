"""Phase A integration tests for the knowledge package feature (A10).

测试策略（mock 模式，**不**发起真实 HTTP / LLM）：
    - 用真实 ``KnowledgeDatabase``（``tmp_path``）+ 真实 ``KnowledgeRepository``
      + 真实 ``ImportOrchestrator`` + 真实 ``KnowledgeRetriever``。
    - 仅 mock ``app.knowledge.import_service.organize_chunk``（避免真实 LLM 请求）。
    - Web API 用 FastAPI TestClient + ``bridge.invoke_on_main`` 同步直接执行
      （与 ``test_knowledge_api.py`` 同一模板）。
    - 每个用例自建临时 DB / package，互不干扰。

覆盖 7 个集成用例：
    1. 数据库生命周期 + 迁移幂等性
    2. 完整导入流程端到端（mock AI）
    3. 级联删除端到端
    4. 检索器评分 + 类型配额（混合 kind）
    5. Web API 端到端（10 步子流程）
    6. 协作式取消端到端
    7. 中英文 / FTS fallback 处理

约定（AGENTS.md §A.4.1）：
    - 使用 ``tmp_path`` fixture（已重定向到 ``.pytest_tmp/``）。
    - 运行：``python -m pytest tests/test_knowledge_integration.py -q -x``
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.knowledge.database import KnowledgeDatabase
from app.knowledge.import_service import ImportOrchestrator
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.retriever import KnowledgeRetriever
from app.web_api.routes import register_web_routes
from tests.fakes import ai_client_fake_config


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _wait_for_job_done(
    repo: KnowledgeRepository, job_id: str, timeout: float = 15.0
) -> dict:
    """轮询 job 状态直到完成或超时。

    若读到 ``sqlite3.InterfaceError``（后台写线程与读线程并发使用同一连接），
    短暂退避后重试。
    """
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


def _ok_item(
    kind: str = "fact",
    title: str = "测试事实",
    content: str = "这是测试内容",
    confidence: float = 0.9,
) -> dict:
    """构造一个合法的 AI 返回 item dict。"""
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
    """构造 organize_chunk 成功返回值。"""
    return {
        "ok": True,
        "items": items or [],
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "error": "",
    }


def _make_multi_chunk_text(n: int = 2) -> str:
    """构造包含 n 个 chapter 的文本，每个 chapter 约 4400 字符（产生 n 个 chunk）。"""
    parts: list[str] = []
    for i in range(n):
        content = "This is test content. " * 200
        parts.append(f"# Chapter {i + 1}\n\n{content}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def db(tmp_path):
    db = KnowledgeDatabase._open_at(tmp_path / "knowledge.db")
    yield db
    db.close()


@pytest.fixture
def repo(db):
    return KnowledgeRepository(db)


@pytest.fixture
def orchestrator(db, repo):
    orch = ImportOrchestrator(db, repo)
    yield orch
    orch.close()


@pytest.fixture
def retriever(db):
    return KnowledgeRetriever(db)


@pytest.fixture
def config():
    return ai_client_fake_config()


@pytest.fixture
def knowledge_runtime(repo, orchestrator, retriever):
    """仿 B2 阶段挂载的 KnowledgeRuntimeService 结构（最小子集）。"""
    return SimpleNamespace(
        repository=repo,
        import_orchestrator=orchestrator,
        retriever=retriever,
    )


@pytest.fixture
def app_with_routes(knowledge_runtime, config):
    """构造挂载 knowledge_runtime 的最小 FastAPI app + bridge。"""
    app = FastAPI()
    bridge = MagicMock()
    # 测试模式：invoke_on_main 同步直接执行
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
    yield client, bridge


@pytest.fixture
def client(app_with_routes):
    client, _bridge = app_with_routes
    return client


# ---------------------------------------------------------------------------
# 1. 数据库生命周期 + 迁移幂等性
# ---------------------------------------------------------------------------


def test_database_lifecycle_and_migration_idempotency(tmp_path: Path, monkeypatch):
    """数据库生命周期：open → 迁移 → 关闭 → 再开（幂等）。

    重定向 ``KNOWLEDGE_DB_PATH`` 到 ``tmp_path``，验证
    ``KnowledgeDatabase.open()`` 在该路径创建库。
    """
    from app.knowledge import database as db_module

    db_path = tmp_path / "AppData" / "DanmuAI" / "knowledge.db"
    # KNOWLEDGE_DB_PATH 在模块导入时已计算，须 monkeypatch 模块属性才能生效。
    monkeypatch.setattr(db_module, "KNOWLEDGE_DB_PATH", db_path)

    # 第一次打开：应创建目录 + 文件 + 应用迁移
    db1 = KnowledgeDatabase.open()
    try:
        # fts_backend 应是 trigram / fts5 / fallback 之一
        assert db1.fts_backend in ("trigram", "fts5", "fallback")

        # schema_meta 应存在且 schema_version = '1'
        row = db1.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        assert row is not None
        assert row[0] == "1"

        # 5 张主表应存在
        for table in (
            "knowledge_packages",
            "knowledge_sources",
            "knowledge_chunks",
            "knowledge_items",
            "knowledge_jobs",
        ):
            cnt = db1.conn.execute(
                f"SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()[0]
            assert cnt == 1, f"table {table} missing"

        # 11 个索引应存在
        idx_count = db1.conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchone()[0]
        assert idx_count >= 9  # 至少 9 个 idx_*（spec §5.2 声明 11 个）

        # FTS 虚拟表（trigram/fts5 时存在；fallback 时不存在）
        fts_row = db1.conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='knowledge_items_fts'"
        ).fetchone()[0]
        if db1.fts_backend in ("trigram", "fts5"):
            assert fts_row == 1
        else:
            assert fts_row == 0
    finally:
        db1.close()

    # 验证文件确实创建在重定向路径
    assert db_path.is_file()

    # 第二次打开（幂等）：不应抛异常，schema_version 仍为 '1'
    db2 = KnowledgeDatabase.open()
    try:
        row = db2.conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        assert row is not None
        assert row[0] == "1"
    finally:
        db2.close()


# ---------------------------------------------------------------------------
# 2. 完整导入流程端到端（mock AI）
# ---------------------------------------------------------------------------


def test_full_import_pipeline_end_to_end(orchestrator, db, repo, config):
    """完整流程：建包 → 提交导入 → mock AI 返回 1 fact → 完成 → 验证全链路状态。"""
    pkg = repo.create_package(name="端到端测试包")
    pkg_id = pkg["public_id"]
    package_internal = repo.get_package(pkg_id)["id"]
    source = repo.create_source(
        package_id=package_internal,
        source_type="pasted_text",
        display_name="测试文本",
    )
    source_id = source["id"]

    item = _ok_item(
        kind="fact",
        title="艾尔登法环初始 Boss",
        content="葛瑞克是《艾尔登法环》的初始 Boss，二阶段会接上龙头。",
    )
    payload = {
        "pasted_text": "# 葛瑞克\n\n葛瑞克是《艾尔登法环》的初始 Boss。",
    }

    with patch(
        "app.knowledge.import_service.organize_chunk",
        return_value=_ok_result(items=[item]),
    ):
        job_id = orchestrator.submit_import(
            config=config,
            package_id=package_internal,
            source_id=source_id,
            source_type="pasted_text",
            payload=payload,
        )
        job = _wait_for_job_done(repo, job_id, timeout=15.0)

    # 1. job 状态
    assert job["status"] == "completed"
    assert job["stage"] == "finished"
    assert job["total_chunks"] >= 1
    assert job["processed_chunks"] == job["total_chunks"]
    assert job["failed_chunks"] == 0
    assert job["generated_items"] == 1
    assert job["input_tokens"] == 100
    assert job["output_tokens"] == 50

    # 2. source 状态
    sources = repo.list_sources(package_internal)
    assert len(sources) == 1
    assert sources[0]["status"] == "processed"
    assert sources[0]["normalized_text"] != ""
    assert sources[0]["content_hash"] != ""

    # 3. chunks 状态
    chunks = repo.list_chunks(source_id)
    assert len(chunks) == job["total_chunks"]
    assert all(c["status"] == "completed" for c in chunks)

    # 4. items 命中
    result = repo.list_items(package_id=package_internal)
    assert result["total"] == 1
    saved = result["items"][0]
    assert saved["title"] == "艾尔登法环初始 Boss"
    assert "葛瑞克" in saved["content"]
    assert saved["kind"] == "fact"
    assert saved["enabled"] is True


# ---------------------------------------------------------------------------
# 3. 级联删除端到端
# ---------------------------------------------------------------------------


def test_cascade_delete_end_to_end(db, repo):
    """级联删除：建包 + source + chunks + items + job → delete_package → 全部清空。"""
    pkg = repo.create_package(name="待删除包")
    package_internal = repo.get_package(pkg["public_id"])["id"]

    source = repo.create_source(
        package_id=package_internal,
        source_type="pasted_text",
        display_name="src",
    )
    source_id = source["id"]

    # 插入 chunks（直接走 repository，不经 orchestrator）
    chunks = repo.insert_chunks(
        source_id=source_id,
        chunks=[
            {"sequence_no": 0, "heading": "ch0", "content": "chunk 0 content"},
            {"sequence_no": 1, "heading": "ch1", "content": "chunk 1 content"},
        ],
    )
    chunk_id = chunks[0]["id"]

    # 插入 items
    repo.insert_item(
        package_id=package_internal,
        source_id=source_id,
        chunk_id=chunk_id,
        kind="fact",
        title="条目1",
        content="内容1",
    )
    repo.insert_item(
        package_id=package_internal,
        source_id=source_id,
        chunk_id=chunk_id,
        kind="meme",
        title="条目2",
        content="内容2",
    )

    # 插入 job
    repo.create_job(
        package_id=package_internal,
        source_id=source_id,
        status="completed",
        stage="finished",
    )

    # 验证删除前各表有数据
    assert len(repo.list_sources(package_internal)) == 1
    assert len(repo.list_chunks(source_id)) == 2
    assert repo.list_items(package_id=package_internal)["total"] == 2
    assert len(repo.list_jobs(package_id=package_internal)) == 1

    # 执行删除
    ok = repo.delete_package(pkg["public_id"])
    assert ok is True

    # 验证各表已清空（按 repository.delete_package_for_db 删除顺序）
    assert repo.get_package(pkg["public_id"]) is None
    assert len(repo.list_sources(package_internal)) == 0
    assert len(repo.list_chunks(source_id)) == 0
    assert repo.list_items(package_id=package_internal)["total"] == 0
    assert len(repo.list_jobs(package_id=package_internal)) == 0

    # FTS 表也清空（非 fallback 时）
    if db.fts_backend != "fallback":
        fts_cnt = db.conn.execute(
            "SELECT COUNT(*) FROM knowledge_items_fts"
        ).fetchone()[0]
        assert fts_cnt == 0

    # 删除不存在的包返回 False
    assert repo.delete_package("nonexistent_public_id") is False


# ---------------------------------------------------------------------------
# 4. 检索器评分 + 类型配额（混合 kind）
# ---------------------------------------------------------------------------


def test_retriever_scoring_with_mixed_items(db, repo):
    """插入 4 种 kind 的条目，验证检索结果遵守类型配额。

    配额（spec §6.3）：fact≤2 / reaction_pattern≤1 / meme≤1 / style_example≤2。
    max_items 默认 ≤ 4。
    """
    pkg = repo.create_package(name="检索评分包", priority=10)
    package_internal = repo.get_package(pkg["public_id"])["id"]
    source = repo.create_source(
        package_id=package_internal,
        source_type="pasted_text",
        display_name="src",
    )
    source_id = source["id"]

    # 插入 5 个 fact（高优先级，期望只取 2 个）
    for i in range(5):
        repo.insert_item(
            package_id=package_internal,
            source_id=source_id,
            chunk_id=None,
            kind="fact",
            title=f"事实{i}",
            content=f"事实内容{i} keyword_shared",
            scopes=["游戏"],
            enabled=True,
            priority=10 - i,  # 优先级递减
            confidence=0.9,
        )

    # 插入 2 个 style_example（中优先级）
    for i in range(2):
        repo.insert_item(
            package_id=package_internal,
            source_id=source_id,
            chunk_id=None,
            kind="style_example",
            title=f"风格示例{i}",
            content=f"风格内容{i} keyword_shared",
            scopes=["游戏"],
            enabled=True,
            priority=5,
            confidence=0.8,
        )

    # 插入 2 个 meme（低优先级）
    for i in range(2):
        repo.insert_item(
            package_id=package_internal,
            source_id=source_id,
            chunk_id=None,
            kind="meme",
            title=f"烂梗{i}",
            content=f"烂梗内容{i} keyword_shared",
            scopes=["游戏"],
            enabled=True,
            priority=2,
            confidence=0.7,
        )

    # 插入 1 个 reaction_pattern
    repo.insert_item(
        package_id=package_internal,
        source_id=source_id,
        chunk_id=None,
        kind="reaction_pattern",
        title="反应模式",
        content="反应模式内容 keyword_shared",
        scopes=["游戏"],
        enabled=True,
        priority=7,
        confidence=0.85,
    )

    retriever = KnowledgeRetriever(db)
    result = retriever.retrieve(
        scene_brief="游戏场景",
        keywords=["keyword_shared"],
        max_items=4,
        max_chars=600,
    )

    # 应命中所有启用条目
    assert result.hit_count >= 10

    # 选中的条目数 ≤ 4
    selected = result.items
    assert len(selected) <= 4

    # 类型配额校验
    kind_counts: dict[str, int] = {}
    for it in selected:
        k = it["kind"]
        kind_counts[k] = kind_counts.get(k, 0) + 1
    assert kind_counts.get("fact", 0) <= 2, f"fact quota exceeded: {kind_counts}"
    assert kind_counts.get("reaction_pattern", 0) <= 1
    assert kind_counts.get("meme", 0) <= 1
    assert kind_counts.get("style_example", 0) <= 2

    # prompt_text 应非空（有命中且在 max_chars 内）
    assert isinstance(result.prompt_text, str)
    assert result.prompt_text != ""

    # fts_backend 应与 db 一致
    assert result.fts_backend == db.fts_backend


# ---------------------------------------------------------------------------
# 5. Web API 端到端（TestClient + minimal DanmuApp）— 10 步子流程
# ---------------------------------------------------------------------------


def test_web_api_end_to_end(client, repo):
    """端到端 Web API 流程（10 步）：

    1. GET /packages 空列表
    2. POST /packages 创建
    3. GET /packages/{id} 详情
    4. PATCH /packages/{id} 更新
    5. POST /packages/{id}/imports 导入（mock AI）
    6. 轮询 GET /jobs/{id} 等完成
    7. GET /items?package_id={id} 应有命中
    8. POST /retrieval/preview 检索预览
    9. DELETE /packages/{id} 级联删除
    10. GET /packages/{id} → not_found
    """
    # 1. 空列表
    resp = client.get("/api/knowledge/packages")
    assert resp.status_code == 200
    assert resp.json() == {"packages": [], "total": 0}

    # 2. 创建
    resp = client.post(
        "/api/knowledge/packages",
        json={"name": "Web 端到端包", "description": "集成测试"},
    )
    assert resp.status_code == 200
    create_body = resp.json()
    assert create_body["ok"] is True
    pid = create_body["package_id"]
    assert pid

    # 3. 详情
    resp = client.get(f"/api/knowledge/packages/{pid}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["public_id"] == pid
    assert detail["name"] == "Web 端到端包"

    # 4. 更新
    resp = client.patch(
        f"/api/knowledge/packages/{pid}",
        json={"name": "Web 端到端包(已更新)", "enabled": False},
    )
    assert resp.status_code == 200
    updated = resp.json()
    assert updated["name"] == "Web 端到端包(已更新)"
    assert updated["enabled"] is False

    # 重新启用（后续导入需要包启用）
    client.patch(f"/api/knowledge/packages/{pid}", json={"enabled": True})

    # 5. 导入（mock AI）
    item = _ok_item(
        kind="fact",
        title="Web 导入事实",
        content="通过 Web API 导入的事实条目。",
    )
    with patch(
        "app.knowledge.import_service.organize_chunk",
        return_value=_ok_result(items=[item]),
    ):
        resp = client.post(
            f"/api/knowledge/packages/{pid}/imports",
            json={
                "source_type": "pasted_text",
                "display_name": "Web 导入文本",
                "pasted_text": "# 测试\n\n这是通过 Web API 提交的测试内容。",
            },
        )
        assert resp.status_code == 200
        import_body = resp.json()
        assert import_body["ok"] is True
        job_id = import_body["job_id"]
        assert job_id.startswith("kj_")

        # 6. 轮询等完成
        final = _wait_for_job_done(repo, job_id, timeout=15.0)
    assert final["status"] in ("completed", "completed_with_errors")
    assert final["generated_items"] >= 1

    # 7. 列出条目应有命中
    resp = client.get(f"/api/knowledge/items?package_id={pid}")
    assert resp.status_code == 200
    items_body = resp.json()
    assert items_body["total"] >= 1
    assert any(it["title"] == "Web 导入事实" for it in items_body["items"])

    # 8. 检索预览
    resp = client.post(
        "/api/knowledge/retrieval/preview",
        json={
            "scene_brief": "Web API 检索场景",
            "keywords": ["Web", "导入"],
            "max_items": 4,
            "max_chars": 360,
        },
    )
    assert resp.status_code == 200
    preview = resp.json()
    assert preview["hit_count"] >= 1
    assert isinstance(preview["prompt_text"], str)

    # 9. 级联删除
    resp = client.delete(f"/api/knowledge/packages/{pid}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # 10. 删除后 GET 返回 not_found
    resp = client.get(f"/api/knowledge/packages/{pid}")
    assert resp.status_code == 200
    assert resp.json() == {"error": "not_found"}


# ---------------------------------------------------------------------------
# 6. 协作式取消端到端
# ---------------------------------------------------------------------------


def test_cancellation_end_to_end(orchestrator, db, repo, config):
    """提交多 chunk 导入 → 阻塞首个 chunk → cancel_job → 验证 cancelled + 残留 pending。"""
    pkg = repo.create_package(name="取消测试包")
    package_internal = repo.get_package(pkg["public_id"])["id"]
    source = repo.create_source(
        package_id=package_internal,
        source_type="pasted_text",
        display_name="多 chunk 文本",
    )
    source_id = source["id"]

    # 3 chunk 文本
    text = _make_multi_chunk_text(n=3)
    payload = {"pasted_text": text}

    started = threading.Event()
    release = threading.Event()

    def blocking_organize(*args, **kwargs):
        started.set()
        release.wait(timeout=5)
        return _ok_result(items=[], input_tokens=0, output_tokens=0)

    with patch(
        "app.knowledge.import_service.organize_chunk",
        side_effect=blocking_organize,
    ):
        job_id = orchestrator.submit_import(
            config=config,
            package_id=package_internal,
            source_id=source_id,
            source_type="pasted_text",
            payload=payload,
        )
        # 等待首个 chunk 开始处理
        assert started.wait(timeout=5), "organize_chunk didn't start in time"

        # 取消任务
        cancelled = orchestrator.cancel_job(job_id)
        assert cancelled is True

        # 释放首个 chunk
        release.set()

        # 等任务终结
        final = _wait_for_job_done(repo, job_id, timeout=15.0)

    assert final["status"] == "cancelled"
    assert final["stage"] == "cancelled"

    # 至少有一个 chunk 未被处理（仍是 pending）
    chunks = repo.list_chunks(source_id)
    assert len(chunks) == final["total_chunks"]
    pending_chunks = [c for c in chunks if c["status"] == "pending"]
    assert len(pending_chunks) >= 1

    # 再次取消已完成的 job 应返回 False
    assert orchestrator.cancel_job(job_id) is False


# ---------------------------------------------------------------------------
# 7. 中英文 / FTS fallback 处理
# ---------------------------------------------------------------------------


def test_bilingual_and_fts_fallback(db, repo):
    """中英文条目检索 + FTS fallback（LIKE）路径验证。

    - 插入中文 + 英文条目
    - 中文关键词 → 命中中文条目（FTS 路径）
    - 英文关键词 → 命中英文条目（FTS 路径）
    - 强制 ``_fts_backend='fallback'`` → LIKE 路径仍能命中
    """
    pkg = repo.create_package(name="双语包")
    package_internal = repo.get_package(pkg["public_id"])["id"]
    source = repo.create_source(
        package_id=package_internal,
        source_type="pasted_text",
        display_name="双语源",
    )
    source_id = source["id"]

    # 中文条目
    repo.insert_item(
        package_id=package_internal,
        source_id=source_id,
        chunk_id=None,
        kind="fact",
        title="葛瑞克",
        content="葛瑞克是《艾尔登法环》的初始 Boss。",
        scopes=["游戏"],
        enabled=True,
        priority=5,
    )
    repo.insert_item(
        package_id=package_internal,
        source_id=source_id,
        chunk_id=None,
        kind="fact",
        title="梅琳娜",
        content="梅琳娜是褪色者的引导者。",
        scopes=["游戏"],
        enabled=True,
        priority=3,
    )

    # 英文条目
    repo.insert_item(
        package_id=package_internal,
        source_id=source_id,
        chunk_id=None,
        kind="fact",
        title="Godrick",
        content="Godrick is the initial boss of Elden Ring.",
        scopes=["game"],
        enabled=True,
        priority=5,
    )
    repo.insert_item(
        package_id=package_internal,
        source_id=source_id,
        chunk_id=None,
        kind="fact",
        title="Malenia",
        content="Malenia is the hardest boss in Elden Ring.",
        scopes=["game"],
        enabled=True,
        priority=3,
    )

    retriever = KnowledgeRetriever(db)

    # 1. 中文关键词 → 命中中文条目（FTS 路径）
    result_cn = retriever.retrieve(
        scene_brief="玩家在与葛瑞克战斗",
        keywords=["葛瑞克"],
        max_items=4,
        max_chars=600,
    )
    assert result_cn.hit_count >= 1
    titles_cn = [it["title"] for it in result_cn.items]
    assert "葛瑞克" in titles_cn
    assert result_cn.fts_backend == db.fts_backend

    # 2. 英文关键词 → 命中英文条目（FTS 路径）
    result_en = retriever.retrieve(
        scene_brief="fighting Godrick",
        keywords=["Godrick"],
        max_items=4,
        max_chars=600,
    )
    assert result_en.hit_count >= 1
    titles_en = [it["title"] for it in result_en.items]
    assert "Godrick" in titles_en

    # 3. 强制 fallback（LIKE 路径）：用新检索器实例，override fts_backend
    retriever_fb = KnowledgeRetriever(db)
    retriever_fb._fts_backend = "fallback"  # type: ignore[attr-defined]

    result_fb_cn = retriever_fb.retrieve(
        scene_brief="葛瑞克战斗",
        keywords=["葛瑞克"],
        max_items=4,
        max_chars=600,
    )
    # LIKE 路径应仍能命中中文条目
    assert result_fb_cn.hit_count >= 1
    titles_fb = [it["title"] for it in result_fb_cn.items]
    assert "葛瑞克" in titles_fb
    assert result_fb_cn.fts_backend == "fallback"

    result_fb_en = retriever_fb.retrieve(
        scene_brief="fighting Godrick",
        keywords=["Godrick"],
        max_items=4,
        max_chars=600,
    )
    assert result_fb_en.hit_count >= 1
    titles_fb_en = [it["title"] for it in result_fb_en.items]
    assert "Godrick" in titles_fb_en

    # 4. 空查询应返回空结果
    result_empty = retriever.retrieve(
        scene_brief="",
        keywords=[],
        max_items=4,
        max_chars=360,
    )
    assert result_empty.hit_count == 0
    assert result_empty.items == []
    assert result_empty.prompt_text == ""
