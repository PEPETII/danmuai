"""知识包诊断快照测试（Phase B4）。

覆盖 ``DiagnosticSnapshotBuilder._knowledge_summary()``：
1. 降级模式：未挂载 knowledge_runtime → ``enabled=False`` + 全 0/空字段；
2. 挂载 fake runtime → ``enabled=True`` + counts 来自 fake repo；
3. fake repo 抛异常 → 不传播，counts 落到 0；
4. ``build_diagnostic_report`` 文本含 ``[knowledge]`` 段。

约定（AGENTS.md §A.4.1）：
    - 只跑本文件：``python -m pytest tests/test_knowledge_diagnostics.py -q -x``
    - 复用 ``tests/diagnostics_helpers.py:make_diagnostic_app`` 构造可调用
      ``DiagnosticSnapshotBuilder(app).build()`` 的最小 app（绑定
      ``get_request_scheduler`` / ``api_schedule_block_reason`` 等 façade 方法）；
    - 用 ``app.__dict__["knowledge_runtime"] = ...`` 挂载 fake runtime（**勿**用
      ``setattr``，QObject 未走 ``__init__`` 会触发 ``RuntimeError``）。
"""
from __future__ import annotations

from app.application.diagnostic_snapshot import (
    DiagnosticSnapshotBuilder,
    build_diagnostic_report,
)
from tests.diagnostics_helpers import make_diagnostic_app


# ---------------------------------------------------------------------------
# fakes
# ---------------------------------------------------------------------------


class _FakeRetriever:
    """Fake KnowledgeRetriever：暴露 _fts_backend / _last_injected_contents。"""

    _fts_backend = "trigram"
    _last_injected_contents = ["a", "b"]


class _FakeRepo:
    """Fake KnowledgeRepository：list_packages / list_items 返回固定值。"""

    def list_packages(self, *, enabled_only: bool = False):
        if enabled_only:
            return [{"id": 10}]
        return [{"id": 1}, {"id": 2}]

    def list_items(self, *, page: int = 1, page_size: int = 50, **kwargs):
        if kwargs.get("enabled") is True:
            return {"items": [], "page": page, "page_size": page_size, "total": 3}
        return {"items": [], "page": page, "page_size": page_size, "total": 7}


class _FakeRepoExceptional:
    """Fake repo：list_packages / list_items 抛异常。"""

    def list_packages(self, *, enabled_only: bool = False):
        raise RuntimeError("simulated repo failure")

    def list_items(self, *, page: int = 1, page_size: int = 50, **kwargs):
        raise RuntimeError("simulated repo failure")


class _FakeRuntime:
    """Fake KnowledgeRuntimeService。"""

    def __init__(self, repo):
        self.retriever = _FakeRetriever()
        self.repository = repo


# ---------------------------------------------------------------------------
# tests
# ---------------------------------------------------------------------------


def test_knowledge_summary_degraded_when_no_runtime():
    """未挂载 knowledge_runtime → enabled=False + 全 0/空字段。"""
    app = make_diagnostic_app()
    # 显式确认 knowledge_runtime 未挂载
    assert "knowledge_runtime" not in app.__dict__

    snapshot = DiagnosticSnapshotBuilder(app).build()

    knowledge = snapshot["knowledge"]
    assert knowledge == {
        "enabled": False,
        "fts_backend": "",
        "packages_count": 0,
        "enabled_packages_count": 0,
        "items_count": 0,
        "enabled_items_count": 0,
        "last_injected_count": 0,
    }


def test_knowledge_summary_with_runtime_mounted():
    """挂载 fake runtime → enabled=True + counts 取自 fake repo。"""
    app = make_diagnostic_app()
    # 用 __dict__ 直接挂载（QObject 未走 __init__ 时 setattr 会 RuntimeError）
    app.__dict__["knowledge_runtime"] = _FakeRuntime(_FakeRepo())

    snapshot = DiagnosticSnapshotBuilder(app).build()

    knowledge = snapshot["knowledge"]
    assert knowledge["enabled"] is True
    assert knowledge["fts_backend"] == "trigram"
    # _FakeRepo.list_packages() 返回 2 个；list_packages(enabled_only=True) 返回 1 个
    assert knowledge["packages_count"] == 2
    assert knowledge["enabled_packages_count"] == 1
    # _FakeRepo.list_items(page=1, page_size=1) total=7；enabled=True 时 total=3
    assert knowledge["items_count"] == 7
    assert knowledge["enabled_items_count"] == 3
    # _FakeRetriever._last_injected_contents 长度 2
    assert knowledge["last_injected_count"] == 2


def test_knowledge_summary_exception_isolated():
    """fake repo 抛异常 → enabled=True 但计数为 0，不抛异常。"""
    app = make_diagnostic_app()
    app.__dict__["knowledge_runtime"] = _FakeRuntime(_FakeRepoExceptional())

    # build() 不应抛异常
    snapshot = DiagnosticSnapshotBuilder(app).build()

    knowledge = snapshot["knowledge"]
    # runtime 已挂载 + retriever 仍存在 → enabled=True
    assert knowledge["enabled"] is True
    # retriever 字段不受 repo 异常影响
    assert knowledge["fts_backend"] == "trigram"
    assert knowledge["last_injected_count"] == 2
    # repo 调用失败 → 计数保持 0（不抛异常）
    assert knowledge["packages_count"] == 0
    assert knowledge["enabled_packages_count"] == 0
    assert knowledge["items_count"] == 0
    assert knowledge["enabled_items_count"] == 0


def test_diagnostic_report_contains_knowledge_section():
    """build_diagnostic_report(snapshot) 文本含 [knowledge] 段及全部字段。"""
    app = make_diagnostic_app()
    app.__dict__["knowledge_runtime"] = _FakeRuntime(_FakeRepo())

    snapshot = DiagnosticSnapshotBuilder(app).build()
    report = build_diagnostic_report(snapshot)

    # [knowledge] 段存在于 [undisplayed] 与 [boundary_guard] 之间
    assert "[undisplayed]" in report
    assert "[knowledge]" in report
    assert "[boundary_guard]" in report
    undisplayed_idx = report.index("[undisplayed]")
    knowledge_idx = report.index("[knowledge]")
    boundary_idx = report.index("[boundary_guard]")
    assert undisplayed_idx < knowledge_idx < boundary_idx

    # 关键字段渲染
    assert "enabled: True" in report
    assert "fts_backend: trigram" in report
    assert "packages_count: 2" in report
    assert "enabled_packages_count: 1" in report
    assert "items_count: 7" in report
    assert "enabled_items_count: 3" in report
    assert "last_injected_count: 2" in report
