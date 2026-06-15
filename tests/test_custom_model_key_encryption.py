"""Custom model apiKey encryption in ConfigStore."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.config_store import ConfigStore
from app.web_api import custom_models as cm_api


@pytest.fixture
def store(tmp_path):
    return ConfigStore(db_path=tmp_path / "config.db")


def _raw_custom_models_json(store: ConfigStore) -> str:
    row = store.conn.execute(
        "SELECT value FROM config WHERE key = ?", ("custom_models",)
    ).fetchone()
    assert row is not None
    return row[0]


def test_set_custom_models_does_not_store_plaintext_api_key(store):
    store.set_custom_models(
        [
            {
                "name": "Test",
                "modelId": "test-model",
                "mode": "openai-compatible",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "sk-test-key-1234567890",
            }
        ]
    )
    raw = _raw_custom_models_json(store)
    assert "sk-test-key-1234567890" not in raw
    assert store.get_custom_models()[0]["apiKey"] == "sk-test-key-1234567890"


def test_get_custom_models_upgrades_legacy_plaintext(store):
    legacy = [
        {
            "name": "Legacy",
            "modelId": "legacy-model",
            "mode": "openai-compatible",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-legacy-plaintext-key",
        }
    ]
    store.set_json("custom_models", legacy)
    models = store.get_custom_models()
    assert models[0]["apiKey"] == "sk-legacy-plaintext-key"
    raw = _raw_custom_models_json(store)
    assert "sk-legacy-plaintext-key" not in raw


def test_custom_model_crud_roundtrip_encrypted(store, tmp_path):
    app = SimpleNamespace(config=store, config_changed=MagicMock())
    cm_api.create_custom_model(
        app,
        {
            "name": "Roundtrip",
            "modelId": "rt-model",
            "mode": "openai",
            "endpoint": "https://api.example.com/v1",
            "apiKey": "sk-roundtrip-secret",
            "provider": "custom_openai",
        },
    )
    raw = _raw_custom_models_json(store)
    assert "sk-roundtrip-secret" not in raw
    parsed = json.loads(raw)
    assert parsed[0]["apiKey"] != "sk-roundtrip-secret"


def test_get_custom_models_decrypts_at_most_once(store):
    if not store._fernet:
        pytest.skip("cryptography not available")

    store.set_custom_models(
        [
            {
                "name": "DecryptOnce",
                "modelId": "once-model",
                "mode": "openai-compatible",
                "endpoint": "https://api.example.com/v1",
                "apiKey": "sk-decrypt-once-key",
            }
        ]
    )
    store.get_custom_models()
    store._invalidate_custom_models_cache()

    decrypt_calls: list[int] = []
    original_decrypt = store._fernet.decrypt

    def counting_decrypt(data):
        decrypt_calls.append(1)
        return original_decrypt(data)

    store._fernet.decrypt = counting_decrypt  # type: ignore[method-assign]
    models = store.get_custom_models()
    assert models[0]["apiKey"] == "sk-decrypt-once-key"
    assert len(decrypt_calls) <= 1
