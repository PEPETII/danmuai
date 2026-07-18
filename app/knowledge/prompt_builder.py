"""知识包提示词构建（spec §13.5）。

按 ``kind`` 分段输出固定字符预算的提示词片段；空命中返回空字符串。

分段规则（spec §13.5）：
    - ``fact`` → "事实知识"
    - ``reaction_pattern`` → "反应方式"
    - ``style_example`` / ``meme`` → "表达参考"

每条形如 ``- {title}：{content}``；``style_example`` / ``meme`` 若有 examples
则追加 ``（例：例1 / 例2）``。

安全约束（spec §13.5）：
    - 不输出原始资料长段；
    - 不输出 ``evidence`` 字段；
    - 总长 ≤ ``max_chars``（默认 360），硬上限 600；
    - 超限时停止追加；
    - 空分组不输出标题；
    - items 为空返回 ``""``。

调用方：``KnowledgeRetriever``。
"""
from __future__ import annotations

from typing import Any

# 固定前言（spec §13.5 安全要求 + 注入约束）
_PREAMBLE = (
    "以下内容是本地资料检索结果，仅作参考。"
    "请基于当前截图与上一轮弹幕选择是否使用；"
    "与截图冲突时以截图为准；不允许照搬长段原文。"
)

# 硬上限（spec §6.3 / §13.5）
_HARD_MAX_CHARS = 600

# 分组顺序（固定）
_GROUP_ORDER: tuple[str, ...] = ("fact", "reaction_pattern", "expressive")

# kind → 分组桶
_KIND_TO_BUCKET: dict[str, str] = {
    "fact": "fact",
    "reaction_pattern": "reaction_pattern",
    "style_example": "expressive",
    "meme": "expressive",
}

# 分组桶 → 标题
_BUCKET_TITLE: dict[str, str] = {
    "fact": "事实知识",
    "reaction_pattern": "反应方式",
    "expressive": "表达参考",
}


def build_prompt_text(
    items: list[dict[str, Any]], max_chars: int = 360
) -> str:
    """按 spec §13.5 格式构建提示词片段。

    Args:
        items: 命中条目列表（dict 至少含 kind/title/content；可选 examples）。
        max_chars: 字符预算（默认 360；硬上限 600）。

    Returns:
        格式化后的提示词片段；空命中或预算耗尽返回 ``""``。
    """
    if not items:
        return ""
    budget = max(1, min(int(max_chars), _HARD_MAX_CHARS))

    # 分组并格式化每条
    sections = _build_sections(items)
    if not sections:
        return ""

    # 前言必须能放下，否则返回空
    if len(_PREAMBLE) >= budget:
        return ""

    result = _PREAMBLE
    items_added = 0

    for bucket in _GROUP_ORDER:
        title = _BUCKET_TITLE.get(bucket)
        lines = sections.get(bucket)
        if not title or not lines:
            continue
        header = f"\n\n## {title}\n"
        # 尝试加 header + 至少一条
        added_in_section = 0
        section_text = header
        for line in lines:
            line_nl = line + "\n"
            if len(result) + len(section_text) + len(line_nl) > budget:
                break
            section_text += line_nl
            added_in_section += 1
        if added_in_section == 0:
            # 这一组一条都放不下，跳过（不输出 header）
            continue
        result += section_text
        items_added += added_in_section

    if items_added == 0:
        return ""
    return result.rstrip()


def _build_sections(
    items: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """按 kind 分组并格式化每条为 ``- {title}：{content}`` 行。"""
    groups: dict[str, list[str]] = {b: [] for b in _GROUP_ORDER}
    for item in items:
        kind = str(item.get("kind", ""))
        bucket = _KIND_TO_BUCKET.get(kind)
        if bucket is None:
            continue
        line = _format_item_line(item, kind)
        if line:
            groups[bucket].append(line)
    return groups


def _format_item_line(item: dict[str, Any], kind: str) -> str:
    """格式化单条 item：``- {title}：{content}`` + 可选 ``（例：...）``。"""
    title = str(item.get("title", "")).strip()
    content = str(item.get("content", "")).strip()
    if not title or not content:
        return ""
    line = f"- {title}：{content}"
    if kind in ("style_example", "meme"):
        raw_examples = item.get("examples")
        if isinstance(raw_examples, list):
            examples = [str(e).strip() for e in raw_examples if str(e).strip()]
            if examples:
                line += "（例：" + " / ".join(examples) + "）"
    return line


__all__ = ["build_prompt_text"]
