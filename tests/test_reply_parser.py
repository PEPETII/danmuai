from app.live_freshness import build_local_fallback_batch
from app.personae import PersonaManager
from app.reply_parser import (
    normalize_reply_batch,
    parse_ai_reply_payload,
)
from tests.fakes import FakeConfig


def test_parse_ai_reply_payload_accepts_json_array():
    items = parse_ai_reply_payload('["第一条", "第二条"]')
    assert items == ["第一条", "第二条"]


def test_parse_ai_reply_payload_object_envelope_with_comments():
    raw = (
        '{"scene_brief": "主播在打团", "comments": ["画面相关", "氛围弹幕"]}'
    )
    items = parse_ai_reply_payload(raw)
    assert items == ["画面相关", "氛围弹幕"]


def test_parse_ai_reply_payload_envelope_without_scene_brief():
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
        '{"scene_brief":"代码工具界面运行中","comments":"这是啥代码工具？",'
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
        '{"scene_brief":"弹幕工具界面待命状态","comments":"":"待命中？",'
        '"这是啥工具啊？","生成弹幕按钮亮着","运行时长刚0分",'
    )
    items = parse_ai_reply_payload(raw)
    assert "待命中？" in items
    assert "这是啥工具啊？" in items


def test_parse_ai_reply_unclosed_comments_array():
    raw = (
        '{"scene_brief":"电脑端AI弹幕生成界面运行中","comments":["这弹幕生成挺有意思啊",'
        '"这工具还能生成弹幕？","API Key报错'
    )
    items = parse_ai_reply_payload(raw)
    assert items[:2] == ["这弹幕生成挺有意思啊", "这工具还能生成弹幕？"]


def test_parse_ai_reply_rejects_punctuation_only_comments():
    raw = '{"scene_brief":"x","comments":[",", "这工具真专业！", ":"]}'
    items = parse_ai_reply_payload(raw)
    assert items == ["这工具真专业！"]


def test_parse_ai_reply_splits_duplicated_json_objects():
    obj = (
        '{"scene_brief":"程序员调试代码遇API报错","comments":["这报错看着我头大",'
        '"这日志也太详细了","API报错咋整啊"]}'
    )
    items = parse_ai_reply_payload(obj + obj)
    assert items == ["这报错看着我头大", "这日志也太详细了", "API报错咋整啊"]


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


def test_normalize_reply_batch_shortfall_when_pool_disabled():
    cfg = FakeConfig({"danmu_pool_use_custom": "0"})
    items = normalize_reply_batch(["only"], config=cfg)
    assert items == ["only"]


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
    system_pt, user_pt = manager.get_prompt("吐槽型")
    assert "固定 5 条" in system_pt
    assert "嘴碎吐槽党" in system_pt
    assert user_pt == "看图发弹幕："
    assert "前 2 条必须强相关当前画面" not in system_pt
    assert "泛用弹幕" not in system_pt


def test_builtin_persona_prompt_reflects_normal_reply_count():
    cfg = FakeConfig({"normal_reply_count": "9"})
    manager = PersonaManager(cfg)
    system_pt, _ = manager.get_prompt("吐槽型")
    assert "固定 9 条" in system_pt
    assert "嘴碎吐槽党" in system_pt
    assert "前 4 条必须强相关当前画面" not in system_pt
