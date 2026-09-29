"""Web custom-model API key masking and masked-update contract."""

from types import SimpleNamespace
from unittest.mock import MagicMock

from app.config_store import ConfigStore
from app.web_api import custom_models as cm_api


def test_listing_masks_key_and_masked_update_keeps_original(tmp_path):
    app = SimpleNamespace(
        config=ConfigStore(db_path=tmp_path / "config.db"),
        config_changed=MagicMock(),
    )
    cm_api.create_custom_model(
        app,
        {
            "name": "Masked roundtrip",
            "model_ids": ["masked-model"],
            "default_model_id": "masked-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-persistent-secret",
            "provider": "custom_openai",
        },
    )
    existing = app.config.get_custom_models()[0]

    cm_api.update_custom_model(
        app,
        0,
        {
            "name": "Masked roundtrip",
            "profile_id": existing["profile_id"],
            "model_ids": ["masked-model"],
            "model_names": {"masked-model": "Masked roundtrip"},
            "default_model_id": "masked-model",
            "max_tokens": 512,
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": cm_api.MASKED_KEY,
            "provider": "custom_openai",
        },
    )

    stored = app.config.get_custom_models()[0]
    assert stored["apiKey"] == "sk-persistent-secret"

    listing = cm_api.list_custom_models(app)
    assert listing["items"][0]["apiKey"] == cm_api.MASKED_KEY
    assert "sk-persistent-secret" not in str(listing)
