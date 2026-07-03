from app.personae import (
    BUILTIN_PERSONAE,
    DEFAULT_REPLY_FILLER_COUNT,
    DEFAULT_REPLY_SCENE_COUNT,
    DEFAULT_SYSTEM_STYLE_ZH,
    LIVE_TOPIC_MAX_LEN,
    NICKNAME_MAX_LEN,
    REPLY_CONTRACT,
    append_live_topic_to_system_pt,
    append_nickname_to_system_pt,
    build_normal_reply_contract_en,
    build_normal_reply_contract_zh,
    build_reply_contract_en,
    build_reply_contract_zh,
    ensure_reply_contract,
    ensure_system_style,
    get_reply_contract,
    reply_counts_from_config,
    strip_reply_contract,
    strip_system_style,
)

from tests.fakes import FakeConfig


def test_reply_counts_from_config_defaults():
    scene, filler = reply_counts_from_config(FakeConfig())
    assert scene == DEFAULT_REPLY_SCENE_COUNT
    assert filler == DEFAULT_REPLY_FILLER_COUNT


def test_reply_counts_from_config_clamps():
    cfg = FakeConfig({"reply_scene_count": "1", "reply_filler_count": "99"})
    scene, filler = reply_counts_from_config(cfg)
    assert scene == 2
    assert filler == 7


def test_build_reply_contract_zh_dynamic():
    text = build_reply_contract_zh(4, 5)
    assert "固定输出9条" in text
    assert '"示例短句4"' in text


def test_build_reply_contract_en_dynamic():
    text = build_reply_contract_en(3, 2)
    assert "Always output exactly 5 danmu" in text


def test_build_reply_contract_zh_uses_max_chars():
    text = build_reply_contract_zh(2, 3, 25)
    assert "每条弹幕不超过25个汉字" in text


def test_build_reply_contract_en_uses_max_chars():
    text = build_reply_contract_en(2, 3, 50)
    assert "Each danmu must not exceed 50 characters" in text


def test_get_reply_contract_uses_danmu_max_chars_from_config():
    cfg = FakeConfig({"danmu_max_chars": "30"})
    contract = get_reply_contract(cfg)
    assert "每条弹幕不超过30个汉字" in contract


def test_get_reply_contract_clamps_danmu_max_chars():
    cfg = FakeConfig({"danmu_max_chars": "2"})
    contract = get_reply_contract(cfg)
    assert "每条弹幕不超过5个汉字" in contract


def test_normal_mode_contract_uses_single_reply_count():
    cfg = FakeConfig({"danmu_display_mode": "normal", "normal_reply_count": "8"})
    contract = get_reply_contract(cfg)
    assert "固定输出8条" in contract
    assert "优先贴当前画面" not in contract
    assert "前 " not in contract
    assert "后 " not in contract
    assert "泛用弹幕" not in contract


def test_build_normal_reply_contract_zh():
    text = build_normal_reply_contract_zh(6, 20)
    assert "固定输出6条" in text
    assert "JSON object" not in text
    assert '["这波可以"' in text
    assert "优先贴当前画面" not in text
    assert '"示例短句1"' in text


def test_build_normal_reply_contract_en_uses_json_array_only():
    text = build_normal_reply_contract_en(6, 20)
    assert "Always output exactly 6 danmu" in text
    assert "JSON object" not in text
    assert '"current-frame summary"' not in text


def test_build_normal_reply_contract_zh_avoids_numbered_placeholders():
    text = build_normal_reply_contract_zh(5, 20)
    assert "弹幕1" not in text
    assert "评论1" not in text


def test_build_reply_contract_en_avoids_numbered_placeholders():
    text = build_reply_contract_en(3, 2)
    assert "comment 1" not in text
    assert "comment1" not in text


def test_strip_reply_contract_removes_custom_max_chars():
    custom = build_reply_contract_zh(2, 3, 22) + " 自定义风格"
    assert strip_reply_contract(custom) == "自定义风格"


