"""Custom model web API service tests."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore
from app.web_api import custom_models as cm_api


@pytest.fixture
def model_app(tmp_path):
    config = ConfigStore(db_path=tmp_path / "config.db")
    app = SimpleNamespace(config=config, config_changed=MagicMock())
    return app


def test_custom_model_crud(model_app):
    created = cm_api.create_custom_model(
        model_app,
        {
            "name": "Test",
            "modelId": "test-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-test-key-1234567890",
            "provider": "custom_openai",
        },
    )
    assert created["index"] == 0

    listing = cm_api.list_custom_models(model_app)
    assert len(listing["items"]) == 1
    assert listing["items"][0]["apiKey"] == "********"

    updated = cm_api.update_custom_model(
        model_app,
        0,
        {
            "name": "Test2",
            "modelId": "test-model-2",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
        },
    )
    assert updated["item"]["name"] == "Test2"

    with_mic = cm_api.update_custom_model(
        model_app,
        0,
        {
            "name": "Test2",
            "modelId": "test-model-2",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
            "supportsMic": True,
        },
    )
    assert with_mic["item"]["supportsMic"] is True
    stored = model_app.config.get_custom_models()[0]
    assert stored["supportsMic"] is True

    cm_api.set_default_custom_model(model_app, 0)
    assert model_app.config.get_default_model_id() == "test-model-2"

    cm_api.delete_custom_model(model_app, 0)
    assert model_app.config.get_custom_models() == []


def test_resolve_probe_credentials_restores_masked_key_by_index(model_app):
    cm_api.create_custom_model(
        model_app,
        {
            "name": "Test",
            "modelId": "test-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-custom-probe-key",
            "provider": "custom_openai",
        },
    )
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            "name": "Test",
            "modelId": "renamed-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
            "provider": "custom_openai",
        },
        index=0,
    )
    assert resolved["apiKey"] == "sk-custom-probe-key"
    assert resolved["modelId"] == "renamed-model"


def test_resolve_probe_credentials_masked_key_without_existing_returns_empty(model_app):
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            "name": "New",
            "modelId": "new-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "********",
        },
        index=-1,
    )
    assert resolved["apiKey"] == ""


def test_resolve_probe_credentials_normalizes_full_endpoint_url(model_app):
    resolved = cm_api.resolve_probe_credentials(
        model_app,
        {
            "name": "Test",
            "modelId": "test-model",
            "mode": "openai-compatible",
            "endpoint": "https://openrouter.ai/api/v1/chat/completions",
            "apiKey": "sk-test",
        },
        index=-1,
    )
    assert resolved["endpoint"] == "https://openrouter.ai/api/v1"


def test_create_custom_model_normalizes_endpoint_on_save(model_app):
    created = cm_api.create_custom_model(
        model_app,
        {
            "name": "OpenRouter",
            "modelId": "openrouter-model",
            "mode": "openai",
            "endpoint": "https://openrouter.ai/api/v1/chat/completions/",
            "apiKey": "sk-save-key",
        },
    )
    stored = model_app.config.get_custom_models()[created["index"]]
    assert stored["endpoint"] == "https://openrouter.ai/api/v1"
    assert stored["mode"] == "openai-compatible"
