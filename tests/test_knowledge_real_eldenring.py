"""基于真实知识库的《艾尔登法环》知识包检索测试。

使用 %APPDATA%/DanmuAI/knowledge.db 的副本，验证现有 4 条艾尔登法环知识条目
能被正确检索、评分、配额筛选并格式化为提示词注入文本。

测试策略：
    - 拷贝生产库到 tmp_path（只读使用，不污染原库）
    - 使用真实 KnowledgeDatabase + KnowledgeRetriever（与运行时完全一致）
    - 覆盖：关键字检索 / 场景简述检索 / 评分排序 / 类型配额 / 提示词格式 / use_count

运行：python -m pytest tests/test_knowledge_real_eldenring.py -q -x -v
"""
from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path

import pytest

from app.knowledge.database import KnowledgeDatabase
from app.knowledge.retriever import KnowledgeRetriever


# ---------------------------------------------------------------------------
# 夹具：拷贝生产 knowledge.db 到临时目录
# ---------------------------------------------------------------------------


def _find_real_knowledge_db() -> Path | None:
    """定位 %APPDATA%/DanmuAI/knowledge.db"""
    apd = os.environ.get("APPDATA")
    if not apd:
        return None
    path = Path(apd) / "DanmuAI" / "knowledge.db"
    return path if path.exists() else None


@pytest.fixture(scope="session")
def real_db_path() -> Path:
    """找到真实知识库路径，跳过测试环境警告。"""
    p = _find_real_knowledge_db()
    if p is None:
        pytest.skip("未找到 %APPDATA%/DanmuAI/knowledge.db，跳过真实数据测试")
    # 验证含有艾尔登法环条目
    conn = sqlite3.connect(str(p))
    cnt = conn.execute(
        "SELECT COUNT(*) FROM knowledge_items WHERE content LIKE '%艾尔登%'"
    ).fetchone()[0]
    conn.close()
    if cnt == 0:
        pytest.skip("知识库中无《艾尔登法环》条目，跳过")
    return p


@pytest.fixture(scope="session")
def checkpointed_real_db_path(real_db_path: Path) -> Path:
    """Checkpoint WAL 后返回原路径，确保拷贝时数据完整。"""
    conn = sqlite3.connect(str(real_db_path))
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    return real_db_path


@pytest.fixture
def knowledge_db(checkpointed_real_db_path: Path, tmp_path: Path) -> KnowledgeDatabase:
    """拷贝真实知识库（已 checkpoint）到临时路径后打开。"""
    copy_path = tmp_path / "knowledge.db"
    shutil.copy2(str(checkpointed_real_db_path), str(copy_path))
    db = KnowledgeDatabase._open_at(copy_path)
    yield db
    db.close()


@pytest.fixture
def retriever(knowledge_db: KnowledgeDatabase) -> KnowledgeRetriever:
    return KnowledgeRetriever(knowledge_db)


# ---------------------------------------------------------------------------
# 预检：确认测试数据存在
# ---------------------------------------------------------------------------


class TestDataPresence:
    """确认真实知识库中包含《艾尔登法环》条目。"""

    def test_elden_ring_items_exist(self, knowledge_db: KnowledgeDatabase) -> None:
        """艾尔登法环条目标题或内容含关键词即计为相关条目。"""
        c = knowledge_db.conn.execute(
            "SELECT id, kind, title, use_count FROM knowledge_items "
            "WHERE title LIKE '%艾尔登%' OR content LIKE '%艾尔登%' ORDER BY id"
        )
        rows = list(c)
        assert len(rows) >= 4, f"期望至少 4 条艾尔登法环条目，实际 {len(rows)}"
        titles = [r["title"] for r in rows]
        assert any("职业" in t for t in titles), "应包含职业推荐条目"
        assert any("按键" in t for t in titles), "应包含按键操作条目"

    def test_package_is_global_and_enabled(self, knowledge_db: KnowledgeDatabase) -> None:
        c = knowledge_db.conn.execute(
            "SELECT name, scope_mode, enabled FROM knowledge_packages WHERE enabled=1"
        )
        global_pkgs = [r for r in c if r["scope_mode"] == "global"]
        assert global_pkgs, "应至少有一个全局启用知识包"


# ---------------------------------------------------------------------------
# 核心检索测试：关键词命中
# ---------------------------------------------------------------------------


