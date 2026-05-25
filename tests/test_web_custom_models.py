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

    cm_api.set_default_custom_model(model_app, 0)
    assert model_app.config.get_default_model_id() == "test-model-2"

    cm_api.delete_custom_model(model_app, 0)
    assert model_app.config.get_custom_models() == []
