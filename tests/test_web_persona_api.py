"""Persona web API service tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore
from app.personae import BUILTIN_PERSONA_PINNED_FIRST, BUILTIN_PERSONAE, PersonaManager
from app.templates import TemplateManager
from app.translations import Translator
from app.web_api import persona as persona_api


@pytest.fixture
def persona_app(tmp_path):
    db = tmp_path / "config.db"
    config = ConfigStore(db_path=db)
    config.set("danmu_display_mode", "realtime")
    personae = PersonaManager(config)
    templates = TemplateManager(config)
    config_changed = MagicMock()

    # W-PERSONA-MODEL-BIND-001：façade 闭包，委托到 personae.set_model_binding
    def set_persona_model_binding(name, model_id):
        personae.set_model_binding(name, model_id)
        config_changed.emit()

    app = SimpleNamespace(
        config=config,
        personae=personae,
        templates=templates,
        config_changed=config_changed,
        set_persona_model_binding=set_persona_model_binding,
    )
    return app


def test_get_template_detail_missing_persona_raises():
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    from app.config_store import ConfigStore
    from app.personae import PersonaManager
    from app.templates import TemplateManager

    config = ConfigStore()
    app = SimpleNamespace(
        config=config,
        personae=PersonaManager(config),
        templates=TemplateManager(config),
        config_changed=MagicMock(),
    )
    with pytest.raises(ValueError, match="人格不存在"):
        persona_api.get_template_detail(app, "不存在的测试人格")


def test_get_persona_template_route_returns_400_for_missing(persona_app):
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app = persona_app
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    register_web_routes(app, bridge, lambda _authorization=None: None)
    client = TestClient(app)
    res = client.get("/api/personae/不存在的测试人格/template")
    assert res.status_code == 400
    assert "人格不存在" in res.json()["detail"]


def test_create_persona_rejects_slash_in_name(persona_app):
    with pytest.raises(ValueError, match="不能包含"):
        persona_api.create_persona(persona_app, "测试/人格")


def test_create_persona_rejects_url_reserved_chars(persona_app):
    for bad_name in ("a\\b", "a%b", "a#b", "a?b"):
        with pytest.raises(ValueError, match="不能包含"):
            persona_api.create_persona(persona_app, bad_name)


def test_create_and_save_custom_persona(persona_app):
    created = persona_api.create_persona(persona_app, "测试人格A")
    assert created["id"] == "测试人格A"

    persona_api.save_template(
        persona_app,
        "测试人格A",
        "风格轻松",
        "请生成弹幕：",
    )
    detail = persona_api.get_template_detail(persona_app, "测试人格A")
    assert "风格轻松" in detail["system_custom"]
    assert not detail["builtin"]
    assert detail["system_editable"]

    system_pt, user_pt = persona_app.personae.get_prompt("测试人格A")
    assert "风格轻松" in system_pt
    assert user_pt == "请生成弹幕："

    versions = persona_api.list_versions(persona_app, "测试人格A")
    assert len(versions) >= 1


def test_list_dedupes_builtin_with_custom_override(persona_app):
    persona_api.save_template(persona_app, "高压吐槽型", "覆盖风格", "用户提示")
    persona_api.save_template(persona_app, "熬夜陪看型", "覆盖风格2", "用户提示2")
    names = persona_app.personae.list()
    assert names.count("高压吐槽型") == 1
    assert names.count("熬夜陪看型") == 1


def test_builtin_save_system_and_user_prompt(persona_app):
    persona_api.save_template(persona_app, "高压吐槽型", "多用网络热梗", "自定义用户提示")
    detail = persona_api.get_template_detail(persona_app, "高压吐槽型")
    assert detail["builtin"]
    assert detail["system_editable"]
    assert detail["user_pt"] == "自定义用户提示"
    assert "多用网络热梗" in detail["system_custom"]

    system_pt, user_pt = persona_app.personae.get_prompt("高压吐槽型")
    assert "多用网络热梗" in system_pt
    assert user_pt == "自定义用户提示"


def test_builtin_restore_clears_saved_override(persona_app):
    persona_api.save_template(persona_app, "高压吐槽型", "临时覆盖", "自定义用户提示")
    restored = persona_api.restore_builtin_default(persona_app, "高压吐槽型")
    assert "吐槽观众" in restored["system_custom"]
    detail = persona_api.get_template_detail(persona_app, "高压吐槽型")
    assert "吐槽观众" in detail["system_custom"]
    assert "临时覆盖" not in detail["system_custom"]


def test_reply_contract_follows_normal_reply_count(persona_app):
    persona_app.config.set("normal_reply_count", "9")
    detail = persona_api.get_template_detail(persona_app, "高压吐槽型")
    contract = detail["reply_contract"]
    assert "固定输出9条" in contract
    assert "优先贴当前画面" not in contract
    assert "优先贴当前画面" not in detail["system_custom"]
    assert "前 4 条必须强相关当前画面" not in contract


def test_reply_contract_follows_danmu_max_chars(persona_app):
    persona_app.config.set("danmu_max_chars", "28")
    detail = persona_api.get_template_detail(persona_app, "高压吐槽型")
    assert "每条弹幕不超过28个汉字" in detail["reply_contract"]


def test_builtin_system_custom_differs_by_persona(persona_app):
    a = persona_api.get_template_detail(persona_app, "高压吐槽型")["system_custom"]
    b = persona_api.get_template_detail(persona_app, "阴阳锐评型")["system_custom"]
    assert a and b and a != b


def test_delete_custom_persona(persona_app):
    persona_api.create_persona(persona_app, "待删人格")
    persona_api.delete_persona(persona_app, "待删人格")
    with pytest.raises(ValueError):
        persona_api.get_template_detail(persona_app, "待删人格")


_NEW_STYLE_PERSONAE = (
    "阴阳锐评型",
    "抽象玩梗型",
)


def test_new_style_builtin_personae(persona_app):
    for name in _NEW_STYLE_PERSONAE:
        assert name in BUILTIN_PERSONAE
        detail = persona_api.get_template_detail(persona_app, name)
        assert detail["builtin"]
        assert detail["system_custom"]
        system_pt, user_pt = persona_app.personae.get_prompt(name)
        assert system_pt
        assert user_pt


def test_test_default_active_matches_pinned_first():
    assert list(PersonaManager._TEST_DEFAULT_ACTIVE) == list(BUILTIN_PERSONA_PINNED_FIRST)


def test_save_builtin_test_persona_preserves_user_zh(persona_app):
    builtin_user = BUILTIN_PERSONAE["高压吐槽型"]["user_zh"]
    persona_api.save_template(
        persona_app,
        "高压吐槽型",
        BUILTIN_PERSONAE["高压吐槽型"]["system_zh"],
        "",
    )
    _, user_pt = persona_app.personae.get_prompt("高压吐槽型")
    assert user_pt == builtin_user
    assert "【人格：高压吐槽型】" in user_pt


def test_save_legacy_builtin_persona_preserves_user_zh(persona_app):
    builtin_user = BUILTIN_PERSONAE["测试1"]["user_zh"]
    persona_api.save_template(
        persona_app,
        "测试1",
        BUILTIN_PERSONAE["测试1"]["system_zh"],
        "",
    )
    _, user_pt = persona_app.personae.get_prompt("测试1")
    assert user_pt == builtin_user
    assert "【人格：真实直播间五人弹幕】" in user_pt


def test_default_active_is_eleven_personae(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config.db")
    personae = PersonaManager(config)
    active = personae.get_active()
    assert active == list(PersonaManager.DEFAULT_ACTIVE)
    assert active == [
        "高压吐槽型",
        "熬夜陪看型",
        "阴阳锐评型",
        "抽象玩梗型",
        "测试1",
        "测试3",
        "吐槽型",
        "傲娇型",
        "腹黑型",
    ]


def test_active_personae_v4_migrates_to_v9_default(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config-v4.db")
    config.set_json("active_personae", ["路人惊讶型", "搞笑玩梗型"])
    config.set("active_personae_version", "4")
    personae = PersonaManager(config)
    active = personae.get_active()
    assert active == list(PersonaManager.DEFAULT_ACTIVE)
    assert "路人惊讶型" not in active
    assert "搞笑玩梗型" not in active
    assert config.get_int("active_personae_version") == 11


def test_active_personae_v8_resets_to_eleven_default(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config-v6.db")
    config.set_json(
        "active_personae",
        ["测试1", "测试3", "吐槽型", "萌系型", "傲娇型", "腹黑型", "毒舌型"],
    )
    config.set("active_personae_version", "8")
    personae = PersonaManager(config)
    active = personae.get_active()
    for name in (
        "高压吐槽型",
        "熬夜陪看型",
        "阴阳锐评型",
        "抽象玩梗型",
        "测试1",
        "测试3",
        "吐槽型",
        "傲娇型",
        "腹黑型",
    ):
        assert name in active
    assert "萌系型" not in active
    assert "毒舌型" not in active
    assert config.get_int("active_personae_version") == 11


_REMOVED_TRIM_002 = (
    "测试4",
    "文艺型",
    "技术型",
    "萌系型",
    "中二型",
    "治愈型",
    "毒舌型",
    "元气型",
    "社恐型",
)


def test_builtin_personae_count_is_nine(persona_app):
    names = persona_app.personae.list()
    assert len(names) == 9
    for name in PersonaManager.DEFAULT_ACTIVE:
        assert name in names
    for name in ("测试1", "测试3", "吐槽型", "傲娇型", "腹黑型"):
        assert name in names


def test_removed_builtin_purged_from_active_on_init(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config-trim-active.db")
    config.set_json(
        "active_personae",
        [
            "高压吐槽型",
            "熬夜陪看型",
            "阴阳锐评型",
            "抽象玩梗型",
            "测试1",
            "吐槽型",
            "测试4",
            "萌系型",
        ],
    )
    config.set("active_personae_version", "8")
    personae = PersonaManager(config)
    active = personae.get_active()
    for removed in _REMOVED_TRIM_002:
        assert removed not in active
    assert "测试1" in active
    assert "吐槽型" in active


def test_removed_builtin_override_purged_from_custom(tmp_path):
    import json

    config = ConfigStore(db_path=tmp_path / "config-trim-custom.db")
    config.set(
        "custom_personae",
        json.dumps(
            {
                "文艺型": {"system_pt": "override", "user_pt": "u"},
                "测试4": {"system_pt": "override4", "user_pt": "u4"},
                "吐槽型": {"system_pt": "override5", "user_pt": "u5"},
            },
            ensure_ascii=False,
        ),
    )
    config.set("active_personae_version", "8")
    PersonaManager(config)
    stored = json.loads(config.get("custom_personae", "{}"))
    assert "文艺型" not in stored
    assert "测试4" not in stored
    assert "吐槽型" in stored


def test_removed_builtin_personae_not_listed(persona_app):
    names = persona_app.personae.list()
    for removed in (
        "路人惊讶型",
        "搞笑玩梗型",
        "捧场活跃型",
        "轻度吐槽型",
        *_REMOVED_TRIM_002,
    ):
        assert removed not in names


def test_experimental_personae_pinned_first(persona_app):
    names = persona_app.personae.list()
    assert names[:4] == list(BUILTIN_PERSONA_PINNED_FIRST)
    assert "测试1" in names
    assert "吐槽型" in names
    assert "测试4" not in names
    assert "测试1" in BUILTIN_PERSONAE


def test_experimental_personae_have_prompts(persona_app):
    expected_snippets = {
        "高压吐槽型": "吐槽观众",
        "熬夜陪看型": "佛系观众",
        "阴阳锐评型": "句句带味的观众",
        "抽象玩梗型": "整活的观众",
    }
    for name in BUILTIN_PERSONA_PINNED_FIRST:
        assert name in BUILTIN_PERSONAE
        detail = persona_api.get_template_detail(persona_app, name)
        assert detail["builtin"]
        if name in expected_snippets:
            assert expected_snippets[name] in detail["system_custom"]
        system_pt, user_pt = persona_app.personae.get_prompt(name)
        assert system_pt
        assert "【人格" in user_pt
        assert user_pt.endswith("看图发弹幕：")


def test_legacy_builtin_personae_still_have_prompts(persona_app):
    expected = {
            "测试1": "随机选择一种口吻",
            "测试3": "短句、口语、碎片化",
            "吐槽型": "嘴碎吐槽党",
            "傲娇型": "嘴硬心软",
            "腹黑型": "表面客气",
        }
    for name, snippet in expected.items():
        assert name in BUILTIN_PERSONAE
        detail = persona_api.get_template_detail(persona_app, name)
        assert detail["builtin"]
        assert snippet in detail["system_custom"]


# W-LIVE-TOPIC-001
def test_export_config_includes_live_topic(persona_app):
    from app.web_console_support import export_config

    data = export_config(persona_app.config)
    assert "live_topic" in data
    assert data["live_topic"] == ""


def test_put_config_persists_live_topic(persona_app):
    from unittest.mock import MagicMock

    from app.application.config_service import apply_web_config_patch
    from app.config_store import ConfigStore
    from app.personae import append_live_topic_to_system_pt

    store = persona_app.config
    assert store.get("live_topic", "") == ""

    persona_app.config_changed = MagicMock()
    apply_web_config_patch(persona_app, {"live_topic": "今晚播《艾尔登法环》"})
    assert store.get("live_topic", "") == "今晚播《艾尔登法环》"
    persona_app.config_changed.emit.assert_called_once()

    store2 = ConfigStore(db_path=store.db_path)
    assert store2.get("live_topic", "") == "今晚播《艾尔登法环》"
    assert "[本次直播主题：今晚播《艾尔登法环》" in append_live_topic_to_system_pt(
        "你是主播。", store2
    )

    apply_web_config_patch(persona_app, {"live_topic": ""})
    assert store.get("live_topic", "") == ""
    assert append_live_topic_to_system_pt("你是主播。", store) == "你是主播。"


def test_live_topic_default_in_config_defaults():
    from app.config_defaults import CONFIG_DEFAULTS

    assert CONFIG_DEFAULTS.get("live_topic", "") == ""


def test_live_topic_in_web_config_keys():
    from app.application.config_service import WEB_CONFIG_KEYS

    assert "live_topic" in WEB_CONFIG_KEYS
    assert "live_topic" in tuple(WEB_CONFIG_KEYS)


# ---------------------------------------------------------------------------
# W-PERSONA-MODEL-BIND-001：人格 → 模型档案绑定 Web 端点
# ---------------------------------------------------------------------------


def _persona_routes_client(persona_app):
    from app.web_api.routes import register_web_routes
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    app = FastAPI()
    bridge = MagicMock()
    bridge.danmu_app = persona_app
    bridge.invoke_on_main.side_effect = lambda fn, *args, **kwargs: fn(*args, **kwargs)
    register_web_routes(app, bridge, lambda _authorization=None: None)
    return TestClient(app)


def test_put_persona_model_binding_persists(persona_app):
    client = _persona_routes_client(persona_app)
    # 绑定
    res = client.put("/api/personae/高压吐槽型/model", json={"model_id": "bound-model-1"})
    assert res.status_code == 200
    assert res.json() == {"ok": True}
    # 数据层应已写入
    assert persona_app.personae.get_model_binding("高压吐槽型") == "bound-model-1"
    # façade 应触发 config_changed
    assert persona_app.config_changed.emit.called


def test_put_persona_model_binding_empty_clears(persona_app):
    client = _persona_routes_client(persona_app)
    persona_app.personae.set_model_binding("高压吐槽型", "bound-model-1")
    assert persona_app.personae.get_model_binding("高压吐槽型") == "bound-model-1"
    # 空串清除
    res = client.put("/api/personae/高压吐槽型/model", json={"model_id": ""})
    assert res.status_code == 200
    assert persona_app.personae.get_model_binding("高压吐槽型") == ""


def test_put_persona_model_binding_url_encoded_name(persona_app):
    """中文人格名经 URL 编码后路由仍能正确解析。"""
    from urllib.parse import quote

    client = _persona_routes_client(persona_app)
    res = client.put(f"/api/personae/{quote('熬夜陪看型')}/model", json={"model_id": "m2"})
    assert res.status_code == 200
    assert persona_app.personae.get_model_binding("熬夜陪看型") == "m2"


def test_put_active_personae_empty_list_in_zh(persona_app):
    Translator.set_language("zh")
    try:
        client = _persona_routes_client(persona_app)
        res = client.put("/api/personae/active", json={"active": []})
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "请至少选择一个人格" in detail
        assert "Please select" not in detail
    finally:
        Translator.set_language("zh")


def test_put_active_personae_empty_list_in_en(persona_app):
    Translator.set_language("en")
    try:
        client = _persona_routes_client(persona_app)
        res = client.put("/api/personae/active", json={"active": []})
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "Please select at least one persona" in detail
    finally:
        Translator.set_language("zh")


def test_builtin_saved_zh_default_returns_en_prompt_when_language_en(persona_app):
    from app.web_api import persona as persona_api

    persona_api.save_template(
        persona_app,
        "高压吐槽型",
        BUILTIN_PERSONAE["高压吐槽型"]["system_zh"],
        "",
    )
    Translator.set_language("en")
    try:
        detail = persona_api.get_template_detail(persona_app, "高压吐槽型")
        assert "sharp roast viewer" in detail["system_custom"]
        assert "吐槽观众" not in detail["system_custom"]
    finally:
        Translator.set_language("zh")
        persona_api.restore_builtin_default(persona_app, "高压吐槽型")