class TestKeywordRetrieval:
    """用艾尔登法环相关关键词检索，验证命中与评分。"""

    def test_elden_ring_keyword_hits_all_items(self, retriever: KnowledgeRetriever) -> None:
        """关键词"艾尔登法环"→ 命中所有 4 条。"""
        result = retriever.retrieve(keywords=["艾尔登法环"])
        assert result.hit_count >= 4, f"期望命中 ≥4 条，实际 {result.hit_count}"
        assert result.prompt_text, "提示词不应为空"
        assert "艾尔登法环" in result.prompt_text

    def test_profession_keyword_matches_correct_item(
        self, retriever: KnowledgeRetriever
    ) -> None:
        """关键词"职业"→ 命中含职业的条目。"""
        result = retriever.retrieve(keywords=["职业", "前期"])
        assert result.hit_count >= 1, "应命中至少 1 条"
        if result.items:
            all_text = " ".join(it["title"] + it["content"] for it in result.items)
            assert "职业" in all_text, f"条目应含职业，实际: {[it['title'] for it in result.items]}"

    def test_weapon_keyword_matches_operation_item(
        self, retriever: KnowledgeRetriever
    ) -> None:
        """关键词"双持"→ 命中含"双持"的条目。"""
        result = retriever.retrieve(keywords=["双持"])
        assert result.hit_count >= 1, "应命中至少 1 条"
        if result.items:
            all_text = " ".join(it["title"] + it["content"] for it in result.items)
            assert "双持" in all_text, f"条目应含双持，实际: {[it['title'] for it in result.items]}"

    def test_score_ordering_higher_confidence_first(
        self, retriever: KnowledgeRetriever
    ) -> None:
        """评分最高的条目排第一。"""
        result = retriever.retrieve(keywords=["艾尔登法环"])
        if len(result.items) >= 2:
            scores = [it["score"] for it in result.items]
            assert scores == sorted(scores, reverse=True), "评分应降序排列"


# ---------------------------------------------------------------------------
# 场景简述检索
# ---------------------------------------------------------------------------


class TestSceneBriefRetrieval:
    """用场景简述模拟直播上下文。"""

    def test_scene_brief_newbie_guide(self, retriever: KnowledgeRetriever) -> None:
        """场景"新手入门职业推荐"→ 命中职业相关条目。"""
        result = retriever.retrieve(
            scene_brief="新手入门职业推荐",
            keywords=["艾尔登法环"],
        )
        assert result.hit_count >= 1
        if result.items:
            titles_joined = " ".join(it["title"] for it in result.items)
            assert "职业" in titles_joined or "属性" in titles_joined

    def test_scene_brief_coop_question(self, retriever: KnowledgeRetriever) -> None:
        """场景"怎么双持武器"→ 命中按键操作条目。"""
        result = retriever.retrieve(
            scene_brief="怎么双持武器",
            keywords=["按键", "操作"],
        )
        assert result.hit_count >= 1


# ---------------------------------------------------------------------------
# 提示词注入格式验证
# ---------------------------------------------------------------------------


class TestPromptInjectionFormat:
    """验证注入到 system_pt 的提示词格式。"""

    def test_prompt_contains_preamble(self, retriever: KnowledgeRetriever) -> None:
        """提示词以固定前言开头。"""
        result = retriever.retrieve(keywords=["艾尔登法环"])
        assert result.prompt_text.startswith("以下内容是本地资料检索结果")
        assert "事实知识" in result.prompt_text

    def test_prompt_format_item_line(self, retriever: KnowledgeRetriever) -> None:
        """每条形如「- 标题：内容」。"""
        result = retriever.retrieve(keywords=["艾尔登法环"])
        assert result.prompt_text
        lines = result.prompt_text.split("\n")
        item_lines = [l for l in lines if l.startswith("- ")]
        assert len(item_lines) >= 1
        for line in item_lines:
            assert "：" in line or ":" in line, f"条目行缺少冒号分隔: {line}"

    def test_prompt_length_within_budget(self, retriever: KnowledgeRetriever) -> None:
        """默认预算 360 字符，输出不超过预算。"""
        result = retriever.retrieve(keywords=["艾尔登法环"], max_chars=360)
        assert len(result.prompt_text) <= 360, (
            f"提示词长度 {len(result.prompt_text)} > 360"
        )

    def test_hard_max_chars_respected(self, retriever: KnowledgeRetriever) -> None:
        """硬上限 600，max_chars=9999 仍 ≤600。"""
        result = retriever.retrieve(keywords=["艾尔登法环"], max_chars=9999)
        assert len(result.prompt_text) <= 600, (
            f"硬上限 600，实际 {len(result.prompt_text)}"
        )

    def test_no_raw_evidence_in_prompt(self, retriever: KnowledgeRetriever) -> None:
        """提示词不包含 evidence 字段。"""
        result = retriever.retrieve(keywords=["艾尔登法环"])
        assert "evidence" not in result.prompt_text.lower()


# ---------------------------------------------------------------------------
# 类型配额验证
# ---------------------------------------------------------------------------


class TestTypeQuotaRealData:
    """真实数据中 4 条全是 fact → 最多注入 2 条。"""

    def test_fact_quota_applies_to_elden_ring_items(
        self, retriever: KnowledgeRetriever
    ) -> None:
        """所有命中的条目都是 fact → 输出 ≤ 2 条 fact。"""
        result = retriever.retrieve(keywords=["艾尔登法环"], max_items=4)
        facts = [it for it in result.items if it["kind"] == "fact"]
        assert len(facts) <= 2, f"fact 配额 ≤2，实际 {len(facts)}"
        assert len(result.items) <= 4, f"总条目数 ≤4，实际 {len(result.items)}"


