"""Tests for ``app/knowledge/import_service.py``（A6.2）。

测试策略（mock 模式，**不**发起真实 HTTP）：
    - 用真实 ``KnowledgeDatabase``（``tmp_path``）+ 真实 ``KnowledgeRepository``
    - 用真实 ``source_extractors`` + 真实 ``chunker`` + 真实 ``validator`` + 真实 ``deduplicator``
    - 只 mock ``ai_organizer.organize_chunk``（避免真实 HTTP）
    - 用 ``tests.fakes.ai_client_fake_config()`` 构造 config

覆盖用例（≥ 13 个）：
    1. 完整流程（mock AI 返回标准条目）→ job='completed'，knowledge_items 有 1 条
    2. 单 chunk 失败 job='completed_with_errors'（第一个失败，第二个成功）
    3. 协作式取消（提交后立即 cancel_job，验证 job='cancelled'，未处理 chunk 仍是 'pending'）
    4. 模型未配置（mock 返回 ok=False, error='model_not_configured'）→ 所有 chunk failed → job='failed'
    5. extract 失败（webpage + 127.0.0.1 → ssrf_blocked）→ job='failed', error 含 'ssrf_blocked'
    6. 超大来源（normalized_text > 5 MiB）→ job='failed', error='source_too_large'
    7. token 统计累加（2 个 chunk，每个 input=100/output=50）→ job.input_tokens=200, output_tokens=100
    8. 去重生效（2 个 chunk 返回相同 content 的 item）→ 只存 1 条，dedup_count=1
    9. 空 items（mock 返回 items=[]）→ chunk='completed', job='failed'（no_items_generated）, source='failed'
    10. 异常不终止整个进程（mock 抛 RuntimeError）→ job='failed' 但不传播异常
    11. 多 chunk 进度更新（3 个 chunk，验证 processed_chunks 递增）
    12. public_id 生成（job_public_id 是 "kj_" + uuid4 hex）
    13. close 等待未完成任务（提交后立即 close()，验证任务仍完成）
    14. source 终态映射：success/fail/cancel/zero items/empty chunks/exception
"""
from __future__ import annotations

import re
import threading
import time
from unittest.mock import patch

import pytest

from app.knowledge.database import KnowledgeDatabase
from app.knowledge.import_service import ImportOrchestrator
from app.knowledge.repository import KnowledgeRepository
from app.knowledge.source_extractors import MAX_SOURCE_CHARS, ExtractionResult
from tests.fakes import ai_client_fake_config

# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------


