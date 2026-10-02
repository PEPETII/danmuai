/**
 * 样式生成器页（W-FP-STYLEGEN-WEB-001 / W-FP-STYLEGEN-PREVIEW-PARITY）
 *
 * - 并行 GET /api/config + /api/floating-panel/style-presets
 * - 表单 name 与 ConfigStore 扁平字段同名；仅保存时 PUT /api/config 子集
 * - 预览与默认真实路径 web/static/floating_panel 同构：
 *   column-reverse 底锚、max_items 顶出、2 行 clamp、卡片/气泡尾巴、入场 slideUp / 退出 fadeOut
 */

import { API, apiFetch, apiFormFetch } from './transport.js';
import { t } from './i18n.js';
import { initSettingsRhythmAccordion } from './settings-rhythm-accordion.js?v=20260717-number-stepper-v1';
import { initNumberSteppers } from './number-stepper.js?v=20260717-number-stepper-v1';
import { loadHorizontalFontPage, initHorizontalFontPage } from './app-horizontal-font-page.js';
import { populateFontSelect } from './settings-fonts.js';
import { initStyleGeneratorFieldHints } from './settings-hints.js';

import {
  SG_SINGLE_COLOR_FIELDS,
  hexToColorInputValue,
  hexToRgba,
  mergePickerRgbPreserveAlpha,
  normalizeHex,
  parsePalette,
  parseWeights,
  pickStyleColor,
} from './style-generator-colors.js';
import {
  STYLE_PRESET_CAPABILITIES,
  applyDerivedLegacyStyleFields,
  isStyleWeightBold,
  resolveBasePresetId,
  resolvePresetCapabilities,
} from './style-generator-preset.js';
import { createStyleGeneratorCustomCss } from './style-generator-custom-css.js';
import { createStyleGeneratorFonts } from './style-generator-fonts.js';
import {
  ADJUST_DISPLAY_AREA_KEY,
  BOOL_KEYS,
  DERIVED_STYLE_SAVE_KEYS,
  STYLE_SAVE_KEYS,
} from './style-generator-state.js';
import { createStyleGeneratorPersistence } from './style-generator-persistence.js';

export {
  STYLE_PRESET_CAPABILITIES,
  applyDerivedLegacyStyleFields,
  pickStyleColor,
  resolvePresetCapabilities,
};

const PREVIEW_TEXTS = [
  '呵 生活终于对我下手了吗',
  '我的口水占领了整个枕头',
  '安排的明明白白的',
  '白内障看不清，需要一串猪眼睛',
  '这个慢镜头犯规啊！停下来咽口水',
  '你现在吃的是老子',
  '一个从来没有差评的宝贝',
  '第一次看见有人把手残说的这么秀气的',
  '偷完小孩就偷狗，世风日下啊！',
  '他可能对我们的能力也有点误解',
];

let toast = () => {};
let handlersBound = false;
let presetsPayload = null;
let suppressCustomMark = false;
// 导航回到本页时，保留用户尚未保存的表单与预览；服务端配置只用于首次加载
// 或当前没有未保存编辑时的重新同步。
let styleGeneratorLoaded = false;
let styleGeneratorDirty = false;
let styleGeneratorLoadPromise = null;
let adjustDisplayAreaSaveChain = Promise.resolve();
// 基础风格下拉表示当前自定义样式的来源；它与保存用的 custom preset 字段独立。
// 页面首次加载无法从 custom 配置可靠推断来源时，按产品默认显示仿微信。
let activePresetId = 'blivechat_line';
let styleIndexSeq = 0;
/** @type {{el: HTMLElement, styleIndex: number, cardColor: string, textColor: string, text: string}[]} */
let previewItems = [];
let previewTextIndex = 0;
let maxCardsCached = 12;
let panelWidthCached = 360;
let exitDurationMsCached = 200;
let entryAnimationCached = 'fade';
let exitAnimationCached = 'fade';
let pushDurationMsCached = 180;
const previewPushTransitionHandlers = new WeakMap();
let previewUsername = '高压吐槽型';

function previewStageEl() {
  return document.getElementById('styleGeneratorPreview');
}

/**
 * Keep user CSS inside a shadow root. The real panel receives the same raw
 * selectors, while .card/#panel rules cannot leak into the settings page.
 */
function ensurePreviewShadowDom() {
  const stage = previewStageEl();
  if (!stage) return null;
  if (stage.shadowRoot) return stage.shadowRoot;
  const root = stage.attachShadow({ mode: 'open' });
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = new URL('/static/warm-tokens-pages-stylegen.css', document.baseURI).href;
  root.appendChild(link);

  const base = document.createElement('style');
  base.textContent = `
    :host { display: block; position: relative; }
    #page-style-generator { width: 100%; height: 100%; }
    #panel { width: 100%; height: 100%; min-height: 320px; position: relative; overflow: hidden; }
  `;
  root.appendChild(base);

  const page = document.createElement('div');
  page.id = 'page-style-generator';
  const panel = document.createElement('div');
  panel.id = 'panel';
  panel.className = 'sg-preview-stage';
  const stack = document.createElement('div');
  stack.id = 'styleGeneratorPreviewStack';
  stack.className = 'sg-preview-stack';
  panel.appendChild(stack);
  page.appendChild(panel);
  root.appendChild(page);

  const customStyle = document.createElement('style');
  customStyle.id = 'sgCustomCssOverride';
  customStyle.dataset.purpose = 'managed-custom-css';
  root.appendChild(customStyle);
  return root;
}

function previewStackEl() {
  return ensurePreviewShadowDom()?.getElementById('styleGeneratorPreviewStack') || null;
}

function setPreviewCustomCss(css) {
  const root = ensurePreviewShadowDom();
  const style = root?.getElementById('sgCustomCssOverride');
  if (!style) return;
  try {
    style.textContent = typeof css === 'string' ? css : '';
  } catch (error) {
    console.warn('setPreviewCustomCss failed:', error);
  }
}

function showToast(message, isError = false) {
  toast(message, isError);
}

const styleGeneratorPersistence = createStyleGeneratorPersistence({
  styleSaveKeys: STYLE_SAVE_KEYS,
  boolKeys: BOOL_KEYS,
  adjustDisplayAreaKey: ADJUST_DISPLAY_AREA_KEY,
  derivedStyleSaveKeys: DERIVED_STYLE_SAVE_KEYS,
  readBool,
  readStr,
  applyDerivedLegacyStyleFields,
  apiFetch,
  t,
  showToast,
  setDirty: (dirty) => {
    styleGeneratorDirty = dirty;
  },
});
const scheduleStyleSave = (options = {}) => styleGeneratorPersistence.schedule(options);

