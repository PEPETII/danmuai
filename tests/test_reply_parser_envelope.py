"""``parse_ai_reply_envelope`` 测试（Phase B / Wave 7 B1）。

覆盖：
    - 纯 JSON 数组回复 → ``items`` 提取、``knowledge_used=[]``
    - JSON 对象（仅 ``comments``）→ ``items`` 提取、``knowledge_used=[]``
    - JSON 对象（``comments`` + ``knowledge_used``）→ 两者均提取
    - 纯文本回复 → 行拆分 items、``knowledge_used=[]``
    - 畸形 JSON → 兜底 heuristic、``knowledge_used=[]``
    - ``knowledge_used`` 非 list → 忽略（视为空）
    - ``knowledge_used`` 元素非字符串 → 过滤掉
    - 空 / None 输入 → ``ParsedAiReply(items=[], knowledge_used=[])``
    - 兼容既有 ``parse_ai_reply_payload`` 行为不回归

约定（AGENTS.md §A.4.1）：
    - 只跑本文件：``python -m pytest tests/test_reply_parser_envelope.py -q -x``
    - 不依赖 Qt / DanmuApp / ConfigStore
"""
from __future__ import annotations

from app.reply_parser import (
    ParsedAiReply,
    parse_ai_reply_envelope,
    parse_ai_reply_payload,
)


# ---------------------------------------------------------------------------
# 基本 items 提取（与 parse_ai_reply_payload 行为一致）
# ---------------------------------------------------------------------------


def test_envelope_pure_json_array_items_extracted_no_knowledge():
    """纯 JSON 数组回复：items 提取，knowledge_used 为空。"""
    text = '["第一条弹幕", "第二条弹幕", "这波可以"]'
    result = parse_ai_reply_envelope(text)
    assert isinstance(result, ParsedAiReply)
    assert result.items == ["第一条弹幕", "第二条弹幕", "这波可以"]
    assert result.knowledge_used == []


def test_envelope_json_object_comments_only():
    """JSON 对象（仅 comments）：items 提取，knowledge_used 为空。"""
    text = '{"comments": ["画面相关", "氛围弹幕"]}'
    result = parse_ai_reply_envelope(text)
    assert result.items == ["画面相关", "氛围弹幕"]
    assert result.knowledge_used == []


def test_envelope_json_object_comments_and_knowledge_used():
    """JSON 对象（comments + knowledge_used）：两者均提取。"""
    text = (
        '{"comments": ["葛瑞克二阶段会接龙头", "这Boss真难打"], '
        '"knowledge_used": ["item_abc123", "item_def456"]}'
    )
    result = parse_ai_reply_envelope(text)
    assert result.items == ["葛瑞克二阶段会接龙头", "这Boss真难打"]
    assert result.knowledge_used == ["item_abc123", "item_def456"]


def test_envelope_plain_text_reply():
    """纯文本回复：行拆分 items，knowledge_used 为空。"""
    text = "这是第一条\n这是第二条\n这是第三条"
    result = parse_ai_reply_envelope(text)
    assert result.items == ["这是第一条", "这是第二条", "这是第三条"]
    assert result.knowledge_used == []


def test_envelope_malformed_json_falls_back_to_heuristic():
    """畸形 JSON 走 heuristic 兜底，knowledge_used 为空。"""
    text = '{"comments":["弹幕A","弹幕B'
    result = parse_ai_reply_envelope(text)
    assert result.items  # heuristic 抽到非空
    assert "弹幕A" in result.items
    assert result.knowledge_used == []


# ---------------------------------------------------------------------------
# knowledge_used 字段防御性处理
# ---------------------------------------------------------------------------


def test_envelope_knowledge_used_not_a_list_ignored():
    """knowledge_used 非 list（如字符串 / dict / int）→ 视为空。"""
    text = '{"comments": ["真实弹幕内容"], "knowledge_used": "not_a_list"}'
    result = parse_ai_reply_envelope(text)
    assert result.items == ["真实弹幕内容"]
    assert result.knowledge_used == []


def test_envelope_knowledge_used_integer_value_ignored():
    """knowledge_used 为 int → 视为空。"""
    text = '{"comments": ["真实弹幕内容"], "knowledge_used": 42}'
    result = parse_ai_reply_envelope(text)
    assert result.items == ["真实弹幕内容"]
    assert result.knowledge_used == []


def test_envelope_knowledge_used_dict_value_ignored():
    """knowledge_used 为 dict → 视为空。"""
    text = '{"comments": ["真实弹幕内容"], "knowledge_used": {"a": 1}}'
    result = parse_ai_reply_envelope(text)
    assert result.items == ["真实弹幕内容"]
    assert result.knowledge_used == []


