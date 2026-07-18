"""Pydantic 校验 + 字段裁剪 + evidence 来源校验（知识包功能 A5.1）。

提供两个公开函数：

- :func:`validate_batch`：宽松校验（裁剪超长字段、夹紧 confidence、清空伪造 evidence），
  返回 ``(valid_items_as_dict, errors)``。
- :func:`validate_batch_strict`：严格校验整个 batch 对象，失败抛 ``ValidationError``。

设计原则（spec §ADDED Requirements / Validation and Deduplication）：

- 字段超长时**裁剪**而非拒绝（spec §10 允许裁剪）；
- ``confidence`` 越界时**夹紧**到 [0, 1] 而非拒绝；
- ``evidence`` 不在原始 chunk 中时**清空**（防 Prompt Injection 伪造来源）；
- ``kind`` 非法时**拒绝**（加入 errors）；
- 必填字段缺失或空时**拒绝**（title/content 不能为空，Pydantic ``min_length=1``）。

不修改 ``app/knowledge/models.py``（A1 已实现）；不引入新依赖。
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from app.knowledge.models import KnowledgeBatchResponse, KnowledgeItemCandidate

logger = logging.getLogger(__name__)

__all__ = ["validate_batch", "validate_batch_strict"]

# ---------------------------------------------------------------------------
# 字段约束常量（与 models.py 对齐；这里用于预处理裁剪）
# ---------------------------------------------------------------------------

_MAX_TITLE_LEN = 40
_MAX_CONTENT_LEN = 500
_MAX_EXAMPLES_COUNT = 5
_MAX_EXAMPLE_LEN = 30
_MAX_TRIGGERS_COUNT = 10
_MAX_TONES_COUNT = 5
_MAX_SCOPES_COUNT = 8
_MAX_ENTITIES_COUNT = 8
_MAX_EVIDENCE_LEN = 500


# ---------------------------------------------------------------------------
# 预处理辅助：裁剪 / 夹紧 / 清空
# ---------------------------------------------------------------------------


def _clamp_confidence(value: Any) -> Any:
    """将数值型 confidence 夹紧到 [0, 1]；非数值原样返回（交由 Pydantic 拒绝）。"""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return value
    if f < 0.0:
        return 0.0
    if f > 1.0:
        return 1.0
    return f


def _truncate_str(value: Any, max_len: int) -> Any:
    """字符串裁剪到 ``max_len``；非字符串原样返回（交由 Pydantic 处理）。"""
    if isinstance(value, str):
        return value[:max_len]
    return value


def _truncate_list(value: Any, max_count: int) -> Any:
    """列表截断到 ``max_count``；非列表原样返回（交由 Pydantic 处理）。"""
    if isinstance(value, list):
        return value[:max_count]
    return value


def _truncate_examples(value: Any) -> Any:
    """examples 截断到 5 条 + 每条裁剪到 30 字。"""
    if not isinstance(value, list):
        return value
    result: list[Any] = []
    for ex in value[:_MAX_EXAMPLES_COUNT]:
        if isinstance(ex, str):
            result.append(ex[:_MAX_EXAMPLE_LEN])
        else:
            result.append(ex)
    return result


def _sanitize_evidence(value: Any, chunk_content: str) -> str:
    """evidence 来源校验。

    - 非字符串 → ``""``
    - 空字符串 → ``""``
    - 不在 ``chunk_content`` 中 → ``""``（防伪造来源）
    - 在 chunk 中但超长 → 裁剪到 160 字
    """
    if not isinstance(value, str):
        return ""
    if not value:
        return ""
    if value not in chunk_content:
        return ""
    return value[:_MAX_EVIDENCE_LEN]


def _coerce_to_list(value: Any) -> Any:
    """将标量值包为单元素列表；已经是列表的原样返回；非字符串/数值/None 原样返回。

    AI 有时返回 ``"neutral"`` 而非 ``["neutral"]``，此函数容错处理。
    """
    if isinstance(value, list):
        return value
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, (int, float, bool)):
        return [value]
    return value


def _preprocess_item(item: Any, chunk_content: str) -> dict[str, Any]:
    """预处理单条 item：裁剪超长字段、夹紧 confidence、清空伪造 evidence。

    不做 kind 枚举校验（交由 Pydantic）；不删除任何字段；不添加默认字段。
    """
    if not isinstance(item, dict):
        # 非 dict 无法预处理，返回空 dict 让 Pydantic 拒绝
        return {}
    processed: dict[str, Any] = {}
    for key, val in item.items():
        if key == "title":
            processed[key] = _truncate_str(val, _MAX_TITLE_LEN)
        elif key == "content":
            processed[key] = _truncate_str(val, _MAX_CONTENT_LEN)
        elif key == "evidence":
            processed[key] = _sanitize_evidence(val, chunk_content)
        elif key == "examples":
            processed[key] = _truncate_examples(_coerce_to_list(val))
        elif key == "triggers":
            processed[key] = _truncate_list(_coerce_to_list(val), _MAX_TRIGGERS_COUNT)
        elif key == "tones":
            processed[key] = _truncate_list(_coerce_to_list(val), _MAX_TONES_COUNT)
        elif key == "scopes":
            processed[key] = _truncate_list(_coerce_to_list(val), _MAX_SCOPES_COUNT)
        elif key == "entities":
            processed[key] = _truncate_list(_coerce_to_list(val), _MAX_ENTITIES_COUNT)
        elif key == "confidence":
            processed[key] = _clamp_confidence(val)
        else:
            processed[key] = val
    return processed


# ---------------------------------------------------------------------------
# 公开 API
# ---------------------------------------------------------------------------


def validate_batch(
    parsed: dict, chunk_content: str
) -> tuple[list[dict], list[str]]:
    """宽松校验 AI 整理输出，返回 ``(valid_items_as_dict, errors)``。

    策略（spec §ADDED Requirements / Validation and Deduplication）：

        - ``kind`` 非法 → 拒绝（加入 errors）
        - ``title`` / ``content`` 超长 → 裁剪
        - ``examples`` 超过 5 条 → 截断；每条超 30 字 → 裁剪
        - ``triggers`` / ``tones`` / ``scopes`` / ``entities`` 超过上限 → 截断
        - ``confidence`` 越界 → 夹紧到 [0, 1]
        - ``evidence`` 不在 ``chunk_content`` 中 → 清空
        - ``evidence`` 超长 → 裁剪到 160 字
        - 必填字段缺失或空 → 拒绝（Pydantic ``min_length=1``）

    Args:
        parsed: AI 返回的解析后 dict，预期含 ``document_kind`` 与 ``items``。
        chunk_content: 当前 chunk 的原始文本，用于 evidence 来源校验。

    Returns:
        ``(valid_items, errors)``：``valid_items`` 是 dict 列表（已通过 Pydantic
        校验并经 ``model_dump()`` 转换）；``errors`` 是字符串列表，每条含 item
        index 与错误信息。
    """
    valid_items: list[dict] = []
    errors: list[str] = []

    if not isinstance(parsed, dict):
        return valid_items, ["parsed is not a dict"]

    items = parsed.get("items", [])
    if not isinstance(items, list):
        return valid_items, [f"items is not a list: {type(items).__name__}"]

    for idx, raw_item in enumerate(items):
        if not isinstance(raw_item, dict):
            errors.append(f"item[{idx}]: not a dict ({type(raw_item).__name__})")
            continue

        processed = _preprocess_item(raw_item, chunk_content)
        try:
            candidate = KnowledgeItemCandidate(**processed)
        except ValidationError as exc:
            errors.append(f"item[{idx}]: {exc}")
            continue
        except TypeError as exc:
            # 理论上 _preprocess_item 已保证是 dict，但防御性捕获
            errors.append(f"item[{idx}]: {exc}")
            continue

        valid_items.append(candidate.model_dump())

    return valid_items, errors


def validate_batch_strict(parsed: dict) -> KnowledgeBatchResponse:
    """严格校验整个 batch 对象，失败抛 ``ValidationError``。

    与 :func:`validate_batch` 的差别：

        - 不裁剪、不夹紧、不清空 evidence；
        - 任何字段约束违反直接抛 ``ValidationError``；
        - 用于 AI 输出二次校验（A4 ai_organizer 内可选用）。

    Args:
        parsed: AI 返回的解析后 dict，预期含 ``document_kind`` 与 ``items``。

    Returns:
        :class:`KnowledgeBatchResponse` 实例。

    Raises:
        pydantic.ValidationError: 任何字段约束违反。
        TypeError: ``parsed`` 不是 dict。
    """
    if not isinstance(parsed, dict):
        raise TypeError(f"parsed must be dict, got {type(parsed).__name__}")
    return KnowledgeBatchResponse(**parsed)
