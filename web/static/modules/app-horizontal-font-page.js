/**
 * 弹幕样式 → 横向模式：字体设置表单（自弹幕设置 font Tab 迁入）
 * 配置键与 /api/config 扁平字段同名；保存时 PUT 子集。
 */

import { API, apiFetch } from './transport.js';
import { t } from './i18n.js';
import { initSettingsRhythmAccordion } from './settings-rhythm-accordion.js?v=20260717-number-stepper-v1';
import {
  bindFontControls,
  configureSettingsFonts,
  loadFontFamilies,
  syncColorUIFromConfig,
} from './settings-fonts.js';
import { refreshDanmuPreview, updateDanmuPreviewSnapshot } from './settings-danmu-preview.js';
import { initNumberSteppers } from './number-stepper.js?v=20260717-number-stepper-v1';
import { initOpacityWarning, refreshOpacityWarning } from './settings-core.js';
import { initHorizontalFieldHints } from './settings-hints.js';

export const HORIZONTAL_FONT_SAVE_KEYS = [
  'danmu_font_family',
  'font_size',
  'danmu_lines',
  'layout_mode',
  'danmu_font_bold',
  'danmu_font_color_selected',
  'danmu_font_color_mode',
  'danmu_font_color_weights',
  'opacity',
  'eviction_mode',
];

const HORIZONTAL_FONT_CHECKBOX_KEYS = ['danmu_font_bold'];

let toast = (msg, isError = false) => {
  if (isError) console.error(msg);
};

let handlersBound = false;
let horizontalAccordionInited = false;
let horizontalHintsInited = false;

function formEl() {
  return document.getElementById('horizontalFontForm');
}

function collectHorizontalFontPayload() {
  const payload = {};
  HORIZONTAL_FONT_SAVE_KEYS.forEach((key) => {
    const el = document.getElementById(key);
    if (el && el.type !== 'checkbox') {
      payload[key] = el.value;
    }
  });
  HORIZONTAL_FONT_CHECKBOX_KEYS.forEach((key) => {
    const el = document.getElementById(key);
    if (el) payload[key] = el.checked ? '1' : '0';
  });
  return payload;
}

function applyValuesToForm(values) {
  HORIZONTAL_FONT_SAVE_KEYS.forEach((key) => {
    const el = document.getElementById(key);
    if (!el || values[key] === undefined || values[key] === null) return;
    if (key === 'layout_mode') {
      const allowed = ['fullscreen', '3/4', '1/2', '1/4'];
      el.value = allowed.includes(values[key]) ? values[key] : 'fullscreen';
      return;
    }
    if (key === 'eviction_mode') {
      el.value = values[key] === 'accelerate' ? 'accelerate' : 'natural';
      return;
    }
    el.value = String(values[key]);
  });
  const boldEl = document.getElementById('danmu_font_bold');
  if (boldEl && values.danmu_font_bold !== undefined) {
    const v = values.danmu_font_bold;
    boldEl.checked = v === '1' || v === 'true' || v === true;
  }
  syncColorUIFromConfig(values);
  updateDanmuPreviewSnapshot(values);
  refreshOpacityWarning();
}

export async function loadHorizontalFontPage() {
  const form = formEl();
  if (!form) return;
  try {
    if (!API.token) return;
    const cfg = await apiFetch('/api/config');
    const values = {};
    HORIZONTAL_FONT_SAVE_KEYS.forEach((key) => {
      if (cfg[key] !== undefined && cfg[key] !== null) values[key] = cfg[key];
    });
    if (cfg.danmu_font_bold !== undefined) values.danmu_font_bold = cfg.danmu_font_bold;
    applyValuesToForm(values);
    await loadFontFamilies();
    refreshDanmuPreview();
  } catch (error) {
    toast(error.message || t('dynamic.appHorizontalFont.加载失败'), true);
  }
}

async function saveHorizontalFont(event) {
  event?.preventDefault?.();
  const status = document.getElementById('hfSaveStatus');
  const payload = collectHorizontalFontPayload();
  try {
    await apiFetch('/api/config', {
      method: 'PUT',
      body: JSON.stringify(payload),
    });
    updateDanmuPreviewSnapshot(payload);
    if (status) status.textContent = t('dynamic.appHorizontalFont.字体设置已保存');
    toast(t('dynamic.appHorizontalFont.字体设置已保存'));
    refreshDanmuPreview();
  } catch (error) {
    if (status) status.textContent = '';
    toast(error.message || t('dynamic.appHorizontalFont.保存失败'), true);
  }
}

async function restoreHorizontalFontDefaults() {
  try {
    const defaults = await apiFetch('/api/config/defaults');
    const values = {};
    HORIZONTAL_FONT_SAVE_KEYS.forEach((key) => {
      if (defaults[key] !== undefined) values[key] = defaults[key];
    });
    if (defaults.danmu_font_bold !== undefined) values.danmu_font_bold = defaults.danmu_font_bold;
    applyValuesToForm(values);
    toast(t('dynamic.appHorizontalFont.已恢复默认_请点击保存生效'));
  } catch (error) {
    toast(error.message || t('dynamic.appHorizontalFont.恢复默认失败'), true);
  }
}

function onFormChange() {
  refreshDanmuPreview();
}

export function initHorizontalFontPage(deps = {}) {
  if (typeof deps.showToast === 'function') toast = deps.showToast;
  configureSettingsFonts({ showToast: toast });

  const form = formEl();
  if (!form) return;

  if (!handlersBound) {
    handlersBound = true;
    form.addEventListener('submit', saveHorizontalFont);
    form.addEventListener('input', onFormChange);
    form.addEventListener('change', onFormChange);
    document.getElementById('hfBtnRestoreDefault')?.addEventListener('click', () => {
      restoreHorizontalFontDefaults().catch((error) => toast(error.message, true));
    });
    bindFontControls();
    initNumberSteppers(form);
  }

  if (!horizontalAccordionInited) {
    initSettingsRhythmAccordion(form);
    horizontalAccordionInited = true;
  }

  if (!horizontalHintsInited) {
    initHorizontalFieldHints();
    initOpacityWarning();
    horizontalHintsInited = true;
  }
}