const styleGeneratorFonts = createStyleGeneratorFonts({
  API,
  apiFetch,
  apiFormFetch,
  populateFontSelect,
  showToast,
});
const {
  loadStyleGeneratorFontFamilies,
  uploadStyleGeneratorFont,
} = styleGeneratorFonts;

const styleGeneratorCustomCss = createStyleGeneratorCustomCss({
  apiFetch,
  apiFormFetch,
  t,
  showToast,
  readStr,
  setFieldValue,
  setPreviewCustomCss,
  syncPresetSelect,
  syncPresetVisibility,
  markDirty: () => {
    styleGeneratorDirty = true;
  },
  scheduleStyleSave,
});

function formEl() {
  return document.getElementById('styleGeneratorForm');
}

function field(name) {
  const form = formEl();
  if (!form) return null;
  return form.querySelector(`[name="${name}"]`);
}

function readBool(name) {
  const el = field(name);
  return Boolean(el?.checked);
}

function readStr(name, fallback = '') {
  const el = field(name);
  if (!el) return fallback;
  return String(el.value ?? fallback);
}

function readInt(name, fallback) {
  const n = parseInt(readStr(name, String(fallback)), 10);
  return Number.isNaN(n) ? fallback : n;
}

function setFieldValue(name, value) {
  const el = field(name);
  if (!el) return;
  if (BOOL_KEYS.has(name)) {
    const enabled = value === '1' || value === 1 || value === true || value === 'true';
    // The UI describes the temporary interactive state; the stored key keeps
    // its original native meaning for WebView2/Win32 compatibility.
    el.checked = name === ADJUST_DISPLAY_AREA_KEY ? !enabled : enabled;
    return;
  }
  el.value = value == null ? '' : String(value);
  if (el.type === 'number' && el.closest('.settings-rhythm-stepper')) {
    el.dispatchEvent(new Event('input', { bubbles: true }));
  }
  if (SG_SINGLE_COLOR_FIELDS.includes(name)) {
    const picker = document.querySelector(`[data-sg-color-for="${name}"]`);
    if (picker) picker.value = hexToColorInputValue(el.value, picker.value || '#FFFFFF');
  }
}

function markCustomIfNeeded() {
  if (suppressCustomMark) return;
  styleGeneratorDirty = true;
  if (readStr('floating_panel_style_preset', '') === 'custom_css') {
    syncPresetSelect('custom_css');
    syncPresetVisibility('custom_css');
    return;
  }
  setFieldValue('floating_panel_style_preset', 'custom');
  syncPresetSelect();
  syncPresetVisibility(activePresetId);
}

/** 可见下拉仅表示基础风格地基；custom/wechat 等回退到产品默认仿微信。 */
function syncPresetSelect(basePresetId) {
  if (basePresetId === 'custom_css') {
    const select = document.getElementById('sgPresetSelect');
    if (select) select.value = 'custom_css';
    return;
  }
  if (basePresetId === 'classic' || basePresetId === 'blivechat_line') {
    activePresetId = basePresetId;
  }
  const select = document.getElementById('sgPresetSelect');
  if (!select) return;
  // custom 仅写入隐藏字段；custom_css 是独立模式，不能点亮基础风格。
  select.value = activePresetId;
}

function normalizeVisiblePreset(values, presets) {
  const configuredPreset = String(values.floating_panel_style_preset || '').trim();
  const basePresetId = resolveBasePresetId(configuredPreset, presets);
  activePresetId = basePresetId;

  if (configuredPreset === 'classic' || configuredPreset === 'blivechat_line') {
    values.floating_panel_style_preset = configuredPreset;
    return;
  }
  if (configuredPreset === 'custom') {
    values.floating_panel_style_preset = 'custom';
    return;
  }
  if (configuredPreset === 'custom_css') {
    values.floating_panel_style_preset = 'custom_css';
    return;
  }
  if (presets?.presets?.[basePresetId]) {
    Object.assign(values, presets.presets[basePresetId]);
  }
  values.floating_panel_style_preset = basePresetId;
}

/** 基础风格 → 表单能力映射；新增风格时在此登记即可扩展显隐规则。 */
const CUSTOM_CSS_VISUAL_ACCORDION_TRIGGERS = [
  'sgBasicAccordionTrigger',
  'sgCardColorsAccordionTrigger',
  'sgTextColorsAccordionTrigger',
  'sgStrokeShadowBorderAccordionTrigger',
  'sgUsernameAccordionTrigger',
  'sgTailAccordionTrigger',
  'sgAnimationAccordionTrigger',
];

/** 将 preset/custom 解析为当前基础风格的能力表；仅隐藏 UI，不改动字段值。 */
function setSettingsFieldHidden(fieldId, hidden) {
  const el = document.getElementById(fieldId)?.closest('.settings-field');
  if (el) el.hidden = hidden;
}

function setAccordionItemHidden(triggerId, hidden) {
  const el = document.getElementById(triggerId)?.closest('.settings-rhythm-accordion-item');
  if (el) el.hidden = hidden;
}

function setCapabilityGroupsHidden(capability, hidden) {
  document.querySelectorAll(`#page-style-generator [data-sg-capability="${capability}"]`)
    .forEach((el) => {
      el.hidden = hidden;
    });
}

/** 仿 YouTube 只隐藏不适用的设置，切回仿微信/自定义时恢复可见并保留字段值。 */
export function syncPresetVisibility(preset) {
  const isCustomCss = preset === 'custom_css';
  const caps = resolvePresetCapabilities(preset, activePresetId);
  const customCssSection = document.getElementById('sgCustomCssSection');
  if (customCssSection) customCssSection.hidden = !isCustomCss;

  if (isCustomCss) {
    CUSTOM_CSS_VISUAL_ACCORDION_TRIGGERS.forEach((id) => {
      setAccordionItemHidden(id, true);
    });
    return;
  }

  const show = (key) => caps[key] !== false;
  setSettingsFieldHidden('sg-floating_panel_shape', !show('shape'));
  setSettingsFieldHidden('sg-floating_panel_layout', !show('layout'));
  setAccordionItemHidden('sgCardColorsAccordionTrigger', !show('bubble'));
  setAccordionItemHidden('sgTailAccordionTrigger', !show('tail'));
  setSettingsFieldHidden('sg-floating_panel_radius', !show('radius'));
  setSettingsFieldHidden('sg-floating_panel_padding_x', !show('padding'));
  setSettingsFieldHidden('sg-floating_panel_padding_y', !show('padding'));
  setCapabilityGroupsHidden('shadow', !show('shadow'));
  setCapabilityGroupsHidden('border', !show('border'));

  CUSTOM_CSS_VISUAL_ACCORDION_TRIGGERS.forEach((id) => {
    setAccordionItemHidden(id, false);
  });
  setAccordionItemHidden('sgCardColorsAccordionTrigger', !show('bubble'));
  setAccordionItemHidden('sgTailAccordionTrigger', !show('tail'));
}

