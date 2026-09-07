"""Node-backed contract for the model provider picker refactor."""

from __future__ import annotations

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
