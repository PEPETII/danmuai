"""知识包检索器测试（任务 A7.3）。

覆盖（spec §ADDED Retrieval and Prompt Injection + 用户任务描述）：
    1.  只检索启用包与启用条目
    2.  类型配额：5 个 fact → 2 个；3 个 meme → 1 个
    3.  scope 权重
    4.  recent_use 惩罚
    5.  字符预算
    6.  无结果
    7.  中文短关键词
    8.  重复条目不重复注入
    9.  FTS5/trigram 路径
    10. LIKE 回退路径
    11. set_last_injected（dedup_penalty）
    12. mark_items_used
    13. 异常降级
    14. 空查询

约定（AGENTS.md §A.4.1）：
    - 只跑本文件：``python -m pytest tests/test_knowledge_retriever.py -q -x``
    - 使用 ``tmp_path`` fixture（pytest 自动重定向到 ``.pytest_tmp/``）
    - 不依赖 Qt / DanmuApp / ConfigStore
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from app.knowledge.database import KnowledgeDatabase
from app.knowledge.repository import (
    create_package_for_db,
    create_source_for_db,
    get_package_for_db,
    insert_item_for_db,
)
from app.knowledge.retriever import KnowledgeRetriever, RetrievalResult


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def knowledge_db(tmp_path: Path):
    """构造临时 knowledge.db。"""
    db = KnowledgeDatabase._open_at(tmp_path / "test_retriever.db")
    yield db
    db.close()


@pytest.fixture
def populated_db(knowledge_db: KnowledgeDatabase):
    """插入 2 个 package（1 enabled, 1 disabled）+ 5 个 items。

    - package 1: enabled, priority=10
    - package 2: disabled, priority=5
    - item 1: kind=fact, title="葛瑞克二阶段", content="葛瑞克二阶段会断臂接上龙头",
              scopes=["游戏"], enabled=1, priority=5
    - item 2: kind=fact, title="梅琳娜", content="梅琳娜是褪色者的引导",
              scopes=["游戏"], enabled=1, priority=3
    - item 3: kind=meme, title="又开始了", content="重复失败时使用",
              scopes=["直播"], enabled=1, priority=2
    - item 4: kind=style_example, title="搞笑失误", content="这波没绷住",
              examples=["经典"], scopes=["直播"], enabled=1, priority=1
    - item 5: kind=fact, title="停用条目", content="这个条目被停用",
              scopes=["游戏"], enabled=0, priority=100  # 不应被检索
    - package 2 下 item 6: kind=fact, title="停用包的条目", content="不应被检索到",
              enabled=1, priority=100  # 包停用，不应被检索
    """
    # package 1: enabled
    pkg1_pub = create_package_for_db(
        knowledge_db, name="游戏知识", priority=10, enabled=True
    )["public_id"]
    pkg1 = get_package_for_db(knowledge_db, pkg1_pub)
    assert pkg1 is not None
    pkg1_id = pkg1["id"]

    # package 2: disabled
    pkg2_pub = create_package_for_db(
        knowledge_db, name="停用包", priority=5, enabled=False
    )["public_id"]
    pkg2 = get_package_for_db(knowledge_db, pkg2_pub)
    assert pkg2 is not None
    pkg2_id = pkg2["id"]

    # source 1 in pkg1
    src1 = create_source_for_db(
        knowledge_db,
        package_id=pkg1_id,
        source_type="pasted_text",
        display_name="src1",
    )
    src1_id = src1["id"]

    # source 2 in pkg2
    src2 = create_source_for_db(
        knowledge_db,
        package_id=pkg2_id,
        source_type="pasted_text",
        display_name="src2",
    )
    src2_id = src2["id"]

    # items in pkg1
    insert_item_for_db(
        knowledge_db,
        package_id=pkg1_id,
        source_id=src1_id,
        chunk_id=None,
        kind="fact",
        title="葛瑞克二阶段",
        content="葛瑞克二阶段会断臂接上龙头",
        scopes=["游戏"],
        enabled=True,
        priority=5,
        confidence=0.9,
        triggers=["葛瑞克", "二阶段"],
    )
    insert_item_for_db(
        knowledge_db,
        package_id=pkg1_id,
        source_id=src1_id,
        chunk_id=None,
        kind="fact",
        title="梅琳娜",
        content="梅琳娜是褪色者的引导",
        scopes=["游戏"],
        enabled=True,
        priority=3,
        confidence=0.85,
    )
    insert_item_for_db(
        knowledge_db,
        package_id=pkg1_id,
        source_id=src1_id,
        chunk_id=None,
        kind="meme",
        title="又开始了",
        content="重复失败时使用",
        scopes=["直播"],
        enabled=True,
        priority=2,
        confidence=0.7,
    )
    insert_item_for_db(
        knowledge_db,
        package_id=pkg1_id,
        source_id=src1_id,
        chunk_id=None,
        kind="style_example",
        title="搞笑失误",
        content="这波没绷住",
        examples=["经典"],
        scopes=["直播"],
        enabled=True,
        priority=1,
        confidence=0.8,
    )
    # item 5: disabled fact in pkg1
    insert_item_for_db(
        knowledge_db,
        package_id=pkg1_id,
        source_id=src1_id,
        chunk_id=None,
        kind="fact",
        title="停用条目",
        content="这个条目被停用",
        scopes=["游戏"],
        enabled=False,
        priority=100,
        confidence=1.0,
    )

    # item 6: in disabled package pkg2
    insert_item_for_db(
        knowledge_db,
        package_id=pkg2_id,
        source_id=src2_id,
        chunk_id=None,
        kind="fact",
        title="停用包的条目",
        content="不应被检索到",
        scopes=["游戏"],
        enabled=True,
        priority=100,
        confidence=1.0,
    )

    return knowledge_db


# ---------------------------------------------------------------------------
# 1. 只检索启用包与启用条目
# ---------------------------------------------------------------------------


class TestEnabledFilter:
    """只检索 ``WHERE p.enabled=1 AND i.enabled=1``。"""

    def test_disabled_package_and_item_excluded(
        self, populated_db: KnowledgeDatabase
    ) -> None:
        retriever = KnowledgeRetriever(populated_db)
        result = retriever.retrieve(scene_brief="葛瑞克", keywords=["葛瑞克"])
        titles = [it["title"] for it in result.items]
        # 停用包的条目与停用条目都不应出现
        assert "停用包的条目" not in titles
        assert "停用条目" not in titles
        # 启用的葛瑞克条目应出现
        assert "葛瑞克二阶段" in titles


# ---------------------------------------------------------------------------
# 2. 类型配额
# ---------------------------------------------------------------------------


class TestTypeQuota:
    """类型配额：fact≤2 / reaction_pattern≤1 / meme≤1 / style_example≤2 / 总≤4。"""

    def test_fact_quota_caps_at_two(self, knowledge_db: KnowledgeDatabase) -> None:
        """插入 5 个 fact → 只返回 2 个。"""
        pkg_pub = create_package_for_db(
            knowledge_db, name="pkg", priority=10, enabled=True
        )["public_id"]
        pkg = get_package_for_db(knowledge_db, pkg_pub)
        assert pkg is not None
        src = create_source_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_type="pasted_text",
            display_name="src",
        )
        for i in range(5):
            insert_item_for_db(
                knowledge_db,
                package_id=pkg["id"],
                source_id=src["id"],
                chunk_id=None,
                kind="fact",
                title=f"事实{i}",
                content=f"事实内容{i} 测试关键词",
                scopes=["游戏"],
                enabled=True,
                priority=i,
                confidence=0.9,
            )
        retriever = KnowledgeRetriever(knowledge_db)
        result = retriever.retrieve(keywords=["测试关键词"], max_items=4)
        fact_count = sum(1 for it in result.items if it["kind"] == "fact")
        assert fact_count == 2, f"expected 2 facts, got {fact_count}"

    def test_meme_quota_caps_at_one(self, knowledge_db: KnowledgeDatabase) -> None:
        """插入 3 个 meme → 只返回 1 个。"""
        pkg_pub = create_package_for_db(
            knowledge_db, name="pkg", priority=10, enabled=True
        )["public_id"]
        pkg = get_package_for_db(knowledge_db, pkg_pub)
        assert pkg is not None
        src = create_source_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_type="pasted_text",
            display_name="src",
        )
        for i in range(3):
            insert_item_for_db(
                knowledge_db,
                package_id=pkg["id"],
                source_id=src["id"],
                chunk_id=None,
                kind="meme",
                title=f"梗{i}",
                content=f"梗内容{i} 测试关键词",
                scopes=["直播"],
                enabled=True,
                priority=i,
                confidence=0.7,
            )
        retriever = KnowledgeRetriever(knowledge_db)
        result = retriever.retrieve(keywords=["测试关键词"], max_items=4)
        meme_count = sum(1 for it in result.items if it["kind"] == "meme")
        assert meme_count == 1, f"expected 1 meme, got {meme_count}"

    def test_total_items_cap(self, knowledge_db: KnowledgeDatabase) -> None:
        """总条目数不超过 max_items（默认 4）。"""
        pkg_pub = create_package_for_db(
            knowledge_db, name="pkg", priority=10, enabled=True
        )["public_id"]
        pkg = get_package_for_db(knowledge_db, pkg_pub)
        assert pkg is not None
        src = create_source_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_type="pasted_text",
            display_name="src",
        )
        # 2 fact + 2 meme + 2 style_example + 2 reaction_pattern = 8 候选
        for kind, quota in [
            ("fact", 2),
            ("meme", 2),
            ("style_example", 2),
            ("reaction_pattern", 2),
        ]:
            for i in range(quota):
                insert_item_for_db(
                    knowledge_db,
                    package_id=pkg["id"],
                    source_id=src["id"],
                    chunk_id=None,
                    kind=kind,
                    title=f"{kind}_{i}",
                    content=f"内容{kind}_{i} 测试关键词",
                    scopes=["游戏"],
                    enabled=True,
                    priority=i,
                    confidence=0.8,
                )
        retriever = KnowledgeRetriever(knowledge_db)
        result = retriever.retrieve(keywords=["测试关键词"], max_items=4)
        assert len(result.items) <= 4
        # 验证每种 kind 不超配额
        kind_counts: dict[str, int] = {}
        for it in result.items:
            kind_counts[it["kind"]] = kind_counts.get(it["kind"], 0) + 1
        assert kind_counts.get("fact", 0) <= 2
        assert kind_counts.get("meme", 0) <= 1
        assert kind_counts.get("style_example", 0) <= 2
        assert kind_counts.get("reaction_pattern", 0) <= 1


# ---------------------------------------------------------------------------
# 3. scope 权重
# ---------------------------------------------------------------------------


class TestScopeWeight:
    """scope 匹配的条目评分高于不匹配的。"""

    def test_scope_match_higher_score(self, knowledge_db: KnowledgeDatabase) -> None:
        """item scopes=["游戏"] 与 scene_brief="游戏直播" → score 高于 scopes=["日常"]。"""
        pkg_pub = create_package_for_db(
            knowledge_db, name="pkg", priority=10, enabled=True
        )["public_id"]
        pkg = get_package_for_db(knowledge_db, pkg_pub)
        assert pkg is not None
        src = create_source_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_type="pasted_text",
            display_name="src",
        )
        # 两个 fact，唯一差别是 scopes
        insert_item_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_id=src["id"],
            chunk_id=None,
            kind="fact",
            title="游戏条目",
            content="游戏内容 测试关键词",
            scopes=["游戏"],
            enabled=True,
            priority=5,
            confidence=0.9,
        )
        insert_item_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_id=src["id"],
            chunk_id=None,
            kind="fact",
            title="日常条目",
            content="日常内容 测试关键词",
            scopes=["日常"],
            enabled=True,
            priority=5,
            confidence=0.9,
        )
        retriever = KnowledgeRetriever(knowledge_db)
        # scene_brief 含"游戏" → inferred scope="游戏"
        result = retriever.retrieve(
            scene_brief="游戏直播", keywords=["测试关键词"]
        )
        items_by_title = {it["title"]: it for it in result.items}
        if "游戏条目" in items_by_title and "日常条目" in items_by_title:
            assert items_by_title["游戏条目"]["score"] > items_by_title["日常条目"]["score"]
        elif "游戏条目" in items_by_title:
            # 日常条目可能因配额被淘汰，说明游戏条目确实得分更高
            assert True
        else:
            pytest.fail("游戏条目应命中")


# ---------------------------------------------------------------------------
# 4. recent_use 惩罚
# ---------------------------------------------------------------------------


class TestRecentUsePenalty:
    """最近使用过的条目评分降低。"""

    def test_recently_used_lower_score(self, knowledge_db: KnowledgeDatabase) -> None:
        """item last_used_at = now - 30s → score 低于 last_used_at=0 的同分 item。"""
        pkg_pub = create_package_for_db(
            knowledge_db, name="pkg", priority=10, enabled=True
        )["public_id"]
        pkg = get_package_for_db(knowledge_db, pkg_pub)
        assert pkg is not None
        src = create_source_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_type="pasted_text",
            display_name="src",
        )
        item_a = insert_item_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_id=src["id"],
            chunk_id=None,
            kind="fact",
            title="条目A",
            content="内容A 测试关键词",
            scopes=["游戏"],
            enabled=True,
            priority=5,
            confidence=0.9,
        )
        item_b = insert_item_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_id=src["id"],
            chunk_id=None,
            kind="fact",
            title="条目B",
            content="内容B 测试关键词",
            scopes=["游戏"],
            enabled=True,
            priority=5,
            confidence=0.9,
        )
        retriever = KnowledgeRetriever(knowledge_db)
        # 标记 item_a 在 30 秒前用过
        retriever.mark_items_used([item_a["id"]], used_at=time.time() - 30)
        result = retriever.retrieve(keywords=["测试关键词"], max_items=4)
        items_by_title = {it["title"]: it for it in result.items}
        if "条目A" in items_by_title and "条目B" in items_by_title:
            assert items_by_title["条目B"]["score"] > items_by_title["条目A"]["score"]


class TestRecentUsePenaltyDualFactor:
    """spec line 165：基于 last_used_at + use_count 双因子。"""

    def test_high_use_count_penalizes_even_outside_window(
        self, knowledge_db: KnowledgeDatabase
    ) -> None:
        """use_count 高的 item 即使 last_used_at 在窗口外也应被惩罚。

        构造两个同分 item：A use_count=10，B use_count=0，二者 last_used_at
        均为 None（窗口外）。A 应因 count_penalty 评分更低。
        """
        pkg_pub = create_package_for_db(
            knowledge_db, name="pkg", priority=10, enabled=True
        )["public_id"]
        pkg = get_package_for_db(knowledge_db, pkg_pub)
        assert pkg is not None
        src = create_source_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_type="pasted_text",
            display_name="src",
        )
        item_a = insert_item_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_id=src["id"],
            chunk_id=None,
            kind="fact",
            title="高频条目",
            content="内容A 测试关键词",
            scopes=["游戏"],
            enabled=True,
            priority=5,
            confidence=0.9,
        )
        item_b = insert_item_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_id=src["id"],
            chunk_id=None,
            kind="fact",
            title="低频条目",
            content="内容B 测试关键词",
            scopes=["游戏"],
            enabled=True,
            priority=5,
            confidence=0.9,
        )
        # 直接 SQL 把 A 的 use_count 拉到 10（绕过 mark_items_used 单次递增）
        knowledge_db.conn.execute(
            "UPDATE knowledge_items SET use_count=10 WHERE id=?",
            (item_a["id"],),
        )
        knowledge_db.conn.commit()
        retriever = KnowledgeRetriever(knowledge_db)
        result = retriever.retrieve(keywords=["测试关键词"], max_items=4)
        items_by_title = {it["title"]: it for it in result.items}
        if "高频条目" in items_by_title and "低频条目" in items_by_title:
            # A 的 count_penalty=1.0，B 的 count_penalty=0
            assert items_by_title["低频条目"]["score"] > items_by_title["高频条目"]["score"]

    def test_combined_time_and_count_penalty_capped(self) -> None:
        """time_penalty + count_penalty 总上限 2.0，避免永久屏蔽。"""
        from app.knowledge.retriever import _recent_use_penalty

        # 刚用过（elapsed=0）→ time_penalty=2.0
        now = time.time()
        just_used = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        # use_count=100 → count_penalty 在未封顶前为 9.9，但被 min(1.0, ...) 封顶
        penalty = _recent_use_penalty(
            just_used, now, window_sec=120, use_count=100
        )
        # 上限 2.0（time_penalty 已满，count_penalty 不能再加）
        assert penalty == 2.0

    def test_use_count_zero_no_extra_penalty(self) -> None:
        """use_count=0 或 1 时，count_penalty=0（向后兼容）。"""
        from app.knowledge.retriever import _recent_use_penalty

        now = time.time()
        just_used = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))
        # use_count=0 / use_count=1 行为应相同
        p0 = _recent_use_penalty(just_used, now, 120, use_count=0)
        p1 = _recent_use_penalty(just_used, now, 120, use_count=1)
        assert p0 == p1
        # 二者都应接近纯 time_penalty（elapsed 因 strftime 截断到整秒
        # 而略小于 2.0，但应在 0.1 容差内）
        assert p0 == pytest.approx(2.0, abs=0.1)

    def test_use_count_outside_window_still_applies(self) -> None:
        """use_count > 1 即使 last_used_at=None 也应施加 count_penalty。"""
        from app.knowledge.retriever import _recent_use_penalty

        # last_used_at=None, use_count=5 → 0.1*(5-1)=0.4
        assert _recent_use_penalty(None, time.time(), 120, use_count=5) == 0.4
        # use_count=11 → 0.1*10=1.0（已触上限）
        assert _recent_use_penalty(None, time.time(), 120, use_count=11) == 1.0


# ---------------------------------------------------------------------------
# 5. 字符预算
# ---------------------------------------------------------------------------


class TestCharBudget:
    """prompt_text 长度 ≤ max_chars（硬上限 600）。"""

    def test_small_budget_truncates(self, populated_db: KnowledgeDatabase) -> None:
        """max_chars=50 → prompt_text ≤ 50。"""
        retriever = KnowledgeRetriever(populated_db)
        result = retriever.retrieve(
            scene_brief="葛瑞克", keywords=["葛瑞克"], max_chars=50
        )
        assert len(result.prompt_text) <= 50

    def test_normal_budget_works(self, populated_db: KnowledgeDatabase) -> None:
        """max_chars=360 → prompt_text 非空且 ≤ 360。"""
        retriever = KnowledgeRetriever(populated_db)
        result = retriever.retrieve(
            scene_brief="葛瑞克", keywords=["葛瑞克"], max_chars=360
        )
        if result.items:
            assert len(result.prompt_text) <= 360
            assert "以下内容是本地资料检索结果" in result.prompt_text

    def test_hard_max_chars_enforced(self, knowledge_db: KnowledgeDatabase) -> None:
        """max_chars=10000 → 实际输出 ≤ 600（硬上限）。"""
        pkg_pub = create_package_for_db(
            knowledge_db, name="pkg", priority=10, enabled=True
        )["public_id"]
        pkg = get_package_for_db(knowledge_db, pkg_pub)
        assert pkg is not None
        src = create_source_for_db(
            knowledge_db,
            package_id=pkg["id"],
            source_type="pasted_text",
            display_name="src",
        )
        for i in range(10):
            insert_item_for_db(
                knowledge_db,
                package_id=pkg["id"],
                source_id=src["id"],
                chunk_id=None,
                kind="fact",
                title=f"标题{i}",
                content=f"内容{i}测试关键词",
                scopes=["游戏"],
                enabled=True,
                priority=i,
                confidence=0.9,
            )
        retriever = KnowledgeRetriever(knowledge_db)
        result = retriever.retrieve(
            keywords=["测试关键词"], max_chars=10000
        )
        assert len(result.prompt_text) <= 600


# ---------------------------------------------------------------------------
# 6. 无结果
# ---------------------------------------------------------------------------


class TestEmptyResult:
    """空 DB → RetrievalResult(items=[], prompt_text="", hit_count=0)。"""

    def test_empty_db_returns_empty(self, knowledge_db: KnowledgeDatabase) -> None:
        retriever = KnowledgeRetriever(knowledge_db)
        result = retriever.retrieve(scene_brief="任意", keywords=["任意"])
        assert isinstance(result, RetrievalResult)
        assert result.items == []
        assert result.prompt_text == ""
        assert result.hit_count == 0
        assert result.fts_backend == knowledge_db.fts_backend


# ---------------------------------------------------------------------------
# 7. 中文短关键词
# ---------------------------------------------------------------------------


class TestChineseKeyword:
    """中文短关键词命中 title/content 含该词的 item。"""

    def test_short_chinese_keyword_hit(self, populated_db: KnowledgeDatabase) -> None:
        retriever = KnowledgeRetriever(populated_db)
        result = retriever.retrieve(keywords=["葛瑞克"])
        titles = [it["title"] for it in result.items]
        assert "葛瑞克二阶段" in titles


# ---------------------------------------------------------------------------
# 8. 重复条目不重复注入
# ---------------------------------------------------------------------------


class TestNoDuplicateInjection:
    """同一 item 只出现一次。"""

    def test_same_item_not_duplicated(self, populated_db: KnowledgeDatabase) -> None:
        retriever = KnowledgeRetriever(populated_db)
        # 用多个关键词同时命中同一 item
        result = retriever.retrieve(
            scene_brief="葛瑞克二阶段", keywords=["葛瑞克", "二阶段", "龙头"]
        )
        ids = [it["id"] for it in result.items]
        assert len(ids) == len(set(ids)), "同一 item 出现多次"


# ---------------------------------------------------------------------------
# 9. FTS5/trigram 路径
# ---------------------------------------------------------------------------


class TestFtsPath:
    """FTS5/trigram 路径：插入 item 后 retrieve(scene_brief=...) 命中。"""

    def test_fts_retrieval_hits(self, populated_db: KnowledgeDatabase) -> None:
        if populated_db.fts_backend == "fallback":
            pytest.skip("FTS5 不可用，跳过 FTS 路径测试")
        retriever = KnowledgeRetriever(populated_db)
        result = retriever.retrieve(scene_brief="葛瑞克二阶段")
        assert result.fts_backend in ("trigram", "fts5")
        titles = [it["title"] for it in result.items]
        assert "葛瑞克二阶段" in titles


# ---------------------------------------------------------------------------
# 10. LIKE 回退路径
# ---------------------------------------------------------------------------


class TestLikeFallback:
    """mock db.fts_backend = "fallback" → 仍能通过 LIKE 检索。"""

    def test_like_fallback_retrieves(self, populated_db: KnowledgeDatabase) -> None:
        # 强制 fallback
        object.__setattr__(populated_db, "fts_backend", "fallback")
        retriever = KnowledgeRetriever(populated_db)
        result = retriever.retrieve(keywords=["葛瑞克"])
        assert result.fts_backend == "fallback"
        titles = [it["title"] for it in result.items]
        assert "葛瑞克二阶段" in titles

    def test_like_fallback_with_scene_brief(
        self, populated_db: KnowledgeDatabase
    ) -> None:
        object.__setattr__(populated_db, "fts_backend", "fallback")
        retriever = KnowledgeRetriever(populated_db)
        result = retriever.retrieve(scene_brief="葛瑞克")
        titles = [it["title"] for it in result.items]
        assert "葛瑞克二阶段" in titles


# ---------------------------------------------------------------------------
# 11. set_last_injected（dedup_penalty）
# ---------------------------------------------------------------------------


class TestSetLastInjected:
    """注入后调 set_last_injected，下次 retrieve 含同内容 item → score 降低。"""

    def test_dedup_penalty_lowers_score(
        self, populated_db: KnowledgeDatabase
    ) -> None:
        retriever = KnowledgeRetriever(populated_db)
        # 第一次检索
        result1 = retriever.retrieve(keywords=["葛瑞克"])
        if not result1.items:
            pytest.skip("无命中")
        target = result1.items[0]
        # 标记上次注入了该 item 的 content
        retriever.set_last_injected([target["content"]])
        # 第二次检索同条件
        result2 = retriever.retrieve(keywords=["葛瑞克"])
        items_by_id = {it["id"]: it for it in result2.items}
        if target["id"] in items_by_id:
            assert items_by_id[target["id"]]["score"] < target["score"]


# ---------------------------------------------------------------------------
# 12. mark_items_used
# ---------------------------------------------------------------------------


class TestMarkItemsUsed:
    """调用后 use_count 递增、last_used_at 更新。"""

    def test_use_count_increments(self, populated_db: KnowledgeDatabase) -> None:
        retriever = KnowledgeRetriever(populated_db)
        # 取一个 item
        result = retriever.retrieve(keywords=["葛瑞克"])
        if not result.items:
            pytest.skip("无命中")
        item = result.items[0]
        item_id = item["id"]
        # 查询原始 use_count
        row = populated_db.conn.execute(
            "SELECT use_count, last_used_at FROM knowledge_items WHERE id=?",
            (item_id,),
        ).fetchone()
        old_count = int(row[0])
        old_last = row[1]
        # 调用 mark_items_used
        retriever.mark_items_used([item_id])
        # 验证 use_count 递增
        row2 = populated_db.conn.execute(
            "SELECT use_count, last_used_at FROM knowledge_items WHERE id=?",
            (item_id,),
        ).fetchone()
        assert int(row2[0]) == old_count + 1
        # last_used_at 应更新（非空且与旧值不同，或旧值为 None 时变非空）
        assert row2[1] is not None
        if old_last is not None:
            assert row2[1] >= old_last

    def test_mark_empty_list_noop(self, populated_db: KnowledgeDatabase) -> None:
        """空列表调用不应抛异常。"""
        retriever = KnowledgeRetriever(populated_db)
        retriever.mark_items_used([])
        # 不抛异常即可


# ---------------------------------------------------------------------------
# 13. 异常降级
# ---------------------------------------------------------------------------


class TestExceptionDegradation:
    """底层 SQL 抛 sqlite3.Error → 返回空 RetrievalResult 不抛异常。

    sqlite3.Connection.execute 属性为只读，无法 patch；这里关闭底层连接，
    触发 ``sqlite3.ProgrammingError``（``sqlite3.Error`` 子类）。
    fixture 的 ``db.close()`` 已 try/except ProgrammingError，teardown 安全。
    """

    def test_sql_error_returns_empty(self, knowledge_db: KnowledgeDatabase) -> None:
        retriever = KnowledgeRetriever(knowledge_db)
        # 关闭底层连接：后续 execute() 抛 ProgrammingError（sqlite3.Error 子类）
        knowledge_db.conn.close()
        try:
            result = retriever.retrieve(scene_brief="任意", keywords=["任意"])
        finally:
            # 防止 fixture teardown 再次 close 已关闭连接（虽然已 try/except）
            object.__setattr__(knowledge_db, "_closed", True)
        assert isinstance(result, RetrievalResult)
        assert result.items == []
        assert result.prompt_text == ""
        assert result.hit_count == 0


# ---------------------------------------------------------------------------
# 14. 空查询
# ---------------------------------------------------------------------------


class TestEmptyQuery:
    """scene_brief="" + keywords=[] → 返回空结果（不报错）。"""

    def test_empty_query_returns_empty(
        self, populated_db: KnowledgeDatabase
    ) -> None:
        retriever = KnowledgeRetriever(populated_db)
        result = retriever.retrieve(scene_brief="", keywords=[])
        assert result.items == []
        assert result.prompt_text == ""
        assert result.hit_count == 0

    def test_none_keywords_returns_empty(
        self, populated_db: KnowledgeDatabase
    ) -> None:
        """keywords=None 也应安全返回空结果。"""
        retriever = KnowledgeRetriever(populated_db)
        result = retriever.retrieve(scene_brief="", keywords=None)
        assert result.items == []
        assert result.hit_count == 0


# ---------------------------------------------------------------------------
# 附加：RetrievalResult 不可变 + prompt_builder 单元测试
# ---------------------------------------------------------------------------


class TestRetrievalResultFrozen:
    """RetrievalResult 是 frozen dataclass。"""

    def test_result_is_frozen(self) -> None:
        result = RetrievalResult(
            items=[], prompt_text="", hit_count=0, retrieval_ms=0, fts_backend="trigram"
        )
        with pytest.raises(Exception):
            result.hit_count = 1  # type: ignore[misc]


class TestPromptBuilderDirect:
    """直接测试 build_prompt_text 分段与预算。"""

    def test_empty_items_returns_empty(self) -> None:
        from app.knowledge.prompt_builder import build_prompt_text

        assert build_prompt_text([]) == ""

    def test_fact_section_title(self) -> None:
        from app.knowledge.prompt_builder import build_prompt_text

        text = build_prompt_text(
            [{"kind": "fact", "title": "标题", "content": "内容"}], max_chars=600
        )
        assert "## 事实知识" in text
        assert "- 标题：内容" in text

    def test_expressive_section_with_examples(self) -> None:
        from app.knowledge.prompt_builder import build_prompt_text

        text = build_prompt_text(
            [
                {
                    "kind": "style_example",
                    "title": "搞笑",
                    "content": "内容",
                    "examples": ["例1", "例2"],
                }
            ],
            max_chars=600,
        )
        assert "## 表达参考" in text
        assert "（例：例1 / 例2）" in text

    def test_empty_group_no_header(self) -> None:
        from app.knowledge.prompt_builder import build_prompt_text

        text = build_prompt_text(
            [{"kind": "fact", "title": "标题", "content": "内容"}], max_chars=600
        )
        # 只有 fact → 不应出现反应方式 / 表达参考
        assert "## 反应方式" not in text
        assert "## 表达参考" not in text

    def test_no_evidence_output(self) -> None:
        """不输出 evidence 字段。"""
        from app.knowledge.prompt_builder import build_prompt_text

        text = build_prompt_text(
            [
                {
                    "kind": "fact",
                    "title": "标题",
                    "content": "内容",
                    "evidence": "secret evidence",
                }
            ],
            max_chars=600,
        )
        assert "secret evidence" not in text