function writePaletteHidden(kind) {
  const listId = kind === 'card' ? 'sgCardColorList' : 'sgTextColorList';
  const colors = Array.from(document.querySelectorAll(`#${listId} .sg-color-chip`))
    .map((chip) => normalizeHex(chip.dataset.color))
    .filter(Boolean);
  const key = kind === 'card' ? 'floating_panel_card_colors' : 'floating_panel_text_colors';
  setFieldValue(key, JSON.stringify(colors));
  renderWeightsPanel(kind, colors);
}

function renderColorList(kind, colors) {
  const listId = kind === 'card' ? 'sgCardColorList' : 'sgTextColorList';
  const list = document.getElementById(listId);
  if (!list) return;
  list.innerHTML = '';
  (colors || []).forEach((color) => {
    const chip = document.createElement('div');
    chip.className = 'sg-color-chip';
    chip.dataset.color = color;
    chip.innerHTML = `
      <span class="sg-color-swatch" style="background:${hexToRgba(color)}"></span>
      <span class="sg-color-hex">${color}</span>
      <button type="button" class="sg-color-remove" data-kind="${kind}" data-color="${color}" aria-label="remove">×</button>
    `;
    list.appendChild(chip);
  });
  writePaletteHidden(kind);
}

function renderWeightsPanel(kind, colors) {
  const modeKey = kind === 'card' ? 'floating_panel_card_color_mode' : 'floating_panel_text_color_mode';
  const weightsKey = kind === 'card' ? 'floating_panel_card_color_weights' : 'floating_panel_text_color_weights';
  const panelId = kind === 'card' ? 'sgCardWeightsPanel' : 'sgTextWeightsPanel';
  const panel = document.getElementById(panelId);
  if (!panel) return;
  const mode = readStr(modeKey, 'equal');
  panel.classList.toggle('hidden', mode !== 'weighted');
  if (mode !== 'weighted') return;

  const existing = parseWeights(readStr(weightsKey, '{}'));
  panel.innerHTML = '';
  (colors || []).forEach((color) => {
    const row = document.createElement('label');
    row.className = 'sg-weight-row';
    const w = existing[color] != null ? existing[color] : 1;
    row.innerHTML = `
      <span class="sg-color-swatch" style="background:${hexToRgba(color)}"></span>
      <span class="sg-color-hex">${color}</span>
      <input type="number" min="0" step="0.1" value="${w}" data-weight-color="${color}" data-kind="${kind}" class="settings-field-control sg-weight-input ui-control ui-input">
    `;
    panel.appendChild(row);
  });
  initNumberSteppers(panel);
  syncWeightsFromPanel(kind);
}

function syncWeightsFromPanel(kind) {
  const panelId = kind === 'card' ? 'sgCardWeightsPanel' : 'sgTextWeightsPanel';
  const weightsKey = kind === 'card' ? 'floating_panel_card_color_weights' : 'floating_panel_text_color_weights';
  const panel = document.getElementById(panelId);
  if (!panel) return;
  const obj = {};
  panel.querySelectorAll('.sg-weight-input').forEach((input) => {
    const color = normalizeHex(input.dataset.weightColor);
    const n = parseFloat(input.value);
    if (color) obj[color] = Number.isFinite(n) && n >= 0 ? n : 0;
  });
  setFieldValue(weightsKey, JSON.stringify(obj));
}

function applyValuesToForm(values) {
  if (!values) return;
  suppressCustomMark = true;
  try {
    STYLE_SAVE_KEYS.forEach((key) => {
      if (values[key] !== undefined && values[key] !== null) {
        setFieldValue(key, values[key]);
      }
    });
    const cardColors = parsePalette(values.floating_panel_card_colors);
    const textColors = parsePalette(values.floating_panel_text_colors);
    renderColorList('card', cardColors.length ? cardColors : ['#FFECD2']);
    renderColorList('text', textColors.length ? textColors : ['#281C12']);
    const savedPreset = String(values.floating_panel_style_preset || '').trim();
    if (savedPreset === 'classic' || savedPreset === 'blivechat_line') {
      activePresetId = savedPreset;
    }
    syncPresetSelect(savedPreset === 'custom_css' ? 'custom_css' : undefined);
    syncPresetVisibility(savedPreset === 'custom_css' ? 'custom_css' : activePresetId);
  } finally {
    suppressCustomMark = false;
  }
}

function applyPreset(presetId) {
  if (presetId === 'custom_css') {
    setFieldValue('floating_panel_style_preset', 'custom_css');
    syncPresetSelect('custom_css');
    syncPresetVisibility('custom_css');
    setPreviewCustomCss(styleGeneratorCustomCss.getText());
    styleGeneratorDirty = true;
    scheduleStyleSave();
    showToast(t('dynamic.appStyleGenerator.已切换自定义CSS'));
    return;
  }
  const patch = presetsPayload?.presets?.[presetId];
  if (!patch) {
    showToast(t('dynamic.appStyleGenerator.预设不可用'), true);
    return;
  }
  applyValuesToForm({
    ...patch,
    floating_panel_style_preset: presetId,
    floating_panel_custom_css_file: '',
  });
  activePresetId = presetId;
  syncPresetSelect(presetId);
  syncPresetVisibility(presetId);
  styleGeneratorCustomCss.clearText();
  setPreviewCustomCss('');
  styleGeneratorDirty = true;
  restyleVisiblePreviewItems();
  scheduleStyleSave();
  showToast(t('dynamic.appStyleGenerator.已应用预设_preset', { preset: presetId }));
}

