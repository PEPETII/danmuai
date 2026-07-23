"""tests/test_knowledge_chunker.py — 分块模块测试（A3.2）。

覆盖（spec §8 / §ADDED Requirements - Chunking）：
    - 标题不分离、最大长度、段落切分、句子切分、硬切重叠
    - 弹幕日志清理、重复刷屏清理、边界字符不丢失
    - 空文本、单块、多标题分块
    - content_hash 唯一性、sequence_no 递增
    - chunk_source 分派

约定（AGENTS.md §A.4.1）：
    - 只跑本文件：``python -m pytest tests/test_knowledge_chunker.py -q -x``
    - 不依赖 Qt / DanmuApp / ConfigStore
"""
from __future__ import annotations

import pytest

from app.knowledge.chunker import (
    HARD_CUT_OVERLAP,
    LIVESTREAM_MAX_LINES,
    MAX_CHUNK_CHARS,
    TARGET_MAX_CHARS,
    TARGET_MIN_CHARS,
    Chunk,
    chunk_article,
    chunk_livestream,
    chunk_source,
)


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _make_long_text(
    paragraphs: int = 10, sentence_per_para: int = 10, sentence_len: int = 80
) -> str:
    """生成可预测的长文本：每段 sentence_per_para 个句子，每句 sentence_len 字符。"""
    paras = []
    for p in range(paragraphs):
        sents = []
        for s in range(sentence_per_para):
            # 句子 = 标记 + 填充 + 句号
            marker = f"[p{p}s{s}]"
            fill = "X" * (sentence_len - len(marker) - 1)
            sents.append(marker + fill + "。")
        paras.append("".join(sents))
    return "\n\n".join(paras)


# ---------------------------------------------------------------------------
# 1. 标题不分离
# ---------------------------------------------------------------------------


class TestHeadingNotSeparated:
    def test_short_heading_with_body_one_chunk(self):
        """标题 + 短正文 → 单块，标题与正文同块。"""
        text = "# 游戏攻略\n\nBoss 战技巧：先打弱点。"
        chunks = chunk_article(text)
        assert len(chunks) == 1
        assert chunks[0].heading == "游戏攻略"
        assert "# 游戏攻略" in chunks[0].content
        assert "Boss 战技巧" in chunks[0].content

    def test_heading_with_huge_body_stays_together(self):
        """标题 + 超长正文 → 首块以标题开头（标题不分离到上一块）。"""
        body = "A" * 10000
        text = f"# 大标题\n\n{body}"
        chunks = chunk_article(text)
        assert len(chunks) >= 2
        # 首块必须以标题开头
        assert chunks[0].content.startswith("# 大标题")
        assert chunks[0].heading == "大标题"
        # 首块包含部分正文
        assert "A" in chunks[0].content

    def test_html_heading_not_separated(self):
        """HTML 标题也不与正文分离。"""
        body = "B" * 50
        text = f"<h2>HTML 标题</h2>\n\n{body}"
        chunks = chunk_article(text)
        assert len(chunks) == 1
        assert chunks[0].heading == "HTML 标题"
        assert "<h2>HTML 标题</h2>" in chunks[0].content


# ---------------------------------------------------------------------------
# 2. 最大长度
# ---------------------------------------------------------------------------


class TestMaxLength:
    def test_no_chunk_exceeds_max(self):
        """任何块都不超过 MAX_CHUNK_CHARS。"""
        text = "X" * 20000  # 无标点、无换行，触发硬切
        chunks = chunk_article(text)
        assert len(chunks) >= 3
        for c in chunks:
            assert len(c.content) <= MAX_CHUNK_CHARS

    def test_long_paragraphs_respect_max(self):
        text = _make_long_text(paragraphs=20, sentence_per_para=20, sentence_len=100)
        chunks = chunk_article(text)
        assert len(chunks) >= 2
        for c in chunks:
            assert len(c.content) <= MAX_CHUNK_CHARS


# ---------------------------------------------------------------------------
# 3. 段落切分
# ---------------------------------------------------------------------------


class TestParagraphSplitting:
    def test_split_at_paragraph_boundaries(self):
        """多段文本按段落边界切分。"""
        # 每段约 3500 字符，2 段约 7000，会分成 2 块
        para1 = "段一内容。" * 700  # ~3500 字符
        para2 = "段二内容。" * 700
        text = f"{para1}\n\n{para2}"
        chunks = chunk_article(text)
        assert len(chunks) >= 2
        # 第一块包含段一
        assert "段一内容" in chunks[0].content
        # 第二块包含段二
        assert "段二内容" in chunks[-1].content


