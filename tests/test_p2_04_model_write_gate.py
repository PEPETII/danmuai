"""P2-04: public /api/config must not write custom model profiles."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.application.config_service import apply_web_config_patch
from app.config_store import ConfigStore
from app.web_console_runtime import (
    CUSTOM_MODELS_CONFIG_WRITE_ERROR,
    reject_custom_models_config_write,
)
from app.web_console_support import extract_config_payload


@pytest.mark.parametrize(
    "payload",
    [
        {"custom_models": []},
        {"data": {"custom_models": [{"default_model_id": "model-2"}]}},
    ],
)
def test_public_config_rejects_custom_models_with_stable_client_error(payload):
    with pytest.raises(
        ValueError,
        match=r"^custom_models writes must use /api/custom-models$",
    ) as exc_info:
        reject_custom_models_config_write(extract_config_payload(payload))

    assert str(exc_info.value) == CUSTOM_MODELS_CONFIG_WRITE_ERROR


def test_public_config_gate_allows_unrelated_patch():
    reject_custom_models_config_write({"danmu_speed": "2.5"})


def test_internal_config_service_custom_models_write_path_remains_available(tmp_path):
    store = ConfigStore(db_path=tmp_path / "internal_custom_models.db")
    app = SimpleNamespace(
        config=store,
        personae=MagicMock(),
        config_changed=MagicMock(),
    )

    apply_web_config_patch(
        app,
        {
            "custom_models": [
                {
                    "name": "Internal",
                    "modelId": "model-2",
                    "mode": "openai",
                    "endpoint": "https://api.example.com/v1",
                    "apiKey": "sk-internal-key-1234567890",
                }
            ]
        },
    )

    assert store.get_custom_models()[0]["default_model_id"] == "model-2"