def test_strip_reply_contract_removes_legacy_and_dynamic():
    legacy = REPLY_CONTRACT + " 风格要求：轻松"
    stripped_legacy = strip_reply_contract(legacy)
    assert stripped_legacy == "风格要求：轻松"

    dynamic = build_reply_contract_zh(5, 6) + " 自定义风格"
    stripped_dynamic = strip_reply_contract(dynamic)
    assert stripped_dynamic == "自定义风格"


def test_ensure_reply_contract_replaces_old_counts():
    old = build_reply_contract_zh(2, 3) + " 保留补充"
    cfg = FakeConfig({"normal_reply_count": "4"})
    merged = ensure_reply_contract(old, cfg)
    assert "固定输出4条" in merged
    assert "保留补充" in merged


def test_strip_reply_contract_removes_new_normal_contract():
    custom = build_normal_reply_contract_zh(5, 15) + " 嘴碎吐槽党"
    assert strip_reply_contract(custom) == "嘴碎吐槽党"


def test_ensure_system_style_prefixes_default():
    assert ensure_system_style("") == DEFAULT_SYSTEM_STYLE_ZH
    assert ensure_system_style("嘴碎吐槽党") == f"{DEFAULT_SYSTEM_STYLE_ZH} 嘴碎吐槽党"


def test_strip_system_style_removes_default_prefix():
    styled = ensure_system_style("保留补充")
    assert strip_system_style(styled) == "保留补充"


def test_test1_persona_strip_roundtrip():
    system_zh = BUILTIN_PERSONAE["高压吐槽型"]["system_zh"]
    user_zh = BUILTIN_PERSONAE["高压吐槽型"]["user_zh"]
    assert "吐槽观众" in system_zh
    assert "【人格：高压吐槽型】" in user_zh
    cfg = FakeConfig({"normal_reply_count": "5"})
    merged = ensure_reply_contract(system_zh, cfg)
    assert "固定输出5条" in merged
    assert strip_system_style(strip_reply_contract(merged)) == system_zh
    assert "测试" not in BUILTIN_PERSONAE


def test_legacy_test1_persona_strip_roundtrip():
    system_zh = BUILTIN_PERSONAE["测试1"]["system_zh"]
    user_zh = BUILTIN_PERSONAE["测试1"]["user_zh"]
    assert "随机选择一种口吻" in system_zh
    assert "【人格：真实直播间五人弹幕】" in user_zh
    cfg = FakeConfig({"normal_reply_count": "5"})
    merged = ensure_reply_contract(system_zh, cfg)
    assert "固定输出5条" in merged
    assert strip_system_style(strip_reply_contract(merged)) == system_zh


# W-NICKNAME-001
def test_append_nickname_returns_prompt_unchanged_when_empty():
    base = "你是主播。\n[输出契约] ABC"
    cfg = FakeConfig({"user_nickname": ""})
    assert append_nickname_to_system_pt(base, cfg) == base


def test_append_nickname_returns_prompt_unchanged_when_key_missing():
    base = "你是主播。\n[输出契约] ABC"
    assert append_nickname_to_system_pt(base, FakeConfig()) == base


def test_append_nickname_returns_prompt_unchanged_when_only_whitespace():
    base = "你是主播。"
    cfg = FakeConfig({"user_nickname": "   "})
    assert append_nickname_to_system_pt(base, cfg) == base


def test_append_nickname_handles_none_config():
    base = "你是主播。"
    assert append_nickname_to_system_pt(base, None) == base


def test_append_nickname_appends_chinese_line_for_zh():
    base = "你是主播。"
    cfg = FakeConfig({"user_nickname": "小明"})
    out = append_nickname_to_system_pt(base, cfg)
    assert out.startswith(base)
    assert "[用户昵称：小明" in out
    assert "不要每条回复都重复" in out