function readPreviewStyle() {
  const layoutRaw = readStr('floating_panel_layout', 'inline');
  return {
    shape: readStr('floating_panel_shape', 'bubble'),
    layout: layoutRaw === 'stacked' ? 'stacked' : 'inline',
    cardColors: parsePalette(readStr('floating_panel_card_colors', '[]')),
    cardMode: readStr('floating_panel_card_color_mode', 'equal'),
    cardWeights: parseWeights(readStr('floating_panel_card_color_weights', '{}')),
    textColors: parsePalette(readStr('floating_panel_text_colors', '[]')),
    textMode: readStr('floating_panel_text_color_mode', 'equal'),
    textWeights: parseWeights(readStr('floating_panel_text_color_weights', '{}')),
    cardOpacity: Math.max(0, Math.min(100, readInt('floating_panel_card_opacity', 88))) / 100,
    panelOpacity: Math.max(0, Math.min(100, readInt('floating_panel_opacity', 85))) / 100,
    outlineEnabled: readBool('floating_panel_outline_enabled'),
    outlineColor: readStr('floating_panel_outline_color', '#FFFFFFC8'),
    outlineWidth: readInt('floating_panel_outline_width', 2),
    shadowEnabled: readBool('floating_panel_shadow_enabled'),
    shadowColor: readStr('floating_panel_shadow_color', '#000000'),
    shadowOpacity: Math.max(0, Math.min(100, readInt('floating_panel_shadow_opacity', 30))) / 100,
    shadowBlur: readInt('floating_panel_shadow_blur', 12),
    shadowOffsetX: readInt('floating_panel_shadow_offset_x', 2),
    shadowOffsetY: readInt('floating_panel_shadow_offset_y', 2),
    borderEnabled: readBool('floating_panel_border_enabled'),
    borderColor: readStr('floating_panel_border_color', '#FFFFFF'),
    borderWidth: readInt('floating_panel_border_width', 1),
    borderOpacity: Math.max(0, Math.min(100, readInt('floating_panel_border_opacity', 45))) / 100,
    paddingX: readInt('floating_panel_padding_x', 14),
    paddingY: readInt('floating_panel_padding_y', 10),
    radius: readInt('floating_panel_radius', 16),
    tailEnabled: readBool('floating_panel_tail_enabled'),
    tailStyle: readStr('floating_panel_tail_style', 'round'),
    tailWidth: readInt('floating_panel_tail_width', 8),
    tailHeight: readInt('floating_panel_tail_height', 10),
    tailOffsetY: readInt('floating_panel_tail_offset_y', 38),
    tailBorder: readInt('floating_panel_tail_border', 8),
    tailLongSide: readInt('floating_panel_tail_long_side', 18),
    tailRotateDeg: readInt('floating_panel_tail_rotate_deg', 35),
    usernameEnabled: readBool('floating_panel_username_enabled'),
    usernameText: readStr('floating_panel_username_text', '弹幕'),
    usernameColor: readStr('floating_panel_username_color', '#281C12'),
    usernameSize: readInt('floating_panel_username_size', 14),
    usernameWeight: readInt('floating_panel_username_weight', 700),
    usernameSeparator: readStr('floating_panel_username_separator', '：'),
    contentSize: readInt('floating_panel_content_size', 16),
    contentWeight: readInt('floating_panel_content_weight', 400),
    contentLineHeight: Math.max(1, readInt('floating_panel_content_line_height', 140) / 100),
    gapUsernameContent: readInt('floating_panel_gap_username_content', 4),
    entryAnimation: readStr('floating_panel_entry_animation', 'fade'),
    entryMs: Math.max(0, readInt('floating_panel_entry_duration_ms', 200)),
    pushMs: Math.max(0, readInt('floating_panel_push_duration_ms', 180)),
    exitAnimation: readStr('floating_panel_exit_animation', 'fade'),
    exitMs: Math.max(0, readInt('floating_panel_exit_duration_ms', 200)),
    stackGap: Math.max(0, readInt('floating_panel_stack_gap', 8)),
    fontFamily: readStr('floating_panel_font_family', 'Microsoft YaHei'),
    fontBold: isStyleWeightBold(readInt('floating_panel_content_weight', 400))
      || isStyleWeightBold(readInt('floating_panel_username_weight', 700)),
    maxItems: maxCardsCached,
    panelWidth: panelWidthCached,
  };
}

/** 同步舞台级 CSS 变量（与 floating_panel applyConfig 对齐） */
function applyStageConfig(style) {
  const stage = document.getElementById('styleGeneratorPreview');
  if (!stage) return;
  stage.style.setProperty('--stack-gap', `${style.stackGap}px`);
  stage.style.setProperty('--panel-padding', '16px');
  stage.style.setProperty('--entry-duration', `${style.entryMs}ms`);
  stage.style.setProperty('--push-duration', `${style.pushMs}ms`);
  stage.style.setProperty('--exit-duration', `${style.exitMs}ms`);
  stage.style.setProperty('--panel-opacity', String(style.panelOpacity));
  stage.style.setProperty('--font-family', style.fontFamily || 'Microsoft YaHei, PingFang SC, sans-serif');
  const maxW = Math.max(120, style.panelWidth - 40);
  stage.style.setProperty('--card-max-width', `${maxW}px`);
  maxCardsCached = style.maxItems;
  entryAnimationCached = ['none', 'fade', 'slide_up'].includes(style.entryAnimation)
    ? style.entryAnimation : 'fade';
  pushDurationMsCached = style.pushMs;
  exitAnimationCached = ['none', 'fade'].includes(style.exitAnimation)
    ? style.exitAnimation : 'fade';
  exitDurationMsCached = style.exitMs;
}

