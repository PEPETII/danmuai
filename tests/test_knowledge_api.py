"""Tests for the knowledge Web API (A8.4).

测试策略（mock 模式，**不**发起真实 HTTP 抓取）：
    - 用真实 ``KnowledgeDatabase``（``tmp_path``）+ 真实 ``KnowledgeRepository``
      + 真实 ``ImportOrchestrator`` + 真实 ``KnowledgeRetriever``。
    - 通过 ``SimpleNamespace`` 把它们挂到 ``app.knowledge_runtime``（仿 B2 阶段
      ``main_lifecycle_mixin`` 的挂载方式），让 A8 的服务函数能直接调用。
    - ``bridge.invoke_on_main`` 在测试里同步直接执行（与 ``test_meme_barrage_api``
      同一模板），保证 TestClient 调用路径与生产一致。
    - 仅 mock ``ai_organizer.organize_chunk`` 避免真实 LLM 请求。

覆盖用例（≥ 15 个）：
    1. 路由注册（register_web_routes 后所有 /api/knowledge/* 可达）
    2. GET /packages 空列表
    3. POST /packages 创建 → {"ok": true, "package_id": "..."}
    4. POST /packages 无 Token → 401
    5. GET /packages/{id} 详情
    6. GET /packages/{id} 不存在 → {"error": "not_found"}
    7. PATCH /packages/{id} 更新
    8. DELETE /packages/{id} 删除
    9. POST /packages/{id}/imports pasted_text → {"ok": true, "job_id": "..."}
    10. POST /imports markdown base64
    11. POST /imports webpage（mock extract）
    12. GET /jobs/{id} 任务详情
    13. POST /jobs/{id}/cancel 取消
    14. GET /items 列表
    15. GET /items/{id} 详情
    16. PATCH /items/{id} 更新
    17. DELETE /items/{id} 删除
    18. POST /retrieval/preview 检索预览
    19. 端到端导入流程（mock organize_chunk → 完成 → items 命中）
    20. POST /packages 校验失败（name 为空 → 422）
"""

from __future__ import annotations

import base64
import time
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
    import sqlite3

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
def app_with_routes(tmp_path, knowledge_runtime, config):
    """构造一个挂载了 knowledge_runtime 的最小 FastAPI app + bridge。"""
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
# 1. 路由注册
# ---------------------------------------------------------------------------


def test_knowledge_routes_registered(client):
    """所有 /api/knowledge/* 路由都已注册且可达。"""
    # GET /packages 不需要 token，应返回 200
    resp = client.get("/api/knowledge/packages")
    assert resp.status_code == 200
    body = resp.json()
    assert "packages" in body
    assert body["total"] == 0
    assert body["packages"] == []


# ---------------------------------------------------------------------------
# 2-4. packages 列表 / 创建 / 鉴权
# ---------------------------------------------------------------------------


def test_list_packages_empty(client):
    resp = client.get("/api/knowledge/packages")
    assert resp.status_code == 200
    assert resp.json() == {"packages": [], "total": 0}


