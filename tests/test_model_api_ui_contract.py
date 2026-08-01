import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(name):
    return (ROOT / name).read_text(encoding="utf-8")


def test_model_catalog_contract_has_safe_defaults_and_unknown_capabilities():
    source = read("web/static/modules/settings-model-catalog.js")
    assert "model.main_flow_recommended" in source
    assert "const cheapest" not in source
    assert "未验证" in source
    assert "source_kind" in source and "source_url" in source
    assert "请查看平台" in source
    assert "return wrap;" not in source[source.index("function buildModelRowBadges"):source.index("function buildModelTooltipHtml")]
    assert "model.main_flow_recommended" in source
    assert "model.cheapest" not in source[source.index("pickDefaultCatalogModelId"):source.index("function formatTokenPrice")]


def test_provider_resolve_and_hunyuan_warning_contract():
    source = read("web/static/modules/settings-providers.js")
    assert "/api/model-api/resolve" in source
    assert "apiFetch" in source and "authHeaders" in source
    assert "data.provider?.id || data.provider_id" in source
    assert "response.ok" not in source
    assert "hunyuanWarning" in source
    assert "2026-09-30" in source


def test_thinking_ui_keeps_legacy_dom_and_four_states():
    settings = read("web/static/modules/settings.js")
    partial = read("web/static/partials/settings.html")
    locales = read("web/static/locales/zh/dynamic.json") + read("web/static/locales/en/dynamic.json")
    assert 'id="use_thinking"' in partial
    assert 'id="thinking_effort"' in partial
    assert 'id="thinking_always_on"' in partial
    for state in ("off", "hybrid", "always", "unknown"):
        assert f"thinking_{state}" in settings or f"thinking_{state}" in partial or f"thinking_{state}" in locales
    assert "thinkingUnknownBadge" in partial
    assert "syncThinkingAdvancedControls" in settings


def test_locales_are_valid_json():
    for language in ("zh", "en"):
        json.loads(read(f"web/static/locales/{language}/dynamic.json"))
