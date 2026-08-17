"""现有知识检索能力到虚拟主播上下文的窄适配层。"""

from __future__ import annotations

import logging
from typing import Any

from app.knowledge.runtime_service import build_knowledge_scene_context
from app.virtual_host.contracts import (
    DanmuBatchCreated,
    KnowledgeContextResult,
    KnowledgeSourceRef,
    SceneContext,
)

logger = logging.getLogger(__name__)


class KnowledgeContextAdapter:
    """复用 ``KnowledgeRuntimeService`` 或其 ``KnowledgeRetriever``。

    适配层只取检索结果的有限 Prompt 片段和来源标识，不读取或拼接整个知识库。
    当 runtime 暴露 retriever 时直接使用现有 ``retrieve``，以便区分无命中和
    异常；只有测试替身/窄服务没有 retriever 时才走 runtime 的公开注入方法。
    """

    def __init__(
        self,
        runtime_service: Any | None = None,
        *,
        retriever: Any | None = None,
        max_items: int = 4,
        max_chars: int = 360,
    ) -> None:
        self.runtime_service = runtime_service
        self.retriever = retriever or getattr(runtime_service, "retriever", None)
        self.max_items = max(1, min(int(max_items), 4))
        self.max_chars = max(1, min(int(max_chars), 600))

    def retrieve(
        self,
        *,
        turn_id: int,
        input_text: str,
        scene_context: SceneContext | None = None,
        recent_batches: tuple[DanmuBatchCreated, ...] = (),
        mic_text: str = "",
        live_topic: str = "",
        now: float | None = None,
    ) -> KnowledgeContextResult:
        """按预算检索；异常、无命中和不可用都返回可观察状态。"""

        scene = scene_context
        if scene is not None and not scene.is_fresh(now=now):
            scene = None
        recent_lines = [line for batch in recent_batches for line in batch.lines]
        source_screenshot_id = scene.screenshot_id if scene is not None else None
        source_generation = scene.scene_generation if scene is not None else 0
        input_text = str(input_text or "").strip()
        query_brief = " ".join(
            part for part in (
                scene.summary if scene is not None else "",
                input_text,
            ) if part
        )
        query = build_knowledge_scene_context(
            live_topic=live_topic,
            recent_danmu=recent_lines,
            mic_text=mic_text,
            extra_brief=query_brief,
            extra_keywords=list(scene.keywords) if scene is not None else [],
            request_round=turn_id,
            screenshot_id=_safe_int(source_screenshot_id),
            scene_generation=source_generation,
            now=now,
        )
        if not query.has_semantic_query and not str(input_text or "").strip():
            return KnowledgeContextResult(
                status="no_hit",
                diagnostic="empty_query",
            )

        runtime = self.runtime_service
        note_generation = getattr(runtime, "note_scene_generation", None)
        if callable(note_generation):
            try:
                note_generation(source_generation)
            except Exception as exc:  # boundary: diagnostics only
                logger.debug("virtual host note_scene_generation failed: %r", exc)

        try:
            if self.retriever is not None:
                raw_result = self.retriever.retrieve(
                    scene_brief=query.scene_brief or input_text[:200],
                    keywords=list(query.keywords),
                    scene_tags=list(query.scene_tags),
                    max_items=self.max_items,
                    max_chars=self.max_chars,
                    request_round=turn_id,
                    screenshot_id=_safe_int(source_screenshot_id),
                )
            else:
                build_injection = getattr(runtime, "build_visual_prompt_injection", None)
                if not callable(build_injection):
                    return KnowledgeContextResult(
                        status="unavailable",
                        diagnostic="knowledge_runtime_unavailable",
                    )
                raw_result = build_injection(
                    scene_brief=query.scene_brief or input_text[:200],
                    keywords=list(query.keywords),
                    request_round=turn_id,
                    screenshot_id=_safe_int(source_screenshot_id),
                    scene_tags=list(query.scene_tags),
                )
        except Exception as exc:
            logger.warning("virtual host knowledge retrieval failed: %r", exc)
            return KnowledgeContextResult(status="error", diagnostic="retrieval_exception")

        if raw_result is None:
            return KnowledgeContextResult(status="no_hit", diagnostic="no_matching_items")

        prompt_text = str(getattr(raw_result, "prompt_text", "") or "")[: self.max_chars].rstrip()
        items = list(getattr(raw_result, "items", []) or [])[: self.max_items]
        hit_count = int(getattr(raw_result, "hit_count", 0) or 0)
        sources, item_ids, public_ids = self._source_refs(items)
        if not sources:
            item_ids = _safe_int_tuple(getattr(raw_result, "item_ids", ()) or ())
            public_ids = tuple(
                str(value).strip()
                for value in (getattr(raw_result, "public_ids", ()) or ())
                if str(value).strip()
            )[: self.max_items]
            sources = [
                KnowledgeSourceRef(
                    item_id=item_id,
                    public_id=public_id,
                    source=(
                        f"knowledge_item:{item_id}"
                        if item_id is not None
                        else (public_id or "knowledge_item")
                    ),
                )
                for item_id, public_id in _zip_ids(item_ids, public_ids)
            ]
        if not prompt_text or not sources:
            return KnowledgeContextResult(
                status="no_hit",
                hit_count=hit_count,
                diagnostic="no_budgeted_items",
            )
        return KnowledgeContextResult(
            status="hit",
            prompt_text=prompt_text,
            sources=tuple(sources),
            item_ids=tuple(item_ids),
            public_ids=tuple(public_ids),
            hit_count=hit_count,
            diagnostic="retrieved",
        )

    @staticmethod
    def _source_refs(items: list[Any]) -> tuple[list[KnowledgeSourceRef], list[int], list[str]]:
        sources: list[KnowledgeSourceRef] = []
        item_ids: list[int] = []
        public_ids: list[str] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            raw_id = item.get("id")
            try:
                item_id = int(raw_id) if raw_id is not None else None
            except (TypeError, ValueError):
                item_id = None
            public_id = str(item.get("public_id") or "").strip()
            source = str(
                item.get("source_url")
                or item.get("source")
                or item.get("title")
                or (f"knowledge_item:{item_id}" if item_id is not None else "knowledge_item")
            ).strip()
            if item_id is not None:
                item_ids.append(item_id)
            if public_id:
                public_ids.append(public_id)
            sources.append(
                KnowledgeSourceRef(item_id=item_id, public_id=public_id, source=source)
            )
        return sources, item_ids, public_ids


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_int_tuple(values: Any) -> tuple[int, ...]:
    result: list[int] = []
    for value in values:
        try:
            result.append(int(value))
        except (TypeError, ValueError):
            continue
    return tuple(result)


def _zip_ids(item_ids: tuple[int, ...], public_ids: tuple[str, ...]):
    count = max(len(item_ids), len(public_ids))
    for index in range(count):
        yield (
            item_ids[index] if index < len(item_ids) else None,
            public_ids[index] if index < len(public_ids) else "",
        )
