from app.live_freshness import build_local_fallback_batch
from app.personae import PersonaManager
from app.reply_parser import (
    normalize_reply_batch,
    parse_ai_reply_payload,
    parse_ai_reply_with_memory,
)


class FakeConfig:
    def __init__(self, data=None):
        self._data = {}
        self._data.update(data or {})

    def get(self, key, default=""):
        return self._data.get(key, default)

    def get_json(self, key, default=None):
        return default or []

    def get_int(self, key, default=0):
        raw = self._data.get(key)
        if raw is None or raw == "":
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    def set(self, key, value):
        self._data[key] = value

    def set_json(self, key, value):
        pass


def test_parse_ai_reply_payload_accepts_json_array():
    items = parse_ai_reply_payload('["第一条", "第二条"]')
    assert items == ["第一条", "第二条"]


def test_parse_ai_reply_with_memory_envelope():
    raw = (
        '{"comments": ["画面相关", "氛围弹幕"], '
        '"scene_memory": {"scene_type": "game", "scene_summary": "团战中", "confidence": 0.9}}'
    )
    items, update = parse_ai_reply_with_memory(raw, scene_generation=3)
    assert items == ["画面相关", "氛围弹幕"]
    assert update is not None
    assert update.scene_type == "game"
    assert update.scene_summary == "团战中"
    assert update.scene_generation == 3


def test_parse_ai_reply_payload_splits_duplicated_json_arrays():
    raw = (
        '["终于搞定这个bug啦", "修复方案挺清晰啊", "这代码界面好专业"]'
        '["终于搞定这个bug啦", "修复方案挺清晰啊", "这代码界面好专业"]'
    )
    items = parse_ai_reply_payload(raw)
    assert items == ["终于搞定这个bug啦", "修复方案挺清晰啊", "这代码界面好专业"]


def test_normalize_reply_batch_pads_to_default_five_items():
    items = normalize_reply_batch(["强相关1", "强相关2"])
    assert len(items) == 5
    assert items[:2] == ["强相关1", "强相关2"]
    assert len(items) == len(set(items))


def test_normalize_reply_batch_custom_partition():
    items = normalize_reply_batch(["a"], scene_count=3, filler_count=4)
    assert len(items) == 7
    assert items[0] == "a"


def test_normalize_reply_batch_shortfall_when_pool_disabled():
    cfg = FakeConfig({"danmu_pool_enabled": "0", "danmu_pool_use_custom": "0"})
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
    monkeypatch.setattr("app.danmu_pool.load_danmu_pool", lambda: ["兜底A", "兜底B", "兜底C"])
    monkeypatch.setattr(
        "app.danmu_pool.sample_danmu",
        lambda n, rng=None: ["兜底A", "兜底B", "兜底C"][:n],
    )
    items = build_local_fallback_batch(scene_count=5, filler_count=5)
    assert len(items) < 10
    assert len(items) == len(set(items))


def test_build_local_fallback_batch_empty_when_pool_disabled(monkeypatch):
    monkeypatch.setattr(
        "app.danmu_pool.load_danmu_pool",
        lambda: ["句库不应出现"] * 20,
    )
    cfg = FakeConfig({"danmu_pool_enabled": "0", "danmu_pool_use_custom": "0"})
    items = build_local_fallback_batch(scene_count=2, filler_count=3, config=cfg)
    assert items == []


def test_builtin_persona_prompt_contains_release_contract():
    manager = PersonaManager(FakeConfig())
    system_pt, _ = manager.get_prompt("吐槽型")
    assert "固定返回 5 条弹幕" in system_pt
    assert "必须与当前画面或直播氛围相关" in system_pt
    assert "前 2 条必须强相关当前画面" not in system_pt
    assert "泛用弹幕" not in system_pt


def test_builtin_persona_prompt_reflects_normal_reply_count():
    cfg = FakeConfig({"normal_reply_count": "9"})
    manager = PersonaManager(cfg)
    system_pt, _ = manager.get_prompt("吐槽型")
    assert "固定返回 9 条弹幕" in system_pt
    assert "必须与当前画面或直播氛围相关" in system_pt
    assert "前 4 条必须强相关当前画面" not in system_pt
