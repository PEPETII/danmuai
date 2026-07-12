import time

from app.live_freshness import build_local_fallback_batch
from app.mic_prompt import mic_insert_reply_count
from app.persona_manager import PersonaManager
from app.reply_parser import (
    _MAX_HEURISTIC_NODES,
    _heuristic_comments_from_malformed_json,
    normalize_reply_batch,
    parse_ai_reply_payload,
)

from tests.fakes import FakeConfig


def test_parse_ai_reply_payload_accepts_json_array():
    items = parse_ai_reply_payload('["第一条", "第二条"]')
    assert items == ["第一条", "第二条"]


def test_parse_ai_reply_payload_object_envelope_with_comments():
    raw = '{"comments": ["画面相关", "氛围弹幕"]}'
    items = parse_ai_reply_payload(raw)
    assert items == ["画面相关", "氛围弹幕"]


def test_parse_ai_reply_payload_invalid_json_falls_back_to_plain_line():
    """非 JSON 且无换行时整段作为单条纯文本。"""
    assert parse_ai_reply_payload("{not json") == ["{not json"]


def test_parse_ai_reply_payload_empty_array_returns_empty():
    assert parse_ai_reply_payload("[]") == []


def test_parse_ai_reply_payload_empty_and_whitespace():
    assert parse_ai_reply_payload("") == []
    assert parse_ai_reply_payload("   \n  ") == []


def test_parse_ai_reply_payload_unclosed_array_falls_back_to_plain():
    """流式截断且无法 json.loads 时退化为纯文本行。"""
    assert parse_ai_reply_payload('["only start') == ['["only start']


def test_parse_ai_reply_payload_json_object_without_comments_key():
    assert parse_ai_reply_payload('{"scene_type": "game"}') == []


def test_parse_ai_reply_payload_splits_duplicated_json_arrays():
    raw = (
        '["终于搞定这个bug啦", "修复方案挺清晰啊", "这代码界面好专业"]'
        '["终于搞定这个bug啦", "修复方案挺清晰啊", "这代码界面好专业"]'
    )
    items = parse_ai_reply_payload(raw)
    assert items == ["终于搞定这个bug啦", "修复方案挺清晰啊", "这代码界面好专业"]


def test_parse_ai_reply_malformed_comments_as_bare_strings():
    raw = (
        '{"comments":"这是啥代码工具？",'
        '"弹弹幕好有意思","界面看着好专业","启动了？这是在干啥"'
    )
    items = parse_ai_reply_payload(raw)
    assert items == [
        "这是啥代码工具？",
        "弹弹幕好有意思",
        "界面看着好专业",
        "启动了？这是在干啥",
    ]


def test_parse_ai_reply_malformed_comments_double_colon():
    raw = (
        '{"comments":"":"待命中？",'
        '"这是啥工具啊？","生成弹幕按钮亮着","运行时长刚0分",'
    )
    items = parse_ai_reply_payload(raw)
    assert "待命中？" in items
    assert "这是啥工具啊？" in items


def test_parse_ai_reply_unclosed_comments_array():
    raw = (
        '{"comments":["这弹幕生成挺有意思啊",'
        '"这工具还能生成弹幕？","API Key报错'
    )
    items = parse_ai_reply_payload(raw)
    assert items[:2] == ["这弹幕生成挺有意思啊", "这工具还能生成弹幕？"]


def test_parse_ai_reply_rejects_punctuation_only_comments():
    raw = '{"comments":[",", "这工具真专业！", ":"]}'
    items = parse_ai_reply_payload(raw)
    assert items == ["这工具真专业！"]


def test_parse_ai_reply_rejects_numbered_placeholder_comments():
    raw = '{"comments":["评论1", "comment 2", "弹幕3", "正常弹幕"]}'
    items = parse_ai_reply_payload(raw)
    assert items == ["正常弹幕"]


def test_parse_ai_reply_keeps_normal_short_comments():
    raw = '{"comments":["这波可以", "6", "真的假的"]}'
    items = parse_ai_reply_payload(raw)
    assert items == ["这波可以", "6", "真的假的"]


