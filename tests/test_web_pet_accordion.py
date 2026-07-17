from __future__ import annotations

from pathlib import Path
import re


STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"
CONTENT_PAGES_HTML = STATIC_ROOT / "partials" / "content-pages.html"


def _pet_page_html() -> str:
    html = CONTENT_PAGES_HTML.read_text(encoding="utf-8")
    start = html.index('id="page-pet"')
    end = html.index('id="page-live-overlay"', start) if 'id="page-live-overlay"' in html[start:] else len(html)
    return html[start:end]


def test_pet_accordion_wraps_only_target_sections():
    section = _pet_page_html()

    assert section.count('data-settings-rhythm-accordion') == 1
    assert 'id="petDisplayAccordionTrigger"' in section
    assert 'id="petCommandAccordionTrigger"' in section
    assert 'id="petEnabled"' in section
    assert 'id="petBarrageModeEnabled"' in section
    assert 'id="btnPetCommandSubmit"' in section
    assert '宠物素材' in section


def test_pet_accordion_preserves_field_ids_and_aria():
    section = _pet_page_html()

    for field_id in (
        "petScale",
        "petOpacity",
        "petAlwaysOnTop",
        "petClickThrough",
        "petCommandBoxEnabled",
        "petCommandTtl",
        "petCommandApplyCount",
        "petCommandInput",
        "btnPetCommandSubmit",
    ):
        assert f'id="{field_id}"' in section
        assert section.count(f'id="{field_id}"') == 1

    # 默认全部折叠：用户未点击前不自动展开首项
    assert 'aria-expanded="true"' not in section
    assert 'settings-rhythm-accordion-item is-open' not in section
    assert re.search(r'id="petDisplayAccordionPanel"[^>]*\bhidden\b', section)
    assert re.search(r'id="petCommandAccordionPanel"[^>]*\bhidden\b', section)
    assert 'aria-controls="petDisplayAccordionPanel"' in section
    assert 'aria-labelledby="petDisplayAccordionTrigger"' in section