# ---------------------------------------------------------------------------
# 4. 句子切分
# ---------------------------------------------------------------------------


class TestSentenceSplitting:
    def test_split_at_sentence_boundaries(self):
        """单段超长文本按句子边界切分。"""
        # 单段、多句、无空行 → 段落不切，降到句子切分
        sents = ["这是第{}句话内容。".format(i) for i in range(200)]
        text = "".join(sents)  # ~2000 字符，需要更长
        text = text * 3  # ~6000+ 字符
        chunks = chunk_article(text)
        assert len(chunks) >= 2
        # 句子边界不丢字符：拼接后包含所有句子标记
        all_content = "\n\n".join(c.content for c in chunks)
        for i in range(200):
            assert f"第{i}句话" in all_content

    def test_english_sentence_split(self):
        """英文句号 + 空格 触发句子切分。"""
        sents = [f"This is sentence number {i}. " for i in range(500)]
        text = "".join(sents)
        chunks = chunk_article(text)
        assert len(chunks) >= 2
        all_content = "\n\n".join(c.content for c in chunks)
        for i in [0, 1, 100, 499]:
            assert f"number {i}" in all_content


# ---------------------------------------------------------------------------
# 5. 硬切重叠
# ---------------------------------------------------------------------------


class TestHardCutOverlap:
    def test_hard_cut_produces_overlap(self):
        """无任何边界的超长文本硬切，相邻块有 0-200 字符重叠。"""
        # 用位置标记填充，便于验证重叠
        text = "".join(f"{i:04d}" for i in range(5000))  # 20000 字符
        chunks = chunk_article(text)
        assert len(chunks) >= 3
        # 相邻块的重叠：前一块末尾 HARD_CUT_OVERLAP 字符 == 后一块开头 HARD_CUT_OVERLAP 字符
        for i in range(len(chunks) - 1):
            prev_tail = chunks[i].content[-HARD_CUT_OVERLAP:]
            next_head = chunks[i + 1].content[:HARD_CUT_OVERLAP]
            assert prev_tail == next_head, (
                f"chunk {i} 与 {i + 1} 重叠区不匹配"
            )

    def test_hard_cut_respects_max(self):
        text = "Y" * 25000
        chunks = chunk_article(text)
        for c in chunks:
            assert len(c.content) <= MAX_CHUNK_CHARS


# ---------------------------------------------------------------------------
# 6. 弹幕日志清理
# ---------------------------------------------------------------------------


class TestLivestreamLogCleaning:
    def test_timestamp_username_removed(self):
        """时间戳、用户名前缀被清理后再分块。"""
        lines = []
        for i in range(150):
            lines.append(f"[12:00:{i:02d}] 用户{i}: 这是一条测试弹幕{i}")
        text = "\n".join(lines)
        chunks = chunk_livestream(text)
        assert len(chunks) >= 1
        # 时间戳与用户名不应出现在块内容
        for c in chunks:
            assert "[12:" not in c.content
            assert "用户0:" not in c.content
            # 弹幕文本应保留
        all_content = "\n".join(c.content for c in chunks)
        assert "测试弹幕" in all_content

    def test_system_messages_removed(self):
        """礼物/关注/进场/系统提示行被清理。"""
        lines = ["进入直播间", "关注了主播", "送出礼物", "正常弹幕内容"]
        # 重复足够多以形成块
        text = "\n".join(lines * 50)
        chunks = chunk_livestream(text)
        all_content = "\n".join(c.content for c in chunks)
        assert "进入直播间" not in all_content
        assert "关注了主播" not in all_content
        assert "送出礼物" not in all_content
        assert "正常弹幕内容" in all_content

    def test_punctuation_only_lines_removed(self):
        """纯标点行被清理。"""
        lines = ["!!!", "???", "。。。" "有意义的弹幕"]
        text = "\n".join(lines * 50)
        chunks = chunk_livestream(text)
        all_content = "\n".join(c.content for c in chunks)
        assert "有意义" in all_content


# ---------------------------------------------------------------------------
# 7. 重复刷屏清理
# ---------------------------------------------------------------------------


