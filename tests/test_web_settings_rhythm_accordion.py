from __future__ import annotations

from pathlib import Path
import re


STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"
SETTINGS_HTML = STATIC_ROOT / "partials" / "settings.html"
ACCORDION_MODULE = STATIC_ROOT / "modules" / "settings-rhythm-accordion.js"
PAGES_CSS = STATIC_ROOT / "warm-tokens-settings.css"
INDEX_TEMPLATE = STATIC_ROOT / "index.template.html"
THEME_BUNDLE = STATIC_ROOT / "warm-tokens.css"
APP_MODULE = STATIC_ROOT / "app.js"
SETTINGS_MODULE = STATIC_ROOT / "modules" / "settings.js"


def test_rhythm_accordion_keeps_existing_config_field_contracts():
    html = SETTINGS_HTML.read_text(encoding="utf-8")

    # 压缩折叠已并入 AI识图相关（settingsTab-capture）；无独立 rhythm tab
    assert 'data-settings-tab="rhythm"' not in html
    assert 'id="settingsTab-rhythm"' not in html
    capture_start = html.index('id="settingsTab-capture"')
    font_start = html.index('id="settingsTab-font"')
    capture = html[capture_start:font_start]
    assert 'id="settingsRhythmAccordionTrigger"' in capture
    assert 'type="button"' in capture
    assert 'aria-expanded="false"' in capture
    assert 'aria-controls="settingsRhythmCompressionPanel"' in capture
    assert re.search(r'id="settingsRhythmCompressionPanel"[^>]*\bhidden\b', capture)
    assert 'aria-labelledby="settingsRhythmAccordionTrigger"' in capture
    assert 'id="image_max_width"' in capture
    assert 'name="image_max_width"' in capture
    assert 'id="image_quality"' in capture
    assert 'name="image_quality"' in capture
    assert 'data-rhythm-step' not in capture
    assert 'data-i18n="settings.text.AI识图相关"' in capture or 'AI识图相关' in capture


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
    # E 批：高度对齐 --control-height-md（40px）；兼容旧字面量 40px
    assert (
        "min-height: var(--control-height-md)" in css
        or "min-height: 40px" in css
    )
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

    assert "warm-tokens.css" in template
    assert "warm-tokens-settings.css" in theme_bundle
    assert "warm-tokens-pages.css" in theme_bundle
    assert "app.js" in template
    assert "./modules/settings.js" in app_module
    assert "./settings-rhythm-accordion.js" in settings_module
