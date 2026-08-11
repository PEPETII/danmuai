"""W-UI-SETTINGS-STYLEGEN-TAB-001: 样式生成器设置 Tab / 构建产物契约检查。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from app.bundle_paths import project_root
from app.floating_panel_style import STYLE_FIELD_KEYS, STYLE_PRESET_APPLY_KEYS


def _root() -> Path:
    return project_root()


def _static() -> Path:
    return _root() / "web" / "static"


def test_style_generator_partial_is_independent_page_fragment():
    partial = _static() / "partials" / "style-generator.html"
    assert partial.is_file()
    text = partial.read_text(encoding="utf-8")
    assert 'id="page-style-generator"' in text
    assert 'id="styleGeneratorForm"' in text
    assert 'id="horizontalFontForm"' in text
    assert 'id="styleGeneratorPreview"' in text
    assert 'id="styleGeneratorPreviewStack"' in text
    assert 'id="settingsTab-stylegen"' not in text
    assert 'data-settings-panel="stylegen"' not in text
    assert '横向模式即将推出' not in text
    settings = (_static() / "partials" / "settings.html").read_text(encoding="utf-8")
    assert "{{style_generator}}" not in settings
    assert 'data-settings-tab="font"' not in settings


def test_style_generator_form_names_match_contract_keys():
    text = (_static() / "index.html").read_text(encoding="utf-8")
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


def test_style_generator_color_fields_use_picker_plus_hex():
    """颜色字段应为 type=color 色盘 + hex 高级输入，而非仅文本框。"""
    text = (_static() / "index.html").read_text(encoding="utf-8")
    mod = (_static() / "modules" / "app-style-generator-page.js").read_text(encoding="utf-8")
    css = (_static() / "warm-tokens-pages-stylegen.css").read_text(encoding="utf-8")

    for field in (
        "floating_panel_outline_color",
        "floating_panel_shadow_color",
        "floating_panel_border_color",
        "floating_panel_username_color",
    ):
        assert f'data-sg-color-for="{field}"' in text, f"missing color picker for {field}"
        assert f'name="{field}"' in text
        assert f'data-sg-color-field="{field}"' in text
        # 不得再是单独的纯文本 type=text 而无配套 picker 容器
        assert 'class="sg-color-input"' in text

    assert 'id="sgCardColorPicker"' in text and 'type="color"' in text
    assert 'id="sgCardColorHex"' in text
    assert 'id="sgTextColorPicker"' in text
    assert 'id="sgTextColorHex"' in text
    assert "sg-color-input" in css
    assert "sg-color-hex-input" in css
    assert "syncSingleColorPickersFromText" in mod
    assert "mergePickerRgbPreserveAlpha" in mod
    assert "onSingleColorPickerInput" in mod


def test_style_generator_tabs_share_accordion_layout_contract():
    """两个弹幕样式 Tab 的折叠面板共用字段行与操作栏规范。"""
    partial = (_static() / "partials" / "style-generator.html").read_text(encoding="utf-8")
    css = (_static() / "warm-tokens-pages-stylegen.css").read_text(encoding="utf-8")

    assert "#page-style-generator .sg-accordion .settings-params-grid" in css
    assert "#page-style-generator .sg-accordion .settings-rhythm-accordion-fields" in css
    assert "#page-style-generator .sg-accordion .settings-field," in css
    assert ".sg-action-bar .ui-button" in css
    assert partial.count('class="sg-action-bar"') == 2

    for button_id in (
        "sgBtnSave",
        "sgBtnRestoreDefault",
        "sgBtnAddPreview",
        "sgBtnClearPreview",
        "hfBtnSave",
        "hfBtnRestoreDefault",
    ):
        start = partial.index(f'id="{button_id}"')
        button = partial[start : start + 220]
        assert "ui-button" in button, button_id


def test_style_generator_accordion_number_stepper_inner_matches_reference():
    """折叠面板内步进器内层 input 应与设置页步进器约定一致（居中、透明、6px padding）。"""
    partial = (_static() / "partials" / "style-generator.html").read_text(encoding="utf-8")
    css = (_static() / "warm-tokens-pages-stylegen.css").read_text(encoding="utf-8")
    mod = (_static() / "modules" / "app-style-generator-page.js").read_text(encoding="utf-8")

    assert (
        "#page-style-generator .sg-accordion .settings-rhythm-stepper .settings-field-control"
        in css
    )
    stepper_inner_start = css.index(
        "#page-style-generator .sg-accordion .settings-rhythm-stepper .settings-field-control"
    )
    stepper_inner_block = css[stepper_inner_start : stepper_inner_start + 320]
    assert "padding: 0 6px" in stepper_inner_block
    assert "text-align: center" in stepper_inner_block
    assert "background: transparent !important" in stepper_inner_block
    assert 'input[type="number"].settings-field-control {\n  text-align: right' not in css
    assert partial.count('type="number"') >= 35
    assert 'class="settings-field-control ui-control ui-input"' in partial
    assert "initNumberSteppers(form)" in mod


def test_sidebar_has_independent_style_generator_entry():
    sidebar = (_static() / "partials" / "sidebar.html").read_text(encoding="utf-8")
    assert 'data-page="style-generator"' in sidebar
    assert 'href="#style-generator"' in sidebar


def test_build_registers_style_generator_fragment():
    build = (_static() / "build_index_html.py").read_text(encoding="utf-8")
    template = (_static() / "index.template.html").read_text(encoding="utf-8")
    assert '"{{style_generator}}"' in build or "'{{style_generator}}'" in build
    assert "style-generator.html" in build
    # index.template.html 中保留 {{style_generator}} 注入点，由 build 脚本替换为独立页面片段
    assert "{{style_generator}}" in template


def test_built_index_html_contains_style_generator_page_once():
    html = (_static() / "index.html").read_text(encoding="utf-8")
    assert 'id="page-style-generator"' in html
    assert 'data-settings-tab="stylegen"' not in html
    assert 'id="settingsTab-stylegen"' not in html
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


def test_preview_recomputes_existing_card_colors_when_presets_change_round_trip():
    """已有卡片必须按稳定 styleIndex 重算 classic -> wechat -> classic。"""
    script = """
