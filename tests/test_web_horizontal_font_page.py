from __future__ import annotations

from pathlib import Path


STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"


def test_settings_no_longer_has_font_tab():
    settings = (STATIC_ROOT / "partials" / "settings.html").read_text(encoding="utf-8")
    assert 'data-settings-tab="font"' not in settings
    assert 'id="settingsTab-font"' not in settings


def test_horizontal_font_module_exports():
    mod = (STATIC_ROOT / "modules" / "app-horizontal-font-page.js").read_text(encoding="utf-8")
    assert "export const HORIZONTAL_FONT_SAVE_KEYS" in mod
    assert "'opacity'" in mod
    assert "'eviction_mode'" in mod
    assert "'persona_name_prefix_enabled'" in mod
    assert "export async function loadHorizontalFontPage" in mod
    assert "export function initHorizontalFontPage" in mod
    assert "/api/config" in mod
    assert "method: 'PUT'" in mod


def test_style_generator_horizontal_has_persona_name_prefix_toggle():
    partial = (STATIC_ROOT / "partials" / "style-generator.html").read_text(encoding="utf-8")
    horizontal_start = partial.index('data-sg-tab-panel="horizontal"')
    horizontal = partial[horizontal_start:]
    assert 'id="persona_name_prefix_enabled"' in horizontal
    assert horizontal.count('id="persona_name_prefix_enabled"') == 1


def test_style_generator_horizontal_has_opacity_and_eviction():
    partial = (STATIC_ROOT / "partials" / "style-generator.html").read_text(encoding="utf-8")
    horizontal_start = partial.index('data-sg-tab-panel="horizontal"')
    horizontal = partial[horizontal_start:]
    assert 'id="opacity"' in horizontal
    assert 'id="eviction_mode"' in horizontal
    assert horizontal.count('id="opacity"') == 1
    assert horizontal.count('id="eviction_mode"') == 1


def test_style_generator_wires_horizontal_font_page():
    mod = (STATIC_ROOT / "modules" / "app-style-generator-page.js").read_text(encoding="utf-8")
    assert "app-horizontal-font-page.js" in mod
    assert "initHorizontalFontPage" in mod
    assert "loadHorizontalFontPage" in mod
    assert "tabName === 'horizontal'" in mod


def test_preview_module_exports_snapshot():
    mod = (STATIC_ROOT / "modules" / "settings-danmu-preview.js").read_text(encoding="utf-8")
    assert "export function updateDanmuPreviewSnapshot" in mod
    assert "horizontalDanmuStylePreview" in mod
    assert "font_size" in mod
    assert "danmu_font_size" not in mod
