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
    assert "formatProviderStatusPart" in source
    assert "formatProviderSourcePart" in source
    assert "hasProviderWarningContext" in source
    assert "kind !== 'unknown'" in source
    assert "formatProviderSourcePart(provider.source)" in source
    assert "provider.source].filter" not in source


def test_provider_status_hides_unknown_source_for_active_providers():
    from app.model_providers import get_provider, provider_for_api

    doubao = provider_for_api(get_provider("doubao"))
    mimo = provider_for_api(get_provider("mimo"))
    assert doubao.get("status") == "active"
    assert mimo.get("status") == "active"
    assert doubao["source"]["source_kind"] == "unknown"
    assert mimo["source"]["source_kind"] == "unknown"
    assert doubao["source"]["url"]
    assert mimo["source"]["url"]


def test_thinking_ui_is_per_model_advanced_configuration():
    settings = read("web/static/partials/settings.html")
    modal = read("web/static/partials/modals.html")
    form_js = read("web/static/modules/settings-model-modal-form.js")
    assert 'id="use_thinking"' not in settings
    assert 'id="thinking_effort"' not in settings
    assert 'id="thinking_always_on"' not in settings
    assert 'id="modelThinkingEffort"' in modal
    for value in ("off", "low", "medium", "high", "xhigh", "max"):
        assert f'value="{value}"' in modal
    assert "thinking_effort" in form_js


def test_temperature_ui_is_per_model_advanced_configuration():
    settings = read("web/static/partials/settings.html")
    modal = read("web/static/partials/modals.html")
    form_js = read("web/static/modules/settings-model-modal-form.js")
    assert 'id="temperature"' not in settings
    assert 'id="modelTemperature"' in modal
    assert 'min="0"' in modal
    assert 'max="2"' in modal
    assert 'step="0.1"' in modal
    assert "temperature" in form_js
    assert "parseModelTemperatureInput" in form_js
    assert "temperature_support" in read("web/static/modules/settings-model-modal-state.js")
    assert "模型不支持_Temperature" in read("web/static/locales/zh/dynamic.json")


def test_locales_are_valid_json():
    for language in ("zh", "en"):
        json.loads(read(f"web/static/locales/{language}/dynamic.json"))


def _sync_model_modal_mic_block(source: str) -> str:
    marker = "function syncModelMicForDefault"
    start = source.index(marker)
    end = source.index("export function expandModelModalAdvanced", start)
    return source[start:end]


def test_model_modal_mic_switch_allows_user_override():
    """Default-model catalog gates mic; saved value preserved on open only."""
    source = read("web/static/modules/settings-model-modal-state.js")
    form_src = read("web/static/modules/settings-model-modal-form.js")
    mic_block = _sync_model_modal_mic_block(source)

    assert "mic.disabled = true" in mic_block
    assert "preserveSaved" in mic_block
    assert "catalogModel.supports_mic" in mic_block
    assert "supportsMicEl.checked = Boolean(model.supportsMic)" in form_src
    assert "supportsMic: Boolean(document.getElementById(\"modelSupportsMic\")" in form_src