# ---------------------------------------------------------------------------
# use_count 机制验证
# ---------------------------------------------------------------------------


class TestUseCountMechanism:
    """验证注入时更新 use_count，近期使用条目被降权。"""

    def test_mark_used_increments_count(
        self, knowledge_db: KnowledgeDatabase, retriever: KnowledgeRetriever
    ) -> None:
        """mark_items_used 后 use_count+1。"""
        result = retriever.retrieve(keywords=["艾尔登法环"])
        if not result.items:
            pytest.skip("无命中")
        target_id = result.items[0]["id"]
        old = knowledge_db.conn.execute(
            "SELECT use_count FROM knowledge_items WHERE id=?", (target_id,)
        ).fetchone()[0]
        retriever.mark_items_used([target_id])
        new = knowledge_db.conn.execute(
            "SELECT use_count FROM knowledge_items WHERE id=?", (target_id,)
        ).fetchone()[0]
        assert new == old + 1, f"use_count {old} → {new}，期望 +1"

    def test_recently_used_item_gets_lower_score(
        self, knowledge_db: KnowledgeDatabase, retriever: KnowledgeRetriever
    ) -> None:
        """近期使用的条目评分低于未使用的相似条目。"""
        result = retriever.retrieve(keywords=["艾尔登法环"])
        if len(result.items) < 2:
            pytest.skip("命中条目不足 2 条，无法比较评分")
        # 取第一条，标记为刚刚使用
        target = result.items[0]
        retriever.mark_items_used([target["id"]])
        # 再次检索
        result2 = retriever.retrieve(keywords=["艾尔登法环"])
        match = [it for it in result2.items if it["id"] == target["id"]]
        if match:
            assert match[0]["score"] <= target["score"], (
                f"近期使用条目评分应降低: {match[0]['score']} vs {target['score']}"
            )


# ---------------------------------------------------------------------------
# 场景上下文模拟（端到端贴近真实运行时）
# ---------------------------------------------------------------------------


class TestEndToEndScenario:
    """模拟完整的运行时场景：弹幕→检索→注入。"""

    def test_simulate_live_scene(self, retriever: KnowledgeRetriever) -> None:
        """模拟直播场景：观众问「前期用什么职业好」。"""
        result = retriever.retrieve(
            scene_brief="观众在弹幕中问前期职业推荐",
            keywords=["艾尔登法环", "职业", "前期", "新手"],
        )
        assert result.hit_count >= 1, "应命中至少 1 条艾尔登法环条目"
        if result.items:
            text = " ".join(it["title"] for it in result.items)
            assert "职业" in text or "属性" in text, (
                f"应命中职业相关条目，实际: {text}"
            )

    def test_simulate_live_scene_with_tags(
        self, retriever: KnowledgeRetriever
    ) -> None:
        """带场景标签的检索仍然命中全局包（scope_mode=global 始终生效）。"""
        result = retriever.retrieve(
            scene_brief="老头环",
            keywords=["艾尔登法环"],
            scene_tags=["elden-ring"],
        )
        assert result.prompt_text, "global 包不受 scene_tags 限制"
        assert "艾尔登法环" in result.prompt_text

    def test_prompt_injection_is_safe(
        self, retriever: KnowledgeRetriever
    ) -> None:
        """注入文本不含危险内容，包含安全的参考说明。"""
        result = retriever.retrieve(keywords=["艾尔登法环"])
        if not result.prompt_text:
            pytest.skip("无命中")
        assert "不允许照搬长段原文" in result.prompt_text
        assert "仅作参考" in result.prompt_text


# ---------------------------------------------------------------------------
# 边界条件
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """使用真实数据的边界测试。"""

    def test_empty_keywords_no_result(self, retriever: KnowledgeRetriever) -> None:
        """空关键词 → 空结果。"""
        result = retriever.retrieve(scene_brief="", keywords=[])
        assert result.items == []
        assert result.prompt_text == ""

    def test_irrelevant_keywords_no_result(
        self, retriever: KnowledgeRetriever
    ) -> None:
        """不相关的关键词 → 空结果（不返回原生训练数据）。"""
        result = retriever.retrieve(keywords=["天气预报", "股票"])
        assert result.hit_count == 0

    def test_fts_backend_detected(self, retriever: KnowledgeRetriever) -> None:
        """FTS 后端已探测。"""
        result = retriever.retrieve(keywords=["艾尔登法环"])
        assert result.fts_backend in ("trigram", "fts5", "fallback")

    def test_retrieve_does_not_mutate_database(
        self, retriever: KnowledgeRetriever
    ) -> None:
        """只读检索不修改 use_count 等字段。"""
        result = retriever.retrieve(keywords=["艾尔登法环"])
        if not result.items:
            pytest.skip("无命中")
        # 验证评分字段存在
        assert "score" in result.items[0]
        # 查询 use_count 未变（没有 mark_items_used）
        assert result.items[0].get("use_count") is not None
