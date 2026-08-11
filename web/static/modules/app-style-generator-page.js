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

/** 保存/应用预设时提交的键（与 STYLE_PRESET_APPLY_KEYS 对齐） */
const STYLE_SAVE_KEYS = [
  'floating_panel_style_preset',
  'floating_panel_shape',
  'floating_panel_layout',
  'floating_panel_card_colors',
  'floating_panel_card_color_mode',
  'floating_panel_card_color_weights',
  'floating_panel_text_colors',
  'floating_panel_text_color_mode',
  'floating_panel_text_color_weights',
  'floating_panel_card_opacity',
  'floating_panel_outline_enabled',
  'floating_panel_outline_color',
  'floating_panel_outline_width',
  'floating_panel_shadow_enabled',
  'floating_panel_shadow_color',
  'floating_panel_shadow_opacity',
  'floating_panel_shadow_blur',
  'floating_panel_shadow_offset_x',
  'floating_panel_shadow_offset_y',
  'floating_panel_border_enabled',
  'floating_panel_border_color',
  'floating_panel_border_width',
  'floating_panel_border_opacity',
  'floating_panel_padding_x',
  'floating_panel_padding_y',
  'floating_panel_radius',
  'floating_panel_tail_enabled',
  'floating_panel_tail_style',
  'floating_panel_tail_width',
  'floating_panel_tail_height',
  'floating_panel_tail_size',
  'floating_panel_tail_offset_y',
  'floating_panel_tail_border',
  'floating_panel_tail_long_side',
  'floating_panel_tail_rotate_deg',
  'floating_panel_username_enabled',
  'floating_panel_username_text',
  'floating_panel_username_color',
  'floating_panel_username_size',
  'floating_panel_username_weight',
  'floating_panel_username_separator',
  'floating_panel_content_size',
  'floating_panel_content_weight',
  'floating_panel_content_line_height',
  'floating_panel_gap_username_content',
  'floating_panel_entry_animation',
  'floating_panel_entry_duration_ms',
  'floating_panel_push_duration_ms',
  'floating_panel_exit_animation',
  'floating_panel_exit_duration_ms',
  'floating_panel_stack_gap',
  'floating_panel_font_family',
  'floating_panel_font_size',
  'floating_panel_font_bold',
  'floating_panel_opacity',
  'floating_panel_width',
  'floating_panel_max_items',
  'floating_panel_speed',
  'floating_panel_x_offset',
  'floating_panel_y_offset',
  'floating_panel_click_through',
];

const BOOL_KEYS = new Set([
  'floating_panel_outline_enabled',
  'floating_panel_shadow_enabled',
  'floating_panel_tail_enabled',
  'floating_panel_border_enabled',
  'floating_panel_username_enabled',
  'floating_panel_font_bold',
  'floating_panel_click_through',
]);

const PREVIEW_TEXTS = [
  () => t('dynamic.settingsDanmuPreview.这波操作666'),
  () => t('dynamic.settingsDanmuPreview.哈哈哈哈哈太搞了'),
  () => t('dynamic.settingsDanmuPreview.主播好强'),
  () => t('dynamic.settingsDanmuPreview.前方高能预警'),
  () => 'awsl',
  () => t('dynamic.appStyleGenerator.预览消息_精彩操作'),
];

let toast = () => {};
let handlersBound = false;
let presetsPayload = null;
let suppressCustomMark = false;
let styleIndexSeq = 0;
/** @type {{el: HTMLElement, styleIndex: number, cardColor: string, textColor: string, text: string}[]} */
let previewItems = [];
let previewTextIndex = 0;
let maxCardsCached = 12;
let panelWidthCached = 360;
let exitDurationMsCached = 200;

function showToast(message, isError = false) {
  toast(message, isError);
}

function formEl() {
  return document.getElementById('styleGeneratorForm');
}

function field(name) {
  const form = formEl();
  if (!form) return null;
  return form.querySelector(`[name="${name}"]`);
}

