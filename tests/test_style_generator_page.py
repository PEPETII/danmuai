"""W-FP-STYLEGEN-WEB-001: 样式生成器页 partial / 构建产物 / 模块契约静态检查。"""

from __future__ import annotations

from pathlib import Path

from app.bundle_paths import project_root
from app.floating_panel_style import STYLE_FIELD_KEYS, STYLE_PRESET_APPLY_KEYS


def _root() -> Path:
    return project_root()


def _static() -> Path:
    return _root() / "web" / "static"


def test_style_generator_partial_exists_and_has_page_id():
    partial = _static() / "partials" / "style-generator.html"
    assert partial.is_file()
    text = partial.read_text(encoding="utf-8")
    assert 'id="page-style-generator"' in text
    assert 'id="styleGeneratorForm"' in text
    assert 'id="styleGeneratorPreview"' in text
    assert 'id="styleGeneratorPreviewStack"' in text
    assert text.count('id="page-style-generator"') == 1


def test_style_generator_form_names_match_contract_keys():
    text = (_static() / "partials" / "style-generator.html").read_text(encoding="utf-8")
    for key in STYLE_FIELD_KEYS:
        assert f'name="{key}"' in text, f"missing form name for {key}"
    # 预设应用键中的基础字体/不透明度也必须可编辑
    for key in (
        "floating_panel_font_family",
        "floating_panel_font_size",
        "floating_panel_font_bold",
        "floating_panel_opacity",
    ):
        assert f'name="{key}"' in text, f"missing form name for {key}"
    assert 'data-preset="blivechat_line"' in text
    assert 'id="sgBtnPresetBlivechatLine"' in text
    assert 'value="line_like"' in text
    assert 'value="stacked"' in text
    assert 'value="inline"' in text
    assert set(STYLE_PRESET_APPLY_KEYS)


def test_sidebar_has_style_generator_nav():
    sidebar = (_static() / "partials" / "sidebar.html").read_text(encoding="utf-8")
    assert 'data-page="style-generator"' in sidebar
    assert 'href="#style-generator"' in sidebar
    assert 'data-i18n="nav.styleGenerator"' in sidebar


def test_build_registers_style_generator_partial():
    build = (_static() / "build_index_html.py").read_text(encoding="utf-8")
    template = (_static() / "index.template.html").read_text(encoding="utf-8")
    assert '"{{style_generator}}"' in build or "'{{style_generator}}'" in build
    assert "style-generator.html" in build
    assert "{{style_generator}}" in template


def test_built_index_html_contains_style_generator_once():
    html = (_static() / "index.html").read_text(encoding="utf-8")
    assert 'data-page="style-generator"' in html
    assert 'id="page-style-generator"' in html
    assert html.count('id="page-style-generator"') == 1
    assert html.count('id="styleGeneratorForm"') == 1
    assert html.count('id="styleGeneratorPreview"') == 1
    assert 'name="floating_panel_style_preset"' in html
    assert 'name="floating_panel_card_colors"' in html
    assert 'name="floating_panel_shape"' in html
    assert 'name="floating_panel_layout"' in html
    assert 'name="floating_panel_tail_border"' in html
    assert 'name="floating_panel_tail_long_side"' in html
    assert 'name="floating_panel_tail_rotate_deg"' in html
    assert 'data-preset="blivechat_line"' in html
    assert 'btnOpenStyleGeneratorFromSettings' in html


def test_settings_floating_preview_is_entry_not_second_stack():
    settings = (_static() / "partials" / "settings.html").read_text(encoding="utf-8")
    assert 'id="btnOpenStyleGeneratorFromSettings"' in settings
    assert 'id="danmuPreviewFloatingPanel"' not in settings
    assert 'id="danmuPreviewScrolling"' in settings
    assert 'id="danmuPreviewTrack"' in settings