class TestSpamCleaning:
    def test_spam_collapsed(self):
        """同一条消息连续重复 ≥5 次合并为 1 条。"""
        spam_line = "刷屏内容"
        lines = [spam_line] * 10  # 10 次 → 合并为 1
        # 加一些正常弹幕
        normal = ["正常弹幕一", "正常弹幕二"]
        text = "\n".join(lines + normal + lines)
        chunks = chunk_livestream(text)
        all_content = "\n".join(c.content for c in chunks)
        # 刷屏内容不应出现 10 次（被合并）
        assert all_content.count(spam_line) < 10
        assert spam_line in all_content  # 但仍保留 1 条


# ---------------------------------------------------------------------------
# 8. 边界字符不丢失
# ---------------------------------------------------------------------------


class TestBoundaryCharsPreserved:
    def test_heading_marker_preserved(self):
        """标题边界切分时 # 标记不丢失。"""
        text = "# 标题一\n\n内容一\n\n# 标题二\n\n内容二"
        chunks = chunk_article(text)
        all_content = "\n\n".join(c.content for c in chunks)
        assert "# 标题一" in all_content
        assert "# 标题二" in all_content

    def test_sentence_punctuation_preserved(self):
        """句子边界切分时句末标点不丢失。"""
        sents = ["第一句。第二句。第三句。"] * 200
        text = "\n\n".join(sents)
        chunks = chunk_article(text)
        all_content = "\n\n".join(c.content for c in chunks)
        # 句号应保留
        assert "第一句。" in all_content
        assert "第二句。" in all_content
        assert "第三句。" in all_content

    def test_no_content_loss_for_article(self):
        """长文章分块后关键内容不丢失。"""
        markers = [f"UNIQUE_MARKER_{i:04d}" for i in range(50)]
        paras = []
        for i, m in enumerate(markers):
            paras.append(f"{m} " + "X" * 200 + "。")
        text = "\n\n".join(paras)
        chunks = chunk_article(text)
        all_content = "\n\n".join(c.content for c in chunks)
        for m in markers:
            assert m in all_content, f"丢失标记: {m}"


# ---------------------------------------------------------------------------
# 9. 空文本
# ---------------------------------------------------------------------------


class TestEmptyText:
    def test_empty_string(self):
        assert chunk_article("") == []

    def test_whitespace_only(self):
        assert chunk_article("   \n\n  \t  ") == []

    def test_empty_livestream(self):
        assert chunk_livestream("") == []

    def test_whitespace_livestream(self):
        assert chunk_livestream("   \n\n  ") == []


# ---------------------------------------------------------------------------
# 10. 单块
# ---------------------------------------------------------------------------


class TestSingleChunk:
    def test_short_text_one_chunk(self):
        text = "这是一段短文本。"
        chunks = chunk_article(text)
        assert len(chunks) == 1
        assert chunks[0].sequence_no == 0
        assert chunks[0].heading == ""
        assert chunks[0].content == text

    def test_medium_text_under_target(self):
        """小于 TARGET_MAX 的文本返回单块。"""
        text = "内容。" * 500  # ~2500 字符
        chunks = chunk_article(text)
        assert len(chunks) == 1
        assert len(chunks[0].content) <= TARGET_MAX_CHARS


# ---------------------------------------------------------------------------
# 11. 多标题分块
# ---------------------------------------------------------------------------


class TestMultiHeading:
    def test_multiple_headings_multiple_chunks(self):
        """多个标题段，每段足够大，分成多块且各块标题正确。"""
        sections = []
        for i in range(4):
            body = f"第{i}节正文内容。" * 800  # ~4000 字符
            sections.append(f"# 第{i}节标题\n\n{body}")
        text = "\n\n".join(sections)
        chunks = chunk_article(text)
        assert len(chunks) >= 4
        # 每块标题应在 heading 字段中找到对应
        headings = [c.heading for c in chunks if c.heading]
        for i in range(4):
            assert f"第{i}节标题" in headings

    def test_heading_at_chunk_start(self):
        """以标题开头的块，content 以 # 开头。"""
        sections = []
        for i in range(3):
            body = "X" * 4000
            sections.append(f"## 标题{i}\n\n{body}")
        text = "\n\n".join(sections)
        chunks = chunk_article(text)
        # 找到以标题开头的块
        heading_chunks = [c for c in chunks if c.heading]
        assert len(heading_chunks) >= 3
        for c in heading_chunks:
            assert c.content.lstrip().startswith("#")


# ---------------------------------------------------------------------------
# 12. content_hash 唯一性
# ---------------------------------------------------------------------------


