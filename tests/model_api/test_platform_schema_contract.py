import json

from app.model_catalog import PLATFORM_CATALOGS
from app.providers.platform_registry import (
    list_model_definitions_for_provider,
    list_provider_definitions,
)

REQUIRED_PLATFORM_IDS = {
    "doubao",
    "dashscope",
    "openai",
    "google-gemini",
    "xai",
    "mistral",
    "together",
    "fireworks",
    "dashscope-intl",
    "siliconflow",
    "mimo",
    "zai",
    "zhipu",
    "moonshot",
    "hunyuan",
    "stepfun",
    "baidu-cloud",
    "openrouter",
    "modelscope",
}


def test_catalog_covers_the_batch6_platform_contract():
    catalogs_by_platform = {item.platform_id: item for item in PLATFORM_CATALOGS}

    assert len(PLATFORM_CATALOGS) >= 19
    assert REQUIRED_PLATFORM_IDS <= catalogs_by_platform.keys()
    for catalog in PLATFORM_CATALOGS:
        assert catalog.platform_id
        assert catalog.provider_id
        assert catalog.platform_label
        assert catalog.models
        assert len({model.id for model in catalog.models}) == len(catalog.models)


def test_provider_and_catalog_registry_join_on_current_ids():
    providers = {item.id: item for item in list_provider_definitions()}
    catalogs = {item.provider_id: item for item in PLATFORM_CATALOGS}

    assert set(catalogs) <= set(providers)
    for provider_id, catalog in catalogs.items():
        definition = providers[provider_id]
        model_definitions = list_model_definitions_for_provider(provider_id)

        assert definition.platform_id == catalog.platform_id
        assert {model.id for model in model_definitions} == {model.id for model in catalog.models}
        for model in model_definitions:
            assert model.provider_id == provider_id
            assert model.platform_id == catalog.platform_id
            assert model.source is None or model.source.url == next(
                item.source_url for item in catalog.models if item.id == model.id
            )


def test_provider_schema_has_safe_official_source_and_serializable_metadata():
    for definition in list_provider_definitions():
        source = definition.official_source
        payload = definition.to_export_dict()

        assert source.website is None or source.website.startswith(("http://", "https://"))
        assert source.url is None or source.url.startswith(("http://", "https://"))
        if source.source_kind == "official":
            assert source.docs_url or source.migration_url
            assert source.verified_at
        encoded = json.dumps(payload, ensure_ascii=False)
        decoded = json.loads(encoded)
        assert decoded["id"] == definition.id
        assert decoded["official_source"] == json.loads(
            json.dumps(payload["official_source"], ensure_ascii=False)
        )


def test_custom_provider_schema_is_explicitly_unknown_without_catalog_identity():
    definitions = {item.id: item for item in list_provider_definitions()}

    for provider_id in ("custom_openai", "custom_doubao"):
        definition = definitions[provider_id]
        assert definition.platform_id is None
        assert definition.endpoint.default_url == ""
        assert definition.status == "unknown"
        assert definition.official_source.source_kind == "unknown"
        assert definition.official_source.url is None
