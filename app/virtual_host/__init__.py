"""与 Live2D 渲染运行时解耦的虚拟主播会话契约。"""

from app.virtual_host.contracts import (
    ActionDraft,
    BatchAcceptance,
    ConversationTurn,
    DanmuBatchCreated,
    EmotionDraft,
    HostPrompt,
    HostTurn,
    HostTurnResult,
    KnowledgeContextResult,
    KnowledgeSourceRef,
    MemoryEffect,
    SceneContext,
)
from app.virtual_host.knowledge import KnowledgeContextAdapter
from app.virtual_host.session import VirtualHostSession

__all__ = [
    "ActionDraft",
    "BatchAcceptance",
    "ConversationTurn",
    "DanmuBatchCreated",
    "EmotionDraft",
    "HostPrompt",
    "HostTurn",
    "HostTurnResult",
    "KnowledgeContextAdapter",
    "KnowledgeContextResult",
    "KnowledgeSourceRef",
    "MemoryEffect",
    "SceneContext",
    "VirtualHostSession",
]
