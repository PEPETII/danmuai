"""W-PERSONA-MODEL-BIND-001：人格 → 自定义模型档案绑定。

测试覆盖：
1. PersonaManager 绑定 CRUD（get_model_bindings / get_model_binding / set_model_binding）
2. delete_custom 删除自定义人格时同步清除绑定
3. resolve_request_credentials_for_persona 按人格绑定解析凭证 + 各种回退场景

模块级纯函数测试，不依赖 DanmuApp / Qt / Web API。
"""

import json

import pytest

from app.ai_client_requests import (
    resolve_request_credentials,
    resolve_request_credentials_for_persona,
)
from app.config_store import ConfigStore
from app.persona_manager import PersonaManager


@pytest.fixture
def persona_config(tmp_path):
    """fresh ConfigStore + PersonaManager（tmp_path 隔离，无 Qt）。"""
    config = ConfigStore(db_path=tmp_path / "config.db")
    personae = PersonaManager(config)
    return config, personae


# 便捷构造一个完整可用的自定义模型档案（参考 tests/test_web_custom_models.py 已验证结构）
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


# ---------------------------------------------------------------------------
# PersonaManager 绑定 CRUD
# ---------------------------------------------------------------------------


def test_get_model_binding_empty_by_default(persona_config):
    """新 ConfigStore，无任何绑定，get_model_binding 返回空串。"""
    _config, personae = persona_config
    assert personae.get_model_binding("高压吐槽型") == ""
    assert personae.get_model_binding("不存在的某人格") == ""
    assert personae.get_model_bindings() == {}


def test_set_and_get_model_binding_persists(persona_config):
    """set 后 get 一致；ConfigStore 中 persona_model_bindings 键已写入。"""
    config, personae = persona_config
    personae.set_model_binding("高压吐槽型", "bound-model-1")
    assert personae.get_model_binding("高压吐槽型") == "bound-model-1"

    # 持久化到 ConfigStore（独立键，JSON 字符串）
    raw = config.get("persona_model_bindings", "{}")
    parsed = json.loads(raw)
    assert parsed == {"高压吐槽型": "bound-model-1"}


def test_clear_model_binding_with_empty_string(persona_config):
    """空串清除绑定：先 set 非空，再 set ""，get 返回 ""。"""
    _config, personae = persona_config
    personae.set_model_binding("高压吐槽型", "bound-model-1")
    assert personae.get_model_binding("高压吐槽型") == "bound-model-1"

    personae.set_model_binding("高压吐槽型", "")
    assert personae.get_model_binding("高压吐槽型") == ""
    assert "高压吐槽型" not in personae.get_model_bindings()


def test_delete_custom_persona_clears_binding(persona_config):
    """删除自定义人格时同步清除其模型绑定（避免悬挂引用）。"""
    _config, personae = persona_config
    # 先创建自定义人格 + 绑定
    personae.save_custom("自定义测试人格", "sys prompt", "user prompt")
    personae.set_model_binding("自定义测试人格", "bound-model-1")
    assert personae.get_model_binding("自定义测试人格") == "bound-model-1"

    # 删除自定义人格 → 绑定应被清除
    personae.delete_custom("自定义测试人格")
    assert personae.get_model_binding("自定义测试人格") == ""
    assert "自定义测试人格" not in personae.get_model_bindings()


def test_builtin_persona_can_bind(persona_config):
    """内置人格（如"高压吐槽型"）也能 set/get 绑定（独立键设计，不进 custom_personae schema）。"""
    _config, personae = persona_config
    personae.set_model_binding("高压吐槽型", "bound-model-1")
    assert personae.get_model_binding("高压吐槽型") == "bound-model-1"
    # 内置人格不在 custom_personae 中，但绑定仍持久化
    assert "高压吐槽型" in personae.get_model_bindings()


# ---------------------------------------------------------------------------
# resolve_request_credentials_for_persona
# ---------------------------------------------------------------------------


def _setup_global_model(config, model_id: str = "global-model") -> None:
    """配置一个全局"使用"模型档案（用于 resolve_request_credentials 回退路径）。"""
    config.set_custom_models([_make_complete_model(model_id=model_id, name="GlobalModel")])
    config.set_default_model_id(model_id)


def test_resolve_credentials_for_persona_uses_binding(persona_config):
    """绑定存在且档案完整 → 返回绑定档案的凭证（非全局）。"""
    config, personae = persona_config
    # 全局模型 = global-model
    _setup_global_model(config, model_id="global-model")
    # 追加一个绑定专用模型档案 bound-model-1
    config.set_custom_models(
        [
            _make_complete_model(model_id="global-model", name="GlobalModel"),
            _make_complete_model(model_id="bound-model-1", name="BoundModel"),
        ]
    )
    config.set_default_model_id("global-model")
    # 给"高压吐槽型"绑定 bound-model-1
    personae.set_model_binding("高压吐槽型", "bound-model-1")

    resolved = resolve_request_credentials_for_persona(config, "高压吐槽型")
    assert resolved is not None
    endpoint, api_key, model_id, _mode = resolved
    assert model_id == "bound-model-1"
    assert endpoint == "https://api.example.com/v1"
    assert api_key == "sk-bound-key-1234567890"


def test_resolve_credentials_for_persona_falls_back_when_unbound(persona_config):
    """persona_id 未在 bindings 中 → 返回全局 resolve_request_credentials 结果。"""
    config, _personae = persona_config
    _setup_global_model(config, model_id="global-model")

    global_resolved = resolve_request_credentials(config)
    assert global_resolved is not None
    assert global_resolved[2] == "global-model"

    # 未绑定的 persona_id 应回退全局
    fallback = resolve_request_credentials_for_persona(config, "未绑定的人格")
    assert fallback is not None
    assert fallback == global_resolved


def test_resolve_credentials_for_persona_falls_back_when_model_deleted(persona_config):
    """绑定的 model_id 不在 custom_models（被删除）→ 返回全局。"""
    config, personae = persona_config
    _setup_global_model(config, model_id="global-model")
    # 绑定一个不存在的 model_id
    personae.set_model_binding("高压吐槽型", "deleted-model-xyz")

    global_resolved = resolve_request_credentials(config)
    fallback = resolve_request_credentials_for_persona(config, "高压吐槽型")
    assert fallback == global_resolved
    assert fallback[2] == "global-model"


def test_resolve_credentials_for_persona_falls_back_when_incomplete(persona_config):
    """绑定档案缺 apiKey（不完整）→ 返回全局。"""
    config, personae = persona_config
    # 全局模型完整
    _setup_global_model(config, model_id="global-model")
    # 绑定专用模型档案不完整（缺 apiKey）
    incomplete = _make_complete_model(model_id="bound-incomplete", name="IncompleteModel")
    incomplete["apiKey"] = ""
    config.set_custom_models(
        [
            _make_complete_model(model_id="global-model", name="GlobalModel"),
            incomplete,
        ]
    )
    config.set_default_model_id("global-model")
    personae.set_model_binding("高压吐槽型", "bound-incomplete")

    global_resolved = resolve_request_credentials(config)
    fallback = resolve_request_credentials_for_persona(config, "高压吐槽型")
    assert fallback == global_resolved
    assert fallback[2] == "global-model"


def test_resolve_credentials_for_persona_empty_persona_id_falls_back(persona_config):
    """persona_id="" → 直接回退全局（边界用例）。"""
    config, _personae = persona_config
    _setup_global_model(config, model_id="global-model")

    global_resolved = resolve_request_credentials(config)
    fallback = resolve_request_credentials_for_persona(config, "")
    assert fallback == global_resolved
    assert fallback[2] == "global-model"
