from __future__ import annotations

from pathlib import Path
import re


STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"
NUMBER_STEPPER_MODULE = STATIC_ROOT / "modules" / "number-stepper.js"
SETTINGS_HTML = STATIC_ROOT / "partials" / "settings.html"
CONTENT_PAGES_HTML = STATIC_ROOT / "partials" / "content-pages.html"
MODALS_HTML = STATIC_ROOT / "partials" / "modals.html"
PAGES_CSS = STATIC_ROOT / "warm-tokens-pages.css"
APP_MODULE = STATIC_ROOT / "app.js"
SETTINGS_FONTS_MODULE = STATIC_ROOT / "modules" / "settings-fonts.js"


def _count_bare_number_inputs(html: str) -> int:
    return len(re.findall(r'<input[^>]*type="number"[^>]*>', html))


def test_number_stepper_module_exports_enhancement_api():
    source = NUMBER_STEPPER_MODULE.read_text(encoding="utf-8")

    assert "export function wrapNumberInput" in source
    assert "export function bindNumberStepper" in source
    assert "export function initNumberSteppers" in source
    assert "data-no-stepper" in source
    assert "data-step-dir" in source
    assert "input.stepUp()" in source
    assert "input.stepDown()" in source
    assert "settings-rhythm-stepper--wide" in source
    assert "settings-rhythm-stepper--compact" in source


def test_partials_keep_bare_number_inputs_for_runtime_enhancement():
    settings_html = SETTINGS_HTML.read_text(encoding="utf-8")
    content_html = CONTENT_PAGES_HTML.read_text(encoding="utf-8")
    modals_html = MODALS_HTML.read_text(encoding="utf-8")

    assert "data-rhythm-step" not in settings_html
    assert _count_bare_number_inputs(settings_html) >= 20
    assert _count_bare_number_inputs(content_html) >= 8
    assert 'id="modelMaxTokens"' in modals_html
    assert 'type="number"' in modals_html


def test_app_and_font_modules_initialize_number_steppers():
    app_source = APP_MODULE.read_text(encoding="utf-8")
    fonts_source = SETTINGS_FONTS_MODULE.read_text(encoding="utf-8")

    assert "initNumberSteppers" in app_source
    assert "initNumberSteppers(document)" in app_source
    assert "./modules/number-stepper.js?v=20260717-number-stepper-v1" in app_source
    assert "initNumberSteppers(container)" in fonts_source


def test_number_stepper_css_covers_layout_variants():
    css = PAGES_CSS.read_text(encoding="utf-8")

    assert ".settings-rhythm-accordion-field > .settings-rhythm-stepper" in css
    assert ".settings-rhythm-accordion-inline-row .settings-rhythm-stepper" in css
    assert ".settings-field .settings-rhythm-stepper" in css
    assert ".settings-rhythm-stepper--wide" in css
    assert ".settings-rhythm-stepper--compact" in css
    # 自定义 +/- 与原生步进器去重：仅保留自定义按钮
    assert '.settings-rhythm-stepper input[type="number"]' in css
    assert "::-webkit-inner-spin-button" in css
    assert "appearance: textfield" in css