def _wait_for_job_done(
    repo: KnowledgeRepository, job_id: str, timeout: float = 10.0
) -> dict:
    """轮询 job 状态直到完成或超时。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = repo.get_job(job_id)
        if job and job["status"] in (
            "completed",
            "completed_with_errors",
            "failed",
            "cancelled",
            "interrupted",
        ):
            return job
        time.sleep(0.05)
    raise TimeoutError(f"job {job_id} didn't finish within {timeout}s")


def _get_package_id(db: KnowledgeDatabase, public_id: str) -> int:
    """按 public_id 查询 package 内部 id。"""
    row = db.conn.execute(
        "SELECT id FROM knowledge_packages WHERE public_id=?", (public_id,)
    ).fetchone()
    return int(row[0])


def _create_package_and_source(
    db: KnowledgeDatabase,
    repo: KnowledgeRepository,
    source_type: str = "pasted_text",
    display_name: str = "test source",
) -> tuple[int, int]:
    """创建 package + source，返回 (package_id, source_id)。"""
    pkg = repo.create_package(name="test package")
    package_id = _get_package_id(db, pkg["public_id"])
    source = repo.create_source(
        package_id=package_id,
        source_type=source_type,
        display_name=display_name,
    )
    return package_id, source["id"]


def _make_multi_chunk_text(n: int = 2) -> str:
    """构造包含 n 个 chapter 的文本，每个 chapter 约 4000 字符（产生 n 个 chunk）。"""
    parts: list[str] = []
    for i in range(n):
        # "This is test content. " is 22 chars; 200 reps = ~4400 chars
        content = "This is test content. " * 200
        parts.append(f"# Chapter {i + 1}\n\n{content}")
    return "\n\n".join(parts)


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


def _fail_result(error: str = "model_not_configured") -> dict:
    """构造 organize_chunk 失败返回值。"""
    return {
        "ok": False,
        "items": [],
        "input_tokens": 0,
        "output_tokens": 0,
        "error": error,
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
def config():
    return ai_client_fake_config()


# ---------------------------------------------------------------------------
# 测试用例
# ---------------------------------------------------------------------------


class TestImportOrchestratorCompleteFlow:
    """1. 完整流程：mock AI 返回标准条目 → job='completed'，knowledge_items 有 1 条。"""

    def test_complete_flow_single_chunk_single_item(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\nThis is a test content for the chunk."}
        item = _ok_item(content="这是测试内容")

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[item]),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "completed"
        assert job["stage"] == "finished"
        assert job["total_chunks"] == 1
        assert job["processed_chunks"] == 1
        assert job["failed_chunks"] == 0
        assert job["generated_items"] == 1
        assert job["deduplicated_items"] == 0
        assert job["input_tokens"] == 100
        assert job["output_tokens"] == 50

        # 验证 source 状态
        sources = repo.list_sources(package_id)
        assert sources[0]["status"] == "processed"
        assert sources[0]["normalized_text"] != ""

        # 验证 chunks 状态
        chunks = repo.list_chunks(source_id)
        assert len(chunks) == 1
        assert chunks[0]["status"] == "completed"

        # 验证 knowledge_items
        result = repo.list_items(package_id=package_id)
        assert result["total"] == 1
        assert result["items"][0]["title"] == "测试事实"
        assert result["items"][0]["content"] == "这是测试内容"


class TestImportOrchestratorSingleChunkFailure:
    """2. 单 chunk 失败 job='completed_with_errors'：第一个失败，第二个成功。"""

    def test_mixed_success_failure(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        text = _make_multi_chunk_text(n=2)
        payload = {"pasted_text": text}
        item = _ok_item(content="成功条目")

        # 第一次调用失败，第二次成功
        side_effects = [_fail_result("json_parse_failed"), _ok_result(items=[item])]

        with patch(
            "app.knowledge.import_service.organize_chunk",
            side_effect=side_effects,
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "completed_with_errors"
        assert job["total_chunks"] == 2
        assert job["processed_chunks"] == 2
        assert job["failed_chunks"] == 1
        assert job["generated_items"] == 1

        # 验证 chunks 状态
        chunks = repo.list_chunks(source_id)
        assert len(chunks) == 2
        statuses = {c["status"] for c in chunks}
        assert "failed" in statuses
        assert "completed" in statuses

        # 验证 error_message 包含错误信息
        assert "json_parse_failed" in job["error_message"]

        # 部分成功 → source=processed_with_errors
        sources = repo.list_sources(package_id)
        assert sources[0]["status"] == "processed_with_errors"


class TestImportOrchestratorCancel:
    """3. 协作式取消：提交后立即 cancel_job，验证 job='cancelled'，未处理 chunk 仍是 'pending'。"""

    def test_cancel_job_during_processing(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
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
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            # 等待第一个 chunk 开始处理
            assert started.wait(timeout=5), "organize_chunk didn't start in time"
            # 取消任务
            cancelled = orchestrator.cancel_job(job_id)
            assert cancelled is True
            # 释放第一个 chunk
            release.set()
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "cancelled"
        # 至少有一个 chunk 未被处理（仍是 pending）
        chunks = repo.list_chunks(source_id)
        pending_chunks = [c for c in chunks if c["status"] == "pending"]
        assert len(pending_chunks) >= 1

        # 取消 → source=cancelled
        sources = repo.list_sources(package_id)
        assert sources[0]["status"] == "cancelled"


class TestImportOrchestratorModelNotConfigured:
    """4. 模型未配置：mock 返回 ok=False, error='model_not_configured' → 所有 chunk failed → job='failed'。"""

    def test_all_chunks_failed_model_not_configured(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\nThis is test content."}

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_fail_result("model_not_configured"),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "failed"
        assert job["failed_chunks"] == 1
        assert job["generated_items"] == 0
        assert "model_not_configured" in job["error_message"]

        # 验证 chunk 状态
        chunks = repo.list_chunks(source_id)
        assert chunks[0]["status"] == "failed"
        assert chunks[0]["error_message"] == "model_not_configured"

        # 全失败 → source=failed
        sources = repo.list_sources(package_id)
        assert sources[0]["status"] == "failed"


class TestImportOrchestratorExtractFailure:
    """5. extract 失败：webpage + 127.0.0.1 → ssrf_blocked → job='failed'。"""

    def test_extract_ssrf_blocked(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(
            db, repo, source_type="webpage"
        )
        payload = {"source_url": "http://127.0.0.1/"}

        # 不需要 mock organize_chunk，因为 extract 会先失败
        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[]),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="webpage",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "failed"
        assert "ssrf_blocked" in job["error_message"]

        # 验证 source 状态
        sources = repo.list_sources(package_id)
        assert sources[0]["status"] == "failed"


class TestImportOrchestratorSourceTooLarge:
    """6. 超大来源：normalized_text > 5 MiB → job='failed', error='source_too_large'。"""

    def test_source_too_large(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        huge_text = "a" * (MAX_SOURCE_CHARS + 1)
        payload = {"pasted_text": "placeholder"}

        # mock extract_source 返回超大文本（绕过提取器自身的大小检查）
        with patch(
            "app.knowledge.import_service.extract_source",
            return_value=ExtractionResult(
                huge_text, {"source_type": "pasted_text"}
            ),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "failed"
        assert job["error_message"] == "source_too_large"

        # 验证 source 状态
        sources = repo.list_sources(package_id)
        assert sources[0]["status"] == "failed"


class TestImportOrchestrationTokenAccumulation:
    """7. token 统计累加：2 个 chunk，每个 input=100/output=50 → 总 input=200, output=100。"""

    def test_token_accumulation(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        text = _make_multi_chunk_text(n=2)
        payload = {"pasted_text": text}

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[], input_tokens=100, output_tokens=50),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "failed"
        assert job["total_chunks"] == 2
        assert job["input_tokens"] == 200
        assert job["output_tokens"] == 100


class TestImportOrchestratorDedup:
    """8. 去重生效：2 个 chunk 返回相同 content 的 item → 只存 1 条，dedup_count=1。"""

    def test_dedup_same_content(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        text = _make_multi_chunk_text(n=2)
        payload = {"pasted_text": text}
        # 两个 chunk 返回相同的 item（content 相同）
        item = _ok_item(content="相同的测试内容")

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[item], input_tokens=0, output_tokens=0),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "completed"
        assert job["total_chunks"] == 2
        # 第一个 chunk 保留 1 条，第二个 chunk 的相同 item 被去重
        assert job["generated_items"] == 1
        assert job["deduplicated_items"] == 1

        # 验证 knowledge_items 只有 1 条
        result = repo.list_items(package_id=package_id)
        assert result["total"] == 1


class TestImportOrchestratorEmptyItems:
    """9. 空 items：mock 返回 items=[] → chunk='completed', job='failed'（no_items_generated）, kept=0。"""

    def test_empty_items(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\nThis is test content."}

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[], input_tokens=10, output_tokens=5),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "failed"
        assert job["generated_items"] == 0
        assert job["failed_chunks"] == 0
        assert "no_items_generated" in job["error_message"]

        # 验证 chunk 状态
        chunks = repo.list_chunks(source_id)
        assert chunks[0]["status"] == "completed"

        # 零条目 → source=failed（禁止无条件 processed）
        sources = repo.list_sources(package_id)
        assert sources[0]["status"] == "failed"
        assert "no_items_generated" in (sources[0].get("error_message") or "")

        # 验证 knowledge_items 为空
        result = repo.list_items(package_id=package_id)
        assert result["total"] == 0


class TestImportOrchestratorExceptionNoCrash:
    """10. 异常不终止整个进程：mock 抛 RuntimeError → job='failed' 但不传播异常。"""

    def test_organize_chunk_raises_exception(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\nThis is test content."}

        with patch(
            "app.knowledge.import_service.organize_chunk",
            side_effect=RuntimeError("unexpected error"),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        # job 应该是 failed（所有 chunk 失败）
        assert job["status"] == "failed"
        assert job["failed_chunks"] == 1
        assert job["generated_items"] == 0


class TestImportOrchestratorMultiChunkProgress:
    """11. 多 chunk 进度更新：构造 3 个 chunk，验证每次 chunk 处理后 job.processed_chunks 递增。"""

    def test_progress_increments(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        text = _make_multi_chunk_text(n=3)
        payload = {"pasted_text": text}
        seen_progress: list[int] = []

        def slow_organize(*args, **kwargs):
            time.sleep(0.15)
            return _ok_result(items=[], input_tokens=0, output_tokens=0)

        with patch(
            "app.knowledge.import_service.organize_chunk",
            side_effect=slow_organize,
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            # 轮询进度
            for _ in range(60):  # 3 seconds
                job = repo.get_job(job_id)
                if job:
                    seen_progress.append(job["processed_chunks"])
                if job and job["status"] in (
                    "completed",
                    "completed_with_errors",
                    "failed",
                ):
                    break
                time.sleep(0.05)

        job = repo.get_job(job_id)
        assert job["status"] == "failed"
        assert job["total_chunks"] == 3
        assert job["processed_chunks"] == 3
        # 验证进度从 0 开始并递增
        assert seen_progress[0] == 0
        assert 3 in seen_progress
        # 至少看到 2 个不同的进度值（证明递增）
        assert len(set(seen_progress)) >= 2


class TestImportOrchestratorPublicIdFormat:
    """12. public_id 生成：job_public_id 是 "kj_" + uuid4 hex。"""

    def test_public_id_format(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\nThis is test content."}

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[]),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            _wait_for_job_done(repo, job_id)

        # 验证 public_id 格式
        assert job_id.startswith("kj_")
        assert len(job_id) == 35  # "kj_" (3) + 32 hex chars
        assert re.match(r"^kj_[0-9a-f]{32}$", job_id)

        # 验证 job 行存在且 public_id 一致
        job = repo.get_job(job_id)
        assert job is not None
        assert job["public_id"] == job_id


class TestImportOrchestratorCloseWaits:
    """13. close 等待未完成任务：提交后立即 close()，验证任务仍完成。"""

    def test_close_waits_for_pending_task(self, db, repo, config):
        # 不使用 fixture 的 orchestrator，避免 double-close 干扰
        orch = ImportOrchestrator(db, repo)
        try:
            package_id, source_id = _create_package_and_source(db, repo)
            payload = {"pasted_text": "# Test\n\nThis is test content."}

            def slow_organize(*args, **kwargs):
                time.sleep(0.2)
                return _ok_result(items=[])

            with patch(
                "app.knowledge.import_service.organize_chunk",
                side_effect=slow_organize,
            ):
                job_id = orch.submit_import(
                    config=config,
                    package_id=package_id,
                    source_id=source_id,
                    source_type="pasted_text",
                    payload=payload,
                )
                # 立即 close，应等待任务完成
                orch.close()

            # close 返回后任务应已完成
            job = repo.get_job(job_id)
            assert job["status"] in ("completed", "completed_with_errors", "failed")
        finally:
            # 确保关闭（shutdown 是幂等的）
            orch.close()


class TestImportOrchestratorCancelNonExistent:
    """补充：cancel_job 对不存在或已完成的 job 返回 False。"""

    def test_cancel_non_existent_job(self, orchestrator):
        result = orchestrator.cancel_job("kj_nonexistent")
        assert result is False

    def test_cancel_already_completed_job(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\nThis is test content."}

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[]),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            _wait_for_job_done(repo, job_id)

        # 任务已完成，cancel 应返回 False
        result = orchestrator.cancel_job(job_id)
        assert result is False


class TestImportOrchestratorSourceStatusUpdate:
    """补充：验证 source 状态在导入过程中正确更新。"""

    def test_source_status_transitions_success(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\nThis is test content for source status."}
        item = _ok_item(content="source status ok")

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[item]),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "completed"
        # 成功有条目 → source=processed
        sources = repo.list_sources(package_id)
        assert sources[0]["status"] == "processed"
        # normalized_text 应非空
        assert sources[0]["normalized_text"] != ""
        # content_hash 应已更新
        assert sources[0]["content_hash"] != ""

    def test_empty_chunks_fail_source(self, orchestrator, db, repo, config):
        """chunk_source 返回 [] → job/source=failed, error=no_chunks_generated。"""
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\ncontent that will be chunked empty."}

        with patch(
            "app.knowledge.import_service.chunk_source",
            return_value=[],
        ), patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[_ok_item()]),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "failed"
        assert job["error_message"] == "no_chunks_generated"
        sources = repo.list_sources(package_id)
        assert sources[0]["status"] == "failed"
        assert sources[0]["error_message"] == "no_chunks_generated"
        # 不应进入 AI，source 应已 extracted 再失败
        assert sources[0]["normalized_text"] != ""

    def test_top_level_exception_fails_source(self, orchestrator, db, repo, config):
        """顶层异常路径同时更新 job 与 source 为 failed。"""
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\nThis is test content."}

        with patch(
            "app.knowledge.import_service.chunk_source",
            side_effect=RuntimeError("chunk boom"),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "failed"
        assert "chunk boom" in job["error_message"]
        sources = repo.list_sources(package_id)
        assert sources[0]["status"] == "failed"
        assert "chunk boom" in (sources[0].get("error_message") or "")


class TestImportOrchestratorValidationErrors:
    """校验错误可见：mock 返回非法 kind 的 items → chunk/job 错误文本含校验线索。"""

    def test_validation_errors_surface(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\nThis is test content."}
        # 构造非法 kind 的 item（title/content 为空也会被拒绝）
        bad_item = _ok_item(kind="invalid_kind", title="", content="")

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[bad_item]),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        # 校验全灭 → 0 items → job=failed
        assert job["status"] == "failed"
        assert job["generated_items"] == 0
        # error_message 含 validation 或校验相关线索
        assert "validation" in job["error_message"] or "item[" in job["error_message"]

        # chunk 的 error_message 也应有校验错误
        chunks = repo.list_chunks(source_id)
        assert chunks[0]["status"] == "completed"  # chunk 本身处理成功，只是校验有错误
        assert chunks[0]["error_message"]  # 非空


class TestImportOrchestratorWebpageWithMockItems:
    """T2: webpage payload + mock extract + mock 合法 items → items≥1, job=completed。"""

    def test_webpage_mock_items(self, orchestrator, db, repo, config):
        package_id, source_id = _create_package_and_source(
            db, repo, source_type="webpage"
        )
        payload = {"source_url": "https://example.com/test"}
        item = _ok_item(content="网页测试内容")

        with patch(
            "app.knowledge.import_service.extract_source",
            return_value=ExtractionResult(
                "Example page content for testing.",
                {"source_type": "webpage"},
            ),
        ), patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[item]),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="webpage",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "completed"
        assert job["generated_items"] >= 1
        result = repo.list_items(package_id=package_id)
        assert result["total"] >= 1


class TestImportOrchestratorCrossImportDedup:
    """Wave 4：跨导入 / 跨 source 去重。"""

    def test_reimport_same_content_no_double_items(
        self, orchestrator, db, repo, config
    ):
        """同一包第二次导入相同 content → 不新增 item，deduplicated_items>0。"""
        package_id, source_id_1 = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\nThis is test content for reimport."}
        item = _ok_item(content="跨导入去重内容唯一")

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[item]),
        ):
            job1 = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id_1,
                source_type="pasted_text",
                payload=payload,
            )
            _wait_for_job_done(repo, job1)

        assert repo.list_items(package_id=package_id)["total"] == 1

        # 第二 source + 再导入相同 item
        source2 = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="second source",
        )
        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[item]),
        ):
            job2 = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source2["id"],
                source_type="pasted_text",
                payload=payload,
            )
            done2 = _wait_for_job_done(repo, job2)

        assert done2["generated_items"] == 0
        assert done2["deduplicated_items"] >= 1
        assert repo.list_items(package_id=package_id)["total"] == 1

    def test_same_content_two_sources_deduped(
        self, orchestrator, db, repo, config
    ):
        """两个 source 各返回相同 content → 只存 1 条。"""
        package_id, source_id_1 = _create_package_and_source(db, repo)
        item = _ok_item(content="双 source 相同内容")
        payload = {"pasted_text": "# A\n\nContent for dual source."}

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[item]),
        ):
            j1 = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id_1,
                source_type="pasted_text",
                payload=payload,
            )
            _wait_for_job_done(repo, j1)

        source2 = repo.create_source(
            package_id=package_id,
            source_type="pasted_text",
            display_name="src2",
        )
        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[item]),
        ):
            j2 = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source2["id"],
                source_type="pasted_text",
                payload=payload,
            )
            _wait_for_job_done(repo, j2)

        assert repo.list_items(package_id=package_id)["total"] == 1

    def test_different_kind_same_text_keeps_both(
        self, orchestrator, db, repo, config
    ):
        """不同 kind 同 content 可并存。"""
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "# Test\n\nDual kind content."}
        items = [
            _ok_item(kind="fact", content="同文不同 kind"),
            _ok_item(kind="meme", content="同文不同 kind"),
        ]

        with patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=items),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
            )
            job = _wait_for_job_done(repo, job_id)

        assert job["status"] == "completed"
        assert job["generated_items"] == 2
        assert repo.list_items(package_id=package_id)["total"] == 2

    def test_document_kind_livestream_log_passed_to_chunk_source(
        self, orchestrator, db, repo, config
    ):
        """import 将 document_kind 传给 chunk_source。"""
        package_id, source_id = _create_package_and_source(db, repo)
        payload = {"pasted_text": "弹幕一行\n弹幕二行"}
        captured: dict = {}

        def _capture_chunk(source_type, text, content_kind="auto", document_kind="auto", metadata=None):
            captured["document_kind"] = document_kind
            captured["content_kind"] = content_kind
            from app.knowledge.chunker import chunk_source as real_chunk

            return real_chunk(
                source_type,
                text,
                content_kind=content_kind,
                document_kind=document_kind,
                metadata=metadata,
            )

        with patch(
            "app.knowledge.import_service.chunk_source",
            side_effect=_capture_chunk,
        ), patch(
            "app.knowledge.import_service.organize_chunk",
            return_value=_ok_result(items=[_ok_item()]),
        ):
            job_id = orchestrator.submit_import(
                config=config,
                package_id=package_id,
                source_id=source_id,
                source_type="pasted_text",
                payload=payload,
                document_kind="livestream_log",
                content_kind="auto",
            )
            _wait_for_job_done(repo, job_id)

        assert captured.get("document_kind") == "livestream_log"