function normalizeHex(raw) {
  if (typeof raw !== 'string') return null;
  const s = raw.trim().toUpperCase();
  if (/^#[0-9A-F]{6}$/.test(s) || /^#[0-9A-F]{8}$/.test(s)) return s;
  return null;
}

/** native <input type="color"> only accepts #RRGGBB */
function hexToColorInputValue(raw, fallback = '#FFFFFF') {
  const h = normalizeHex(raw);
  if (!h) {
    const fb = normalizeHex(fallback) || '#FFFFFF';
    return fb.slice(0, 7);
  }
  return h.slice(0, 7);
}

function mergePickerRgbPreserveAlpha(pickerRgb, previousHex) {
  const rgb = hexToColorInputValue(pickerRgb, '#FFFFFF');
  const prev = normalizeHex(previousHex);
  if (prev && prev.length === 9) return `${rgb}${prev.slice(7, 9)}`;
  return rgb;
}

const SG_SINGLE_COLOR_FIELDS = [
  'floating_panel_outline_color',
  'floating_panel_shadow_color',
  'floating_panel_border_color',
  'floating_panel_username_color',
];

function syncSingleColorPickersFromText() {
  SG_SINGLE_COLOR_FIELDS.forEach((name) => {
    const textEl = field(name);
    const picker = document.querySelector(`[data-sg-color-for="${name}"]`);
    if (!textEl || !picker) return;
    picker.value = hexToColorInputValue(textEl.value, picker.value || '#FFFFFF');
  });
}

function syncAddColorHexFromPicker(kind) {
  const pickerId = kind === 'card' ? 'sgCardColorPicker' : 'sgTextColorPicker';
  const hexId = kind === 'card' ? 'sgCardColorHex' : 'sgTextColorHex';
  const picker = document.getElementById(pickerId);
  const hexEl = document.getElementById(hexId);
  if (!picker || !hexEl) return;
  const next = hexToColorInputValue(picker.value, '#FFFFFF');
  picker.value = next;
  hexEl.value = next;
}

function syncAddColorPickerFromHex(kind) {
  const pickerId = kind === 'card' ? 'sgCardColorPicker' : 'sgTextColorPicker';
  const hexId = kind === 'card' ? 'sgCardColorHex' : 'sgTextColorHex';
  const picker = document.getElementById(pickerId);
  const hexEl = document.getElementById(hexId);
  if (!picker || !hexEl) return;
  const normalized = normalizeHex(hexEl.value);
  if (!normalized) return;
  picker.value = normalized.slice(0, 7);
  hexEl.value = normalized;
}

function parsePalette(raw) {
  try {
    const arr = typeof raw === 'string' ? JSON.parse(raw || '[]') : raw;
    if (!Array.isArray(arr)) return [];
    return arr.map(normalizeHex).filter(Boolean);
  } catch {
    return [];
  }
}

function parseWeights(raw) {
  try {
    const obj = typeof raw === 'string' ? JSON.parse(raw || '{}') : raw;
    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return {};
    const out = {};
    Object.entries(obj).forEach(([k, v]) => {
      const color = normalizeHex(k);
      const n = Number(v);
      if (color && Number.isFinite(n) && n >= 0) out[color] = n;
    });
    return out;
  } catch {
    return {};
  }
}

/** equal: colors[i % n]；weighted: 与 Qt overlay 相同 32-bit 槽位（无全局 random） */
export function pickStyleColor(colors, mode, weights, styleIndex) {
  const list = Array.isArray(colors) ? colors.filter(Boolean) : [];
  if (!list.length) return '#FFFFFF';
  if (mode === 'weighted') {
    const wmap = weights || {};
    const pairs = list.map((c) => [c, Number(wmap[c]) > 0 ? Number(wmap[c]) : 0]);
    const total = pairs.reduce((s, [, w]) => s + w, 0);
    if (total > 0) {
      // Match floating_panel_overlay._pick_palette_color: (style_index * 2654435761) & 0xFFFFFFFF / 2^32
      let h = ((Number(styleIndex) || 0) * 2654435761) >>> 0;
      let r = (h / 4294967296) * total;
      for (const [c, w] of pairs) {
        r -= w;
        if (r <= 0) return c;
      }
      return pairs[pairs.length - 1][0];
    }
  }
  const idx = Math.abs(Number(styleIndex) || 0) % list.length;
  return list[idx];
}

function hexToRgba(hex, alphaOverride) {
  const h = normalizeHex(hex) || '#FFFFFF';
  const r = parseInt(h.slice(1, 3), 16);
  const g = parseInt(h.slice(3, 5), 16);
  const b = parseInt(h.slice(5, 7), 16);
  let a = alphaOverride;
  if (a === undefined) {
    a = h.length === 9 ? parseInt(h.slice(7, 9), 16) / 255 : 1;
  }
  return `rgba(${r}, ${g}, ${b}, ${a})`;
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
    el.checked = value === '1' || value === 1 || value === true || value === 'true';
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

function collectStylePayload() {
  const data = {};
  STYLE_SAVE_KEYS.forEach((key) => {
    if (BOOL_KEYS.has(key)) {
      data[key] = readBool(key) ? '1' : '0';
      return;
    }
    data[key] = readStr(key, '');
  });
  return data;
}

function markCustomIfNeeded() {
  if (suppressCustomMark) return;
  setFieldValue('floating_panel_style_preset', 'custom');
  syncPresetButtons('custom');
}

function syncPresetButtons(preset) {
  document.querySelectorAll('.sg-preset-btn').forEach((btn) => {
    const active = btn.dataset.preset === preset;
    btn.classList.toggle('is-active', active);
    if (btn.dataset.preset === 'custom') {
      btn.disabled = preset !== 'custom';
    }
  });
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
    const preset = values.floating_panel_style_preset || 'custom';
    syncPresetButtons(preset);
  } finally {
    suppressCustomMark = false;
  }
}

function applyPreset(presetId) {
  const patch = presetsPayload?.presets?.[presetId];
  if (!patch) {
    showToast(t('dynamic.appStyleGenerator.预设不可用'), true);
    return;
  }
  applyValuesToForm({ ...patch, floating_panel_style_preset: presetId });
  restyleVisiblePreviewItems();
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
    entryMs: Math.max(0, readInt('floating_panel_entry_duration_ms', 200)),
    exitMs: Math.max(0, readInt('floating_panel_exit_duration_ms', 200)),
    stackGap: Math.max(0, readInt('floating_panel_stack_gap', 8)),
    fontFamily: readStr('floating_panel_font_family', 'Microsoft YaHei'),
    fontBold: readBool('floating_panel_font_bold'),
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
  stage.style.setProperty('--exit-duration', `${style.exitMs}ms`);
  stage.style.setProperty('--panel-opacity', String(style.panelOpacity));
  stage.style.setProperty('--font-family', style.fontFamily || 'Microsoft YaHei, PingFang SC, sans-serif');
  const maxW = Math.max(120, style.panelWidth - 40);
  stage.style.setProperty('--card-max-width', `${maxW}px`);
  maxCardsCached = style.maxItems;
  exitDurationMsCached = style.exitMs || 200;
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
    ? `${style.usernameText}${style.usernameSeparator}`
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
      usernameEl.textContent = `${style.usernameText}${style.usernameSeparator}`;
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

function scheduleCardExit(node) {
  if (!node || node.classList.contains('exiting')) return;
  node.classList.add('exiting');
  const id = node.dataset?.cardId;
  setTimeout(() => {
    if (node.parentNode) node.parentNode.removeChild(node);
    previewItems = previewItems.filter((it) => it.el !== node);
    if (id) {
      /* card id cleanup not needed beyond filter */
    }
  }, exitDurationMsCached || 200);
}

function removeOldestIfNeeded() {
  const stack = document.getElementById('styleGeneratorPreviewStack');
  if (!stack) return;
  const maxCards = maxCardsCached || 12;
  let active = 0;
  for (let i = 0; i < stack.children.length; i++) {
    if (!stack.children[i].classList.contains('exiting')) active += 1;
  }
  let needExit = active - maxCards;
  for (let i = 0; i < stack.children.length && needExit > 0; i++) {
    if (stack.children[i].classList.contains('exiting')) continue;
    scheduleCardExit(stack.children[i]);
    needExit -= 1;
  }
}

function addPreviewMessage(text) {
  const stack = document.getElementById('styleGeneratorPreviewStack');
  if (!stack) return;
  const style = readPreviewStyle();
  applyStageConfig(style);
  const idx = styleIndexSeq++ % 1024;
  const cardColor = pickStyleColor(style.cardColors, style.cardMode, style.cardWeights, idx);
  const textColor = pickStyleColor(style.textColors, style.textMode, style.textWeights, idx);

  const el = document.createElement('div');
  el.className = 'sg-preview-card';
  el.dataset.styleIndex = String(idx);
  el.dataset.cardId = `sg-${idx}-${Date.now()}`;
  el.dataset.cardColor = cardColor;
  el.dataset.textColor = textColor;
  el.innerHTML = buildPreviewCardInnerHtml(style, text);

  applyCardStyleVars(el, style, cardColor, textColor);
  stack.appendChild(el);
  previewItems.push({
    el,
    text,
    styleIndex: idx,
    cardColor,
    textColor,
  });
  removeOldestIfNeeded();
}

function escapePreviewHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c],
  );
}

