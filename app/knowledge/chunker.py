"""确定性分块模块（知识包功能 A3.1）。

提供 3 个纯函数（无 IO、无副作用）：

- :func:`chunk_article`：普通文章分块（标题边界 → 段落 → 句子 → 硬切四级降级）。
- :func:`chunk_livestream`：直播弹幕分块（先调 ``clean_livestream_log`` 清理，
  再按 100-250 行 + 3000-6000 字符双约束分组）。
- :func:`chunk_source`：统一入口，按 ``content_kind`` / ``source_type`` 分派。

设计原则（spec §8 / §ADDED Requirements - Chunking）：

- 分块在本地完成，不调用 AI；
- 标题不与正文分离（标题作为下一块开头，与后续正文一起）；
- 目标块大小 3000-6000 字符，硬上限 7000；
- 硬切时使用 0-200 字符重叠（取前一块末尾 0-200 字符作为下一块开头）；
- 直播弹幕日志先清理结构，按行数+字符数双约束分组。
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.knowledge.normalizer import clean_livestream_log

__all__ = ["Chunk", "chunk_article", "chunk_livestream", "chunk_source"]


# ---------------------------------------------------------------------------
# 常量（spec §8.1 / §8.2）
# ---------------------------------------------------------------------------

# 普通文章分块
TARGET_MIN_CHARS = 3000
TARGET_MAX_CHARS = 6000
MAX_CHUNK_CHARS = 7000
HARD_CUT_OVERLAP = 200

# 直播弹幕分块
LIVESTREAM_MIN_LINES = 100
LIVESTREAM_MAX_LINES = 250

# 标题边界识别
_MD_HEADING_START_RE = re.compile(r"^#{1,6}\s", re.MULTILINE)
_HTML_HEADING_START_RE = re.compile(r"<h[1-6][\s>]", re.IGNORECASE)

# 段落边界：2+ 换行（中间可有空白）
_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")


# ---------------------------------------------------------------------------
# Chunk dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Chunk:
    """不可变分块。

    Attributes:
        sequence_no: 块序号，从 0 开始递增。
        heading: 块内首个标题文本（无 ``#`` 前缀）；若块不以标题开头则为空字符串。
        content: 块完整文本（含标题行）。
        content_hash: ``content`` 的 SHA-256 十六进制摘要。
    """

    sequence_no: int
    heading: str
    content: str
    content_hash: str


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _compute_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _extract_first_heading(text: str) -> str:
    """若 ``text`` 以 Markdown/HTML 标题开头，返回标题文本（无 ``#`` 前缀）。

    否则返回空字符串。仅在块首匹配，避免误识别块内出现的 ``#`` 字符。
    """
    stripped = text.lstrip()
    if not stripped:
        return ""

    # Markdown: 首行 ^#+\s+...
    first_line = stripped.split("\n", 1)[0]
    m = re.match(r"^#{1,6}\s+(.+?)\s*$", first_line)
    if m:
        return m.group(1).strip()

    # HTML: 开头 <hN>...</hN>
    m = re.match(r"^<h[1-6][^>]*>(.*?)</h[1-6]>", stripped, re.IGNORECASE | re.DOTALL)
    if m:
        inner = m.group(1).strip()
        # 去除内嵌 HTML 标签
        inner = re.sub(r"<[^>]+>", "", inner).strip()
        return inner

    return ""


def _find_heading_positions(text: str) -> list[int]:
    """返回所有标题边界位置（字符偏移）。"""
    positions: list[int] = []
    for m in _MD_HEADING_START_RE.finditer(text):
        positions.append(m.start())
    for m in _HTML_HEADING_START_RE.finditer(text):
        positions.append(m.start())
    return sorted(set(positions))


def _split_by_headings(text: str) -> list[str]:
    """按标题边界切分；每个返回段以标题开头（首段可能不含标题）。"""
    positions = _find_heading_positions(text)
    if not positions:
        return [text] if text else []

    sections: list[str] = []
    # 首个标题之前的内容（preamble）
    if positions[0] > 0:
        preamble = text[: positions[0]].strip()
        if preamble:
            sections.append(preamble)
    # 各标题段
    for i, start in enumerate(positions):
        end = positions[i + 1] if i + 1 < len(positions) else len(text)
        section = text[start:end].strip()
        if section:
            sections.append(section)
    return sections


def _split_sentences(text: str) -> list[str]:
    """按句子边界切分（``。！？`` / ``. `` / ``! `` / ``? `` / ``\\n``）。

    保留标点与所属句子；返回的句子拼接后等于原文本（无字符丢失）。
    """
    sentences: list[str] = []
    current: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        current.append(ch)
        if ch in "。！？":
            sentences.append("".join(current))
            current = []
            i += 1
            continue
        if ch in ".!?":
            # 英文句末标点：后跟空白/行尾/换行 才视为句子结束
            if i + 1 >= n or text[i + 1] in " \t\n\r":
                sentences.append("".join(current))
                current = []
                i += 1
                continue
        if ch == "\n":
            sentences.append("".join(current))
            current = []
            i += 1
            continue
        i += 1
    if current:
        sentences.append("".join(current))
    return [s for s in sentences if s]


def _hard_cut(text: str) -> list[str]:
    """字符级硬切，每段 ≤ ``MAX_CHUNK_CHARS``，重叠 ``HARD_CUT_OVERLAP`` 字符。

    下一块开头 = 前一块末尾 0-200 字符 + 新内容。
    """
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    parts: list[str] = []
    pos = 0
    n = len(text)
    while pos < n:
        end = min(pos + MAX_CHUNK_CHARS, n)
        parts.append(text[pos:end])
        if end >= n:
            break
        # 下一块从前一块末尾 overlap 字符处开始
        next_pos = end - HARD_CUT_OVERLAP
        if next_pos <= pos:  # 安全保证：必须前进
            next_pos = pos + 1
        pos = next_pos
    return parts


def _split_large_paragraph(para: str) -> list[str]:
    """对超大段落按句子切分；句子仍超 ``MAX_CHUNK_CHARS`` 时硬切。"""
    if len(para) <= TARGET_MAX_CHARS:
        return [para]
    sentences = _split_sentences(para)
    parts: list[str] = []
    current = ""
    for sent in sentences:
        if len(sent) > MAX_CHUNK_CHARS:
            # 先冲刷当前累积
            if current:
                parts.append(current)
                current = ""
            parts.extend(_hard_cut(sent))
        elif not current:
            current = sent
        elif len(current) + len(sent) > TARGET_MAX_CHARS:
            parts.append(current)
            current = sent
        else:
            current += sent
    if current:
        parts.append(current)
    return parts


def _split_large_body(body: str) -> list[str]:
    """对正文（无标题）按段落 → 句子 → 硬切降级切分。"""
    if not body:
        return []
    if len(body) <= TARGET_MAX_CHARS:
        return [body]

    paragraphs = _PARAGRAPH_SPLIT_RE.split(body)
    parts: list[str] = []
    current = ""
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if len(para) > TARGET_MAX_CHARS:
            if current:
                parts.append(current)
                current = ""
            parts.extend(_split_large_paragraph(para))
        elif not current:
            current = para
        elif len(current) + len(para) + 2 > TARGET_MAX_CHARS:
            parts.append(current)
            current = para
        else:
            current += "\n\n" + para
    if current:
        parts.append(current)
    return parts


def _split_large_section(section: str) -> list[str]:
    """对超大 section（标题段）按段落 → 句子 → 硬切降级切分。

    标题不与正文分离：标题行保留在首段开头。
    """
    if len(section) <= TARGET_MAX_CHARS:
        return [section]

    # 分离标题行与正文
    heading_line = ""
    body_start = 0
    md_match = re.match(r"^(#{1,6}\s+.+?)\n", section)
    if md_match:
        heading_line = md_match.group(1)
        body_start = md_match.end()
    else:
        html_match = re.match(
            r"^(<h[1-6][^>]*>.*?</h[1-6]>)\s*\n?", section, re.IGNORECASE | re.DOTALL
        )
        if html_match:
            heading_line = html_match.group(1)
            body_start = html_match.end()

    body = section[body_start:].strip()
    body_parts = _split_large_body(body)

    if heading_line:
        if body_parts:
            body_parts[0] = heading_line + "\n\n" + body_parts[0]
            # 安全检查：若首段超限，硬切（标题仍保留在首段开头）
            if len(body_parts[0]) > MAX_CHUNK_CHARS:
                hard_parts = _hard_cut(body_parts[0])
                body_parts = hard_parts + body_parts[1:]
        else:
            body_parts = [heading_line]

    return body_parts if body_parts else ([section] if section else [])


# ---------------------------------------------------------------------------
# chunk_article
# ---------------------------------------------------------------------------


def chunk_article(text: str, metadata: dict | None = None) -> list[Chunk]:
    """普通文章分块（四级降级：标题 → 段落 → 句子 → 硬切）。

    Args:
        text: 已提取并清洗的文本。空字符串返回 ``[]``。
        metadata: 可选元数据（当前实现未使用，预留扩展）。

    Returns:
        ``Chunk`` 列表，``sequence_no`` 从 0 递增。
    """
    if not text or not text.strip():
        return []

    # 输入应已 normalize，但为防御性再 strip 一次
    text = text.strip()
    if not text:
        return []

    # Step 1: 按标题边界切分
    sections = _split_by_headings(text)

    # Step 2: 对超大 section 降级切分
    parts: list[str] = []
    for section in sections:
        parts.extend(_split_large_section(section))

    # Step 3: 贪心合并 parts 至目标 3000-6000 字符
    # 规则：
    #   - 以标题开头的 part 始终开启新块（保证 heading 字段可正确识别）；
    #   - 若当前累积 < TARGET_MIN 且合并后不超 MAX_CHUNK_CHARS，允许超出 TARGET_MAX 合并；
    #   - 否则合并后超出 TARGET_MAX 时冲刷。
    chunk_contents: list[str] = []
    current = ""
    for part in parts:
        if not current:
            current = part
            continue
        part_has_heading = bool(_extract_first_heading(part))
        combined_len = len(current) + len(part) + 2
        if part_has_heading:
            # 标题开头的 part 始终开启新块（标题不分离到上一块末尾）
            chunk_contents.append(current)
            current = part
        elif len(current) < TARGET_MIN_CHARS and combined_len <= MAX_CHUNK_CHARS:
            # 当前过小，合并以接近目标下限
            current += "\n\n" + part
        elif combined_len > TARGET_MAX_CHARS:
            # 超出目标上限，冲刷
            chunk_contents.append(current)
            current = part
        else:
            current += "\n\n" + part
    if current:
        chunk_contents.append(current)

    # Step 4: 构建 Chunk 对象
    result: list[Chunk] = []
    for i, content in enumerate(chunk_contents):
        heading = _extract_first_heading(content)
        result.append(
            Chunk(
                sequence_no=i,
                heading=heading,
                content=content,
                content_hash=_compute_hash(content),
            )
        )
    return result


# ---------------------------------------------------------------------------
# chunk_livestream
# ---------------------------------------------------------------------------


def chunk_livestream(text: str, metadata: dict | None = None) -> list[Chunk]:
    """直播弹幕分块。

    先调 :func:`clean_livestream_log` 清理结构，再按
    100-250 行 + 3000-6000 字符双约束分组。

    Args:
        text: 原始直播弹幕日志文本。空字符串返回 ``[]``。
        metadata: 可选元数据（当前实现未使用）。

    Returns:
        ``Chunk`` 列表，``heading`` 恒为空字符串（弹幕无标题概念）。
    """
    if not text:
        return []
    cleaned = clean_livestream_log(text)
    if not cleaned:
        return []

    lines = [ln.strip() for ln in cleaned.split("\n") if ln.strip()]
    if not lines:
        return []

    chunk_contents: list[str] = []
    current_lines: list[str] = []
    current_chars = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for "\n"
        # 触达上限必须冲刷：250 行或 6000 字符
        if current_lines and (
            len(current_lines) >= LIVESTREAM_MAX_LINES
            or current_chars + line_len > TARGET_MAX_CHARS
        ):
            chunk_contents.append("\n".join(current_lines))
            current_lines = []
            current_chars = 0
        current_lines.append(line)
        current_chars += line_len

    if current_lines:
        chunk_contents.append("\n".join(current_lines))

    result: list[Chunk] = []
    for i, content in enumerate(chunk_contents):
        result.append(
            Chunk(
                sequence_no=i,
                heading="",
                content=content,
                content_hash=_compute_hash(content),
            )
        )
    return result


# ---------------------------------------------------------------------------
# chunk_source
# ---------------------------------------------------------------------------


def chunk_source(
    source_type: str,
    normalized_text: str,
    content_kind: str = "auto",
    document_kind: str = "auto",
    metadata: dict | None = None,
) -> list[Chunk]:
    """统一分块入口。

    分派规则（任一命中即走直播分块）：

    - ``content_kind`` 为 ``livestream`` / ``livestream_chat``（含历史别名）；
    - ``source_type == "livestream"``；
    - ``document_kind`` 为 ``livestream_log`` / ``livestream_chat``。
    - 其他 → :func:`chunk_article`

    Args:
        source_type: 来源类型（如 ``"pasted_text"`` / ``"txt"`` / ``"markdown"``
            / ``"webpage"`` / ``"livestream"``）。
        normalized_text: 已提取并清洗的文本。
        content_kind: 内容类型（``"auto"`` / ``"article"`` / ``"livestream_chat"``
            / 历史别名 ``"livestream"``）。
        document_kind: 文档类型（``"auto"`` / ``"article"`` / ``"livestream_log"`` 等）。
        metadata: 可选元数据。

    Returns:
        ``Chunk`` 列表。
    """
    kind = str(content_kind or "auto").strip().lower()
    doc_kind = str(document_kind or "auto").strip().lower()
    src = str(source_type or "").strip().lower()
    is_livestream = (
        kind in ("livestream", "livestream_chat")
        or src == "livestream"
        or doc_kind in ("livestream_log", "livestream_chat")
    )
    if is_livestream:
        return chunk_livestream(normalized_text, metadata)
    return chunk_article(normalized_text, metadata)
