"""tests/test_knowledge_deduplicator.py — 去重器测试（A5.2 / A5.3）。

覆盖（spec §ADDED Requirements / Validation and Deduplication + 用户任务描述）：
    - 完全重复（同 content）：dedup_count=1，保留 1 条
    - 轻微改写（threshold=0.85 时相似度 >0.85）：dedup_count=1，保留 1 条
    - 含义相近但不应合并（相似度 <0.85）：保留 2 条
    - 相同梗不同短句：保留 2 条
    - 不同事实但共享词汇：保留 2 条
    - 不同 kind 内容相似：保留 2 条
    - 多个 kind 混合：4 种 kind 各 2 条不重复 → 保留 8 条
    - reset 后状态清空
    - 空 candidates：返回 ([], 0)
    - 跨 package_id 不去重

约定（AGENTS.md §A.4.1）：
    - 只跑本文件：``python -m pytest tests/test_knowledge_deduplicator.py -q -x``
    - 不依赖 Qt / DanmuApp / ConfigStore / 数据库
"""
from __future__ import annotations

from app.knowledge.deduplicator import KnowledgeDeduplicator


# ---------------------------------------------------------------------------
# 辅助：构造 item dict（validator 已校验后的形态）
# ---------------------------------------------------------------------------


def _make_item(kind: str, content: str, **overrides) -> dict:
    """构造一个已通过 validator 校验形态的 item dict。"""
    item = {
        "kind": kind,
        "title": f"{kind}_title",
        "content": content,
        "examples": [],
        "triggers": [],
        "tones": [],
        "scopes": [],
        "entities": [],
        "confidence": 0.9,
        "evidence": "",
    }
    item.update(overrides)
    return item


# ---------------------------------------------------------------------------
# 精确哈希去重
# ---------------------------------------------------------------------------


class TestExactHashDedup:
    """精确哈希去重：同 content → 丢弃。"""

    def test_exact_duplicate_deduped(self) -> None:
        """完全重复（同 content）→ dedup_count=1，保留 1 条。"""
        dd = KnowledgeDeduplicator(package_id=1)
        candidates = [
            _make_item("fact", "葛瑞克二阶段会喷火"),
            _make_item("fact", "葛瑞克二阶段会喷火"),  # 完全相同
        ]
        kept, dedup_count = dd.dedupe(candidates)

        assert len(kept) == 1
        assert dedup_count == 1
        assert kept[0]["content"] == "葛瑞克二阶段会喷火"

    def test_exact_duplicate_with_whitespace_difference_deduped(self) -> None:
        """content 仅首尾空白不同 → 精确哈希一致（strip）→ 去重。"""
        dd = KnowledgeDeduplicator(package_id=1)
        candidates = [
            _make_item("fact", "葛瑞克会喷火"),
            _make_item("fact", "  葛瑞克会喷火  "),  # strip 后相同
        ]
        kept, dedup_count = dd.dedupe(candidates)

        assert len(kept) == 1
        assert dedup_count == 1

    def test_different_content_not_deduped(self) -> None:
        """不同 content → 保留 2 条。"""
        dd = KnowledgeDeduplicator(package_id=1)
        candidates = [
            _make_item("fact", "葛瑞克会喷火"),
            _make_item("fact", "玛尔基特会投掷匕首"),
        ]
        kept, dedup_count = dd.dedupe(candidates)

        assert len(kept) == 2
        assert dedup_count == 0


# ---------------------------------------------------------------------------
# 同 kind 近似去重
# ---------------------------------------------------------------------------


