from __future__ import annotations

from pathlib import Path

from web.static.build_index_html import build_index_html


STATIC_ROOT = Path(__file__).resolve().parents[1] / "web" / "static"
SETTINGS_HTML = STATIC_ROOT / "partials" / "settings.html"
CONTENT_PAGES_HTML = STATIC_ROOT / "partials" / "content-pages.html"
PAGES_CSS = STATIC_ROOT / "warm-tokens-pages.css"
INDEX_HTML = STATIC_ROOT / "index.html"

ROW_LAYOUT_PANELS = (
    "settingsDanmuBatchAccordionPanel",
    "settingsDanmuAppearanceAccordionPanel",
    "settingsDanmuScrollingAccordionPanel",
    "settingsFontScrollingAccordionPanel",
    "settingsFontFloatingAccordionPanel",
    "petDisplayAccordionPanel",
    "petCommandAccordionPanel",
)

INLINE_LAYOUT_PANELS = (
    "memeCollectAccordionPanel",
    "memeDisplayAccordionPanel",
)


def _extract_panel(html: str, panel_id: str) -> str:
    marker = f'id="{panel_id}"'
    start = html.index(marker)
    open_end = html.index(">", start) + 1
    depth = 1
    pos = open_end
    while depth and pos < len(html):
        next_open = html.find("<div", pos)
        next_close = html.find("</div>", pos)
        if next_close == -1:
            break
        if next_open != -1 and next_open < next_close:
            depth += 1
            pos = next_open + 4
            continue
        depth -= 1
        pos = next_close + len("</div>")
    return html[start:pos]


def _accordion_root_css_block() -> str:
    css = PAGES_CSS.read_text(encoding="utf-8")
    start = css.index(".settings-rhythm-accordion {")
    end = css.index("}", start) + 1
    return css[start:end]


def test_target_panels_use_row_layout_without_grid_cards():
    settings_html = SETTINGS_HTML.read_text(encoding="utf-8")
    content_html = CONTENT_PAGES_HTML.read_text(encoding="utf-8")

    for panel_id in ROW_LAYOUT_PANELS:
        source = content_html if panel_id.startswith("pet") else settings_html
        panel = _extract_panel(source, panel_id)
        assert "settings-rhythm-accordion-fields" in panel, panel_id
        assert "settings-params-grid" not in panel, panel_id
        assert 'class="settings-field"' not in panel, panel_id


def test_meme_inline_panels_keep_sentence_layout_without_cards():
    content_html = CONTENT_PAGES_HTML.read_text(encoding="utf-8")

    for panel_id in INLINE_LAYOUT_PANELS:
        panel = _extract_panel(content_html, panel_id)
        assert "settings-rhythm-accordion-inline-row" in panel, panel_id
        assert "settings-params-grid" not in panel, panel_id
        assert 'class="settings-field"' not in panel, panel_id


def test_accordion_root_css_has_no_outer_border():
    block = _accordion_root_css_block()
    assert "border:" not in block
    assert "border-radius:" not in block


def test_accordion_css_preserves_focus_rings():
    css = PAGES_CSS.read_text(encoding="utf-8")

    assert ".settings-rhythm-accordion-trigger:focus-visible" in css
    assert ".settings-rhythm-accordion-field .settings-field-control:focus" in css
    assert ".settings-rhythm-accordion-inline-row .settings-field-control:focus" in css


def test_built_index_html_contains_visual_parity_markers():
    built = build_index_html()
    INDEX_HTML.write_text(built, encoding="utf-8")

    assert "settings-rhythm-accordion-fields" in built
    assert "settings-rhythm-accordion-inline-row" in built
    assert "settings-rhythm-accordion-field--toggle" in built
    assert 'id="settingsDanmuBatchAccordionPanel"' in built
    assert 'id="petCommandAccordionPanel"' in built

    batch_panel = _extract_panel(built, "settingsDanmuBatchAccordionPanel")
    assert "settings-rhythm-accordion-fields" in batch_panel
    assert "settings-params-grid" not in batch_panel