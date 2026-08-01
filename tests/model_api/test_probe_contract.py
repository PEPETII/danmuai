from unittest.mock import patch

import pytest
from app.api_probe import probe_connection
from app.model_catalog import PLATFORM_CATALOGS
from app.providers.platform_registry import get_provider_definition


def _probe_cases():
    return tuple(
        (
            catalog.provider_id,
            catalog.models[0].id,
            get_provider_definition(catalog.provider_id).endpoint.default_url,
            get_provider_definition(catalog.provider_id).endpoint.api_mode,
        )
        for catalog in PLATFORM_CATALOGS
    )


@pytest.mark.parametrize("provider_id,model_id,endpoint,api_mode", _probe_cases())
def test_local_probe_is_offline_for_every_catalog_platform(provider_id, model_id, endpoint, api_mode):
    with patch("app.api_probe.httpx.Client") as client_cls:
        result = probe_connection(endpoint, "sk-probe-contract", model_id, api_mode, stage="local")

    assert result.ok is True
    assert result.provider_id == provider_id
    assert result.model_id == model_id
    assert result.stage == "local"
    client_cls.assert_not_called()


def test_unknown_custom_local_probe_is_conservative_and_offline():
    with patch("app.api_probe.httpx.Client") as client_cls:
        result = probe_connection(
            "https://custom.example.test/v1",
            "sk-probe-contract",
            "vendor/unknown-model",
            "openai-compatible",
            stage="local",
        )

    assert result.ok is True
    assert result.provider_id == "custom_openai"
    assert result.model_id == "vendor/unknown-model"
    client_cls.assert_not_called()


def test_probe_validation_and_errors_are_safe_without_real_network():
    with patch("app.api_probe.httpx.Client") as client_cls:
        missing_key = probe_connection("https://custom.example.test/v1", "", "unknown", "openai-compatible")
        missing_model = probe_connection("https://custom.example.test/v1", "sk-probe-contract", "", "openai-compatible")
        invalid_endpoint = probe_connection("not-an-endpoint", "sk-probe-contract", "unknown", "openai-compatible")

    assert missing_key.error_category == "auth_missing"
    assert missing_model.error_category == "model_not_found"
    assert invalid_endpoint.error_category == "invalid_endpoint"
    for result in (missing_key, missing_model, invalid_endpoint):
        assert "sk-probe-contract" not in result.message
    client_cls.assert_not_called()


def test_probe_result_serialization_contains_contract_fields_without_secret():
    result = probe_connection(
        "https://custom.example.test/v1",
        "sk-probe-contract",
        "vendor/unknown-model",
        "openai-compatible",
        stage="local",
    )

    payload = result.to_dict()
    assert set(payload) >= {
        "ok",
        "message",
        "stage",
        "provider_id",
        "model_id",
        "error_category",
        "capability_updates",
        "warnings",
    }
    assert "sk-probe-contract" not in repr(payload)