def test_parse_ai_reply_splits_duplicated_json_objects():
    """B03 修复后，}{ 拼接的相同对象会合并所有段 comments（去重由下游处理）。"""
    obj = (
        '{"comments":["这报错看着我头大",'
        '"这日志也太详细了","API报错咋整啊"]}'
    )
    items = parse_ai_reply_payload(obj + obj)
    # 合并后包含两段的 comments（6 条），去重由 normalize_reply_batch 处理
    assert len(items) == 6
    assert items[:3] == ["这报错看着我头大", "这日志也太详细了", "API报错咋整啊"]


def test_normalize_reply_batch_pads_to_default_five_items(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser._scene_fillers",
        lambda config=None: ["场景A", "场景B", "场景C"],
    )
    monkeypatch.setattr(
        "app.reply_parser._generic_fillers",
        lambda config=None: ["泛用1", "泛用2", "泛用3"],
    )
    items = normalize_reply_batch(["强相关1", "强相关2"])
    assert len(items) == 5
    assert items[:2] == ["强相关1", "强相关2"]
    assert len(items) == len(set(items))


def test_normalize_reply_batch_custom_partition(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser._scene_fillers",
        lambda config=None: ["场景A", "场景B", "场景C", "场景D"],
    )
    monkeypatch.setattr(
        "app.reply_parser._generic_fillers",
        lambda config=None: ["泛用1", "泛用2", "泛用3", "泛用4"],
    )
    items = normalize_reply_batch(["a"], scene_count=3, filler_count=4)
    assert len(items) == 7
    assert items[0] == "a"


def test_normalize_reply_batch_loads_custom_pool_once(tmp_path, monkeypatch):
    """G-005/F-P002: normalize_reply_batch uses id sampling, not get_custom_danmu_pool."""
    from app.config_store import ConfigStore
    from app.reply_parser import normalize_reply_batch

    store = ConfigStore(db_path=tmp_path / "normalize_pool_once.db")
    store.set("danmu_pool_use_custom", "1")
    store.set_custom_danmu_pool([f"句{i}" for i in range(20)])

    getter_calls: list[int] = []
    original_get = store.get_custom_danmu_pool

    def _count_get():
        getter_calls.append(1)
        return original_get()

    monkeypatch.setattr(store, "get_custom_danmu_pool", _count_get)

    by_ids_calls: list[int] = []
    original_by_ids = store.custom_danmu_texts_by_ids

    def _count_by_ids(ids):
        by_ids_calls.append(len(ids))
        return original_by_ids(ids)

    monkeypatch.setattr(store, "custom_danmu_texts_by_ids", _count_by_ids)

    items = normalize_reply_batch(["ai1"], config=store)
    assert len(items) == 5
    assert getter_calls == []
    assert len(by_ids_calls) == 1
    assert by_ids_calls[0] == 20
    store.close()


def test_normalize_reply_batch_shortfall_when_pool_disabled():
    cfg = FakeConfig({"danmu_pool_use_custom": "0"})
    items = normalize_reply_batch(["only"], config=cfg)
    assert items == ["only"]


def test_normalize_reply_batch_matches_mic_insert_contract(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser._scene_fillers",
        lambda config=None: ["场景A", "场景B", "场景C"],
    )
    cfg = FakeConfig({})
    items = normalize_reply_batch(
        ["mic1", "mic2"],
        scene_count=mic_insert_reply_count(cfg),
        filler_count=0,
        config=cfg,
    )
    assert len(items) == mic_insert_reply_count(cfg)
    assert items[:2] == ["mic1", "mic2"]
    assert len(items) == len(set(items))


def test_normalize_reply_batch_no_duplicate_padding(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser._scene_fillers",
        lambda config=None: ["场景A", "场景B"],
    )
    monkeypatch.setattr(
        "app.reply_parser._generic_fillers",
        lambda config=None: ["泛用1", "泛用2", "泛用3"],
    )
    items = normalize_reply_batch(["only"], scene_count=5, filler_count=0)
    assert len(items) == 5
    assert len(items) == len(set(items))
    assert items[0] == "only"
    assert "继续看下一手" not in items


