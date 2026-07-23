"""知识条目去重：精确哈希 + 同 kind 近似（知识包功能 A5.2）。

提供 :class:`KnowledgeDeduplicator` 类：

- 精确哈希去重：``sha256(content.strip())`` 命中已有 hash → 丢弃；
- 归一化全文相等：``content.strip().lower()`` 命中 → 丢弃；
- 同 kind 近似去重：复用 ``app.danmu_engine_dedup.texts_are_similar``，threshold=0.85；
- 不同 kind 之间**不**做近似比较；
- **不**直接使用运行时 ``danmu_engine_dedup`` 的 deque（spec §10 第 4 条）；
- 可经 :meth:`seed_existing` 预载包内已有条目，实现**跨导入**去重。

设计原则（spec §ADDED Requirements / Validation and Deduplication）：

- 去重在本地完成，不额外调用 AI；
- 仅在同一 ``(package_id, kind)`` 内做近似比较；
- ``normalized_content = content.strip().lower()`` 用于近似比较。
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any

from app.danmu_engine_dedup import texts_are_similar

logger = logging.getLogger(__name__)

__all__ = ["KnowledgeDeduplicator"]


class KnowledgeDeduplicator:
    """知识条目去重器（单次 import 任务内存态，可预载包内已有条目）。

    维护内存中 ``dict[(package_id, kind), list[(content_hash, normalized_content)]]``。
    精确哈希命中 → 丢弃；归一化相等 → 丢弃；同 kind 近似命中 → 丢弃；不同 kind 不互相比较。

    线程安全说明：
        本类**不**加锁。调用方（``ImportOrchestrator``）在单线程
        ``ThreadPoolExecutor(max_workers=1)`` 中串行调用 ``dedupe``，
        不存在并发访问。如需多线程使用，调用方须自行加锁。

    Attributes:
        _package_id: 当前知识包 ID。
        _threshold: 近似去重阈值（默认 0.85）。
        _seen: 按 ``(package_id, kind)`` 分组的已保留条目列表，
            每个元素是 ``(content_hash, normalized_content)`` 二元组。
    """

    def __init__(self, package_id: int, threshold: float = 0.85) -> None:
        self._package_id = package_id
        self._threshold = threshold
        self._seen: dict[tuple[int, str], list[tuple[str, str]]] = {}

    def reset(self) -> None:
        """清空状态（多包导入时切换）。"""
        self._seen.clear()

    def seed_existing(self, rows: list[dict[str, Any]] | None) -> int:
        """预载包内已有条目，使后续 ``dedupe`` 能跨导入去重。

        每行至少提供 ``kind``，以及 ``content`` 或
        ``(content_hash, normalized_content)``。

        Args:
            rows: ``list_item_dedupe_keys`` 等返回的 dict 列表。

        Returns:
            实际写入 ``_seen`` 的条数。
        """
        if not rows:
            return 0
        seeded = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            kind = row.get("kind")
            if not isinstance(kind, str) or not kind:
                continue
            content = row.get("content")
            if isinstance(content, str):
                self._mark_seen(kind, content)
                seeded += 1
                continue
            content_hash = row.get("content_hash")
            normalized = row.get("normalized_content")
            if not isinstance(content_hash, str) or not content_hash:
                continue
            if not isinstance(normalized, str):
                normalized = ""
            else:
                normalized = normalized.strip().lower()
            key = (self._package_id, kind)
            seen_list = self._seen.get(key)
            if seen_list is None:
                self._seen[key] = [(content_hash, normalized)]
            else:
                seen_list.append((content_hash, normalized))
            seeded += 1
        return seeded

    def _content_hash(self, content: str) -> str:
        """精确哈希：``sha256(content.strip())``。"""
        return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()

    def _is_duplicate(self, kind: str, content: str) -> bool:
        """检查是否与已保留条目重复（精确哈希 + 归一化相等 + 同 kind 近似）。

        Args:
            kind: 条目类型（fact/style_example/reaction_pattern/meme）。
            content: 条目内容（原始大小写）。

        Returns:
            True 表示重复（应丢弃）；False 表示新条目（应保留）。
        """
        key = (self._package_id, kind)
        seen_list = self._seen.get(key)
        if not seen_list:
            return False

        content_hash = self._content_hash(content)
        normalized = content.strip().lower()

        for prev_hash, prev_normalized in seen_list:
            if prev_hash == content_hash:
                return True
            if normalized and prev_normalized and normalized == prev_normalized:
                return True
            if texts_are_similar(normalized, prev_normalized, self._threshold):
                return True
        return False

    def _mark_seen(self, kind: str, content: str) -> None:
        """将条目加入已保留集合。"""
        key = (self._package_id, kind)
        content_hash = self._content_hash(content)
        normalized = content.strip().lower()
        seen_list = self._seen.get(key)
        if seen_list is None:
            self._seen[key] = [(content_hash, normalized)]
        else:
            seen_list.append((content_hash, normalized))

    def dedupe(
        self, candidates: list[dict]
    ) -> tuple[list[dict], int]:
        """对候选条目列表去重，返回 ``(kept_items, dedup_count)``。

        Args:
            candidates: validator 已校验的 item dict 列表，每个含 ``kind``、
                ``content`` 等字段。

        Returns:
            ``(kept_items, dedup_count)``：``kept_items`` 是未重复的 dict 列表
            （保持原始顺序）；``dedup_count`` 是被去重的条目数。
        """
        kept: list[dict] = []
        dedup_count = 0

        for candidate in candidates:
            kind = candidate.get("kind")
            content = candidate.get("content", "")

            if not isinstance(kind, str) or not isinstance(content, str):
                # 缺少 kind/content 的条目直接保留（validator 应已过滤）
                kept.append(candidate)
                continue

            if self._is_duplicate(kind, content):
                dedup_count += 1
                continue

            self._mark_seen(kind, content)
            kept.append(candidate)

        return kept, dedup_count
