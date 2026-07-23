from __future__ import annotations

from pathlib import Path
import re


STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"
CONTENT_PAGES_HTML = STATIC_ROOT / "partials" / "content-pages.html"


def _meme_tab_html() -> str:
    html = CONTENT_PAGES_HTML.read_text(encoding="utf-8")
    start = html.index('id="danmuPoolTab-meme"')
    end = html.index('id="danmuPoolTab-custom"', start)
    return html[start:end]


def test_meme_accordion_wraps_only_target_sections():
    section = _meme_tab_html()

    assert section.count('data-settings-rhythm-accordion') == 1
    assert 'id="memeDisplayModeAccordionTrigger"' in section
    assert 'id="memeCollectAccordionTrigger"' in section
    assert 'id="memeDisplayAccordionTrigger"' in section
    assert 'id="memeBarrageEnabled"' in section
    assert 'id="memeTagGrid"' in section
    assert 'id="btnSaveMemeBarrageSettings"' in section
    assert section.index('id="memeTagGrid"') < section.index('data-settings-rhythm-accordion')
    assert section.index('data-settings-rhythm-accordion') < section.index('id="btnSaveMemeBarrageSettings"')
    # 分类模式含标签选择；采集/展示为独立分区
    assert 'id="hintMemeCategoryTitle"' in section
    assert '分类模式' in section
    assert 'meme-category-settings' in section
    assert 'meme-category-tag-block' in section
    assert 'id="hintMemeTagTitle"' in section
    assert 'meme-advanced-settings' in section
    assert '采集与展示' in section
    assert section.index('id="hintMemeCategoryTitle"') < section.index('id="memeTagGrid"')
    assert section.index('id="memeTagGrid"') < section.index('meme-advanced-settings')
    assert section.index('meme-advanced-settings') < section.index('data-settings-rhythm-accordion')


def test_meme_accordion_preserves_field_ids_and_aria():
    section = _meme_tab_html()

    assert 'name="memeDisplayMode"' in section
    for field_id in (
        "memeCollectInterval",
        "memeCollectBatch",
        "memeDisplayInterval",
        "memeDisplayBatch",
        "hintMemeDisplayModeTitle",
        "hintMemeCollectTitle",
        "hintMemeDisplayTitle",
    ):
        assert f'id="{field_id}"' in section
        assert section.count(f'id="{field_id}"') == 1

    # 默认全部折叠：用户未点击前不自动展开首项
    assert 'aria-expanded="true"' not in section
    assert 'settings-rhythm-accordion-item is-open' not in section
    assert re.search(r'id="memeDisplayModeAccordionPanel"[^>]*\bhidden\b', section)
    assert re.search(r'id="memeCollectAccordionPanel"[^>]*\bhidden\b', section)
    assert re.search(r'id="memeDisplayAccordionPanel"[^>]*\bhidden\b', section)
    assert 'aria-controls="memeDisplayModeAccordionPanel"' in section
    assert 'aria-labelledby="memeDisplayModeAccordionTrigger"' in section