def test_envelope_knowledge_used_non_string_entries_filtered():
    """knowledge_used 元素非字符串（int / None / dict）→ 过滤掉，仅保留字符串。"""
    text = (
        '{"comments": ["真实弹幕内容"], '
        '"knowledge_used": ["valid_id_1", 123, null, {"x": 1}, "valid_id_2"]}'
    )
    result = parse_ai_reply_envelope(text)
    assert result.items == ["真实弹幕内容"]
    assert result.knowledge_used == ["valid_id_1", "valid_id_2"]


def test_envelope_knowledge_used_empty_string_filtered():
    """knowledge_used 中的空字符串被过滤掉。"""
    text = '{"comments": ["真实弹幕内容"], "knowledge_used": ["", "valid_id"]}'
    result = parse_ai_reply_envelope(text)
    assert result.knowledge_used == ["valid_id"]


def test_envelope_knowledge_used_empty_list():
    """knowledge_used 为空列表 → 正常返回空列表。"""
    text = '{"comments": ["真实弹幕内容"], "knowledge_used": []}'
    result = parse_ai_reply_envelope(text)
    assert result.items == ["真实弹幕内容"]
    assert result.knowledge_used == []


# ---------------------------------------------------------------------------
# 空输入与边界
# ---------------------------------------------------------------------------


def test_envelope_empty_string_input():
    """空字符串输入 → items=[]、knowledge_used=[]。"""
    result = parse_ai_reply_envelope("")
    assert result.items == []
    assert result.knowledge_used == []


def test_envelope_none_input():
    """None 输入 → items=[]、knowledge_used=[]（防御性，不抛异常）。"""
    result = parse_ai_reply_envelope(None)  # type: ignore[arg-type]
    assert result.items == []
    assert result.knowledge_used == []


def test_envelope_whitespace_only_input():
    """纯空白输入 → items=[]、knowledge_used=[]。"""
    result = parse_ai_reply_envelope("   \n  \t ")
    assert result.items == []
    assert result.knowledge_used == []


def test_envelope_json_array_no_knowledge_key():
    """JSON 数组回复（无 knowledge_used 字段）→ items 提取、knowledge_used=[]。"""
    text = '["只是一条弹幕"]'
    result = parse_ai_reply_envelope(text)
    assert result.items == ["只是一条弹幕"]
    assert result.knowledge_used == []


# ---------------------------------------------------------------------------
# 兼容既有 parse_ai_reply_payload 行为
# ---------------------------------------------------------------------------


def test_envelope_items_match_parse_ai_reply_payload_for_json_array():
    """对纯 JSON 数组，envelope.items 与 parse_ai_reply_payload 完全一致。"""
    text = '["A", "B", "C"]'
    direct = parse_ai_reply_payload(text)
    envelope = parse_ai_reply_envelope(text)
    assert envelope.items == direct


def test_envelope_items_match_parse_ai_reply_payload_for_object_envelope():
    """对 comments 信封，envelope.items 与 parse_ai_reply_payload 完全一致。"""
    text = '{"comments": ["X", "Y"]}'
    direct = parse_ai_reply_payload(text)
    envelope = parse_ai_reply_envelope(text)
    assert envelope.items == direct


def test_envelope_items_match_parse_ai_reply_payload_for_plain_text():
    """对纯文本，envelope.items 与 parse_ai_reply_payload 完全一致。"""
    text = "纯文本第一条\n纯文本第二条"
    direct = parse_ai_reply_payload(text)
    envelope = parse_ai_reply_envelope(text)
    assert envelope.items == direct


def test_envelope_with_reasoning_block_stripped():
    """带 <think>...</think> 推理块的回复：items 正常解析、knowledge_used 提取。"""
    text = (
        '<think>analysis here</think>'
        '{"comments": ["真实弹幕内容"], "knowledge_used": ["kid_1"]}'
    )
    result = parse_ai_reply_envelope(text)
    assert result.items == ["真实弹幕内容"]
    assert result.knowledge_used == ["kid_1"]


def test_envelope_truncated_knowledge_used_does_not_break_items():
    """knowledge_used 字段截断（JSON 不完整）→ items 仍能提取，不抛异常。

    ``_try_parse_json_object`` 会尝试追加 ``]}`` 等后缀修复截断 JSON，
    因此 knowledge_used 可能被成功解析；本用例只断言 items 不受影响。
    """
    text = '{"comments": ["真实弹幕内容"], "knowledge_used": ["kid_1", "kid_2'
    result = parse_ai_reply_envelope(text)
    # items 至少能从 heuristic 抽到
    assert "真实弹幕内容" in result.items
    # knowledge_used 即使被修复解析出来也必须是字符串列表（不抛异常）
    assert all(isinstance(k, str) for k in result.knowledge_used)


def test_envelope_parsed_reply_is_frozen_dataclass():
    """ParsedAiReply 是 frozen dataclass，字段不可变。"""
    result = parse_ai_reply_envelope('["x"]')
    try:
        result.items = ["y"]  # type: ignore[misc]
        raise AssertionError("ParsedAiReply should be frozen")
    except AttributeError:
        pass  # expected: frozen dataclass raises AttributeError on assignment