def test_normalize_reply_batch_dedups_fuzzy_duplicates_within_ai_batch(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser._scene_fillers",
        lambda config=None: ["场景补位A", "场景补位B"],
    )
    monkeypatch.setattr(
        "app.reply_parser._generic_fillers",
        lambda config=None: ["泛用补位1", "泛用补位2", "泛用补位3"],
    )
    items = normalize_reply_batch(
        [
            "这波操作太秀了",
            "这波操作太秀啦",
            "主播这波操作太秀了",
            "后排围观一下",
        ]
    )
    assert len(items) == 5
    assert items[0] == "这波操作太秀了"
    assert "后排围观一下" in items
    assert "泛用补位1" in items
    assert "这波操作太秀啦" not in items
    assert "主播这波操作太秀了" not in items


def test_normalize_reply_batch_keeps_distinct_short_comments(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser._scene_fillers",
        lambda config=None: ["场景A", "场景B", "场景C"],
    )
    items = normalize_reply_batch(
        ["这波可以", "这把可以", "真的假的"],
        scene_count=3,
        filler_count=0,
    )
    assert items == ["这波可以", "这把可以", "真的假的"]


def test_english_batch_fuzzy_dedup_keeps_distinct_short_phrases(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser._scene_fillers",
        lambda config=None: [],
    )
    monkeypatch.setattr(
        "app.reply_parser._generic_fillers",
        lambda config=None: [],
    )
    items = normalize_reply_batch(
        ["that was clean", "that was close", "no way"],
        scene_count=3,
        filler_count=0,
    )
    assert items == ["that was clean", "that was close", "no way"]


def test_batch_fuzzy_dedup_still_removes_exact_duplicates(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser._scene_fillers",
        lambda config=None: [],
    )
    monkeypatch.setattr(
        "app.reply_parser._generic_fillers",
        lambda config=None: [],
    )
    items = normalize_reply_batch(
        ["nice play", "nice play", "calm down"],
        scene_count=3,
        filler_count=0,
    )
    assert items == ["nice play", "calm down"]


def test_chinese_batch_fuzzy_dedup_still_removes_near_duplicates(monkeypatch):
    monkeypatch.setattr(
        "app.reply_parser._scene_fillers",
        lambda config=None: [],
    )
    monkeypatch.setattr(
        "app.reply_parser._generic_fillers",
        lambda config=None: [],
    )
    items = normalize_reply_batch(
        [
            "这波操作太秀了",
            "这波操作太秀啦",
            "后排围观一下",
        ],
        scene_count=3,
        filler_count=0,
    )
    assert items == ["这波操作太秀了", "后排围观一下"]


def test_build_local_fallback_batch_no_intra_batch_duplicates():
    items = build_local_fallback_batch(scene_count=3, filler_count=3)
    assert len(items) == len(set(items))
    assert len(items) <= 6


def test_build_local_fallback_batch_shortfall_when_pool_exhausted(monkeypatch):
    pool = ["兜底A", "兜底B", "兜底C"]
    monkeypatch.setattr("app.danmu_pool.load_danmu_pool_for_config", lambda _cfg: pool)
    monkeypatch.setattr(
        "app.danmu_pool.sample_danmu_for_config",
        lambda _cfg, n, rng=None: pool[:n],
    )
    cfg = FakeConfig({"danmu_pool_use_custom": "1"})
    items = build_local_fallback_batch(scene_count=5, filler_count=5, config=cfg)
    assert len(items) < 10
    assert len(items) == len(set(items))


def test_build_local_fallback_batch_empty_when_pool_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.danmu_pool.load_danmu_pool_for_config",
        lambda _cfg: ["句库不应出现"] * 20,
    )
    cfg = FakeConfig({"danmu_pool_use_custom": "0"})
    items = build_local_fallback_batch(scene_count=2, filler_count=3, config=cfg)
    assert items == []


def test_builtin_persona_prompt_contains_release_contract():
    manager = PersonaManager(FakeConfig())
    system_pt, user_pt = manager.get_prompt("高压吐槽型")
    assert "固定输出5条" in system_pt
    assert "只输出JSON字符串数组格式" in system_pt
    assert "【人格：高压吐槽型】" in user_pt
    assert user_pt.endswith("看图发弹幕：")
    assert "前 2 条必须强相关当前画面" not in system_pt
    assert "泛用弹幕" not in system_pt
    assert "弹幕1" not in system_pt
    assert "comment 1" not in system_pt