/** 与 floating_panel/app.js applyCardStyleVars 同语义（写在卡片元素上） */
function applyCardStyleVars(cardEl, style, cardColor, textColor) {
  if (!cardEl) return;
  const s = cardEl.style;
  const bg = hexToRgba(cardColor, style.cardOpacity);
  s.setProperty('--card-bg', bg);
  s.setProperty('--tail-color', bg);
  s.setProperty('--card-border', hexToRgba(style.borderColor, style.borderOpacity));
  s.setProperty('--username-color', style.usernameColor);
  s.setProperty('--content-color', textColor);
  s.setProperty('--outline-color', style.outlineColor);
  s.setProperty('--font-family', style.fontFamily || 'inherit');
  s.setProperty('--font-size-username', `${style.usernameSize}px`);
  s.setProperty('--font-size-content', `${style.contentSize}px`);
  s.setProperty('--card-radius', `${style.radius}px`);
  s.setProperty('--card-max-width', `${Math.max(120, style.panelWidth - 40)}px`);
  s.setProperty('--padding-x', `${style.paddingX}px`);
  s.setProperty('--padding-y', `${style.paddingY}px`);
  s.setProperty('--border-width', `${style.borderWidth}px`);
  s.setProperty('--font-weight-username', String(style.usernameWeight));
  s.setProperty('--font-weight-content', String(style.contentWeight));
  s.setProperty('--content-line-height', String(style.contentLineHeight));
  s.setProperty('--gap-username-content', `${style.gapUsernameContent}px`);
  s.setProperty('--outline-w', `${style.outlineWidth}px`);
  s.setProperty('--tail-w', `${style.tailWidth}px`);
  s.setProperty('--tail-h', `${style.tailHeight}px`);
  s.setProperty('--tail-offset-y', `${style.tailOffsetY}%`);
  s.setProperty('--tail-border', `${style.tailBorder}px`);
  s.setProperty('--tail-long-side', `${style.tailLongSide}px`);
  s.setProperty('--tail-rotate', `${style.tailRotateDeg}deg`);
  if (style.shadowEnabled) {
    s.setProperty(
      '--card-shadow',
      `${style.shadowOffsetX}px ${style.shadowOffsetY}px ${style.shadowBlur}px ${hexToRgba(style.shadowColor, style.shadowOpacity)}`,
    );
  } else {
    s.setProperty('--card-shadow', 'none');
  }

  const isStacked = style.layout === 'stacked';
  cardEl.classList.toggle('layout-stacked', isStacked);
  cardEl.classList.toggle('layout-inline', !isStacked);
  cardEl.classList.toggle('no-border', !(style.borderEnabled && style.borderWidth > 0));
  cardEl.classList.toggle('no-card-surface', style.cardOpacity <= 0);
  cardEl.classList.toggle('uses-backdrop', style.cardOpacity > 0 && style.cardOpacity < 100);
  cardEl.classList.toggle('has-outline', Boolean(style.outlineEnabled && style.outlineWidth > 0));
  cardEl.classList.toggle('is-bold', Boolean(style.fontBold));
  const isBubble = style.shape === 'bubble' && style.tailEnabled;
  cardEl.classList.toggle('is-bubble', isBubble);
  if (isBubble) {
    cardEl.dataset.tailStyle = style.tailStyle || 'round';
  } else {
    delete cardEl.dataset.tailStyle;
  }
}

/** Recompute palette colors for an existing preview item after a style change. */
export function refreshPreviewItemColors(item, style) {
  if (!item || !style) return { cardColor: '#FFFFFF', textColor: '#FFFFFF' };
  const cardColor = pickStyleColor(
    style.cardColors,
    style.cardMode,
    style.cardWeights,
    item.styleIndex,
  );
  const textColor = pickStyleColor(
    style.textColors,
    style.textMode,
    style.textWeights,
    item.styleIndex,
  );
  item.cardColor = cardColor;
  item.textColor = textColor;
  if (item.el?.dataset) {
    item.el.dataset.cardColor = cardColor;
    item.el.dataset.textColor = textColor;
  }
  return { cardColor, textColor };
}

/** 与 floating_panel addCard 同构：stacked → .username + .bubble > .content */
function buildPreviewCardInnerHtml(style, text) {
  const usernameLabel = style.usernameEnabled
    ? `${previewUsername}${style.usernameSeparator}`
    : '';
  const usernameHtml = style.usernameEnabled
    ? `<div class="username">${escapePreviewHtml(usernameLabel)}</div>`
    : '<div class="username is-hidden"></div>';
  if (style.layout === 'stacked') {
    return (
      `${usernameHtml}` +
      `<div class="bubble"><div class="content">${escapePreviewHtml(text)}</div></div>`
    );
  }
  return (
    `${usernameHtml}` +
    `<div class="content">${escapePreviewHtml(text)}</div>`
  );
}

function syncPreviewCardDom(cardEl, style, text) {
  if (!cardEl) return;
  const wantStacked = style.layout === 'stacked';
  const hasBubble = Boolean(cardEl.querySelector(':scope > .bubble'));
  if (wantStacked !== hasBubble) {
    cardEl.innerHTML = buildPreviewCardInnerHtml(style, text);
    return;
  }
  const usernameEl = cardEl.querySelector(':scope > .username');
  if (usernameEl) {
    if (style.usernameEnabled) {
      usernameEl.classList.remove('is-hidden');
      usernameEl.textContent = `${previewUsername}${style.usernameSeparator}`;
    } else {
      usernameEl.classList.add('is-hidden');
      usernameEl.textContent = '';
    }
  }
  const contentEl = wantStacked
    ? cardEl.querySelector(':scope > .bubble > .content')
    : cardEl.querySelector(':scope > .content');
  if (contentEl && text != null) {
    contentEl.textContent = text;
  }
}

function restyleVisiblePreviewItems() {
  const style = readPreviewStyle();
  applyStageConfig(style);
  previewItems.forEach((item) => {
    if (!item.el) return;
    syncPreviewCardDom(item.el, style, item.text);
    const { cardColor, textColor } = refreshPreviewItemColors(item, style);
    applyCardStyleVars(item.el, style, cardColor, textColor);
  });
  removeOldestIfNeeded();
}

function applyPreviewEntryAnimation(card) {
  if (!card) return;
  card.classList.remove('entry-fade', 'entry-slide-up');
  if (entryAnimationCached === 'fade') card.classList.add('entry-fade');
  if (entryAnimationCached === 'slide_up') card.classList.add('entry-slide-up');
}

function parseTransformY(value) {
  const raw = String(value || '');
  if (!raw || raw === 'none') return 0;
  let match = raw.match(/^matrix3d\(([^)]+)\)$/);
  if (match) {
    const matrix3d = match[1].split(',');
    return Number(matrix3d[13]) || 0;
  }
  match = raw.match(/^matrix\(([^)]+)\)$/);
  if (match) {
    const matrix = match[1].split(',');
    return Number(matrix[5]) || 0;
  }
  return 0;
}

function forgetPreviewPushTransition(slot) {
  if (!slot) return;
  const handler = previewPushTransitionHandlers.get(slot);
  if (!handler) return;
  slot.removeEventListener('transitionend', handler);
  slot.removeEventListener('transitioncancel', handler);
  previewPushTransitionHandlers.delete(slot);
}