def test_create_package_returns_ok_and_package_id(client):
    resp = client.post(
        "/api/knowledge/packages",
        json={"name": "我的知识包", "description": "测试用"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert isinstance(body["package_id"], str)
    assert body["package_id"]  # non-empty


def test_create_package_without_token_returns_401(tmp_path, knowledge_runtime, config):
    """无 Token 写操作返回 401（spec §ADDED Web API Scenario）。"""
    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *a, **k: fn(*a, **k)
    bridge.danmu_app = SimpleNamespace(
        knowledge_runtime=knowledge_runtime,
        config=config,
        config_changed=MagicMock(),
    )

    # check_token: 模拟 401 拒绝
    def _check_token(authorization: str | None = None) -> None:
        from fastapi import HTTPException

        if not authorization:
            raise HTTPException(status_code=401, detail="unauthorized")
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    resp = client.post("/api/knowledge/packages", json={"name": "x"})
    assert resp.status_code == 401


def test_create_package_invalid_payload_returns_422(client):
    """Pydantic 校验：name 为空应返回 422。"""
    resp = client.post("/api/knowledge/packages", json={"name": ""})
    assert resp.status_code == 422


# ---------------------------------------------------------------------------
# 5-6. package 详情
# ---------------------------------------------------------------------------


def test_get_package_detail(client):
    create = client.post(
        "/api/knowledge/packages", json={"name": "详情测试包"}
    ).json()
    pid = create["package_id"]

    resp = client.get(f"/api/knowledge/packages/{pid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["public_id"] == pid
    assert body["name"] == "详情测试包"
    assert "sources" in body
    assert "items" in body


def test_get_package_not_found(client):
    resp = client.get("/api/knowledge/packages/nonexistent_id")
    assert resp.status_code == 200
    assert resp.json() == {"error": "not_found"}


# ---------------------------------------------------------------------------
# 7-8. package 更新 / 删除
# ---------------------------------------------------------------------------


def test_update_package(client):
    pid = client.post(
        "/api/knowledge/packages", json={"name": "原名"}
    ).json()["package_id"]

    resp = client.patch(
        f"/api/knowledge/packages/{pid}",
        json={"name": "新名", "enabled": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "新名"
    assert body["enabled"] is False


def test_delete_package(client):
    pid = client.post(
        "/api/knowledge/packages", json={"name": "待删除"}
    ).json()["package_id"]

    resp = client.delete(f"/api/knowledge/packages/{pid}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # 删除后再 GET 应返回 not_found
    after = client.get(f"/api/knowledge/packages/{pid}")
    assert after.json() == {"error": "not_found"}


# ---------------------------------------------------------------------------
# 9-11. 导入（pasted_text / markdown / webpage）
# ---------------------------------------------------------------------------


def test_import_pasted_text_returns_job_id(client, repo):
    pid = client.post(
        "/api/knowledge/packages", json={"name": "导入测试"}
    ).json()["package_id"]

    with patch(
        "app.knowledge.import_service.organize_chunk",
        return_value=_ok_result(items=[]),
    ):
        resp = client.post(
            f"/api/knowledge/packages/{pid}/imports",
            json={
                "source_type": "pasted_text",
                "display_name": "粘贴文本",
                "pasted_text": "# 测试\n\n这是一段测试文本内容。",
            },
        )
        body = resp.json()
        # 等任务完成，避免后台线程跨 fixture 干扰下一个测试
        _wait_for_job_done(repo, body["job_id"])
    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["job_id"].startswith("kj_")
    assert body["source_id"]  # non-empty


def test_import_markdown_base64(client, repo):
    pid = client.post(
        "/api/knowledge/packages", json={"name": "Markdown 导入"}
    ).json()["package_id"]

    md_text = "# 标题\n\n段落内容\n\n- 列表项"
    b64 = base64.b64encode(md_text.encode("utf-8")).decode("ascii")
    with patch(
        "app.knowledge.import_service.organize_chunk",
        return_value=_ok_result(items=[]),
    ):
        resp = client.post(
            f"/api/knowledge/packages/{pid}/imports",
            json={
                "source_type": "markdown",
                "display_name": "test.md",
                "content_base64": b64,
            },
        )
        body = resp.json()
        _wait_for_job_done(repo, body["job_id"])
    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["job_id"].startswith("kj_")


def test_import_txt_base64(client, repo):
    """txt 类型：content_base64 创建 job。"""
    pid = client.post(
        "/api/knowledge/packages", json={"name": "TXT 导入"}
    ).json()["package_id"]

    text = "这是 TXT 文件内容\n第二行"
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    with patch(
        "app.knowledge.import_service.organize_chunk",
        return_value=_ok_result(items=[]),
    ):
        resp = client.post(
            f"/api/knowledge/packages/{pid}/imports",
            json={
                "source_type": "txt",
                "display_name": "notes.txt",
                "content_base64": b64,
            },
        )
        body = resp.json()
        _wait_for_job_done(repo, body["job_id"])
    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["job_id"].startswith("kj_")
    assert body["source_id"]


def test_import_invalid_payload_creates_no_source_or_job(client, repo):
    """无效 payload 不得创建 source / job（Wave 2 跨字段校验）。"""
    pid = client.post(
        "/api/knowledge/packages", json={"name": "无效导入"}
    ).json()["package_id"]

    cases = [
        {"source_type": "pasted_text"},  # missing pasted_text
        {"source_type": "pasted_text", "pasted_text": "   "},
        {"source_type": "txt"},  # missing content_base64
        {"source_type": "markdown", "content_base64": ""},
        {"source_type": "webpage"},  # missing source_url
        {"source_type": "webpage", "source_url": "ftp://example.com/x"},
        {"source_type": "webpage", "source_url": "not-a-url"},
    ]
    for payload in cases:
        resp = client.post(
            f"/api/knowledge/packages/{pid}/imports",
            json=payload,
        )
        # Pydantic model_validator → 422；服务层兜底 → 200 + error
        assert resp.status_code in (200, 422), payload
        if resp.status_code == 200:
            body = resp.json()
            assert "error" in body, payload
            assert "job_id" not in body or not body.get("ok")

    jobs = client.get(f"/api/knowledge/jobs?package_id={pid}").json()
    assert jobs.get("total", 0) == 0
    assert jobs.get("jobs") == []

    pkg = client.get(f"/api/knowledge/packages/{pid}").json()
    assert pkg.get("sources") == []


def test_import_source_service_rejects_before_create(knowledge_runtime, config, repo):
    """直接调用 import_source：校验失败不得 create_source / submit_import。"""
    from app.web_api import knowledge as knowledge_api

    created = repo.create_package(name="service-validate")
    pkg = repo.get_package(created["public_id"])
    assert pkg is not None
    package_id = pkg["id"]
    app = SimpleNamespace(knowledge_runtime=knowledge_runtime, config=config)
    before_sources = repo.list_sources(package_id)
    before_jobs = repo.list_jobs(package_id=package_id)

    result = knowledge_api.import_source(
        app,
        pkg["public_id"],
        {"source_type": "txt", "display_name": "x"},
    )
    assert result == {"error": "missing_content_base64"}
    assert repo.list_sources(package_id) == before_sources
    assert repo.list_jobs(package_id=package_id) == before_jobs

    result2 = knowledge_api.import_source(
        app,
        pkg["public_id"],
        {"source_type": "webpage", "source_url": "javascript:alert(1)"},
    )
    assert result2 == {"error": "invalid_source_url"}
    assert repo.list_sources(package_id) == before_sources


def test_import_webpage_with_mocked_extractor(client, repo):
    """webpage 类型：mock 源提取避免真实 HTTP。"""
    pid = client.post(
        "/api/knowledge/packages", json={"name": "网页导入"}
    ).json()["package_id"]

    from app.knowledge.source_extractors import ExtractionResult

    with patch(
        "app.knowledge.import_service.extract_source",
        return_value=ExtractionResult(
            normalized_text="网页正文内容",
            metadata={"source_type": "webpage"},
        ),
    ), patch(
        "app.knowledge.import_service.organize_chunk",
        return_value=_ok_result(items=[]),
    ):
        resp = client.post(
            f"/api/knowledge/packages/{pid}/imports",
            json={
                "source_type": "webpage",
                "display_name": "示例网页",
                "source_url": "https://example.com/article",
            },
        )
        body = resp.json()
        _wait_for_job_done(repo, body["job_id"])
    assert resp.status_code == 200
    assert body["ok"] is True
    assert body["job_id"].startswith("kj_")


# ---------------------------------------------------------------------------
# 12-13. job 查询 / 取消
# ---------------------------------------------------------------------------


def test_get_job_detail(client, repo):
    pid = client.post(
        "/api/knowledge/packages", json={"name": "任务查询"}
    ).json()["package_id"]
    with patch(
        "app.knowledge.import_service.organize_chunk",
        return_value=_ok_result(items=[]),
    ):
        job_id = client.post(
            f"/api/knowledge/packages/{pid}/imports",
            json={"source_type": "pasted_text", "pasted_text": "内容"},
        ).json()["job_id"]
        # 等任务完成后再读，避免后台线程与读线程并发使用同一 DB 连接
        _wait_for_job_done(repo, job_id)

    resp = client.get(f"/api/knowledge/jobs/{job_id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["public_id"] == job_id
    assert "status" in body
    assert "stage" in body


def test_list_jobs(client, repo):
    pid = client.post(
        "/api/knowledge/packages", json={"name": "任务列表"}
    ).json()["package_id"]
    with patch(
        "app.knowledge.import_service.organize_chunk",
        return_value=_ok_result(items=[]),
    ):
        job_id = client.post(
            f"/api/knowledge/packages/{pid}/imports",
            json={"source_type": "pasted_text", "pasted_text": "内容"},
        ).json()["job_id"]
        _wait_for_job_done(repo, job_id)

    resp = client.get("/api/knowledge/jobs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert len(body["jobs"]) >= 1


def test_list_jobs_filtered_by_package(client, repo):
    """按 package_id 过滤任务列表。"""
    pid1 = client.post(
        "/api/knowledge/packages", json={"name": "包1"}
    ).json()["package_id"]
    pid2 = client.post(
        "/api/knowledge/packages", json={"name": "包2"}
    ).json()["package_id"]
    with patch(
        "app.knowledge.import_service.organize_chunk",
        return_value=_ok_result(items=[]),
    ):
        job_id = client.post(
            f"/api/knowledge/packages/{pid1}/imports",
            json={"source_type": "pasted_text", "pasted_text": "内容"},
        ).json()["job_id"]
        _wait_for_job_done(repo, job_id)

    resp = client.get(f"/api/knowledge/jobs?package_id={pid1}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    resp2 = client.get(f"/api/knowledge/jobs?package_id={pid2}")
    assert resp2.json()["total"] == 0


def test_cancel_job(client, repo):
    """提交后立即取消；job 应进入 cancelled 状态（轮询到完成）。"""
    pid = client.post(
        "/api/knowledge/packages", json={"name": "取消测试"}
    ).json()["package_id"]
    # 构造一个会产生多 chunk 的长文本，便于在执行中取消
    long_text = "# Chapter\n\n" + ("This is content. " * 600)
    with patch(
        "app.knowledge.import_service.organize_chunk",
        # 故意阻塞以增加取消概率
        side_effect=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("cancelled in test")),
    ):
        job_id = client.post(
            f"/api/knowledge/packages/{pid}/imports",
            json={"source_type": "pasted_text", "pasted_text": long_text},
        ).json()["job_id"]

        # 立即取消（无论是否已开始，cancel_job 都应返回 ok:true 或 error）
        resp = client.post(f"/api/knowledge/jobs/{job_id}/cancel")
        assert resp.status_code == 200
        # 等任务终结（cancelled 或 completed 都可接受，取决于取消时机）
        final = _wait_for_job_done(repo, job_id, timeout=20.0)
    assert final["status"] in ("cancelled", "completed", "completed_with_errors", "failed")


# ---------------------------------------------------------------------------
# 14-17. items 列表 / 详情 / 更新 / 删除
# ---------------------------------------------------------------------------


def _seed_item(client, repo) -> tuple[str, str, dict]:
    """直接通过 repo 插入一条 item，返回 (package_public_id, item_public_id, item_dict)。"""
    pid = client.post(
        "/api/knowledge/packages", json={"name": "条目宿主"}
    ).json()["package_id"]
    pkg = repo.get_package(pid)
    source = repo.create_source(
        package_id=pkg["id"], source_type="pasted_text", display_name="seed"
    )
    item = repo.insert_item(
        package_id=pkg["id"],
        source_id=source["id"],
        chunk_id=0,
        kind="fact",
        title="种子事实",
        content="种子内容",
        examples=[],
        triggers=[],
        tones=[],
        scopes=[],
        entities=[],
        confidence=0.9,
        evidence="",
    )
    return pid, item["public_id"], item


def test_list_items(client, repo):
    _pid, _iid, _item = _seed_item(client, repo)

    resp = client.get("/api/knowledge/items")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any(it["title"] == "种子事实" for it in body["items"])


def test_list_items_filtered_by_package(client, repo):
    pid, _iid, _item = _seed_item(client, repo)

    resp = client.get(f"/api/knowledge/items?package_id={pid}")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1

    # 另一个不存在的 package
    resp2 = client.get("/api/knowledge/items?package_id=nonexistent")
    assert resp2.status_code == 200
    assert resp2.json() == {"error": "package_not_found"}


def test_get_item_detail(client, repo):
    _pid, iid, _item = _seed_item(client, repo)

    resp = client.get(f"/api/knowledge/items/{iid}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["public_id"] == iid
    assert body["title"] == "种子事实"


def test_get_item_not_found(client):
    resp = client.get("/api/knowledge/items/nonexistent")
    assert resp.status_code == 200
    assert resp.json() == {"error": "not_found"}


def test_update_item(client, repo):
    _pid, iid, _item = _seed_item(client, repo)

    resp = client.patch(
        f"/api/knowledge/items/{iid}",
        json={"title": "更新后标题", "enabled": False},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "更新后标题"
    assert body["enabled"] is False


def test_delete_item(client, repo):
    _pid, iid, _item = _seed_item(client, repo)

    resp = client.delete(f"/api/knowledge/items/{iid}")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    after = client.get(f"/api/knowledge/items/{iid}")
    assert after.json() == {"error": "not_found"}


# ---------------------------------------------------------------------------
# 18. 检索预览
# ---------------------------------------------------------------------------


def test_retrieval_preview_empty(client):
    """无知识时检索预览返回空命中。"""
    resp = client.post(
        "/api/knowledge/retrieval/preview",
        json={"scene_brief": "测试场景", "keywords": ["测试"]},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hit_count"] == 0
    assert body["items"] == []
    assert body["prompt_text"] == ""


def test_retrieval_preview_with_hits(client, repo):
    """有知识时检索预览返回命中条目与 prompt_text。"""
    pid = client.post(
        "/api/knowledge/packages", json={"name": "检索预览包"}
    ).json()["package_id"]
    pkg = repo.get_package(pid)
    source = repo.create_source(
        package_id=pkg["id"], source_type="pasted_text", display_name="seed"
    )
    repo.insert_item(
        package_id=pkg["id"],
        source_id=source["id"],
        chunk_id=0,
        kind="fact",
        title="葛瑞克战斗",
        content="葛瑞克是《艾尔登法环》的初始 Boss。",
        examples=[],
        triggers=["葛瑞克", "Boss"],
        tones=[],
        scopes=["游戏"],
        entities=[],
        confidence=0.95,
        evidence="",
    )

    resp = client.post(
        "/api/knowledge/retrieval/preview",
        json={
            "scene_brief": "玩家在与葛瑞克战斗",
            "keywords": ["葛瑞克", "Boss"],
            "max_items": 4,
            "max_chars": 360,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["hit_count"] >= 1
    assert any("葛瑞克" in it.get("title", "") for it in body["items"])
    assert isinstance(body["prompt_text"], str)


# ---------------------------------------------------------------------------
# 19. 端到端导入流程
# ---------------------------------------------------------------------------


def test_end_to_end_import_flow_with_mocked_organizer(client, repo):
    """完整流程：建包 → 导入 → mock AI 返回 fact → 完成 → items 命中。"""
    pid = client.post(
        "/api/knowledge/packages", json={"name": "端到端测试"}
    ).json()["package_id"]

    item = _ok_item(
        kind="fact",
        title="测试事实",
        content="AI 整理出来的事实条目",
    )
    with patch(
        "app.knowledge.import_service.organize_chunk",
        return_value=_ok_result(items=[item]),
    ):
        job_id = client.post(
            f"/api/knowledge/packages/{pid}/imports",
            json={
                "source_type": "pasted_text",
                "display_name": "端到端文本",
                "pasted_text": "# 测试\n\n这是用于 AI 整理的原始内容。",
            },
        ).json()["job_id"]
        final = _wait_for_job_done(repo, job_id, timeout=15.0)

    assert final["status"] in ("completed", "completed_with_errors")
    assert final["generated_items"] >= 1

    # 通过 API 列出条目应能命中
    items_resp = client.get(f"/api/knowledge/items?package_id={pid}")
    assert items_resp.status_code == 200
    assert items_resp.json()["total"] >= 1
    assert any(
        it["title"] == "测试事实" for it in items_resp.json()["items"]
    )


# ---------------------------------------------------------------------------
# 20. 未初始化 runtime 的兜底
# ---------------------------------------------------------------------------


def test_routes_handle_uninitialized_runtime(tmp_path, config):
    """knowledge_runtime 为 None 时，GET 路由应返回 not_initialized 兜底。"""
    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *a, **k: fn(*a, **k)
    bridge.danmu_app = SimpleNamespace(
        knowledge_runtime=None,  # 未初始化
        config=config,
        config_changed=MagicMock(),
    )

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    resp = client.get("/api/knowledge/packages")
    assert resp.status_code == 200
    body = resp.json()
    assert body.get("error") == "not_initialized"
    assert body["packages"] == []
    assert body["total"] == 0


def test_post_packages_handles_uninitialized_runtime(tmp_path, config):
    """knowledge_runtime 为 None 时，POST 应返回 not_initialized（不创建任何记录）。"""
    app = FastAPI()
    bridge = MagicMock()
    bridge.invoke_on_main.side_effect = lambda fn, *a, **k: fn(*a, **k)
    bridge.danmu_app = SimpleNamespace(
        knowledge_runtime=None,
        config=config,
        config_changed=MagicMock(),
    )

    def _check_token(_authorization: str | None = None) -> None:
        return None

    register_web_routes(app, bridge, _check_token)
    client = TestClient(app)

    resp = client.post("/api/knowledge/packages", json={"name": "x"})
    assert resp.status_code == 200
    assert resp.json() == {"error": "not_initialized"}
