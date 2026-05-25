from app.personae import (
    DEFAULT_REPLY_FILLER_COUNT,
    DEFAULT_REPLY_SCENE_COUNT,
    REPLY_CONTRACT,
    build_normal_reply_contract_zh,
    build_reply_contract_en,
    build_reply_contract_zh,
    ensure_reply_contract,
    get_reply_contract,
    reply_counts_from_config,
    strip_reply_contract,
)


class FakeConfig:
    def __init__(self, data=None):
        self._data = dict(data or {})

    def get(self, key, default=""):
        return self._data.get(key, default)

    def get_int(self, key, default=0):
        raw = self._data.get(key)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default


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
    assert "固定返回 9 条弹幕" in text
    assert "前 4 条必须强相关当前画面" in text
    assert "后 5 条必须是适合直播间氛围的泛用弹幕" in text
    assert '"弹幕9"' in text


def test_build_reply_contract_en_dynamic():
    text = build_reply_contract_en(3, 2)
    assert "Always return exactly 5 comments" in text
    assert "the first 3 must be strongly tied" in text
    assert "the last 2 must be generic danmu" in text


def test_build_reply_contract_zh_uses_max_chars():
    text = build_reply_contract_zh(2, 3, 25)
    assert "每条不超过 25 个字" in text


def test_build_reply_contract_en_uses_max_chars():
    text = build_reply_contract_en(2, 3, 50)
    assert "Each comment must stay within 50 characters" in text


def test_get_reply_contract_uses_danmu_max_chars_from_config():
    cfg = FakeConfig({"danmu_max_chars": "30"})
    contract = get_reply_contract(cfg)
    assert "每条不超过 30 个字" in contract


def test_get_reply_contract_clamps_danmu_max_chars():
    cfg = FakeConfig({"danmu_max_chars": "2"})
    contract = get_reply_contract(cfg)
    assert "每条不超过 5 个字" in contract


def test_normal_mode_contract_uses_single_reply_count():
    cfg = FakeConfig({"danmu_display_mode": "normal", "normal_reply_count": "8"})
    contract = get_reply_contract(cfg)
    assert "固定返回 8 条弹幕" in contract
    assert "必须与当前画面或直播氛围相关" in contract
    assert "前 " not in contract
    assert "后 " not in contract
    assert "泛用弹幕" not in contract


def test_build_normal_reply_contract_zh():
    text = build_normal_reply_contract_zh(6, 20)
    assert "固定返回 6 条弹幕" in text
    assert '"弹幕6"' in text


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
    cfg = FakeConfig({"reply_scene_count": "4", "reply_filler_count": "3"})
    merged = ensure_reply_contract(old, cfg)
    assert "前 4 条必须强相关当前画面" in merged
    assert "后 3 条必须是适合直播间氛围的泛用弹幕" in merged
    assert "保留补充" in merged
    assert "前 2 条必须强相关当前画面" not in merged