/** Freeze only the preview slot; leave the child card's entry animation alive. */
function freezePreviewCardMotion(slot, currentY) {
  if (!slot) return;
  if (currentY == null) currentY = parseTransformY(getComputedStyle(slot).transform);
  const isPushing = slot.classList.contains('is-pushing');
  if (!isPushing && Math.abs(currentY) <= 0.01) return;
  forgetPreviewPushTransition(slot);
  slot.classList.remove('is-pushing');
  slot.style.setProperty('transition', 'none');
  if (Math.abs(currentY) > 0.01) {
    slot.style.transform = `translateY(${currentY}px)`;
  } else {
    slot.style.removeProperty('transform');
  }
  slot.style.removeProperty('transition');
}

function freezeAllPreviewCardMotions() {
  const stack = previewStackEl();
  if (!stack) return;
  const motions = Array.from(stack.children).map((slot) => ({
    slot,
    currentY: parseTransformY(getComputedStyle(slot).transform),
  }));
  motions.forEach(({ slot, currentY }) => freezePreviewCardMotion(slot, currentY));
}

function snapshotPreviewCardTops() {
  const stack = previewStackEl();
  const tops = new Map();
  if (!stack) return tops;
  Array.from(stack.children).forEach((slot) => tops.set(slot, slot.getBoundingClientRect().top));
  return tops;
}

function animatePushedPreviewCards(previousTops) {
  const stack = previewStackEl();
  if (!stack || !previousTops) return;
  const motions = [];

  // Read every post-layout slot position before writing any inverse transform.
  previousTops.forEach((beforeTop, slot) => {
    if (!slot.parentNode) return;
    const frozenY = parseTransformY(getComputedStyle(slot).transform);
    const afterRect = slot.getBoundingClientRect();
    const layoutTop = afterRect.top - frozenY;
    const delta = Number.isFinite(beforeTop - layoutTop) ? beforeTop - layoutTop : 0;
    if (Math.abs(delta) > 0.01) motions.push({ slot, delta });
  });

  if (pushDurationMsCached <= 0) {
    motions.forEach(({ slot }) => slot.style.removeProperty('transform'));
    return;
  }
  if (!motions.length) return;

  // FLIP write phase, followed by one layout read for the complete batch.
  motions.forEach(({ slot, delta }) => {
    forgetPreviewPushTransition(slot);
    slot.classList.remove('is-pushing');
    slot.style.setProperty('transition', 'none');
    slot.style.transform = `translateY(${delta}px)`;
    slot.style.removeProperty('transition');
  });
  void stack.offsetHeight;

  // FLIP play phase; only the slot moves, so entry fade/slide stays on .card.
  motions.forEach(({ slot }) => {
    const handler = (event) => {
      if (event.target !== slot || event.propertyName !== 'transform') return;
      if (previewPushTransitionHandlers.get(slot) !== handler) return;
      forgetPreviewPushTransition(slot);
      slot.classList.remove('is-pushing');
      slot.style.removeProperty('transform');
    };
    previewPushTransitionHandlers.set(slot, handler);
    slot.addEventListener('transitionend', handler);
    slot.addEventListener('transitioncancel', handler);
    slot.classList.add('is-pushing');
    slot.style.removeProperty('transform');
  });
}
function removePreviewSlot(slot) {
  if (!slot) return;
  forgetPreviewPushTransition(slot);
  const card = slot.querySelector(':scope > .sg-preview-card');
  if (card) previewItems = previewItems.filter((item) => item.el !== card);
  if (slot.parentNode) slot.parentNode.removeChild(slot);
}

function scheduleCardExit(node) {
  // Strict max-card parity with the real WebView panel: an evicted slot leaves
  // flex layout synchronously, so an exit animation cannot expose max + 1.
  const slot = node?.classList?.contains('sg-preview-card-slot') ? node : node?.parentNode;
  removePreviewSlot(slot || node);
}

function removeOldestIfNeeded() {
  const stack = previewStackEl();
  if (!stack) return;
  const maxCards = maxCardsCached || 12;
  while (stack.children.length > maxCards) {
    scheduleCardExit(stack.lastElementChild);
  }
}

function addPreviewMessage(text) {
  const stack = previewStackEl();
  if (!stack) return;
  freezeAllPreviewCardMotions();
  const previousTops = snapshotPreviewCardTops();
  const style = readPreviewStyle();
  applyStageConfig(style);
  const idx = styleIndexSeq++ % 1024;
  const cardColor = pickStyleColor(style.cardColors, style.cardMode, style.cardWeights, idx);
  const textColor = pickStyleColor(style.textColors, style.textMode, style.textWeights, idx);

  const slot = document.createElement('div');
  slot.className = 'sg-preview-card-slot';
  const el = document.createElement('div');
  el.className = 'sg-preview-card card';
  el.dataset.styleIndex = String(idx);
  el.dataset.cardId = `sg-${idx}-${Date.now()}`;
  el.dataset.cardColor = cardColor;
  el.dataset.textColor = textColor;
  el.innerHTML = buildPreviewCardInnerHtml(style, text);

  applyCardStyleVars(el, style, cardColor, textColor);
  applyPreviewEntryAnimation(el);
  slot.appendChild(el);
  // column-reverse places the first DOM child at the bottom; prepend keeps
  // the newest preview card at the bottom and pushes older cards upward.
  stack.prepend(slot);
  previewItems.push({
    el,
    text,
    styleIndex: idx,
    cardColor,
    textColor,
  });
  removeOldestIfNeeded();
  animatePushedPreviewCards(previousTops);
}

function escapePreviewHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
}

function clearPreview() {
  previewItems = [];
  const stack = previewStackEl();
  if (stack) {
    Array.from(stack.children).forEach((slot) => forgetPreviewPushTransition(slot));
    stack.innerHTML = '';
  }
}

function saveAdjustDisplayArea() {
  const checkbox = field(ADJUST_DISPLAY_AREA_KEY);
  if (!checkbox) return;
  const requested = Boolean(checkbox.checked);
  adjustDisplayAreaSaveChain = adjustDisplayAreaSaveChain
    .catch(() => {})
    .then(async () => {
      // If another toggle arrived before this request started, only the newest
      // state should reach the server.
      if (Boolean(checkbox.checked) !== requested) return;
      await apiFetch('/api/config', {
        method: 'PUT',
        body: JSON.stringify({
          [ADJUST_DISPLAY_AREA_KEY]: requested ? '0' : '1',
        }),
      });
    })
    .catch((error) => {
      if (Boolean(checkbox.checked) === requested) checkbox.checked = !requested;
      showToast(error.message || t('dynamic.appStyleGenerator.保存失败'), true);
    });
}