def test_builtin_persona_prompt_reflects_normal_reply_count():
    cfg = FakeConfig({"normal_reply_count": "9"})
    manager = PersonaManager(cfg)
    system_pt, _ = manager.get_prompt("高压吐槽型")
    assert "固定输出9条" in system_pt
    assert "只输出JSON字符串数组格式" in system_pt
    assert "前 4 条必须强相关当前画面" not in system_pt


def test_test3_persona_prompt_no_longer_hardcodes_front_row_takeout_gossip():
    manager = PersonaManager(FakeConfig())
    _, user_pt = manager.get_prompt("抽象玩梗型")
    assert "前排出售瓜子" not in user_pt
    assert "外卖作业摸鱼" not in user_pt
    assert "吃瓜围观" not in user_pt


# --- MiniMax reasoning leakage fix (W-PR-INTAKE-020) ---


def test_parse_strips_complete_reasoning_block():
    """Complete <think>...</think> reasoning block is removed before parsing."""
    raw = '<think>let me analyze this</think>\n["第一条", "第二条"]'
    items = parse_ai_reply_payload(raw)
    assert items == ["第一条", "第二条"]


def test_parse_strips_unclosed_reasoning_open_tag():
    """Unclosed <think> reasoning block (from <think> to end) is removed."""
    raw = '["第一条", "第二条"]<think>让我想想这画面真有趣'
    items = parse_ai_reply_payload(raw)
    assert "第一条" in items
    assert "第二条" in items
    assert "让我想想" not in "".join(items)


def test_parse_strips_unclosed_reasoning_close_tag():
    """Leading unclosed ...</think> is removed."""
    raw = 'thinking content here</think>["第一条", "第二条"]'
    items = parse_ai_reply_payload(raw)
    assert items == ["第一条", "第二条"]


def test_parse_reasoning_then_json_array():
    """JSON array after reasoning block is still extracted."""
    raw = '<think>analysis</think>["精彩操作", "这波可以"]'
    items = parse_ai_reply_payload(raw)
    assert items == ["精彩操作", "这波可以"]


def test_parse_plain_text_filters_reasoning_preamble():
    """Plain-text fallback filters obvious reasoning preamble lines."""
    raw = "让我想想这画面\n这是第一条弹幕\n思考：第二条弹幕"
    items = parse_ai_reply_payload(raw)
    assert "这是第一条弹幕" in items
    # "让我想想这画面" is ambiguous (could be valid danmu), keep it
    # "思考：..." with colon is clearly reasoning preamble, filter it
    assert "思考：" not in "".join(items)
    assert "第二条弹幕" not in "".join(items)


def test_parse_plain_text_keeps_normal_lines():
    """Normal plain-text lines are not affected by reasoning filter."""
    raw = "这是第一条\n这是第二条\n这是第三条"
    items = parse_ai_reply_payload(raw)
    assert items == ["这是第一条", "这是第二条", "这是第三条"]


def test_parse_no_reasoning_tags_unchanged():
    """Text without reasoning tags is parsed normally."""
    raw = '["弹幕一", "弹幕二"]'
    items = parse_ai_reply_payload(raw)
    assert items == ["弹幕一", "弹幕二"]


# --- B03: }{ concatenated JSON objects ---


def test_parse_ai_reply_merges_concatenated_json_objects_with_different_comments():
    """B03: }{ 拼接的不同内容 JSON 对象应合并所有 comments。"""
    raw = '{"comments":["弹幕A","弹幕B"]}{"comments":["弹幕C"]}'
    items = parse_ai_reply_payload(raw)
    assert "弹幕A" in items
    assert "弹幕B" in items
    assert "弹幕C" in items


def test_parse_ai_reply_merges_concatenated_json_objects_envelope_only():
    """B03: 纯 comments 协议 }{ 拼接合并。"""
    raw = '{"comments":["弹幕A"]}{"comments":["弹幕B"]}'
    items = parse_ai_reply_payload(raw)
    assert "弹幕A" in items
    assert "弹幕B" in items


def test_parse_ai_reply_concatenated_first_segment_invalid():
    """B03: }{ 拼接时第一段无效，仍尝试解析后续段。"""
    raw = '{invalid}{"comments":["弹幕A"]}'
    items = parse_ai_reply_payload(raw)
    assert "弹幕A" in items