def test_append_nickname_appends_english_line_for_en():
    from app.translations import Translator

    Translator.set_language("en")
    try:
        base = "You are a host."
        cfg = FakeConfig({"user_nickname": "Alice"})
        out = append_nickname_to_system_pt(base, cfg)
        assert out.startswith(base)
        assert "[User nickname: Alice" in out
        assert "do not repeat it" in out
    finally:
        Translator.set_language("zh")


def test_append_nickname_truncates_over_long_value():
    base = "你是主播。"
    long_nick = "A" * (NICKNAME_MAX_LEN + 12)
    cfg = FakeConfig({"user_nickname": long_nick})
    out = append_nickname_to_system_pt(base, cfg)
    expected_nick = long_nick[:NICKNAME_MAX_LEN]
    assert f"[用户昵称：{expected_nick}" in out
    # The truncated tail must not appear right after the nickname; the rest of the
    # suffix template (advice about repetition) is unrelated and stays.
    assert f"昵称：{expected_nick}；" in out
    assert f"昵称：{expected_nick}A" not in out


def test_append_nickname_to_empty_base_just_returns_line():
    cfg = FakeConfig({"user_nickname": "小明"})
    out = append_nickname_to_system_pt("", cfg)
    assert "[用户昵称：小明" in out
    assert out == out.strip()


# W-LIVE-TOPIC-001
def test_append_live_topic_empty_returns_unchanged():
    base = "你是主播。\n[输出契约] ABC"
    cfg = FakeConfig({"live_topic": ""})
    assert append_live_topic_to_system_pt(base, cfg) == base
    assert append_live_topic_to_system_pt(base, FakeConfig()) == base
    assert append_live_topic_to_system_pt(base, FakeConfig({"live_topic": "   "})) == base
    assert append_live_topic_to_system_pt(base, None) == base


def test_append_live_topic_basic_injection_zh():
    base = "你是主播。"
    cfg = FakeConfig({"live_topic": "今晚播《艾尔登法环》"})
    out = append_live_topic_to_system_pt(base, cfg)
    assert out.startswith(base)
    assert "[本次直播主题：今晚播《艾尔登法环》" in out
    assert "营造氛围" in out


def test_append_live_topic_basic_injection_en():
    from app.translations import Translator

    Translator.set_language("en")
    try:
        base = "You are a host."
        cfg = FakeConfig({"live_topic": "Elden Ring DLC"})
        out = append_live_topic_to_system_pt(base, cfg)
        assert out.startswith(base)
        assert "[Live stream topic: Elden Ring DLC" in out
        assert "weave it naturally" in out
    finally:
        Translator.set_language("zh")


def test_append_live_topic_truncates_long_input():
    base = "你是主播。"
    long_topic = "啊" * (LIVE_TOPIC_MAX_LEN + 300)
    cfg = FakeConfig({"live_topic": long_topic})
    out = append_live_topic_to_system_pt(base, cfg)
    expected = long_topic[:LIVE_TOPIC_MAX_LEN]
    assert f"[本次直播主题：{expected}" in out
    assert f"主题：{expected}啊" not in out


def test_nickname_then_live_topic_chain_both_present():
    base = "你是主播。"
    cfg = FakeConfig({"user_nickname": "小明", "live_topic": "黑神话悟空"})
    out = append_live_topic_to_system_pt(
        append_nickname_to_system_pt(base, cfg),
        cfg,
    )
    nick_pos = out.index("[用户昵称：小明")
    topic_pos = out.index("[本次直播主题：黑神话悟空")
    assert nick_pos < topic_pos


def test_nickname_then_live_topic_chain_topic_empty():
    base = "你是主播。"
    cfg = FakeConfig({"user_nickname": "小明", "live_topic": ""})
    out = append_live_topic_to_system_pt(
        append_nickname_to_system_pt(base, cfg),
        cfg,
    )
    assert "[用户昵称：小明" in out
    assert "[本次直播主题：" not in out
