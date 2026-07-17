from __future__ import annotations

from pathlib import Path
import re


STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"
SETTINGS_HTML = STATIC_ROOT / "partials" / "settings.html"
ACCORDION_MODULE = STATIC_ROOT / "modules" / "settings-rhythm-accordion.js"
PAGES_CSS = STATIC_ROOT / "warm-tokens-pages.css"
INDEX_TEMPLATE = STATIC_ROOT / "index.template.html"
THEME_BUNDLE = STATIC_ROOT / "warm-tokens.css"
APP_MODULE = STATIC_ROOT / "app.js"
SETTINGS_MODULE = STATIC_ROOT / "modules" / "settings.js"


def test_rhythm_accordion_keeps_existing_config_field_contracts():
    html = SETTINGS_HTML.read_text(encoding="utf-8")

    assert 'data-settings-rhythm-accordion' in html
    assert 'id="settingsRhythmAccordionTrigger"' in html
    assert 'type="button"' in html
    assert 'aria-expanded="false"' in html
    assert 'aria-controls="settingsRhythmCompressionPanel"' in html
    assert re.search(r'id="settingsRhythmCompressionPanel"[^>]*\bhidden\b', html)
    assert 'aria-labelledby="settingsRhythmAccordionTrigger"' in html
    assert 'id="image_max_width"' in html
    assert 'name="image_max_width"' in html
    assert 'id="image_quality"' in html
    assert 'name="image_quality"' in html
    assert 'data-rhythm-step' not in html


def test_rhythm_accordion_module_only_toggles_dom_state():
    assert ACCORDION_MODULE.is_file()
    source = ACCORDION_MODULE.read_text(encoding="utf-8")

    assert 'export function initSettingsRhythmAccordion' in source
    assert 'root.querySelectorAll(ROOT_SELECTOR)' in source
    assert "accordion.querySelectorAll(ITEM_SELECTOR)" in source
    assert "item.classList.toggle('is-open', isOpen)" in source
    assert "trigger.setAttribute('aria-expanded', String(isOpen))" in source
    assert 'panel.hidden = !isOpen' in source
    assert "accordion.dataset.bound = 'true'" in source
    assert "addEventListener('click'" in source
    assert 'apiFetch' not in source
    assert 'initNumberSteppers' not in source
    assert '/api/config' not in source


def test_rhythm_accordion_styles_preserve_focus_and_compact_controls():
    css = PAGES_CSS.read_text(encoding="utf-8")

    assert '.settings-rhythm-accordion-trigger:focus-visible' in css
    assert '.settings-rhythm-accordion-field' in css
    assert 'border: 0 !important' in css
    assert 'background: rgba(var(--color-primary-rgb), 0.08) !important' in css
    assert 'transform: rotate(-45deg)' in css
    assert 'transform: rotate(45deg)' in css
    assert 'flex: 0 0 132px' in css
    assert 'min-height: 40px' in css
    assert 'appearance: textfield' in css
    assert '.settings-rhythm-accordion-field .settings-field-control:focus' in css
    assert '.settings-rhythm-stepper' in css
    assert '.settings-rhythm-step-button' in css
    assert '.settings-rhythm-accordion-item + .settings-rhythm-accordion-item' in css
    assert 'border-top: 1px solid var(--border)' in css


def test_rhythm_accordion_refreshes_the_imported_theme_bundle():
    template = INDEX_TEMPLATE.read_text(encoding="utf-8")
    theme_bundle = THEME_BUNDLE.read_text(encoding="utf-8")
    app_module = APP_MODULE.read_text(encoding="utf-8")
    settings_module = SETTINGS_MODULE.read_text(encoding="utf-8")

    assert 'warm-tokens.css?v=20260717-number-stepper-v2' in template
    assert 'warm-tokens-pages.css?v=20260717-number-stepper-v2' in theme_bundle
    assert 'app.js?v=20260717-number-stepper-v1' in template
    assert "./modules/settings.js?v=20260717-number-stepper-v1" in app_module
    assert "./settings-rhythm-accordion.js?v=20260717-number-stepper-v1" in settings_module
