from __future__ import annotations

import re
from pathlib import Path

STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"
STYLE_GEN_HTML = STATIC_ROOT / "partials" / "style-generator.html"


def _horizontal_font_html() -> str:
    html = STYLE_GEN_HTML.read_text(encoding="utf-8")
    start = html.index('data-sg-tab-panel="horizontal"')
    return html[start:]


def test_horizontal_font_accordion_single_panel():
    section = _horizontal_font_html()

    assert 'id="horizontalFontForm"' in section
    assert section.count('data-settings-rhythm-accordion') == 1
    assert 'id="sgHorizontalFontAccordionTrigger"' in section
    assert 'id="sgHorizontalFontAccordionPanel"' in section
    assert 'id="settingsFontScrollingAccordionTrigger"' not in section
    assert 'id="font_file_input"' in section
    assert 'id="btnImportFont"' in section
    assert '横向模式即将推出' not in section


def test_horizontal_font_preserves_field_ids_and_aria():
    section = _horizontal_font_html()

    for field_id in (
        "danmu_font_family",
        "font_size",
        "danmu_lines",
        "layout_mode",
        "danmu_font_bold",
        "danmuFontColorSwatches",
        "danmuFontColorModeEqual",
        "danmuFontColorModeWeighted",
        "danmuFontColorWeights",
        "danmu_font_color_selected",
        "danmu_font_color_weights",
        "danmu_font_color_mode",
        "font_file_input",
        "btnImportFont",
        "importedFontsList",
        "fontRowTemplate",
    ):
        assert f'id="{field_id}"' in section
        assert section.count(f'id="{field_id}"') == 1

    assert 'aria-expanded="true"' not in section
    assert 'settings-rhythm-accordion-item is-open' not in section
    assert re.search(r'id="sgHorizontalFontAccordionPanel"[^>]*\bhidden\b', section)
    assert 'aria-controls="sgHorizontalFontAccordionPanel"' in section
    assert 'aria-labelledby="sgHorizontalFontAccordionTrigger"' in section