function clearPreview() {
  previewItems.forEach((item) => item.el?.remove());
  previewItems = [];
  const stack = document.getElementById('styleGeneratorPreviewStack');
  if (stack) stack.innerHTML = '';
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

async function saveStyle(event) {
  event?.preventDefault?.();
  const status = document.getElementById('sgSaveStatus');
  const payload = collectStylePayload();
  try {
    await apiFetch('/api/config', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    // 样式已保存；字体字段由横向模式页独立维护
    if (status) status.textContent = t('dynamic.appStyleGenerator.样式已保存');
    showToast(t('dynamic.appStyleGenerator.样式已保存'));
  } catch (error) {
    if (status) status.textContent = '';
    showToast(error.message || t('dynamic.appStyleGenerator.保存失败'), true);
  }
}

async function restoreDefaultAndSave() {
  applyPreset('wechat');
  await saveStyle();
}

/* ---- 字体加载与导入 ---- */

async function loadStyleGeneratorFontFamilies() {
  try {
    if (!API.token) return;
    const data = await apiFetch('/api/fonts');
    refreshStyleGeneratorFontSelect(data.families || []);
    renderStyleGeneratorImportedFontsList(data.imported || []);
  } catch (error) {
    console.warn('loadStyleGeneratorFontFamilies failed:', error);
  }
}

function refreshStyleGeneratorFontSelect(families) {
  const builtin = ['Microsoft YaHei', 'SimHei', 'SimSun', 'KaiTi', 'DengXian', 'Arial', 'Segoe UI'];
  const sel = document.getElementById('sg-floating_panel_font_family');
  if (!sel) return;
  const current = sel.value;
  const merged = Array.from(new Set([...builtin, ...families]));
  let html = '<option value="">— 系统默认 —</option>';
  merged.forEach((family) => {
    const safe = String(family).replace(/"/g, '&quot;');
    html += `<option value="${safe}">${safe}</option>`;
  });
  if (current && !merged.includes(current)) {
    const safe = String(current).replace(/"/g, '&quot;');
    html += `<option value="${safe}">${safe}</option>`;
  }
  sel.innerHTML = html;
  sel.value = current || '';
}

function renderStyleGeneratorImportedFontsList(imported) {
  const list = document.getElementById('sg-importedFontsList');
  const tmpl = document.getElementById('sg-fontRowTemplate');
  if (!list || !tmpl) return;
  list.innerHTML = '';
  imported.forEach((item) => {
    const node = tmpl.content.firstElementChild.cloneNode(true);
    node.querySelector('.font-family').textContent = item.family;
    node.querySelector('.font-meta').textContent =
      `（${item.original_name} · ${(item.size / 1024).toFixed(1)} KB）`;
    node.querySelector('.btn-delete-font').addEventListener('click', async () => {
      if (!confirm(`确认删除已导入字体「${item.family}」？`)) return;
      try {
        await apiFetch(`/api/fonts/${item.sha256}`, { method: 'DELETE' });
        showToast(`已删除字体「${item.family}」`);
        const sgSel = document.getElementById('sg-floating_panel_font_family');
        if (sgSel && sgSel.value === item.family) sgSel.value = '';
        await loadStyleGeneratorFontFamilies();
      } catch (error) {
        showToast(error.message || '删除失败', true);
      }
    });
    list.appendChild(node);
  });
}

async function uploadStyleGeneratorFont() {
  const input = document.getElementById('sg-font_file_input');
  const file = input?.files?.[0];
  if (!file) {
    showToast('请先选择一个 .ttf 或 .otf 文件', true);
    return;
  }
  const form = new FormData();
  form.append('file', file, file.name);
  try {
    if (!API.token) throw new Error('未获取会话令牌，请刷新页面或重启 DanmuAI');
    const data = await apiFormFetch('/api/fonts/import', form);
    showToast(`已导入字体「${data.family}」`);
    await loadStyleGeneratorFontFamilies();
    if (input) input.value = '';
  } catch (error) {
    showToast(error.message || '导入失败', true);
  }
}

export async function loadStyleGeneratorPage() {
  const form = formEl();
  if (!form) return;
  try {
    const [cfg, presets] = await Promise.all([
      apiFetch('/api/config'),
      apiFetch('/api/floating-panel/style-presets'),
    ]);
    presetsPayload = presets;
    const values = {};
    STYLE_SAVE_KEYS.forEach((key) => {
      if (cfg[key] !== undefined && cfg[key] !== null) values[key] = cfg[key];
    });
    // 若服务端无样式键，用 wechat 预设补齐
    if (!values.floating_panel_style_preset && presets?.presets?.wechat) {
      Object.assign(values, presets.presets.wechat);
      values.floating_panel_style_preset = presets.default_preset || 'wechat';
    }
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
    seedPreview();
  } catch (error) {
    showToast(error.message || t('dynamic.appStyleGenerator.加载失败'), true);
  }
}

export function initStyleGeneratorPage(deps = {}) {
  if (typeof deps.showToast === 'function') toast = deps.showToast;
  if (handlersBound) return;
  handlersBound = true;

  const form = formEl();
  if (!form) return;

  form.addEventListener('submit', saveStyle);
  form.addEventListener('input', onFormChange);
  form.addEventListener('change', onFormChange);

  document.getElementById('sgBtnPresetClassic')?.addEventListener('click', () => applyPreset('classic'));
  document.getElementById('sgBtnPresetBlivechatLine')?.addEventListener('click', () => applyPreset('blivechat_line'));
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
  initHorizontalFontPage({ showToast: toast, navigate: deps.navigate });
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

  // 设置页入口
  document.getElementById('btnOpenStyleGeneratorFromSettings')?.addEventListener('click', (event) => {
    event.preventDefault();
    if (typeof deps.navigate === 'function') deps.navigate('style-generator');
    else window.location.hash = 'style-generator';
  });
}
