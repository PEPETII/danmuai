"""知识包子包：本地知识库 + AI 整理 + 实时检索注入。

模块组成（spec §C）：
    database       — SQLite 连接 + PRAGMA + 非可重入写锁 + FTS5 探测
    migrations     — schema_meta + run_pending + @register 迁移机制
    repository     — packages/sources/chunks/items/jobs CRUD（*_for_db 风格）
    models         — Pydantic 模型 + KnowledgeContextSnapshot dataclass
    source_extractors / normalizer / chunker  — A2/A3 任务实现
    ai_organizer   — A4 任务实现（duck-typed worker，复用当前 AI Provider）
    validator / deduplicator — A5 任务实现
    retriever / prompt_builder — A7 任务实现
    runtime_service — B2 任务实现（KnowledgeRuntimeService）
    import_service — A6 任务实现（ImportOrchestrator）

公开符号（spec §A1.1）：``KnowledgeDatabase``、``KnowledgeRepository``、
``KnowledgeItemCandidate``、``KnowledgeBatchResponse``、
``KnowledgeContextSnapshot``、``KnowledgeRuntimeService``、``ImportOrchestrator``。

后两个（``KnowledgeRuntimeService`` / ``ImportOrchestrator``）暂未实现，
用 ``try/except ImportError`` 占位，避免阻塞本子包导入。
"""
from __future__ import annotations

from app.knowledge.database import KNOWLEDGE_DB_PATH, KnowledgeDatabase
from app.knowledge.models import (
    KnowledgeBatchResponse,
    KnowledgeContextSnapshot,
    KnowledgeItemCandidate,
)
from app.knowledge.repository import KnowledgeRepository

# 以下模块将在后续任务（A6 / B2）实现；lazy import 避免 ImportError 阻塞本子包导入。
try:
    from app.knowledge.runtime_service import KnowledgeRuntimeService  # noqa: F401
except ImportError:  # pragma: no cover — 占位，后续任务实现后自动可用
    KnowledgeRuntimeService = None  # type: ignore[assignment,misc]

try:
    from app.knowledge.import_service import ImportOrchestrator  # noqa: F401
except ImportError:  # pragma: no cover — 占位，后续任务实现后自动可用
    ImportOrchestrator = None  # type: ignore[assignment,misc]


__all__ = [
    "KnowledgeDatabase",
    "KnowledgeRepository",
    "KnowledgeItemCandidate",
    "KnowledgeBatchResponse",
    "KnowledgeContextSnapshot",
    "KnowledgeRuntimeService",
    "ImportOrchestrator",
    "KNOWLEDGE_DB_PATH",
]
