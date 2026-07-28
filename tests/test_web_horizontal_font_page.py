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
    assert "export async function loadHorizontalFontPage" in mod
    assert "export function initHorizontalFontPage" in mod
    assert "/api/config" in mod
    assert "method: 'PUT'" in mod


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
