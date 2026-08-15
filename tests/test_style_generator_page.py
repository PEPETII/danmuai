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
    derived_form_keys = {
        "floating_panel_tail_size",
    }
    for key in STYLE_FIELD_KEYS:
        if key in derived_form_keys:
            continue
        assert f'name="{key}"' in text, f"missing form name for {key}"
    # 遗留键由保存时派生，不要求表单控件
    for key in (
        "floating_panel_font_family",
        "floating_panel_opacity",
    ):
        assert f'name="{key}"' in text, f"missing form name for {key}"
    mod = (_static() / "modules" / "app-style-generator-page.js").read_text(encoding="utf-8")
    assert "applyDerivedLegacyStyleFields" in mod
    assert 'name="floating_panel_font_size"' not in text
    assert 'name="floating_panel_font_bold"' not in text
    assert 'data-preset="blivechat_line"' in text
    assert 'id="sgPresetSelect"' in text
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


def test_style_generator_accordion_titles_follow_domain_grouping():
    """标题按参考项目的领域语义分组，且被移动的字段只保留在新归属面板。"""
    partial = (_static() / "partials" / "style-generator.html").read_text(encoding="utf-8")

    for title_key in (
        "全局外观",
        "显示布局与频率",
        "弹幕气泡背景",
        "描边、阴影、边框",
        "弹幕字体",
        "弹幕用户名",
        "用户名",
        "弹幕布局",
        "显示与退场",
        "字体资源",
    ):
        assert f'data-i18n="content.text.{title_key}"' in partial

    layout_start = partial.index('id="sgLayoutAccordionPanel"')
    card_start = partial.index('id="sgCardColorsAccordionPanel"')
    assert layout_start < partial.index('id="floating_panel_danmu_per_second"') < card_start

    card_start = partial.index('id="sgCardColorsAccordionPanel"')
    text_colors_start = partial.index('id="sgTextColorsAccordionPanel"')
    assert card_start < partial.index('id="sg-floating_panel_card_opacity"') < text_colors_start
    assert 'data-i18n="content.text.弹幕字体透明度"' in partial
    assert 'data-i18n="content.text.弹幕字体设置提示"' in partial

    text_colors_start = partial.index('id="sgTextColorsAccordionPanel"')
    username_start = partial.index('id="sgUsernameAccordionPanel"')
    tail_start = partial.index('id="sgTailAccordionPanel"')
    assert text_colors_start < partial.index('id="sg-floating_panel_opacity"') < username_start
    assert text_colors_start < partial.index('id="sg-floating_panel_font_family"') < username_start
    assert text_colors_start < partial.index('id="sg-floating_panel_content_size"') < username_start
    assert text_colors_start < partial.index('id="sg-font_file_input"') < tail_start
    assert 'id="sgFontAccordionPanel"' not in partial
    assert 'id="sg-floating_panel_content_size"' not in partial[
        username_start : partial.index('id="sgTailAccordionPanel"')
    ]
    assert 'id="sgFontImportAccordionTrigger"' not in partial

    horizontal_style_start = partial.index('id="sgHorizontalFontAccordionPanel"')
    horizontal_layout_start = partial.index('id="sgHorizontalLayoutAccordionPanel"')
    display_start = partial.index('id="sgHorizontalDisplayAccordionPanel"')
    resource_start = partial.index('id="sgHorizontalFontImportAccordionPanel"')
    assert horizontal_style_start < horizontal_layout_start < display_start < resource_start
    assert horizontal_style_start < partial.index('id="danmu_font_family"') < horizontal_layout_start
    assert horizontal_layout_start < partial.index('id="danmu_lines"') < display_start
    assert horizontal_layout_start < partial.index('id="layout_mode"') < display_start
    assert 'data-i18n="content.text.横向弹幕字体设置提示"' in partial
    assert display_start < partial.index('id="opacity"') < resource_start
    assert resource_start < partial.index('id="font_file_input"')


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