def test_style_generator_module_uses_api_fetch_and_config_put():
    mod = (_static() / "modules" / "app-style-generator-page.js").read_text(encoding="utf-8")
    assert "from './transport.js'" in mod
    assert "apiFetch" in mod
    assert "/api/floating-panel/style-presets" in mod
    assert "/api/config" in mod
    assert "method: 'PUT'" in mod
    assert "localStorage" not in mod
    assert "export function pickStyleColor" in mod
    assert "export async function loadStyleGeneratorPage" in mod
    assert "export function initStyleGeneratorPage" in mod


def test_style_generator_preview_matches_web_panel_structure():
    """Preview must mirror real floating_panel: column-reverse, card DOM, 2-line clamp, maxCards."""
    mod = (_static() / "modules" / "app-style-generator-page.js").read_text(encoding="utf-8")
    css = (_static() / "warm-tokens-pages-stylegen.css").read_text(encoding="utf-8")
    panel_css = (_static() / "floating_panel" / "style.css").read_text(encoding="utf-8")
    assert "sg-preview-card" in mod
    assert "column-reverse" in css
    assert "column-reverse" in panel_css
    assert "line-clamp: 2" in css or "-webkit-line-clamp: 2" in css
    assert "-webkit-line-clamp: 2" in panel_css
    assert "removeOldestIfNeeded" in mod
    assert "scheduleCardExit" in mod
    assert "applyCardStyleVars" in mod
    assert "is-bubble" in css and "is-bubble" in panel_css
    # LineLike stacked DOM + CSS vars (W-FP-LINELIKE-STYLEGEN-001)
    assert "layout-stacked" in mod
    assert "buildPreviewCardInnerHtml" in mod
    assert "class=\"bubble\"" in mod or "class='bubble'" in mod or 'class="bubble"' in mod
    assert "floating_panel_layout" in mod
    assert "floating_panel_tail_border" in mod
    assert "floating_panel_tail_long_side" in mod
    assert "floating_panel_tail_rotate_deg" in mod
    assert "applyPreset('blivechat_line')" in mod or 'applyPreset("blivechat_line")' in mod
    assert "layout-stacked" in css
    assert "--tail-border" in css
    assert "--tail-long-side" in css
    assert "--tail-rotate" in css
    assert 'data-tail-style="line_like"' in css or "[data-tail-style=\"line_like\"]" in css


def test_settings_danmu_preview_no_longer_implements_floating_stack():
    mod = (_static() / "modules" / "settings-danmu-preview.js").read_text(encoding="utf-8")
    assert "function renderFloatingPreview" not in mod
    assert "danmuPreviewFloatingPanel" not in mod
    assert "renderScrollingPreview" in mod


def test_app_js_wires_style_generator_navigate():
    app_js = (_static() / "app.js").read_text(encoding="utf-8")
    assert "ensureStyleGeneratorPage" in app_js
    assert "app-style-generator-page.js" in app_js
    assert "page === 'style-generator'" in app_js
    assert "loadStyleGeneratorPage" in app_js
    assert "btnOpenStyleGeneratorFromSettings" in app_js


def test_i18n_keys_for_style_generator():
    zh_nav = (_static() / "locales" / "zh" / "nav.json").read_text(encoding="utf-8")
    en_nav = (_static() / "locales" / "en" / "nav.json").read_text(encoding="utf-8")
    zh_content = (_static() / "locales" / "zh" / "content.json").read_text(encoding="utf-8")
    en_content = (_static() / "locales" / "en" / "content.json").read_text(encoding="utf-8")
    zh_dyn = (_static() / "locales" / "zh" / "dynamic.json").read_text(encoding="utf-8")
    en_dyn = (_static() / "locales" / "en" / "dynamic.json").read_text(encoding="utf-8")
    assert '"styleGenerator"' in zh_nav and '"styleGenerator"' in en_nav
    assert "样式生成器" in zh_content
    assert "Style Generator" in en_content
    assert "appStyleGenerator" in zh_dyn and "appStyleGenerator" in en_dyn
    assert "预设LineLike" in zh_content and "预设LineLike" in en_content
    assert "布局" in zh_content and '"布局"' in en_content
    assert "Line尾巴边框" in zh_content and "Line尾巴边框" in en_content
    assert "尾巴LineLike" in zh_content and "尾巴LineLike" in en_content