import { refreshPreviewItemColors } from './web/static/modules/app-style-generator-page.js';
const item = { styleIndex: 1, cardColor: '#OLDOLD', textColor: '#OLDOLD', el: { dataset: {} } };
const classic = { cardColors: ['#FFFFFF', '#F5D401'], cardMode: 'equal', cardWeights: {}, textColors: ['#000000'], textMode: 'equal', textWeights: {} };
const wechat = { cardColors: ['#FFECD2', '#DDF5D7'], cardMode: 'equal', cardWeights: {}, textColors: ['#281C12'], textMode: 'equal', textWeights: {} };
const first = refreshPreviewItemColors(item, classic);
const second = refreshPreviewItemColors(item, wechat);
const third = refreshPreviewItemColors(item, classic);
console.log(JSON.stringify({ first, second, third, item }));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=_root(),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["first"] == {"cardColor": "#F5D401", "textColor": "#000000"}
    assert payload["second"] == {"cardColor": "#DDF5D7", "textColor": "#281C12"}
    assert payload["third"] == payload["first"]
    assert payload["item"]["el"]["dataset"] == {
        "cardColor": "#F5D401",
        "textColor": "#000000",
    }


def test_preview_tail_rules_match_floating_panel_round_sharp_none_geometry():
    """预览的 inline/stacked round/sharp/none 尾巴应复用真实 card 几何。"""
    css = (_static() / "warm-tokens-pages-stylegen.css").read_text(encoding="utf-8")
    panel_css = (_static() / "floating_panel" / "style.css").read_text(encoding="utf-8")
    for value in ("round", "sharp", "none"):
        assert f'[data-tail-style="{value}"]' in css
        assert f'[data-tail-style="{value}"]' in panel_css
    for fragment in (
        "margin-left: calc(var(--tail-w) + 4px)",
        "left: calc(-1 * var(--tail-w) - 1px)",
        "background: var(--tail-color)",
        "border-radius: 0 0 0 50%",
        "clip-path: polygon(100% 0, 100% 100%, 0 100%)",
        "clip-path: polygon(100% 0, 0 50%, 100% 100%)",
        "display: none",
    ):
        assert fragment in css
        assert fragment in panel_css
    assert "border-radius: 100% 0 100% 100%" not in css
    assert "border-color: transparent var(--tail-color) transparent transparent" not in css


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
    assert "Danmaku Style" in en_content
    assert "appStyleGenerator" in zh_dyn and "appStyleGenerator" in en_dyn
    assert "预设LineLike" in zh_content and "预设LineLike" in en_content
    assert "布局" in zh_content and '"布局"' in en_content
    assert "Line尾巴边框" in zh_content and "Line尾巴边框" in en_content
    assert "尾巴LineLike" in zh_content and "尾巴LineLike" in en_content