class TestSimilarDedup:
    """同 kind 近似去重：texts_are_similar(threshold=0.85) 返回 True → 丢弃。"""

    def test_slight_rewrite_deduped(self) -> None:
        """轻微改写（相似度 >0.85）→ dedup_count=1，保留 1 条。

        content1="主播操作失误了" (7 字)
        content2="主播又操作失误了" (8 字)
        Levenshtein.ratio = (7+8-1)/(7+8) = 14/15 ≈ 0.933 > 0.85 → 去重
        """
        dd = KnowledgeDeduplicator(package_id=1, threshold=0.85)
        candidates = [
            _make_item("fact", "主播操作失误了"),
            _make_item("fact", "主播又操作失误了"),
        ]
        kept, dedup_count = dd.dedupe(candidates)

        assert len(kept) == 1
        assert dedup_count == 1
        assert kept[0]["content"] == "主播操作失误了"

    def test_similar_meaning_not_merged(self) -> None:
        """含义相近但不应合并（相似度 <0.85）→ 保留 2 条。

        content1="今天天气很好" (6 字)
        content2="主播操作失误了" (7 字)
        完全不同字符 → 相似度 ≈ 0 < 0.85 → 保留
        """
        dd = KnowledgeDeduplicator(package_id=1, threshold=0.85)
        candidates = [
            _make_item("fact", "今天天气很好"),
            _make_item("fact", "主播操作失误了"),
        ]
        kept, dedup_count = dd.dedupe(candidates)

        assert len(kept) == 2
        assert dedup_count == 0

    def test_same_meme_different_phrases_not_deduped(self) -> None:
        """相同梗不同短句 → 保留 2 条（短句相似度低）。

        content1="又开始了" (4 字)
        content2="经典再现" (4 字)
        完全不同 → 相似度 = 0.5 < 0.85 → 保留
        """
        dd = KnowledgeDeduplicator(package_id=1, threshold=0.85)
        candidates = [
            _make_item("meme", "又开始了"),
            _make_item("meme", "经典再现"),
        ]
        kept, dedup_count = dd.dedupe(candidates)

        assert len(kept) == 2
        assert dedup_count == 0

    def test_different_facts_shared_vocab_not_deduped(self) -> None:
        """不同事实但共享词汇 → 保留 2 条。

        content1="艾尔登法环是 ARPG"
        content2="艾尔登法环的葛瑞克是 Boss"
        共享 "艾尔登法环" 但后续不同 → 相似度 < 0.85 → 保留
        """
        dd = KnowledgeDeduplicator(package_id=1, threshold=0.85)
        candidates = [
            _make_item("fact", "艾尔登法环是 ARPG"),
            _make_item("fact", "艾尔登法环的葛瑞克是 Boss"),
        ]
        kept, dedup_count = dd.dedupe(candidates)

        assert len(kept) == 2
        assert dedup_count == 0


# ---------------------------------------------------------------------------
# 不同 kind 不互相去重
# ---------------------------------------------------------------------------


class TestCrossKindNoDedup:
    """不同 kind 之间不做近似比较。"""

    def test_different_kind_same_content_not_deduped(self) -> None:
        """不同 kind 内容相似 → 保留 2 条（不同 kind 不去重）。

        kind1="fact" content="测试"
        kind2="meme" content="测试"
        """
        dd = KnowledgeDeduplicator(package_id=1, threshold=0.85)
        candidates = [
            _make_item("fact", "测试"),
            _make_item("meme", "测试"),
        ]
        kept, dedup_count = dd.dedupe(candidates)

        assert len(kept) == 2
        assert dedup_count == 0

    def test_mixed_kinds_all_preserved(self) -> None:
        """多个 kind 混合：fact + meme + style_example + reaction_pattern
        各 2 条不重复 → 保留 8 条。"""
        dd = KnowledgeDeduplicator(package_id=1, threshold=0.85)
        candidates = [
            _make_item("fact", "事实一"),
            _make_item("fact", "事实二"),
            _make_item("meme", "梗一"),
            _make_item("meme", "梗二"),
            _make_item("style_example", "样本一"),
            _make_item("style_example", "样本二"),
            _make_item("reaction_pattern", "反应一"),
            _make_item("reaction_pattern", "反应二"),
        ]
        kept, dedup_count = dd.dedupe(candidates)

        assert len(kept) == 8
        assert dedup_count == 0


# ---------------------------------------------------------------------------
# reset / 空 / 跨 package_id
# ---------------------------------------------------------------------------


