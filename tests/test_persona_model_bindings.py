"""人格历史绑定兼容数据与全局模型运行时行为。"""

import json

import pytest
from app.ai_client_requests import resolve_request_credentials
from app.config_store import ConfigStore
from app.persona_manager import PersonaManager


@pytest.fixture
def persona_config(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config.db")
    return config, PersonaManager(config)


def _make_complete_model(
    name: str = "BoundModel",
    model_id: str = "bound-model-1",
    api_key: str = "sk-bound-key-1234567890",
) -> dict:
    return {
        "name": name,
        "modelId": model_id,
        "default_model_id": model_id,
        "mode": "openai",
        "endpoint": "https://api.example.com/v1",
        "apiKey": api_key,
        "provider": "custom_openai",
    }


def test_get_model_binding_empty_by_default(persona_config):
    _config, personae = persona_config
    assert personae.get_model_binding("高压吐槽型") == ""
    assert personae.get_model_bindings() == {}


def test_legacy_model_binding_data_still_persists(persona_config):
    """历史绑定保留在配置中，供兼容迁移/后续清理，不参与运行时选择。"""
    config, personae = persona_config
    personae.set_model_binding("高压吐槽型", "bound-model-1")
    assert personae.get_model_binding("高压吐槽型") == "bound-model-1"
    assert json.loads(config.get("persona_model_bindings", "{}")) == {
        "高压吐槽型": "bound-model-1"
    }


def test_clear_legacy_model_binding_remains_supported(persona_config):
    _config, personae = persona_config
    personae.set_model_binding("高压吐槽型", "bound-model-1")
    personae.set_model_binding("高压吐槽型", "")
    assert personae.get_model_binding("高压吐槽型") == ""
    assert "高压吐槽型" not in personae.get_model_bindings()


def test_delete_custom_persona_preserves_its_legacy_binding(persona_config):
    config, personae = persona_config
    personae.save_custom("自定义测试人格", "sys prompt", "user prompt")
    personae.set_model_binding("自定义测试人格", "bound-model-1")
    personae.delete_custom("自定义测试人格")
    assert json.loads(config.get("persona_model_bindings", "{}")) == {
        "自定义测试人格": "bound-model-1"
    }


def test_all_personas_resolve_same_global_profile(persona_config):
    """persona bindings remain stored but cannot change runtime credentials."""
    config, personae = persona_config
    config.set_custom_models(
        [
            _make_complete_model(name="Model A", model_id="model-a"),
            _make_complete_model(name="Model B", model_id="model-b"),
        ]
    )
    expected = resolve_request_credentials(config)
    assert expected is not None
    personae.set_model_binding("高压吐槽型", "model-b")
    assert resolve_request_credentials(config) == expected


def test_global_profile_switch_is_immediate(persona_config):
    from app.model_selection import set_active_model_profile

    config, _personae = persona_config
    config.set_custom_models(
        [
            _make_complete_model(name="Model A", model_id="model-a"),
            _make_complete_model(name="Model B", model_id="model-b"),
        ]
    )
    second = config.get_custom_models()[1]
    set_active_model_profile(config, second["profile_id"])
    resolved = resolve_request_credentials(config)
    assert resolved is not None
    assert resolved[2] == "model-b"


def test_config_store_clears_retired_global_model_keys_and_initializes_active(tmp_path):
    db_path = tmp_path / "config.db"
    store = ConfigStore(db_path=db_path)
    store.set_custom_models([_make_complete_model(model_id="first-model")])
    store.set("model", "stale-global-model")
    store.set("default_model_id", "stale-global-model")
    store.close()

    reopened = ConfigStore(db_path=db_path)
    try:
        assert reopened.get("model", "") == ""
        assert reopened.get("default_model_id", "") == ""
        assert reopened.get("active_model_profile_id", "") == reopened.get_custom_models()[0]["profile_id"]
    finally:
        reopened.close()
