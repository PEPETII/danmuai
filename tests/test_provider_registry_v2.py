"""Batch 2 provider registry contracts."""

from app.model_providers import PROVIDERS
from app.providers.endpoint_resolver import API_FAMILY_OPENAI_CHAT, API_FAMILY_OPENAI_RESPONSES
from app.providers.platform_registry import (
    get_provider_definition,
    legacy_provider_specs_from_definitions,
    list_provider_definitions,
)
from app.providers.registry import match_host_entry, provider_rules_for_api


def test_registry_has_all_21_legacy_providers_and_no_secrets():
    definitions = list_provider_definitions()
    assert len(definitions) == 21
    assert [item.id for item in definitions] == [item.id for item in PROVIDERS]
    assert all(item.auth_profiles for item in definitions)
    assert all(
        profile.custom is None and profile.query_key is None
        for item in definitions
        for profile in item.auth_profiles
    )


def test_endpoint_profiles_use_exact_hostname_and_real_api_family():
    for definition in list_provider_definitions():
        profile = definition.endpoint
        if profile.default_url:
            assert profile.exact_hosts
            assert profile.exact_hosts == (profile.host_match_fragment,)
            expected = API_FAMILY_OPENAI_RESPONSES if definition.id == "doubao" else API_FAMILY_OPENAI_CHAT
            assert profile.api_family == expected
        else:
            assert profile.exact_hosts == ()
            assert profile.status == "unknown"


def test_exact_host_rejects_malicious_suffixes():
    assert match_host_entry("https://evil-openrouter.ai/api/v1") is None
    assert match_host_entry("https://api.stepfun.com.evil.test/v1") is None
    assert match_host_entry("https://openrouter.ai/api/v1").provider_id == "openrouter"


def test_stepfun_and_hunyuan_profiles_and_migration_source():
    stepfun = get_provider_definition("stepfun")
    hunyuan = get_provider_definition("hunyuan")
    assert stepfun is not None and hunyuan is not None
    assert stepfun.endpoint.exact_hosts == ("api.stepfun.com",)
    assert stepfun.official_source.docs_url == "https://platform.stepfun.com/docs/zh/api-reference/chat/chat-completion-create"
    assert hunyuan.endpoint.api_family == API_FAMILY_OPENAI_CHAT
    assert hunyuan.official_source.migration_url == "https://cloud.tencent.com/document/product/1729/131925"


def test_legacy_round_trip_and_api_rules_increment_only():
    assert tuple(item.id for item in legacy_provider_specs_from_definitions()) == tuple(item.id for item in PROVIDERS)
    rules = provider_rules_for_api()
    assert rules["schema_version"] == 2
    assert all("fragment" in item and "exact_hosts" in item and "api_family" in item for item in rules["host_entries"])