function seedPreview() {
  clearPreview();
  for (let i = 0; i < 3; i++) {
    const fn = PREVIEW_TEXTS[i % PREVIEW_TEXTS.length];
    addPreviewMessage(typeof fn === 'function' ? fn() : fn);
  }
}

function onFormChange(event) {
  const target = event.target;
  if (!target || !formEl()?.contains(target)) return;

  if (target.name === ADJUST_DISPLAY_AREA_KEY) {
    restyleVisiblePreviewItems();
    if (event.type === 'change') saveAdjustDisplayArea();
    return;
  }

  if (target.classList.contains('sg-weight-input')) {
    syncWeightsFromPanel(target.dataset.kind || 'card');
  }

  if (target.name === 'floating_panel_card_color_mode') {
    writePaletteHidden('card');
  }
  if (target.name === 'floating_panel_text_color_mode') {
    writePaletteHidden('text');
  }

  if (target.name && target.name !== 'floating_panel_style_preset') {
    markCustomIfNeeded();
  }

  restyleVisiblePreviewItems();
  scheduleStyleSave({ immediate: event.type === 'change' });
  if (event.type === 'change') styleGeneratorPersistence.flush().catch(() => {});
}

function onColorListClick(event) {
  const btn = event.target.closest('.sg-color-remove');
  if (!btn) return;
  const kind = btn.dataset.kind;
  const color = btn.dataset.color;
  const listId = kind === 'card' ? 'sgCardColorList' : 'sgTextColorList';
  const colors = Array.from(document.querySelectorAll(`#${listId} .sg-color-chip`))
    .map((chip) => chip.dataset.color)
    .filter((c) => c !== color);
  if (!colors.length) {
    showToast(t('dynamic.appStyleGenerator.至少保留一种颜色'), true);
    return;
  }
  renderColorList(kind, colors);
  markCustomIfNeeded();
  restyleVisiblePreviewItems();
  scheduleStyleSave();
}

function addColor(kind) {
  const pickerId = kind === 'card' ? 'sgCardColorPicker' : 'sgTextColorPicker';
  const hexId = kind === 'card' ? 'sgCardColorHex' : 'sgTextColorHex';
  const picker = document.getElementById(pickerId);
  const hexEl = document.getElementById(hexId);
  const listId = kind === 'card' ? 'sgCardColorList' : 'sgTextColorList';
  const color = normalizeHex(hexEl?.value) || normalizeHex(picker?.value || '#FFFFFF');
  if (!color) return;
  if (hexEl) hexEl.value = color;
  if (picker) picker.value = color.slice(0, 7);
  const colors = Array.from(document.querySelectorAll(`#${listId} .sg-color-chip`))
    .map((chip) => chip.dataset.color);
  if (colors.includes(color)) return;
  if (colors.length >= 16) {
    showToast(t('dynamic.appStyleGenerator.最多十六种颜色'), true);
    return;
  }
  colors.push(color);
  renderColorList(kind, colors);
  markCustomIfNeeded();
  restyleVisiblePreviewItems();
  scheduleStyleSave();
}

function onSingleColorPickerInput(event) {
  const picker = event.target;
  if (!(picker instanceof HTMLInputElement) || picker.type !== 'color') return;
  const name = picker.dataset.sgColorFor;
  if (!name) return;
  const textEl = field(name);
  if (!textEl) return;
  textEl.value = mergePickerRgbPreserveAlpha(picker.value, textEl.value);
  markCustomIfNeeded();
  restyleVisiblePreviewItems();
  scheduleStyleSave();
}

function onSingleColorTextInput(event) {
  const textEl = event.target;
  if (!(textEl instanceof HTMLInputElement)) return;
  const name = textEl.dataset.sgColorField || textEl.name;
  if (!SG_SINGLE_COLOR_FIELDS.includes(name)) return;
  const normalized = normalizeHex(textEl.value);
  const picker = document.querySelector(`[data-sg-color-for="${name}"]`);
  if (normalized && picker) {
    picker.value = normalized.slice(0, 7);
  }
}

function onAddColorPickerInput(event) {
  const picker = event.target;
  if (!(picker instanceof HTMLInputElement) || picker.type !== 'color') return;
  if (picker.id === 'sgCardColorPicker') syncAddColorHexFromPicker('card');
  if (picker.id === 'sgTextColorPicker') syncAddColorHexFromPicker('text');
}

function onAddColorHexInput(event) {
  const hexEl = event.target;
  if (!(hexEl instanceof HTMLInputElement)) return;
  if (hexEl.id === 'sgCardColorHex') syncAddColorPickerFromHex('card');
  if (hexEl.id === 'sgTextColorHex') syncAddColorPickerFromHex('text');
}

async function restoreDefaultAndSave() {
  // 页面当前的“仿微信”基础风格对应 LineLike 预设；不要恢复到
  // 不再展示为按钮的旧 wechat 预设，否则不会有任何基础风格处于选中状态。
  applyPreset('blivechat_line');
  styleGeneratorPersistence.schedule({ immediate: true });
  await styleGeneratorPersistence.flush();
}

