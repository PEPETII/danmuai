from app.model_catalog import lookup_catalog_model
from app.providers.platform_registry import (
    get_provider_definition,
    list_model_definitions_for_provider,
)


def test_p0_capability_contract_is_explicit_and_conservative():
    assert lookup_catalog_model("deepseek-flash").supports_vision is True
    assert lookup_catalog_model("deepseek-v4-pro").supports_vision is False
    assert lookup_catalog_model("ernie-5.0").supports_vision is True
    assert lookup_catalog_model("ernie-5.1").supports_vision is False
    assert lookup_catalog_model("step-3.7-flash").supports_vision is True
    assert lookup_catalog_model("mimo-v2.6-flash").supports_vision is True


def test_lifecycle_and_availability_are_separate_fields():
    old = lookup_catalog_model("mimo-v2.5")
    assert old.status == "deprecated"
    assert old.lifecycle_status == "deprecated"
    assert old.availability == "curated"
    assert old.replacement_model_id == "mimo-v2.6-flash"


def test_deepseek_and_tokenhub_are_first_class_provider_catalogs():
    deepseek = get_provider_definition("deepseek")
    tokenhub = get_provider_definition("tencent_tokenhub")
    assert deepseek is not None and deepseek.endpoint.exact_hosts == ("api.deepseek.com",)
    assert tokenhub is not None and tokenhub.endpoint.exact_hosts == ("tokenhub.tencentmaas.com",)
    assert {model.id for model in list_model_definitions_for_provider("deepseek")} >= {
        "deepseek-flash", "deepseek-v4-pro",
    }
