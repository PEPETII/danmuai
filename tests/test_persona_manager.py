"""PersonaManager 持久化与加载边界测试。"""

from app.config_store import ConfigStore
from app.personae import PersonaManager


def test_load_custom_corrupt_json_falls_back_to_empty(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config.db")
    config.set("custom_personae", "{not json")

    personae = PersonaManager(config)

    assert personae._load_custom() == {}
    assert personae.list()  # 内置人格仍可用
