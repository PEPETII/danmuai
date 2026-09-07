"""Node-backed contract for the model provider picker refactor."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDER_PICKER_MJS = Path(__file__).with_name("test_model_provider_picker.mjs")
FORM_JS = ROOT / "web" / "static" / "modules" / "settings-model-modal-form.js"
LIST_JS = ROOT / "web" / "static" / "modules" / "settings-model-modal-list.js"
PROVIDERS_JS = ROOT / "web" / "static" / "modules" / "settings-providers.js"
STATE_JS = ROOT / "web" / "static" / "modules" / "settings-model-modal-state.js"
VALIDATION_JS = ROOT / "web" / "static" / "modules" / "settings-model-modal-validation.js"
MODALS_HTML = ROOT / "web" / "static" / "partials" / "modals.html"


def test_provider_picker_node_contract():
    result = subprocess.run(
        ["node", str(PROVIDER_PICKER_MJS)],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
        encoding="utf-8",
        errors="replace",
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_provider_picker_js_syntax():
    for path in (FORM_JS, LIST_JS, PROVIDERS_JS, STATE_JS, VALIDATION_JS):
        result = subprocess.run(
            ["node", "--check", str(path)],
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
        assert result.returncode == 0, f"{path.name}: {result.stderr or result.stdout}"


def test_model_modal_hides_technical_fields_until_custom():
    html = MODALS_HTML.read_text(encoding="utf-8")
    assert 'id="modelProviderPicker"' in html
    assert 'id="modelProviderSearch"' in html
    assert 'id="modelProviderOptions"' in html
    assert 'id="modelProviderEmpty"' in html
    assert 'id="modelModeField"' in html
    assert 'id="modelModeReadonly"' in html
    assert 'id="modelEndpointField"' in html
    assert 'id="modelCatalogOptions"' in html
    assert 'id="modelProviderRegion"' not in html
    assert 'id="modelMode"' not in html
    assert 'id="modelCatalogMultiselect"' not in html


def test_provider_dependent_visibility_has_one_sync_path_and_css_guard():
    form = FORM_JS.read_text(encoding="utf-8")
    state = STATE_JS.read_text(encoding="utf-8")
    html = MODALS_HTML.read_text(encoding="utf-8")
    pages_css = (ROOT / "web" / "static" / "warm-tokens-pages.css").read_text(
        encoding="utf-8"
    )

    assert re.search(r'id="modelModeField" class="field hidden"', html)
    assert re.search(r'id="modelEndpointField" class="field hidden"', html)
    assert "field.hidden" in pages_css
    assert "field[hidden]" in pages_css

    sync_start = form.index("function syncProviderDependentVisibility")
    sync_end = form.index("function refreshModelModeReadonlyLabel", sync_start)
    sync_block = form[sync_start:sync_end]
    assert "isCustomProvider(providerId)" in sync_block
    assert "field.hidden = !custom" in sync_block
    assert 'field.classList.toggle("hidden", !custom)' in sync_block

    refresh_start = form.index("function refreshModalCapabilitiesState")
    refresh_end = form.index("function onProviderChangeInModal", refresh_start)
    refresh_block = form[refresh_start:refresh_end]
    assert refresh_block.index("syncProviderDependentVisibility(providerId)") < refresh_block.index(
        "syncModelModalUIState"
    )
    open_start = form.index("export function openModelModal")
    open_end = form.index("export function closeModelModal", open_start)
    open_block = form[open_start:open_end]
    assert "syncProviderDependentVisibility(resolvedProviderId)" in open_block
    assert "onProviderChangeInModal(resolvedProviderId, { isEdit: false })" in open_block
    assert "refreshModalCapabilitiesState({ preserveSavedCapabilities: isEdit })" in open_block
    assert 'classList.toggle("hidden"' not in state


def test_model_validation_reuses_shared_custom_provider_rule():
    validation = VALIDATION_JS.read_text(encoding="utf-8")
    assert 'import { isCustomProvider } from "./settings-providers.js";' in validation
    assert "function isCustomProvider" not in validation
    assert "if (isCustomProvider(provider))" in validation


def test_model_provider_picker_uses_semantic_theme_tokens():
    form = FORM_JS.read_text(encoding="utf-8")
    css = (ROOT / "web" / "static" / "warm-tokens-pages.css").read_text(
        encoding="utf-8"
    )
    start = css.index(".model-provider-panel")
    end = css.index(".model-catalog-options", start)
    picker_css = css[start:end]

    for token in (
        "var(--surface-card)",
        "var(--surface-control)",
        "var(--surface-subtle)",
        "var(--text-primary)",
        "var(--text-muted)",
        "var(--border-default)",
        "var(--color-primary)",
    ):
        assert token in picker_css
    assert "scrollbar-color: var(--border-default) var(--surface-card)" in picker_css
    assert "surface-elevated" not in picker_css
    assert "surface-hover" not in picker_css
    assert "#fff" not in picker_css
    assert "rgba(0, 0, 0" not in picker_css
    assert "model-provider-option-id font-mono text-xs text-gray-400" not in form


def test_regular_provider_save_keeps_backend_payload():
    form = FORM_JS.read_text(encoding="utf-8")
    assert "getDefaultEndpoint(providerId)" in form
    assert "providerMode" in form
    assert 'mode: custom ? "openai-compatible" : providerMode' in form
    assert "endpointValue" in form


def test_built_in_model_list_stays_read_only():
    source = LIST_JS.read_text(encoding="utf-8")
    assert "renderCatalogOptions" in source
    assert "renderCustomModelTable" in source
    assert "model-catalog-row" in source
    assert "modelCatalogOptions" in source
    assert "model-list-name-input" not in source
    assert "updateModelEntryDisplayName" in source


def test_custom_doubao_stays_hidden_but_compatible():
    form = FORM_JS.read_text(encoding="utf-8")
    validation = VALIDATION_JS.read_text(encoding="utf-8")
    assert '"custom_doubao"' in form
    assert '"custom_openai"' in form
    providers = PROVIDERS_JS.read_text(encoding="utf-8")
    assert "custom_doubao" in providers
    assert "custom_openai" in providers
    assert "isCustomProvider" in validation
