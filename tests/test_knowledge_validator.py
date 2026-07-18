"""tests/test_knowledge_validator.py — 校验器测试（A5.1 / A5.3）。

覆盖（spec §ADDED Requirements / Validation and Deduplication + 用户任务描述）：
    - 所有字段合法：返回 valid items
    - kind 非法：errors 含该 item
    - title 超长（50 字）：裁剪到 40 字（不报错）
    - content 超长（200 字）：裁剪到 160 字（不报错）
    - examples 超长（10 条 × 50 字）：截断到 5 条 + 每条裁剪到 30 字
    - triggers 超过 10 个：截断到 10 个
    - tones 超过 5 个：截断到 5 个
    - scopes 超过 8 个：截断到 8 个
    - entities 超过 8 个：截断到 8 个
    - confidence=1.5：夹紧到 1.0（不报错）
    - confidence=-0.5：夹紧到 0.0（不报错）
    - evidence 超长（200 字）：裁剪到 160 字
    - evidence 不在 chunk_content 中：清空（设为 ""）
    - evidence 在 chunk_content 中：保留
    - items 为空：返回 ([], [])
    - 缺 document_kind：仍校验 items
    - validate_batch_strict 成功 / 失败抛 ValidationError

约定（AGENTS.md §A.4.1）：
    - 只跑本文件：``python -m pytest tests/test_knowledge_validator.py -q -x``
    - 不依赖 Qt / DanmuApp / ConfigStore
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.knowledge.validator import validate_batch, validate_batch_strict


# ---------------------------------------------------------------------------
# 辅助：构造合法 item / chunk
# ---------------------------------------------------------------------------


def _make_valid_item(**overrides) -> dict:
    """构造一个所有字段都合法的 item dict。"""
    item = {
        "kind": "fact",
        "title": "葛瑞克二阶段",
        "content": "葛瑞克二阶段会断臂接上龙头并使用喷火攻击。",
        "examples": ["这波没绷住", "经典"],
        "triggers": ["葛瑞克", "二阶段", "龙头", "喷火"],
        "tones": ["轻松", "调侃"],
        "scopes": ["游戏", "艾尔登法环"],
        "entities": ["接肢葛瑞克"],
        "confidence": 0.94,
        "evidence": "葛瑞克二阶段",
    }
    item.update(overrides)
    return item


def _make_valid_batch(items: list[dict] | None = None, **overrides) -> dict:
    """构造一个合法的 batch dict。"""
    batch = {
        "document_kind": "game_knowledge",
        "items": items if items is not None else [_make_valid_item()],
    }
    batch.update(overrides)
    return batch


_CHUNK_WITH_EVIDENCE = (
    "葛瑞克是艾尔登法环中的一个 Boss。葛瑞克二阶段会断臂接上龙头并使用喷火攻击。"
    "玩家需要在适当的时候闪避。"
)


# ---------------------------------------------------------------------------
# 基础：合法输入
# ---------------------------------------------------------------------------


class TestValidateBatchValid:
    """validate_batch 合法输入场景。"""

    def test_all_fields_valid_returns_valid_items(self) -> None:
        """所有字段合法 → 返回 valid items（dict 列表）。"""
        parsed = _make_valid_batch()
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert len(valid) == 1
        item = valid[0]
        assert item["kind"] == "fact"
        assert item["title"] == "葛瑞克二阶段"
        assert item["content"] == "葛瑞克二阶段会断臂接上龙头并使用喷火攻击。"
        assert item["confidence"] == pytest.approx(0.94)
        assert item["evidence"] == "葛瑞克二阶段"
        assert item["examples"] == ["这波没绷住", "经典"]
        assert item["triggers"] == ["葛瑞克", "二阶段", "龙头", "喷火"]

    def test_empty_items_returns_empty(self) -> None:
        """items 为空 → 返回 ([], [])。"""
        parsed = {"document_kind": "game", "items": []}
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
        assert valid == []
        assert errors == []

    def test_missing_document_kind_still_validates_items(self) -> None:
        """缺 document_kind → 仍校验 items。"""
        parsed = {"items": [_make_valid_item()]}
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
        assert errors == []
        assert len(valid) == 1

    def test_multiple_valid_items(self) -> None:
        """多个合法 item 全部返回。"""
        items = [
            _make_valid_item(title=f"标题{i}", content=f"内容{i}")
            for i in range(3)
        ]
        parsed = _make_valid_batch(items=items)
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
        assert errors == []
        assert len(valid) == 3
        assert valid[0]["title"] == "标题0"
        assert valid[2]["title"] == "标题2"


# ---------------------------------------------------------------------------
# kind 校验（拒绝）
# ---------------------------------------------------------------------------


class TestValidateBatchKind:
    """kind 枚举校验：非法 → 拒绝（加入 errors）。"""

    def test_invalid_kind_added_to_errors(self) -> None:
        """kind 非法 → errors 含该 item。"""
        item = _make_valid_item(kind="invalid_kind")
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert valid == []
        assert len(errors) == 1
        assert "item[0]" in errors[0]
        assert "invalid_kind" in errors[0] or "kind" in errors[0].lower()

    def test_valid_kinds_all_accepted(self) -> None:
        """4 种合法 kind 全部接受。"""
        kinds = ["fact", "style_example", "reaction_pattern", "meme"]
        items = [_make_valid_item(kind=k, content=f"{k}内容") for k in kinds]
        parsed = _make_valid_batch(items=items)
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
        assert errors == []
        assert len(valid) == 4
        assert [v["kind"] for v in valid] == kinds

    def test_mixed_valid_and_invalid_kinds(self) -> None:
        """合法与非法混合：合法保留，非法进 errors。"""
        items = [
            _make_valid_item(title="合法", content="合法内容"),
            _make_valid_item(kind="bad_kind", title="非法", content="非法内容"),
        ]
        parsed = _make_valid_batch(items=items)
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
        assert len(valid) == 1
        assert valid[0]["title"] == "合法"
        assert len(errors) == 1
        assert "item[1]" in errors[0]


# ---------------------------------------------------------------------------
# 字段超长：裁剪（不报错）
# ---------------------------------------------------------------------------


class TestValidateBatchTruncation:
    """字段超长时裁剪而非拒绝。"""

    def test_title_too_long_truncated_to_40(self) -> None:
        """title 超长（50 字）→ 裁剪到 40 字（不报错）。"""
        long_title = "标题" * 25  # 50 字
        item = _make_valid_item(title=long_title)
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert len(valid) == 1
        assert len(valid[0]["title"]) == 40
        assert valid[0]["title"] == long_title[:40]

    def test_content_within_500_not_truncated(self) -> None:
        """content 200 字 ≤ 500 上限 → 不裁剪。"""
        long_content = "内容" * 100  # 200 字
        item = _make_valid_item(content=long_content, evidence="")
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert len(valid) == 1
        assert len(valid[0]["content"]) == 200
        assert valid[0]["content"] == long_content

    def test_examples_too_many_and_too_long_truncated(self) -> None:
        """examples 超长（10 条 × 50 字）→ 截断到 5 条 + 每条裁剪到 30 字。"""
        long_examples = ["例句" * 25 for _ in range(10)]  # 10 条，每条 50 字
        item = _make_valid_item(examples=long_examples)
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert len(valid) == 1
        result_examples = valid[0]["examples"]
        assert len(result_examples) == 5
        for ex in result_examples:
            assert len(ex) == 30

    def test_triggers_too_many_truncated_to_10(self) -> None:
        """triggers 超过 10 个 → 截断到 10 个。"""
        triggers = [f"触发词{i}" for i in range(15)]
        item = _make_valid_item(triggers=triggers)
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert len(valid[0]["triggers"]) == 10
        assert valid[0]["triggers"] == triggers[:10]

    def test_tones_too_many_truncated_to_5(self) -> None:
        """tones 超过 5 个 → 截断到 5 个。"""
        tones = [f"语气{i}" for i in range(8)]
        item = _make_valid_item(tones=tones)
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert len(valid[0]["tones"]) == 5
        assert valid[0]["tones"] == tones[:5]

    def test_scopes_too_many_truncated_to_8(self) -> None:
        """scopes 超过 8 个 → 截断到 8 个。"""
        scopes = [f"范围{i}" for i in range(12)]
        item = _make_valid_item(scopes=scopes)
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert len(valid[0]["scopes"]) == 8
        assert valid[0]["scopes"] == scopes[:8]

    def test_entities_too_many_truncated_to_8(self) -> None:
        """entities 超过 8 个 → 截断到 8 个。"""
        entities = [f"实体{i}" for i in range(12)]
        item = _make_valid_item(entities=entities)
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert len(valid[0]["entities"]) == 8
        assert valid[0]["entities"] == entities[:8]


# ---------------------------------------------------------------------------
# confidence 夹紧（不报错）
# ---------------------------------------------------------------------------


class TestValidateBatchConfidenceClamp:
    """confidence 越界 → 夹紧到 [0, 1]（不报错）。"""

    def test_confidence_above_1_clamped_to_1(self) -> None:
        """confidence=1.5 → 夹紧到 1.0（不报错）。"""
        item = _make_valid_item(confidence=1.5)
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert valid[0]["confidence"] == pytest.approx(1.0)

    def test_confidence_below_0_clamped_to_0(self) -> None:
        """confidence=-0.5 → 夹紧到 0.0（不报错）。"""
        item = _make_valid_item(confidence=-0.5)
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert valid[0]["confidence"] == pytest.approx(0.0)

    def test_confidence_boundary_values(self) -> None:
        """confidence 边界值 0.0 和 1.0 不变。"""
        for conf in [0.0, 1.0, 0.5]:
            item = _make_valid_item(confidence=conf)
            parsed = _make_valid_batch(items=[item])
            valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
            assert errors == []
            assert valid[0]["confidence"] == pytest.approx(conf)


# ---------------------------------------------------------------------------
# evidence 来源校验
# ---------------------------------------------------------------------------


class TestValidateBatchEvidence:
    """evidence 来源校验：不在 chunk 中 → 清空；超长 → 裁剪。"""

    def test_evidence_within_500_not_truncated(self) -> None:
        """evidence 200 字 ≤ 500 上限 → 不裁剪。"""
        long_evidence = "证据" * 100  # 200 字
        chunk = f"前文 {long_evidence} 后文"
        item = _make_valid_item(evidence=long_evidence)
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, chunk)

        assert errors == []
        assert len(valid[0]["evidence"]) == 200
        assert valid[0]["evidence"] == long_evidence

    def test_evidence_not_in_chunk_cleared(self) -> None:
        """evidence 不在 chunk_content 中 → 清空（设为 ""）。"""
        item = _make_valid_item(evidence="这段证据是AI伪造的不在原文中")
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert valid[0]["evidence"] == ""

    def test_evidence_in_chunk_preserved(self) -> None:
        """evidence 在 chunk_content 中 → 保留。"""
        item = _make_valid_item(evidence="葛瑞克二阶段")
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert valid[0]["evidence"] == "葛瑞克二阶段"

    def test_evidence_empty_string_stays_empty(self) -> None:
        """evidence 为空字符串 → 保持空。"""
        item = _make_valid_item(evidence="")
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert valid[0]["evidence"] == ""

    def test_evidence_non_string_cleared(self) -> None:
        """evidence 非字符串 → 清空。"""
        item = _make_valid_item(evidence=12345)  # type: ignore[arg-type]
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)

        assert errors == []
        assert valid[0]["evidence"] == ""


# ---------------------------------------------------------------------------
# 缺失/空必填字段：拒绝
# ---------------------------------------------------------------------------


class TestValidateBatchRequiredFields:
    """必填字段缺失或空 → 拒绝。"""

    def test_empty_title_rejected(self) -> None:
        """title 为空字符串 → 拒绝。"""
        item = _make_valid_item(title="")
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
        assert valid == []
        assert len(errors) == 1
        assert "item[0]" in errors[0]

    def test_empty_content_rejected(self) -> None:
        """content 为空字符串 → 拒绝。"""
        item = _make_valid_item(content="")
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
        assert valid == []
        assert len(errors) == 1
        assert "item[0]" in errors[0]

    def test_missing_kind_rejected(self) -> None:
        """缺少 kind 字段 → 拒绝。"""
        item = _make_valid_item()
        del item["kind"]
        parsed = _make_valid_batch(items=[item])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
        assert valid == []
        assert len(errors) == 1

    def test_item_not_dict_added_to_errors(self) -> None:
        """item 不是 dict → 加入 errors。"""
        parsed = _make_valid_batch(items=["not a dict", 42])
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
        assert valid == []
        assert len(errors) == 2
        assert "item[0]" in errors[0]
        assert "item[1]" in errors[1]


# ---------------------------------------------------------------------------
# 异常输入
# ---------------------------------------------------------------------------


class TestValidateBatchMalformedInput:
    """parsed 异常输入兜底。"""

    def test_parsed_not_dict_returns_error(self) -> None:
        """parsed 不是 dict → 返回 ([], [error])。"""
        valid, errors = validate_batch("not a dict", _CHUNK_WITH_EVIDENCE)  # type: ignore[arg-type]
        assert valid == []
        assert len(errors) == 1
        assert "not a dict" in errors[0]

    def test_items_not_list_returns_error(self) -> None:
        """items 不是 list → 返回 ([], [error])。"""
        parsed = {"document_kind": "game", "items": "not a list"}
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
        assert valid == []
        assert len(errors) == 1

    def test_missing_items_key_treated_as_empty(self) -> None:
        """缺 items key → 当作空列表。"""
        parsed = {"document_kind": "game"}
        valid, errors = validate_batch(parsed, _CHUNK_WITH_EVIDENCE)
        assert valid == []
        assert errors == []


# ---------------------------------------------------------------------------
# validate_batch_strict
# ---------------------------------------------------------------------------


class TestValidateBatchStrict:
    """validate_batch_strict 严格校验。"""

    def test_strict_valid_batch_returns_response(self) -> None:
        """合法 batch → 返回 KnowledgeBatchResponse。"""
        from app.knowledge.models import KnowledgeBatchResponse

        parsed = _make_valid_batch()
        result = validate_batch_strict(parsed)

        assert isinstance(result, KnowledgeBatchResponse)
        assert result.document_kind == "game_knowledge"
        assert len(result.items) == 1
        assert result.items[0].kind == "fact"

    def test_strict_invalid_kind_raises(self) -> None:
        """非法 kind → 抛 ValidationError。"""
        parsed = _make_valid_batch(items=[_make_valid_item(kind="bad_kind")])
        with pytest.raises(ValidationError):
            validate_batch_strict(parsed)

    def test_strict_title_too_long_raises(self) -> None:
        """title 超长 → 抛 ValidationError（strict 不裁剪）。"""
        item = _make_valid_item(title="标题" * 25)  # 50 字
        parsed = _make_valid_batch(items=[item])
        with pytest.raises(ValidationError):
            validate_batch_strict(parsed)

    def test_strict_confidence_out_of_range_raises(self) -> None:
        """confidence=1.5 → 抛 ValidationError（strict 不夹紧）。"""
        item = _make_valid_item(confidence=1.5)
        parsed = _make_valid_batch(items=[item])
        with pytest.raises(ValidationError):
            validate_batch_strict(parsed)

    def test_strict_empty_items_ok(self) -> None:
        """空 items 列表 → 合法（items 有默认值）。"""
        parsed = {"document_kind": "game", "items": []}
        result = validate_batch_strict(parsed)
        assert result.items == []

    def test_strict_not_dict_raises_type_error(self) -> None:
        """parsed 不是 dict → 抛 TypeError。"""
        with pytest.raises(TypeError):
            validate_batch_strict("not a dict")  # type: ignore[arg-type]
