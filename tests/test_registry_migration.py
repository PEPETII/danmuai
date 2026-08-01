from dataclasses import asdict

from app.model_providers import (
    PROVIDERS,
    ProviderSpec,
    apply_provider_to_form,
    get_provider,
    provider_for_api,
    provider_label,
    provider_region,
)
from app.providers.platform_registry import get_provider_definition


def test_v2_to_legacy_facade_round_trip_returns_provider_spec():
    definition = get_provider_definition("stepfun")
    assert definition is not None
    legacy = get_provider("stepfun")
    assert isinstance(legacy, ProviderSpec)
    assert asdict(legacy) == asdict(definition.to_provider_spec())


def test_facade_label_and_region_are_read_from_v2_definition():
    definition = get_provider_definition("openrouter")
    assert definition is not None
    assert provider_label("openrouter", "zh") == definition.label_zh
    assert provider_label("openrouter", "en") == definition.label_en
    assert provider_region("openrouter") == definition.region


def test_apply_provider_to_form_keeps_legacy_shape_from_v2_endpoint():
    definition = get_provider_definition("stepfun")
    assert definition is not None
    form = apply_provider_to_form("stepfun")
    assert form["endpoint"] == definition.endpoint.default_url
    assert form["mode"] == definition.endpoint.api_mode
    assert form["lock_mode"] is definition.lock_mode
    assert "model_id_hint_zh" in form
    assert "model_id_hint_en" in form


def test_hunyuan_legacy_migration_field_is_distinct_from_official_source():
    definition = get_provider_definition("hunyuan")
    spec = get_provider("hunyuan")
    assert definition is not None and spec is not None
    assert spec.migration_url == "https://cloud.tencent.com/document/product/1729/111007"
    assert definition.official_source.migration_url == (
        "https://cloud.tencent.com/document/product/1729/131925"
    )
    payload = provider_for_api(spec)
    assert payload["migration"] == {
        "legacy_url": spec.migration_url,
        "official_url": definition.official_source.migration_url,
    }


def test_unknown_provider_uses_safe_legacy_fallbacks_without_secrets():
    assert get_provider("unknown-provider") is None
    assert provider_region("unknown-provider") == "china"
    assert provider_label("unknown-provider") == provider_label("custom_openai")
    form = apply_provider_to_form("unknown-provider")
    assert form["endpoint"] == ""
    assert form["mode"] == "openai-compatible"
    payload = provider_for_api(PROVIDERS[-2])
    assert "apiKey" not in payload
    assert "secret" not in str(payload).lower()