# --- BUG-011: deep }{ nesting (iterative stack parser) ---


def test_heuristic_handles_20_concatenated_braces_with_valid_segments():
    """BUG-011: 20+ 个连续 ``}{`` + 合法 JSON 片段不应触发 RecursionError。"""
    # Build 20 {"comments": [...]} segments joined by }{ (21 segments, 20 splitters).
    seg = '{"comments":["弹幕A"]}'
    raw = ("}{" .join([seg] * 21))
    assert raw.count("}{") == 20
    items = _heuristic_comments_from_malformed_json(raw)
    # Iterative parser should successfully extract "弹幕A" from at least one segment.
    assert "弹幕A" in items
    # The segment is duplicated 21 times; downstream _normalize_comment_list dedups.
    assert len(items) >= 1


def test_heuristic_adversarial_braces_only_returns_empty_quickly():
    """BUG-011: 1000 个 ``}{`` 但无 ``"comments"`` key → [] 且不卡死。"""
    raw = "}{" * 1000
    start = time.monotonic()
    items = _heuristic_comments_from_malformed_json(raw)
    elapsed = time.monotonic() - start
    assert items == []
    # Generous bound: the iterative parser should finish in well under a second.
    assert elapsed < 1.0


def test_heuristic_node_budget_caps_processing(monkeypatch):
    """BUG-011: _MAX_HEURISTIC_NODES 触发时停止分裂并把剩余段当 leaf 处理。"""
    # Force the budget low enough that we'll hit it on a modest input.
    monkeypatch.setattr("app.reply_parser._MAX_HEURISTIC_NODES", 8)
    # 50 segments, 49 splitters — well over the 8-node budget.
    seg = '{"comments":["弹幕B"]}'
    raw = ("}{" .join([seg] * 50))
    # Must not raise and must not recurse — returns whatever was extracted before
    # the budget cut in. The contract is "stops gracefully", not "extracts everything".
    items = _heuristic_comments_from_malformed_json(raw)
    # At least one leaf is processed before the budget triggers, so we get at
    # least one "弹幕B"; downstream dedup keeps the result unique.
    assert all(isinstance(x, str) for x in items)


def test_parse_ai_reply_payload_with_deep_nesting_does_not_recurse():
    """BUG-011: 走公共入口 ``parse_ai_reply_payload`` 时 20 层 ``}{`` 不应崩溃。"""
    seg = '{"comments":["弹幕C","弹幕D"]}'
    raw = ("}{" .join([seg] * 21))
    # Public entrypoint must not raise RecursionError.
    items = parse_ai_reply_payload(raw)
    assert "弹幕C" in items
    assert "弹幕D" in items


def test_heuristic_node_budget_constant_is_present():
    """BUG-011: 防御性常量 ``_MAX_HEURISTIC_NODES`` 存在且为正整数。"""
    assert isinstance(_MAX_HEURISTIC_NODES, int)
    assert _MAX_HEURISTIC_NODES > 0


def test_parse_truncated_json_comments_falls_back_to_heuristic():
    """BUG-011: 截断 comments 信封应经 heuristic 抽取非空弹幕。"""
    raw = '{"comments":["弹幕A","弹幕B'
    items = parse_ai_reply_payload(raw)
    assert items
    assert "弹幕A" in items


def test_parse_truncated_json_replies_envelope_uses_heuristic():
    """BUG-011: replies 信封截断也应走 heuristic，而非纯文本分支。"""
    raw = '{"replies":["弹幕一","弹幕二'
    items = parse_ai_reply_payload(raw)
    assert items
    assert "弹幕一" in items


def test_parse_truncated_json_logs_heuristic_warning(caplog):
    """BUG-011: JSON 解析失败回退 heuristic 时记录 warning。"""
    import logging

    # 无法通过后缀修补的截断对象，确保走 parse=None → heuristic 分支。
    raw = '{"comments":'
    with caplog.at_level(logging.WARNING, logger="app.reply_parser"):
        parse_ai_reply_payload(raw)
    assert any("falling back to heuristic" in rec.message for rec in caplog.records)