export async function loadStyleGeneratorPage() {
  const form = formEl();
  if (!form) return;
  if (styleGeneratorLoaded && styleGeneratorDirty) return;
  if (styleGeneratorLoadPromise) return styleGeneratorLoadPromise;

  styleGeneratorLoadPromise = (async () => {
    try {
      const [cfg, presets, personae] = await Promise.all([
        apiFetch('/api/config'),
        apiFetch('/api/floating-panel/style-presets'),
        apiFetch('/api/personae').catch(() => ({ items: [] })),
      ]);
      const activePersona = (personae?.items || []).find((item) => item.active)
        || (personae?.items || [])[0];
      previewUsername = String(activePersona?.label || activePersona?.id || '高压吐槽型').trim()
        || '高压吐槽型';
      presetsPayload = presets;
      const values = {};
      STYLE_SAVE_KEYS.forEach((key) => {
        if (cfg[key] !== undefined && cfg[key] !== null) values[key] = cfg[key];
      });
      const perSecRaw = parseInt(String(values.floating_panel_danmu_per_second ?? cfg.floating_panel_danmu_per_second ?? '1'), 10);
      values.floating_panel_danmu_per_second = String(
        Math.max(1, Math.min(5, Number.isFinite(perSecRaw) ? perSecRaw : 1)),
      );
      // 服务端仍以旧的 wechat 作为工厂默认；页面当前可见的仿微信按钮对应 blivechat_line。
      if (!values.floating_panel_style_preset && presets?.presets?.blivechat_line) {
        Object.assign(values, presets.presets.blivechat_line);
      }
      normalizeVisiblePreset(values, presets);
      applyValuesToForm(values);
      syncSingleColorPickersFromText();
      syncAddColorHexFromPicker('card');
      syncAddColorHexFromPicker('text');
      // max_items / width 在设置页，不在样式表单；预览与真实 Web 面板对齐时需缓存
      const maxRaw = parseInt(String(cfg.floating_panel_max_items ?? '12'), 10);
      maxCardsCached = Math.max(1, Math.min(50, Number.isFinite(maxRaw) ? maxRaw : 12));
      const widthRaw = parseInt(String(cfg.floating_panel_width ?? '360'), 10);
      panelWidthCached = Math.max(200, Math.min(800, Number.isFinite(widthRaw) ? widthRaw : 360));
      await loadStyleGeneratorFontFamilies();
      ensurePreviewShadowDom();
      await styleGeneratorCustomCss.loadStyleGeneratorCustomCssResources(values.floating_panel_custom_css_file || '');
      if (String(values.floating_panel_style_preset || '') === 'custom_css') {
      setPreviewCustomCss(styleGeneratorCustomCss.getText());
      }
      seedPreview();
      styleGeneratorLoaded = true;
    } catch (error) {
      showToast(error.message || t('dynamic.appStyleGenerator.加载失败'), true);
    }
  })();

  try {
    await styleGeneratorLoadPromise;
  } finally {
    styleGeneratorLoadPromise = null;
  }
}

export function initStyleGeneratorPage(deps = {}) {
  if (typeof deps.showToast === 'function') toast = deps.showToast;
  if (handlersBound) return;
  handlersBound = true;

  const form = formEl();
  if (!form) return;

  form.addEventListener('input', onFormChange);
  form.addEventListener('change', onFormChange);

  document.getElementById('sgPresetSelect')?.addEventListener('change', (event) => {
    const preset = String(event.target?.value || '').trim();
    if (preset === 'classic' || preset === 'blivechat_line' || preset === 'custom_css') {
      applyPreset(preset);
    }
  });
  document.getElementById('sgBtnRestoreDefault')?.addEventListener('click', () => {
    restoreDefaultAndSave().catch((error) => showToast(error.message, true));
  });
  document.getElementById('sgBtnAddCardColor')?.addEventListener('click', () => addColor('card'));
  document.getElementById('sgBtnAddTextColor')?.addEventListener('click', () => addColor('text'));
  document.getElementById('sgCardColorList')?.addEventListener('click', onColorListClick);
  document.getElementById('sgTextColorList')?.addEventListener('click', onColorListClick);

  form.querySelectorAll('[data-sg-color-for]').forEach((picker) => {
    picker.addEventListener('input', onSingleColorPickerInput);
  });
  form.querySelectorAll('[data-sg-color-field]').forEach((textEl) => {
    textEl.addEventListener('input', onSingleColorTextInput);
    textEl.addEventListener('change', onSingleColorTextInput);
  });
  document.getElementById('sgCardColorPicker')?.addEventListener('input', onAddColorPickerInput);
  document.getElementById('sgTextColorPicker')?.addEventListener('input', onAddColorPickerInput);
  document.getElementById('sgCardColorHex')?.addEventListener('input', onAddColorHexInput);
  document.getElementById('sgCardColorHex')?.addEventListener('change', onAddColorHexInput);
  document.getElementById('sgTextColorHex')?.addEventListener('input', onAddColorHexInput);
  document.getElementById('sgTextColorHex')?.addEventListener('change', onAddColorHexInput);

  initSettingsRhythmAccordion();
  initNumberSteppers(form);
  initStyleGeneratorFieldHints();
  initHorizontalFontPage({ showToast: toast, navigate: deps.navigate });
  syncPresetSelect();
  syncPresetVisibility(activePresetId);
  syncSingleColorPickersFromText();
  syncAddColorHexFromPicker('card');
  syncAddColorHexFromPicker('text');
  document.getElementById('sgBtnAddPreview')?.addEventListener('click', () => {
    const fn = PREVIEW_TEXTS[previewTextIndex % PREVIEW_TEXTS.length];
    previewTextIndex += 1;
    addPreviewMessage(typeof fn === 'function' ? fn() : fn);
  });
  document.getElementById('sgBtnClearPreview')?.addEventListener('click', clearPreview);

  // 字体导入
  document.getElementById('sg-btnImportFont')?.addEventListener('click', uploadStyleGeneratorFont);

  // 自定义 CSS 文件与内置模板
  document.getElementById('sgBtnOpenCustomCssFolder')?.addEventListener('click', styleGeneratorCustomCss.openCustomCssFolder);
  document.getElementById('sgBtnImportCustomCss')?.addEventListener('click', () => {
    document.getElementById('sgCustomCssFileInput')?.click();
  });
  document.getElementById('sgCustomCssFileInput')?.addEventListener('change', styleGeneratorCustomCss.importCustomCssFile);
  document.getElementById('sgBtnCloseCustomCssTemplate')?.addEventListener('click', styleGeneratorCustomCss.closeCustomCssTemplate);
  document.getElementById('sgBtnCloseCustomCssTemplateBottom')?.addEventListener('click', styleGeneratorCustomCss.closeCustomCssTemplate);
  document.getElementById('sgBtnCopyCustomCssTemplate')?.addEventListener('click', () => {
    styleGeneratorCustomCss.copyCustomCssText(styleGeneratorCustomCss.getActiveTemplateCss());
  });

  // 弹幕样式 Tab 切换
  const sgTabs = document.querySelectorAll('#page-style-generator .sg-tab');
  sgTabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      const tabName = tab.dataset.sgTab;
      sgTabs.forEach((t) => {
        t.classList.remove('is-active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('is-active');
      tab.setAttribute('aria-selected', 'true');
      document.querySelectorAll('#page-style-generator .sg-tab-panel').forEach((panel) => {
        panel.classList.remove('is-active');
        panel.hidden = true;
      });
      const activePanel = document.querySelector(`#page-style-generator .sg-tab-panel[data-sg-tab-panel="${tabName}"]`);
      if (activePanel) {
        activePanel.classList.add('is-active');
        activePanel.hidden = false;
      }
      if (tabName === 'horizontal') {
        loadHorizontalFontPage().catch((error) => showToast(error.message, true));
      }
    });
  });
}
