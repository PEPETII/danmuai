/**
 * 弹幕样式 → 横向模式：字体设置表单（自弹幕设置 font Tab 迁入）
 * 配置键与 /api/config 扁平字段同名；保存时 PUT 子集。
 */

import { API, apiFetch } from './transport.js';
import { t } from './i18n.js';
import { createAutoSave } from './auto-save.js';
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

const HORIZONTAL_FONT_CHECKBOX_KEYS = ['danmu_font_bold', 'persona_name_prefix_enabled'];

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
  HORIZONTAL_FONT_CHECKBOX_KEYS.forEach((key) => {
    const el = document.getElementById(key);
    if (!el || values[key] === undefined) return;
    const v = values[key];
    el.checked = v === '1' || v === 'true' || v === true;
  });
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
    HORIZONTAL_FONT_CHECKBOX_KEYS.forEach((key) => {
      if (cfg[key] !== undefined) values[key] = cfg[key];
    });
    applyValuesToForm(values);
    await loadFontFamilies();
    refreshDanmuPreview();
  } catch (error) {
    toast(error.message || t('dynamic.appHorizontalFont.加载失败'), true);
  }
}

async function persistHorizontalFont(payload, { isLatest = () => true } = {}) {
  await apiFetch('/api/config', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
  if (!isLatest()) return;
  updateDanmuPreviewSnapshot(payload);
  refreshDanmuPreview();
}

const horizontalFontAutoSave = createAutoSave({
  capture: collectHorizontalFontPayload,
  save: persistHorizontalFont,
  onState: (state, error) => {
    const status = document.getElementById('hfSaveStatus');
    if (status) {
      status.textContent = state === 'error'
        ? (error?.message || t('dynamic.autoSaveStatus.error'))
        : t(`dynamic.autoSaveStatus.${state}`);
      status.dataset.state = state;
    }
    if (state === 'error') toast(error?.message || t('dynamic.autoSaveStatus.error'), true);
  },
  delay: 400,
});

async function saveHorizontalFont(event) {
  event?.preventDefault?.();
  horizontalFontAutoSave.schedule({ immediate: true });
  await horizontalFontAutoSave.flush();
}

async function restoreHorizontalFontDefaults() {
  if (!confirm(t('dynamic.autoSaveStatus.restoreConfirm'))) return;
  try {
    const defaults = await apiFetch('/api/config/defaults');
    const values = {};
    HORIZONTAL_FONT_SAVE_KEYS.forEach((key) => {
      if (defaults[key] !== undefined) values[key] = defaults[key];
    });
    HORIZONTAL_FONT_CHECKBOX_KEYS.forEach((key) => {
      if (defaults[key] !== undefined) values[key] = defaults[key];
    });
    applyValuesToForm(values);
    horizontalFontAutoSave.schedule({ immediate: true });
    await horizontalFontAutoSave.flush();
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
    form.addEventListener('input', (event) => {
      onFormChange(event);
      horizontalFontAutoSave.schedule();
    });
    form.addEventListener('change', (event) => {
      onFormChange(event);
      horizontalFontAutoSave.schedule({ immediate: true });
      horizontalFontAutoSave.flush().catch(() => {});
    });
    window.addEventListener('pagehide', () => horizontalFontAutoSave.cancel());
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