def test_settings_danmu_tab_has_no_style_preview():
    settings = (_static() / "partials" / "settings.html").read_text(encoding="utf-8")
    assert 'id="danmuStylePreview"' not in settings
    assert 'id="btnOpenStyleGeneratorFromSettings"' not in settings
    assert 'id="danmuPreviewScrolling"' not in settings
    assert 'id="danmuPreviewTrack"' not in settings


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


def test_style_generator_derives_legacy_style_fields_on_save():
    """遗留键 font_size/font_bold/tail_size 由权威字段派生，不再暴露重复控件。"""
    mod = (_static() / "modules" / "app-style-generator-page.js").read_text(encoding="utf-8")
    assert "export function applyDerivedLegacyStyleFields" in mod
    assert "DERIVED_STYLE_SAVE_KEYS" in mod

    script = """
import { applyDerivedLegacyStyleFields } from './web/static/modules/app-style-generator-page.js';
const payload = applyDerivedLegacyStyleFields({
  floating_panel_content_size: '24',
  floating_panel_content_weight: '400',
  floating_panel_username_weight: '700',
  floating_panel_tail_width: '8',
  floating_panel_tail_height: '18',
});
console.log(JSON.stringify(payload));
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
    assert payload["floating_panel_font_size"] == "24"
    assert payload["floating_panel_font_bold"] == "1"
    assert payload["floating_panel_tail_size"] == "18"


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
    assert "syncPresetVisibility" in mod
    assert "normalizeVisiblePreset" in mod
    assert "let activePresetId = 'blivechat_line';" in mod
    assert "syncPresetSelect" in mod
    assert "select.value = activePresetId" in mod
    assert "values.floating_panel_style_preset = visiblePreset" in mod
    assert "cardSection.hidden = isClassic" in mod
    assert "tailSection.hidden = isClassic" in mod
    assert "shapeField.hidden = isClassic" in mod
    assert "layoutField.hidden = isClassic" in mod
    assert ".settings-rhythm-accordion-item[hidden]" in css
    assert ".settings-field[hidden]" in css
    assert "layout-stacked" in css
    assert "--tail-border" in css
    assert "--tail-long-side" in css
    assert "--tail-rotate" in css
    assert 'data-tail-style="line_like"' in css or "[data-tail-style=\"line_like\"]" in css


def test_style_generator_preserves_unsaved_preview_when_navigating_back():
    """切页返回不应重新用旧服务端配置覆盖未保存的预览状态。"""
    mod = (_static() / "modules" / "app-style-generator-page.js").read_text(encoding="utf-8")
    load_body = mod.split("export async function loadStyleGeneratorPage()")[1].split(
        "export function initStyleGeneratorPage", 1
    )[0]
    assert "let styleGeneratorLoaded = false;" in mod
    assert "let styleGeneratorDirty = false;" in mod
    assert "let styleGeneratorLoadPromise = null;" in mod
    assert "if (styleGeneratorLoaded && styleGeneratorDirty) return;" in load_body
    assert "styleGeneratorDirty = true;" in mod
    assert "styleGeneratorDirty = false;" in mod
    assert "styleGeneratorLoadPromise" in load_body


def test_style_generator_animation_controls_drive_preview_and_web_panel():
    partial = (_static() / "partials" / "style-generator.html").read_text(encoding="utf-8")
    mod = (_static() / "modules" / "app-style-generator-page.js").read_text(encoding="utf-8")
    preview_css = (_static() / "warm-tokens-pages-stylegen.css").read_text(encoding="utf-8")
    panel_js = (_static() / "floating_panel" / "app.js").read_text(encoding="utf-8")
    panel_css = (_static() / "floating_panel" / "style.css").read_text(encoding="utf-8")

    for key in (
        "floating_panel_entry_animation",
        "floating_panel_entry_duration_ms",
        "floating_panel_push_duration_ms",
        "floating_panel_exit_animation",
        "floating_panel_exit_duration_ms",
    ):
        assert f'name="{key}"' in partial

    for fragment in (
        "entryAnimation",
        "pushMs",
        "exitAnimation",
        "animatePushedPreviewCards",
        "entry-slide-up",
        "entry-fade",
    ):
        assert fragment in mod
    for fragment in (
        "entry-slide-up",
        "entry-fade",
        "is-pushing",
        "sg-fp-pushUp",
    ):
        assert fragment in preview_css
        assert fragment.replace("sg-fp-", "") in panel_css or fragment in panel_css
    assert "stack.prepend(el)" in mod
    assert "push_duration_ms" in panel_js
    assert "panel.prepend(card)" in panel_js
    assert "entry_animation" in panel_js
    assert "exit_animation" in panel_js


def test_restore_default_uses_visible_wechat_style_preset():
    """恢复默认必须与当前可见的“仿微信”基础风格保持一致。"""
    mod = (_static() / "modules" / "app-style-generator-page.js").read_text(encoding="utf-8")
    restore_body = mod.split("async function restoreDefaultAndSave()")[1].split(
        "/* ---- 字体加载与导入 ---- */", 1
    )[0]
    assert "applyPreset('blivechat_line')" in restore_body
    assert "applyPreset('wechat')" not in restore_body


def test_manual_edits_mark_custom_but_preset_select_stays_on_base_style():
    """手动编辑后隐藏字段标为 custom，下拉仍保持当前基础风格（不展示自定义项）。"""
    mod = (_static() / "modules" / "app-style-generator-page.js").read_text(encoding="utf-8")
    partial = (_static() / "partials" / "style-generator.html").read_text(encoding="utf-8")
    assert "setFieldValue('floating_panel_style_preset', 'custom')" in mod
    assert "syncPresetSelect('custom')" in mod
    assert "let activePresetId = 'blivechat_line';" in mod
    assert "select.value = activePresetId" in mod
    assert 'value="custom"' not in partial


def test_style_generator_has_a_default_visible_preset_select():
    """页面异步加载配置前下拉默认选中仿微信基础风格。"""
    partial = (_static() / "partials" / "style-generator.html").read_text(encoding="utf-8")
    assert 'id="sgPresetSelect"' in partial
    assert 'value="blivechat_line"' in partial
    assert 'selected data-i18n="content.text.预设LineLike"' in partial


def test_preview_recomputes_existing_card_colors_when_presets_change_round_trip():
    """已有卡片必须按稳定 styleIndex 重算 classic -> wechat -> classic。"""
    script = """
import { refreshPreviewItemColors } from './web/static/modules/app-style-generator-page.js';
const item = { styleIndex: 1, cardColor: '#OLDOLD', textColor: '#OLDOLD', el: { dataset: {} } };
const classic = { cardColors: ['#FFFFFF', '#F5D401'], cardMode: 'equal', cardWeights: {}, textColors: ['#FFFFFF'], textMode: 'equal', textWeights: {} };
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
    assert payload["first"] == {"cardColor": "#F5D401", "textColor": "#FFFFFF"}
    assert payload["second"] == {"cardColor": "#DDF5D7", "textColor": "#281C12"}
    assert payload["third"] == payload["first"]
    assert payload["item"]["el"]["dataset"] == {
        "cardColor": "#F5D401",
        "textColor": "#FFFFFF",
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
    assert "renderStaticPreviewForRoot" in mod
    assert "我喜欢你" in mod


def test_app_js_wires_style_generator_navigate():
    app_js = (_static() / "app.js").read_text(encoding="utf-8")
    assert "ensureStyleGeneratorPage" in app_js
    assert "app-style-generator-page.js" in app_js
    assert "page === 'style-generator'" in app_js
    assert "loadStyleGeneratorPage" in app_js


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
