"""知识包 Pydantic 模型与运行时快照 dataclass。

字段约束严格对齐 ``docs/DanmuAI_知识包功能_实现说明(1).md`` §4.2 与
``.trae/specs/FEATURE-KNOWLEDGE-PACKAGE-001/spec.md`` §ADDED Requirements。

本模块只定义数据形状；持久化逻辑见 ``app.knowledge.repository``，
AI 整理与校验见后续任务（A4/A5）的 ``ai_organizer`` / ``validator``。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, model_validator

# 知识条目 kind 枚举（spec §4.1）
KnowledgeItemKind = Literal["fact", "style_example", "reaction_pattern", "meme"]

# 单条 example 最多 30 字（spec §4.2）
_ExampleStr = Annotated[str, Field(max_length=30)]


class KnowledgeItemCandidate(BaseModel):
    """AI 整理输出的单条知识条目候选（未持久化、未去重）。

    字段约束（spec §4.2）：
        kind: 只允许 fact / style_example / reaction_pattern / meme
        title: 1~40 字
        content: 1~160 字
        examples: 最多 5 条，每条最多 30 字
        triggers: 最多 10 个
        tones: 最多 5 个
        scopes: 最多 8 个
        entities: 最多 8 个
        confidence: 0~1
        evidence: 可选，必须来自当前原始分块，最多 160 字
    """

    kind: KnowledgeItemKind
    title: str = Field(..., min_length=1, max_length=40)
    content: str = Field(..., min_length=1, max_length=500)
    examples: list[_ExampleStr] = Field(default_factory=list, max_length=5)
    triggers: list[str] = Field(default_factory=list, max_length=10)
    tones: list[str] = Field(default_factory=list, max_length=5)
    scopes: list[str] = Field(default_factory=list, max_length=8)
    entities: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: str = Field(default="", max_length=500)

    model_config = {"extra": "ignore"}


class KnowledgeBatchResponse(BaseModel):
    """AI 整理单批输出信封（spec §4.2 示例）。"""

    document_kind: str = ""
    items: list[KnowledgeItemCandidate] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# API DTO（用于 Web API；A8 再使用，本任务先建类型）
# ---------------------------------------------------------------------------


class PackageCreatePayload(BaseModel):
    """POST /api/knowledge/packages 请求体。"""

    name: str = Field(..., min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    content_kind: str = "auto"
    scope_mode: str = "global"
    scope_tags: list[str] = Field(default_factory=list, max_length=20)
    enabled: bool = True
    priority: int = 0

    model_config = {"extra": "ignore"}


class PackageUpdatePayload(BaseModel):
    """PATCH/PUT /api/knowledge/packages/{id} 请求体（部分更新）。"""

    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    content_kind: str | None = None
    scope_mode: str | None = None
    scope_tags: list[str] | None = Field(default=None, max_length=20)
    enabled: bool | None = None
    priority: int | None = None

    model_config = {"extra": "ignore"}


class ImportPayload(BaseModel):
    """POST /api/knowledge/packages/{id}/imports 请求体。

    source_type:
        pasted_text — pasted_text 字段必填
        txt / markdown — content_base64 字段必填（File.arrayBuffer → Base64）
        webpage — source_url 字段必填
    """

    source_type: Literal["pasted_text", "txt", "markdown", "webpage"]
    display_name: str = ""
    source_url: str | None = None
    pasted_text: str | None = None
    content_base64: str | None = None
    document_kind: str = "auto"

    model_config = {"extra": "ignore"}

    @model_validator(mode="after")
    def validate_source_fields(self) -> "ImportPayload":
        """跨字段必填校验（失败时 ValueError 消息为稳定 error code）。"""
        st = self.source_type
        if st == "pasted_text":
            if not (self.pasted_text or "").strip():
                raise ValueError("missing_pasted_text")
        elif st in ("txt", "markdown"):
            b64 = (self.content_base64 or "").strip()
            if not b64:
                raise ValueError("missing_content_base64")
            # 粗估解码后字节：base64 约 4/3 膨胀；超过 10 MiB 原始上限则拒绝
            # （与 source_extractors.MAX_RESPONSE_BYTES 同量级）
            max_b64_len = (10 * 1024 * 1024 * 4) // 3 + 8
            if len(b64) > max_b64_len:
                raise ValueError("source_too_large")
        elif st == "webpage":
            url = (self.source_url or "").strip()
            if not url:
                raise ValueError("missing_source_url")
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.netloc:
                raise ValueError("invalid_source_url")
        return self


class ItemUpdatePayload(BaseModel):
    """PATCH /api/knowledge/items/{id} 请求体（部分更新）。"""

    title: str | None = Field(default=None, min_length=1, max_length=40)
    content: str | None = Field(default=None, min_length=1, max_length=500)
    examples: list[str] | None = Field(default=None, max_length=5)
    triggers: list[str] | None = Field(default=None, max_length=10)
    tones: list[str] | None = Field(default=None, max_length=5)
    scopes: list[str] | None = Field(default=None, max_length=8)
    entities: list[str] | None = Field(default=None, max_length=8)
    enabled: bool | None = None
    priority: int | None = None

    model_config = {"extra": "ignore"}


class RetrievalPreviewPayload(BaseModel):
    """POST /api/knowledge/retrieval/preview 请求体。"""

    scene_brief: str = ""
    keywords: list[str] = Field(default_factory=list, max_length=20)
    max_items: int | None = Field(default=None, ge=1, le=10)
    max_chars: int | None = Field(default=None, ge=1, le=600)

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# 运行时场景上下文与注入结果
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KnowledgeSceneContext:
    """当前轮检索可用的真实场景语义（不可变）。

    来源优先级由 ``build_knowledge_scene_context`` 组装：
    live_topic → 最近弹幕关键词 → 麦文本 → 昵称/附加 brief；
    全空时不得用 ``round=… screenshot=…`` 占位查询。
    """

    scene_brief: str
    keywords: tuple[str, ...]
    scene_tags: tuple[str, ...] = ()
    source_request_round: int = 0
    source_screenshot_id: int = 0
    scene_generation: int = 0
    updated_at: float = 0.0

    @property
    def has_semantic_query(self) -> bool:
        return bool((self.scene_brief or "").strip() or self.keywords)


@dataclass(frozen=True)
class KnowledgeInjectionResult:
    """程序侧注入结果（方案 A：不依赖模型 knowledge_used 才更新使用记录）。

    use_count / last_used_at 语义：被注入次数（注入成功即 mark）。
    """

    prompt_text: str
    item_ids: tuple[int, ...]
    public_ids: tuple[str, ...]
    request_round: int
    screenshot_id: int
    hit_count: int
    retrieval_ms: int
    scene_brief: str = ""
    keywords: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnowledgeContextSnapshot:
    """运行时检索快照（不可变；主线程只读；兼容历史测试与诊断）。

    字段：
        prompt_text: 已构建的提示词片段（空字符串表示无知识命中）。
        scene_brief: 触发该检索的场景简述（用于诊断与防陈旧覆盖）。
        keywords: 触发该检索的关键词元组。
        item_ids: 命中条目的内部 ID 元组（用于 mark_items_used）。
        source_request_round: 触发该检索时的 request_round（防陈旧覆盖）。
        source_screenshot_id: 触发该检索时的 screenshot_id。
        updated_at: 快照生成时间（time.time()，秒）。
    """

    prompt_text: str
    scene_brief: str
    keywords: tuple[str, ...]
    item_ids: tuple[int, ...]
    source_request_round: int
    source_screenshot_id: int
    updated_at: float


__all__ = [
    "KnowledgeItemKind",
    "KnowledgeItemCandidate",
    "KnowledgeBatchResponse",
    "PackageCreatePayload",
    "PackageUpdatePayload",
    "ImportPayload",
    "ItemUpdatePayload",
    "RetrievalPreviewPayload",
    "KnowledgeSceneContext",
    "KnowledgeInjectionResult",
    "KnowledgeContextSnapshot",
]
