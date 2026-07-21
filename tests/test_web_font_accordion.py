from __future__ import annotations

from pathlib import Path
import re


STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"
SETTINGS_HTML = STATIC_ROOT / "partials" / "settings.html"


def _font_tab_html() -> str:
    html = SETTINGS_HTML.read_text(encoding="utf-8")
    start = html.index('id="settingsTab-font"')
    end = html.index('id="settingsTab-live"', start) if 'id="settingsTab-live"' in html[start:] else len(html)
    return html[start:end]


def test_font_accordion_wraps_only_target_sections():
    section = _font_tab_html()

    assert section.count('data-settings-rhythm-accordion') == 1
    assert 'id="settingsFontScrollingAccordionTrigger"' in section
    assert 'id="settingsFontColorAccordionTrigger"' in section
    assert 'id="settingsFontFloatingAccordionTrigger"' in section
    assert 'id="settingsFontImportAccordionTrigger"' in section
    assert 'id="font_file_input"' in section
    assert 'id="btnImportFont"' in section
    # 导入区在同一 accordion 根内（折叠项，非独立 section）
    accordion_start = section.index('data-settings-rhythm-accordion')
    import_panel = section.index('id="settingsFontImportAccordionPanel"')
    font_input_pos = section.index('id="font_file_input"')
    assert accordion_start < import_panel < font_input_pos
    assert 'settings-section-title">导入本地字体' not in section


def test_font_accordion_preserves_field_ids_and_aria():
    section = _font_tab_html()

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
        "floating_panel_font_family",
        "floating_panel_font_size",
        "floating_panel_font_bold",
        "font_file_input",
        "btnImportFont",
        "importedFontsList",
        "fontRowTemplate",
    ):
        assert f'id="{field_id}"' in section
        assert section.count(f'id="{field_id}"') == 1

    # 默认全部折叠：用户未点击前不自动展开首项
    assert 'aria-expanded="true"' not in section
    assert 'settings-rhythm-accordion-item is-open' not in section
    assert re.search(r'id="settingsFontScrollingAccordionPanel"[^>]*\bhidden\b', section)
    assert re.search(r'id="settingsFontColorAccordionPanel"[^>]*\bhidden\b', section)
    assert re.search(r'id="settingsFontFloatingAccordionPanel"[^>]*\bhidden\b', section)
    assert re.search(r'id="settingsFontImportAccordionPanel"[^>]*\bhidden\b', section)
    assert 'aria-controls="settingsFontScrollingAccordionPanel"' in section
    assert 'aria-labelledby="settingsFontScrollingAccordionTrigger"' in section
    assert 'aria-controls="settingsFontImportAccordionPanel"' in section
    assert 'aria-labelledby="settingsFontImportAccordionTrigger"' in section