class TestResetAndEdgeCases:
    """reset、空输入、跨 package_id 隔离。"""

    def test_reset_clears_state(self) -> None:
        """reset 后状态清空：可重新开始。"""
        dd = KnowledgeDeduplicator(package_id=1, threshold=0.85)

        # 第一次：加入一条
        first_batch = [_make_item("fact", "测试内容")]
        kept1, dedup1 = dd.dedupe(first_batch)
        assert len(kept1) == 1
        assert dedup1 == 0

        # 不 reset：相同内容会被去重
        second_batch = [_make_item("fact", "测试内容")]
        kept2, dedup2 = dd.dedupe(second_batch)
        assert len(kept2) == 0
        assert dedup2 == 1

        # reset 后：相同内容不再被去重
        dd.reset()
        third_batch = [_make_item("fact", "测试内容")]
        kept3, dedup3 = dd.dedupe(third_batch)
        assert len(kept3) == 1
        assert dedup3 == 0

    def test_empty_candidates_returns_empty(self) -> None:
        """空 candidates → 返回 ([], 0)。"""
        dd = KnowledgeDeduplicator(package_id=1)
        kept, dedup_count = dd.dedupe([])

        assert kept == []
        assert dedup_count == 0

    def test_cross_package_id_no_dedup(self) -> None:
        """跨 package_id 不去重：不同 deduplicator 相同 content 不互相影响。"""
        dd_a = KnowledgeDeduplicator(package_id=1, threshold=0.85)
        dd_b = KnowledgeDeduplicator(package_id=2, threshold=0.85)

        candidates = [_make_item("fact", "葛瑞克会喷火")]

        # 包 A 先去重
        kept_a, dedup_a = dd_a.dedupe(candidates)
        assert len(kept_a) == 1
        assert dedup_a == 0

        # 包 B 独立去重，不受包 A 影响
        kept_b, dedup_b = dd_b.dedupe(candidates)
        assert len(kept_b) == 1
        assert dedup_b == 0

        # 包 A 再次去重相同内容 → 重复
        kept_a2, dedup_a2 = dd_a.dedupe(candidates)
        assert len(kept_a2) == 0
        assert dedup_a2 == 1

    def test_multiple_batches_accumulate(self) -> None:
        """多次 dedupe 调用累积状态：跨 batch 去重。"""
        dd = KnowledgeDeduplicator(package_id=1, threshold=0.85)

        # 第一批
        batch1 = [_make_item("fact", "内容A"), _make_item("fact", "内容B")]
        kept1, dedup1 = dd.dedupe(batch1)
        assert len(kept1) == 2
        assert dedup1 == 0

        # 第二批：含与第一批重复的内容
        batch2 = [
            _make_item("fact", "内容A"),  # 精确重复
            _make_item("fact", "内容C"),  # 新内容
        ]
        kept2, dedup2 = dd.dedupe(batch2)
        assert len(kept2) == 1
        assert dedup2 == 1
        assert kept2[0]["content"] == "内容C"


# ---------------------------------------------------------------------------
# 阈值边界
# ---------------------------------------------------------------------------


class TestThresholdBehavior:
    """threshold 参数行为验证。"""

    def test_threshold_1_0_only_exact_match(self) -> None:
        """threshold=1.0 → 仅精确匹配去重（相似度不会 > 1.0）。"""
        dd = KnowledgeDeduplicator(package_id=1, threshold=1.0)
        candidates = [
            _make_item("fact", "主播操作失误了"),
            _make_item("fact", "主播又操作失误了"),  # 相似度 ≈ 0.933 < 1.0
        ]
        kept, dedup_count = dd.dedupe(candidates)

        assert len(kept) == 2
        assert dedup_count == 0

    def test_custom_threshold_lower(self) -> None:
        """自定义更低 threshold → 更多近似被去重。

        Levenshtein.ratio('今天天气很好', '今天天气不错') = 0.667
        （4 个匹配字符 / 12 总字符 × 2）
        - threshold=0.85：0.667 < 0.85 → 不去重
        - threshold=0.4：0.667 > 0.4 → 去重
        """
        # 先验证默认 threshold=0.85 不去重
        dd_default = KnowledgeDeduplicator(package_id=1, threshold=0.85)
        candidates = [
            _make_item("fact", "今天天气很好"),
            _make_item("fact", "今天天气不错"),
        ]
        kept_default, dedup_default = dd_default.dedupe(candidates)
        assert len(kept_default) == 2
        assert dedup_default == 0

        # 再验证更低 threshold=0.4 会去重
        dd_low = KnowledgeDeduplicator(package_id=2, threshold=0.4)
        kept_low, dedup_low = dd_low.dedupe(candidates)
        assert len(kept_low) == 1
        assert dedup_low == 1
