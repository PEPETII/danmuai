/**
 * 样式生成器页（W-FP-STYLEGEN-WEB-001 / W-FP-STYLEGEN-PREVIEW-PARITY）
 *
 * - 并行 GET /api/config + /api/floating-panel/style-presets
 * - 表单 name 与 ConfigStore 扁平字段同名；仅保存时 PUT /api/config 子集
 * - 预览与默认真实路径 web/static/floating_panel 同构：
 *   column-reverse 底锚、max_items 顶出、2 行 clamp、卡片/气泡尾巴、入场 slideUp / 退出 fadeOut
 */

import { apiFetch } from './transport.js';
import { t } from './i18n.js';

/** 保存/应用预设时提交的键（与 STYLE_PRESET_APPLY_KEYS 对齐） */
const STYLE_SAVE_KEYS = [
  'floating_panel_style_preset',
  'floating_panel_shape',
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
];

const BOOL_KEYS = new Set([
  'floating_panel_outline_enabled',
  'floating_panel_shadow_enabled',
  'floating_panel_tail_enabled',
  'floating_panel_border_enabled',
  'floating_panel_username_enabled',
  'floating_panel_font_bold',
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
      <input type="number" min="0" step="0.1" value="${w}" data-weight-color="${color}" data-kind="${kind}" class="settings-field-control sg-weight-input">
    `;
    panel.appendChild(row);
  });
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
  return {
    shape: readStr('floating_panel_shape', 'bubble'),
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
  s.setProperty('--outline-color', hexToRgba(style.outlineColor));
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
  if (style.shadowEnabled) {
    s.setProperty(
      '--card-shadow',
      `${style.shadowOffsetX}px ${style.shadowOffsetY}px ${style.shadowBlur}px ${hexToRgba(style.shadowColor, style.shadowOpacity)}`,
    );
  } else {
    s.setProperty('--card-shadow', 'none');
  }

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

function restyleVisiblePreviewItems() {
  const style = readPreviewStyle();
  applyStageConfig(style);
  previewItems.forEach((item) => {
    if (!item.el) return;
    applyCardStyleVars(item.el, style, item.cardColor, item.textColor);
    const usernameEl = item.el.querySelector('.username');
    if (usernameEl) {
      if (style.usernameEnabled) {
        usernameEl.classList.remove('is-hidden');
        usernameEl.textContent = `${style.usernameText}${style.usernameSeparator}`;
      } else {
        usernameEl.classList.add('is-hidden');
        usernameEl.textContent = '';
      }
    }
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

  const usernameLabel = style.usernameEnabled
    ? `${style.usernameText}${style.usernameSeparator}`
    : '';
  el.innerHTML =
    `<div class="username${style.usernameEnabled ? '' : ' is-hidden'}">${escapePreviewHtml(usernameLabel)}</div>` +
    `<div class="content">${escapePreviewHtml(text)}</div>`;

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
  const picker = document.getElementById(pickerId);
  const listId = kind === 'card' ? 'sgCardColorList' : 'sgTextColorList';
  const color = normalizeHex(picker?.value || '#FFFFFF');
  if (!color) return;
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

async function saveStyle(event) {
  event?.preventDefault?.();
  const status = document.getElementById('sgSaveStatus');
  const payload = collectStylePayload();
  try {
    await apiFetch('/api/config', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    // 镜像设置页基础字体字段（同名字段，不写第二套状态）
    mirrorToSettingsForm(payload);
    if (status) status.textContent = t('dynamic.appStyleGenerator.样式已保存');
    showToast(t('dynamic.appStyleGenerator.样式已保存'));
  } catch (error) {
    if (status) status.textContent = '';
    showToast(error.message || t('dynamic.appStyleGenerator.保存失败'), true);
  }
}

function mirrorToSettingsForm(payload) {
  const mirrorKeys = [
    'floating_panel_font_family',
    'floating_panel_font_size',
    'floating_panel_font_bold',
    'floating_panel_opacity',
  ];
  mirrorKeys.forEach((key) => {
    const el = document.getElementById(key);
    if (!el || payload[key] === undefined) return;
    if (key === 'floating_panel_font_bold') {
      el.checked = payload[key] === '1';
    } else {
      el.value = payload[key];
    }
  });
}

async function restoreDefaultAndSave() {
  applyPreset('wechat');
  await saveStyle();
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
    // max_items / width 在设置页，不在样式表单；预览与真实 Web 面板对齐时需缓存
    const maxRaw = parseInt(String(cfg.floating_panel_max_items ?? '12'), 10);
    maxCardsCached = Math.max(1, Math.min(50, Number.isFinite(maxRaw) ? maxRaw : 12));
    const widthRaw = parseInt(String(cfg.floating_panel_width ?? '360'), 10);
    panelWidthCached = Math.max(200, Math.min(800, Number.isFinite(widthRaw) ? widthRaw : 360));
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
  document.getElementById('sgBtnPresetWechat')?.addEventListener('click', () => applyPreset('wechat'));
  document.getElementById('sgBtnRestoreDefault')?.addEventListener('click', () => {
    restoreDefaultAndSave().catch((error) => showToast(error.message, true));
  });
  document.getElementById('sgBtnAddCardColor')?.addEventListener('click', () => addColor('card'));
  document.getElementById('sgBtnAddTextColor')?.addEventListener('click', () => addColor('text'));
  document.getElementById('sgCardColorList')?.addEventListener('click', onColorListClick);
  document.getElementById('sgTextColorList')?.addEventListener('click', onColorListClick);
  document.getElementById('sgBtnAddPreview')?.addEventListener('click', () => {
    const fn = PREVIEW_TEXTS[previewTextIndex % PREVIEW_TEXTS.length];
    previewTextIndex += 1;
    addPreviewMessage(typeof fn === 'function' ? fn() : fn);
  });
  document.getElementById('sgBtnClearPreview')?.addEventListener('click', clearPreview);

  // 设置页入口
  document.getElementById('btnOpenStyleGeneratorFromSettings')?.addEventListener('click', (event) => {
    event.preventDefault();
    if (typeof deps.navigate === 'function') deps.navigate('style-generator');
    else window.location.hash = 'style-generator';
  });
}