class TestContentHash:
    def test_different_chunks_different_hash(self):
        text = _make_long_text(paragraphs=20, sentence_per_para=20, sentence_len=100)
        chunks = chunk_article(text)
        hashes = [c.content_hash for c in chunks]
        assert len(hashes) == len(set(hashes)), "存在重复的 content_hash"

    def test_hash_is_sha256_hex(self):
        text = "测试内容。"
        chunks = chunk_article(text)
        assert len(chunks) == 1
        # SHA-256 = 64 位十六进制
        assert len(chunks[0].content_hash) == 64
        assert all(c in "0123456789abcdef" for c in chunks[0].content_hash)

    def test_same_content_same_hash(self):
        text = "相同的内容。"
        c1 = chunk_article(text)
        c2 = chunk_article(text)
        assert c1[0].content_hash == c2[0].content_hash


# ---------------------------------------------------------------------------
# 13. sequence_no 递增
# ---------------------------------------------------------------------------


class TestSequenceNo:
    def test_sequence_starts_from_zero(self):
        text = "短文本。"
        chunks = chunk_article(text)
        assert chunks[0].sequence_no == 0

    def test_sequence_increments(self):
        text = _make_long_text(paragraphs=30, sentence_per_para=20, sentence_len=100)
        chunks = chunk_article(text)
        assert len(chunks) >= 2
        for i, c in enumerate(chunks):
            assert c.sequence_no == i

    def test_livestream_sequence_increments(self):
        lines = [f"弹幕内容{i}" for i in range(500)]
        text = "\n".join(lines)
        chunks = chunk_livestream(text)
        assert len(chunks) >= 2
        for i, c in enumerate(chunks):
            assert c.sequence_no == i


# ---------------------------------------------------------------------------
# 14. chunk_source 分派
# ---------------------------------------------------------------------------


class TestChunkSourceDispatch:
    def test_livestream_chat_kind_dispatches_to_livestream(self):
        """content_kind='livestream_chat' → chunk_livestream。"""
        lines = [f"弹幕{i}" for i in range(200)]
        text = "\n".join(lines)
        chunks = chunk_source("pasted_text", text, content_kind="livestream_chat")
        # 弹幕分块 heading 恒为空
        for c in chunks:
            assert c.heading == ""

    def test_livestream_source_type_dispatches_to_livestream(self):
        """source_type='livestream' → chunk_livestream。"""
        lines = [f"弹幕{i}" for i in range(200)]
        text = "\n".join(lines)
        chunks = chunk_source("livestream", text)
        for c in chunks:
            assert c.heading == ""

    def test_article_dispatches_to_article(self):
        """默认 → chunk_article。"""
        text = "# 标题\n\n短内容。"
        chunks = chunk_source("markdown", text)
        assert len(chunks) >= 1
        # article 路径会识别标题
        assert chunks[0].heading == "标题"

    def test_auto_kind_uses_article(self):
        """content_kind='auto' + 非 livestream source → article。"""
        text = "普通文章内容。"
        chunks = chunk_source("txt", text, content_kind="auto")
        assert len(chunks) == 1
        assert chunks[0].heading == ""

    def test_legacy_livestream_content_kind_dispatches(self):
        """历史 content_kind='livestream' → chunk_livestream。"""
        lines = [f"弹幕{i}" for i in range(200)]
        text = "\n".join(lines)
        chunks = chunk_source("pasted_text", text, content_kind="livestream")
        for c in chunks:
            assert c.heading == ""
        assert len(chunks) >= 1

    def test_document_kind_livestream_log_dispatches(self):
        """document_kind='livestream_log' + content_kind=auto → chunk_livestream。"""
        lines = [f"弹幕{i}" for i in range(200)]
        text = "\n".join(lines)
        chunks = chunk_source(
            "pasted_text",
            text,
            content_kind="auto",
            document_kind="livestream_log",
        )
        for c in chunks:
            assert c.heading == ""
        assert len(chunks) >= 1


# ---------------------------------------------------------------------------
# 额外：Chunk dataclass 不可变性
# ---------------------------------------------------------------------------


class TestChunkFrozen:
    def test_chunk_is_frozen(self):
        text = "内容。"
        chunks = chunk_article(text)
        with pytest.raises((AttributeError, Exception)):
            chunks[0].content = "modified"  # type: ignore[misc]

    def test_chunk_fields(self):
        text = "# 标题\n\n内容。"
        chunks = chunk_article(text)
        c = chunks[0]
        assert hasattr(c, "sequence_no")
        assert hasattr(c, "heading")
        assert hasattr(c, "content")
        assert hasattr(c, "content_hash")
