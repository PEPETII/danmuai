"""PersonaManager 持久化与加载边界测试。"""

import json

from app.config_store import ConfigStore
from app.persona_manager import PersonaManager
from app.templates import TemplateManager


def test_load_custom_corrupt_json_falls_back_to_empty(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config.db")
    config.set("custom_personae", "{not json")

    personae = PersonaManager(config)

    assert personae._load_custom() == {}
    assert personae.list()  # 内置人格仍可用


def test_renamed_persona_migrates_active_custom_label_and_template_history(tmp_path):
    config = ConfigStore(db_path=tmp_path / "legacy-persona.db")
    config.set_json(
        "active_personae", ["测试1", "测试3", "腹黑型", "高压吐槽型"]
    )
    config.set("active_personae_version", "11")
    config.set(
        "custom_personae",
        json.dumps(
            {"测试1": {"system_pt": "旧覆盖", "user_pt": "旧用户提示"}},
            ensure_ascii=False,
        ),
    )
    config.set("persona_labels", json.dumps({"测试1": "水之女神"}, ensure_ascii=False))
    config.conn.execute(
        "INSERT INTO templates (name, version, system_pt, user_pt, created_at) "
        "VALUES (?,?,?,?,?)",
        ("测试1", 1, "历史系统提示", "历史用户提示", "2026-10-04T00:00:00"),
    )
    config.conn.commit()

    personae = PersonaManager(config)
    templates = TemplateManager(config)

    assert personae.get_active() == ["阿库娅", "银狼", "胡桃", "高压吐槽型"]
    stored_custom = json.loads(config.get("custom_personae", "{}"))
    stored_labels = json.loads(config.get("persona_labels", "{}"))
    assert "测试1" not in stored_custom
    assert stored_custom["阿库娅"]["system_pt"] == "旧覆盖"
    assert "测试1" not in stored_labels
    assert stored_labels["阿库娅"] == "水之女神"
    assert "旧覆盖" in personae.get_prompt("阿库娅")[0]
    assert templates.versions("阿库娅")[0]["user_pt"] == "历史用户提示"
    assert templates.versions("测试1") == []
    assert config.get_int("active_personae_version") == 12
