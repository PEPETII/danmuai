from dataclasses import asdict

from app.model_catalog import CatalogModel, ModelPrice
from app.model_providers import ProviderSpec
from app.providers.platform_definitions import (
    AuthProfile,
    CapabilityProfile,
    EndpointProfile,
    ModelDefinition,
    ModelPriceDefinition,
    OfficialSource,
    ProviderDefinition,
)


def _provider_definition(**overrides):
    base = {
        "id": "example",
        "label_zh": "示例",
        "label_en": "Example",
        "region": "international",
        "endpoint": EndpointProfile(
            default_url="https://api.example.com/v1",
            api_mode="openai-compatible",
            host_match_fragment="api.example.com",
        ),
        "auth": AuthProfile(),
        "capabilities": CapabilityProfile(transport="openai"),
        "official_source": OfficialSource(website="https://example.com"),
        "model_id_hint_zh": "模型 ID",
        "model_id_hint_en": "Model ID",
    }
    base.update(overrides)
    return ProviderDefinition(**base)


def test_extended_provider_schema_serializes_stable_fields_without_secrets():
    auth = AuthProfile(
        scheme="api_key_header",
        header_name="X-API-Key",
        api_key_header="X-API-Key",
    )
    endpoint = EndpointProfile(
        default_url="https://api.example.com/v1",
        api_mode="openai-compatible",
        id="primary",
        base_url="https://api.example.com/v1",
        exact_hosts=("api.example.com",),
        api_family="openai",
        path_prefix="/v1",
        region="international",
        status="active",
    )
    source = OfficialSource(
        website="https://example.com",
        docs_url="https://example.com/docs",
        source_kind="docs",
        url="https://example.com/docs",
        verified_at="2026-08-01",
        confidence="official",
    )
    definition = _provider_definition(
        endpoint=endpoint,
        auth=auth,
        official_source=source,
        api_families=("openai",),
        preferred_api_family="openai",
        model_discovery="static",
        status="active",
        verified_at="2026-08-01",
    )

    payload = definition.to_export_dict()

    assert payload["endpoint"]["id"] == "primary"
    assert payload["endpoint"]["base_url"] == "https://api.example.com/v1"
    assert payload["endpoint"]["exact_hosts"] == ["api.example.com"]
    assert payload["auth"]["scheme"] == "api_key_header"
    assert payload["auth"]["api_key_header"] == "X-API-Key"
    assert "apiKey" not in str(payload)
    assert "sk-" not in str(payload)
    assert payload["official_source"]["source_kind"] == "docs"
    assert payload["official_source"]["verified_at"] == "2026-08-01"
    assert payload["api_families"] == ["openai"]
    assert payload["preferred_api_family"] == "openai"
    assert payload["model_discovery"] == "static"


def test_conservative_unknown_model_capabilities_do_not_enable_mic_from_price():
    model = ModelDefinition(
        id="audio-priced",
        display_name="Audio Priced",
        price=ModelPriceDefinition(input=1.0, audio=2.0, output=3.0),
    )

    payload = model.to_dict()

    assert model.supports_mic is False
    assert payload["supports_mic"] is False
    assert payload["capabilities"] is None
    assert payload["status"] == "unknown"
    assert model.supports_vision is None
    assert payload["supports_vision"] is None


def test_model_mic_support_requires_explicit_audio_capability():
    model = ModelDefinition(
        id="explicit-audio",
        display_name="Explicit Audio",
        price=ModelPriceDefinition(input=1.0, audio=None, output=2.0),
        capabilities=CapabilityProfile(audio_input=True),
    )
    unknown = ModelDefinition(
        id="unknown-audio",
        display_name="Unknown Audio",
        price=ModelPriceDefinition(input=1.0, output=2.0),
        capabilities=CapabilityProfile(audio_input=None),
    )

    assert model.supports_mic is True
    assert model.to_dict()["capabilities"]["audio_input"] is True
    assert model.to_dict()["capabilities"]["audio"] is True
    assert unknown.supports_mic is False
    assert unknown.to_dict()["capabilities"]["audio"] is None


def test_old_provider_definition_round_trip_keeps_legacy_spec_facade():
    definition = _provider_definition(
        lifecycle_status="migrating",
        sunset_date="2026-09-30",
        official_source=OfficialSource(
            website="https://example.com",
            migration_url="https://example.com/migrate",
        ),
        notice_zh="迁移中",
        notice_en="Migrating",
    )

    legacy = definition.to_provider_spec()

    assert asdict(legacy) == asdict(
        ProviderSpec(
            id="example",
            label_zh="示例",
            label_en="Example",
            default_endpoint="https://api.example.com/v1",
            mode="openai-compatible",
            model_id_hint_zh="模型 ID",
            model_id_hint_en="Model ID",
            region="international",
            lock_mode=True,
            lock_endpoint=True,
            website="https://example.com",
            lifecycle_status="migrating",
            sunset_date="2026-09-30",
            migration_url="https://example.com/migrate",
            notice_zh="迁移中",
            notice_en="Migrating",
        )
    )
    assert definition.endpoint_profiles == (definition.endpoint,)
    assert definition.auth_profiles == (definition.auth,)
    assert definition.api_families == ("openai-compatible",)


def test_catalog_model_metadata_maps_explicit_mic_not_audio_price():
    catalog_model = CatalogModel(
        "Catalog Audio",
        "catalog-audio",
        ModelPrice(input=1.0, output=2.0, audio=3.0),
        supports_mic=True,
        supports_vision=False,
        status="active",
        replacement_model_id="catalog-audio-v2",
        source_kind="docs",
        source_url="https://example.com/docs/model",
        verified_at="2026-08-01",
        input_modalities=("text", "audio"),
        output_modalities=("text",),
    )

    from app.providers.platform_definitions import model_definition_from_catalog_model

    model = model_definition_from_catalog_model(catalog_model)

    assert model.supports_mic is True
    assert model.capabilities.audio_input is True
    assert model.supports_vision is False
    assert model.source is not None
    assert model.source.url == "https://example.com/docs/model"
    assert model.input_modalities == ("text", "audio")
