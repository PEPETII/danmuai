import { apiFetch } from './transport.js';
import {
  CONFIG_FIELDS,
  MASKED_API_KEY,
  configDefaultValue,
  getConfigDefaultsCache,
  restorableKeysForScope,
  setConfigDefaultsCache,
  updateNormalBatchPreview,
} from './settings-defaults.js';
import { getActiveSettingsTabId } from './settings-tabs.js';

let coreDeps = {
  showToast: () => {},
  loadCustomModels: async () => {},
  applyCaptureRegionFromPayload: () => {},
  syncVisionModelToHidden: () => {},
  syncMicModelToHidden: () => {},
  syncProviderPresetFromEndpoint: () => {},
  applyApiModeValue: () => {},
  syncApiModeLockState: () => {},
  syncVisionModelPickerFromForm: () => {},
  syncMicProviderPresetFromEndpoint: () => {},
  syncMicModelPickerFromForm: () => {},
  applyMicIndependentVisibility: () => {},
  updateMicModeHint: () => {},
  updateModelActiveSourceBanner: () => {},
  updateMicActiveSourceBanner: () => {},
  setMicAudioLikelySupported: () => {},
};

export function configureSettingsCore(deps) {
  coreDeps = { ...coreDeps, ...deps };
}

function resolveRenderModeFromCfg(cfg) {
  const raw = String(cfg.danmu_render_mode || '').trim().toLowerCase();
  if (raw === 'scrolling' || raw === 'floating_panel') return raw;
  return 'scrolling';
}

function petBarrageModeEnabledFromCfg(cfg) {
  if (cfg == null) {
    return document.documentElement.dataset.petBarrageModeEnabled === '1';
  }
  const raw = String(cfg?.pet_barrage_mode_enabled ?? '').trim().toLowerCase();
  return raw === '1' || raw === 'true';
}

export function syncPetBarrageSettingsLock(cfg = null) {
  const enabled = petBarrageModeEnabledFromCfg(cfg);
  const modeEl = document.getElementById('danmu_render_mode');
  const countEl = document.getElementById('normal_reply_count');
  const hintEl = document.getElementById('petBarrageSettingsLockHint');
  if (modeEl) {
    modeEl.disabled = enabled;
    modeEl.classList.toggle('opacity-60', enabled);
    modeEl.classList.toggle('cursor-not-allowed', enabled);
  }
  if (countEl) {
    if (enabled) countEl.value = '5';
    countEl.disabled = enabled;
    countEl.classList.toggle('opacity-60', enabled);
    countEl.classList.toggle('cursor-not-allowed', enabled);
  }
  if (hintEl) {
    hintEl.classList.toggle('hidden', !enabled);
  }
}

export function syncFloatingPanelV2FieldsVisibility() {
  const modeEl = document.getElementById('danmu_render_mode');
  const mode = modeEl?.value || 'scrolling';
  const floatingBox = document.getElementById('floatingPanelV2Fields');
  const scrollingBox = document.getElementById('scrollingModeFields');
  if (floatingBox) floatingBox.classList.toggle('hidden', mode !== 'floating_panel');
  if (scrollingBox) scrollingBox.classList.toggle('hidden', mode !== 'scrolling');
}

export function initFloatingPanelV2Controls() {
  const modeEl = document.getElementById('danmu_render_mode');
  if (!modeEl) return;
  modeEl.addEventListener('change', syncFloatingPanelV2FieldsVisibility);
  syncFloatingPanelV2FieldsVisibility();
}

function applyDefaultToField(key, rawValue) {
  const value = rawValue === undefined || rawValue === null ? '' : String(rawValue);
  if (key === 'mic_mode_enabled' || key === 'mic_use_visual_model' || key === 'empty_accel' || key === 'danmu_font_bold' || key === 'floating_panel_font_bold') {
    const el = document.getElementById(key);
    if (el) el.checked = value === '1';
    return;
  }
  const el = document.getElementById(key);
  if (!el) return;
  if (key === 'layout_mode') {
    const allowed = ['fullscreen', '3/4', '1/2', '1/4'];
    el.value = allowed.includes(value) ? value : 'fullscreen';
    return;
  }
  if (key === 'danmu_render_mode') {
    const allowed = ['scrolling', 'floating_panel'];
    el.value = allowed.includes(value) ? value : 'scrolling';
    return;
  }
  if (key === 'eviction_mode') {
    el.value = value === 'accelerate' ? 'accelerate' : 'natural';
    return;
  }
  el.value = value;
}

function openRestoreDefaultsModal() {
  const modal = document.getElementById('restoreDefaultsModal');
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeRestoreDefaultsModal() {
  const modal = document.getElementById('restoreDefaultsModal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function applySettingsDefaults(scope) {
  const configDefaultsCache = getConfigDefaultsCache();
  if (!configDefaultsCache || !Object.keys(configDefaultsCache).length) {
    coreDeps.showToast('无法加载默认配置，请刷新页面后重试', true);
    return;
  }
  const keys = restorableKeysForScope(scope, getActiveSettingsTabId());
  if (scope === 'current' && keys.length === 0) {
    coreDeps.showToast('当前分组无可恢复的表单项', true);
    closeRestoreDefaultsModal();
    return;
  }
  const apiKeyEl = document.getElementById('api_key');
  const micKeyEl = document.getElementById('mic_api_key');
  const apiKeySnapshot = apiKeyEl?.value ?? '';
  const micKeySnapshot = micKeyEl?.value ?? '';
  const restoreMode = document.getElementById('danmu_render_mode')?.value || 'scrolling';
  keys.forEach((key) => {
    applyDefaultToField(key, configDefaultValue(key, restoreMode));
  });
  if (apiKeyEl) apiKeyEl.value = apiKeySnapshot;
  if (micKeyEl) micKeyEl.value = micKeySnapshot;
  coreDeps.syncProviderPresetFromEndpoint();
  coreDeps.applyApiModeValue(
    document.getElementById('api_mode')?.value || configDefaultsCache.api_mode || '',
  );
  coreDeps.syncApiModeLockState();
  const modelId = configDefaultsCache.model || document.getElementById('model')?.value || '';
  coreDeps.syncVisionModelPickerFromForm(modelId);
  coreDeps.syncMicProviderPresetFromEndpoint();
  const micModelId = configDefaultsCache.mic_model || document.getElementById('mic_model')?.value || '';
  coreDeps.syncMicModelPickerFromForm(micModelId);
  coreDeps.applyMicIndependentVisibility();
  coreDeps.updateMicModeHint();
  updateNormalBatchPreview();
  closeRestoreDefaultsModal();
  coreDeps.showToast('已恢复默认值，请点击「保存配置」生效');
}

export async function loadConfigDefaults() {
  try {
    setConfigDefaultsCache(await apiFetch('/api/config/defaults'));
  } catch {
    setConfigDefaultsCache({});
  }
}

export function initRestoreDefaultsControls() {
  document.getElementById('btnRestoreSettingsDefaults')?.addEventListener('click', openRestoreDefaultsModal);
  document.getElementById('btnRestoreDefaultsCurrent')?.addEventListener('click', () => {
    applySettingsDefaults('current');
  });
  document.getElementById('btnRestoreDefaultsAll')?.addEventListener('click', () => {
    applySettingsDefaults('all');
  });
  document.getElementById('btnRestoreDefaultsCancel')?.addEventListener('click', closeRestoreDefaultsModal);
  const modal = document.getElementById('restoreDefaultsModal');
  modal?.addEventListener('click', (e) => {
    if (e.target === modal) closeRestoreDefaultsModal();
  });
}

export function collectFormData() {
  coreDeps.syncVisionModelToHidden();
  coreDeps.syncMicModelToHidden();
  const data = {};
  CONFIG_FIELDS.forEach((name) => {
    const el = document.getElementById(name);
    if (el) data[name] = el.value;
  });
  data.empty_accel = document.getElementById('empty_accel')?.checked ? '1' : '0';
  data.mic_mode_enabled = document.getElementById('mic_mode_enabled')?.checked ? '1' : '0';
  data.mic_use_visual_model = document.getElementById('mic_use_visual_model')?.checked ? '1' : '0';
  data.danmu_font_bold = document.getElementById('danmu_font_bold')?.checked ? '1' : '0';
  data.floating_panel_font_bold = document.getElementById('floating_panel_font_bold')?.checked ? '1' : '0';
  const key = (document.getElementById('api_key')?.value || '').trim();
  if (key && key !== MASKED_API_KEY) data.api_key = key;
  const micKey = (document.getElementById('mic_api_key')?.value || '').trim();
  if (micKey && micKey !== MASKED_API_KEY) data.mic_api_key = micKey;
  return data;
}

export function fillForm(cfg) {
  document.documentElement.dataset.petBarrageModeEnabled = petBarrageModeEnabledFromCfg(cfg) ? '1' : '0';
  const renderMode = resolveRenderModeFromCfg(cfg);
  const cfgWithMode = { ...cfg, danmu_render_mode: renderMode };
  CONFIG_FIELDS.forEach((name) => {
    const el = document.getElementById(name);
    if (el && cfgWithMode[name] !== undefined) el.value = cfgWithMode[name];
  });
  const setIfEmpty = (id) => {
    const el = document.getElementById(id);
    const fallback = configDefaultValue(id, renderMode);
    if (el && fallback && (cfg[id] === undefined || cfg[id] === '' || cfg[id] === null)) {
      el.value = fallback;
    }
  };
  [
    'danmu_speed', 'danmu_lines', 'font_size', 'opacity', 'dedup_threshold', 'hotkey',
    'image_max_width', 'temperature', 'max_tokens', 'image_quality', 'danmu_max_chars',
    'danmu_pending_entry_cap', 'danmu_track_retention_cap', 'reply_queue_max_items',
    'danmu_render_mode', 'floating_panel_width', 'floating_panel_max_items',
    'floating_panel_speed', 'floating_panel_x_offset', 'floating_panel_y_offset',
    'floating_panel_opacity', 'floating_panel_font_size', 'danmu_font_family',
    'floating_panel_font_family',
  ].forEach(setIfEmpty);
  syncFloatingPanelV2FieldsVisibility();
  const danmuBold = document.getElementById('danmu_font_bold');
  if (danmuBold) {
    const v = cfg.danmu_font_bold;
    if (v === '0' || v === 'false') danmuBold.checked = false;
    else if (v === '1' || v === 'true') danmuBold.checked = true;
    else danmuBold.checked = configDefaultValue('danmu_font_bold') !== '0';
  }
  const fpBold = document.getElementById('floating_panel_font_bold');
  if (fpBold) {
    const v = cfg.floating_panel_font_bold;
    if (v === '0' || v === 'false') fpBold.checked = false;
    else if (v === '1' || v === 'true') fpBold.checked = true;
    else fpBold.checked = configDefaultValue('floating_panel_font_bold') !== '0';
  }
  const evictionMode = document.getElementById('eviction_mode');
  if (evictionMode && !cfg.eviction_mode) {
    evictionMode.value = configDefaultValue('eviction_mode') || 'natural';
  }
  const emptyAccel = document.getElementById('empty_accel');
  if (emptyAccel) emptyAccel.checked = cfg.empty_accel !== '0';
  coreDeps.setMicAudioLikelySupported(cfg.mic_audio_likely_supported !== false);
  const micMode = document.getElementById('mic_mode_enabled');
  if (micMode) micMode.checked = cfg.mic_mode_enabled === '1';
  const micUseVisual = document.getElementById('mic_use_visual_model');
  if (micUseVisual) micUseVisual.checked = cfg.mic_use_visual_model !== '0';
  const micWindow = document.getElementById('mic_window_sec');
  if (micWindow && !cfg.mic_window_sec) micWindow.value = configDefaultValue('mic_window_sec') || '5';
  const micModelEl = document.getElementById('mic_model');
  const micModelId = cfg.mic_model || configDefaultValue('mic_model') || '';
  if (micModelEl) micModelEl.value = micModelId;
  coreDeps.syncMicProviderPresetFromEndpoint();
  coreDeps.syncMicModelPickerFromForm(micModelId);
  const micKeyEl = document.getElementById('mic_api_key');
  if (micKeyEl) micKeyEl.value = cfg.has_mic_api_key ? MASKED_API_KEY : '';
  coreDeps.applyMicIndependentVisibility();
  coreDeps.updateMicModeHint();
  const layoutMode = document.getElementById('layout_mode');
  if (layoutMode) {
    const allowed = ['fullscreen', '3/4', '1/2', '1/4'];
    const fallback = configDefaultValue('layout_mode') || 'fullscreen';
    layoutMode.value = allowed.includes(cfg.layout_mode) ? cfg.layout_mode : fallback;
  }
  const normalInterval = document.getElementById('normal_recognition_interval_sec');
  if (normalInterval && !cfg.normal_recognition_interval_sec) {
    normalInterval.value = configDefaultValue('normal_recognition_interval_sec', renderMode) || '5';
  }
  const normalCount = document.getElementById('normal_reply_count');
  if (normalCount && !cfg.normal_reply_count) {
    normalCount.value = configDefaultValue('normal_reply_count', renderMode) || '5';
  }
  syncPetBarrageSettingsLock(cfg);
  updateNormalBatchPreview();
  coreDeps.syncProviderPresetFromEndpoint();
  coreDeps.applyApiModeValue(cfg.api_mode);
  coreDeps.syncApiModeLockState();
  const modelId = cfg.active_model_id || cfg.default_model_id || cfg.model || '';
  const modelEl = document.getElementById('model');
  if (modelEl) modelEl.value = modelId;
  coreDeps.syncVisionModelPickerFromForm(modelId);
  coreDeps.updateModelActiveSourceBanner(cfg);
  coreDeps.updateMicActiveSourceBanner(cfg);
  document.getElementById('api_key').value = cfg.has_api_key ? MASKED_API_KEY : '';
}

export async function reloadConfigFromServer() {
  const cfg = await apiFetch('/api/config');
  fillForm(cfg);
  coreDeps.syncProviderPresetFromEndpoint();
  const modelId = cfg.active_model_id || cfg.default_model_id || cfg.model || '';
  coreDeps.syncVisionModelPickerFromForm(modelId);
  coreDeps.updateModelActiveSourceBanner(cfg);
  coreDeps.updateMicActiveSourceBanner(cfg);
  await coreDeps.loadCustomModels();
  coreDeps.applyCaptureRegionFromPayload({
    mode: cfg.capture_region_mode || (cfg.region_w > 0 && cfg.region_h > 0 ? 'custom' : 'full'),
    region: {
      x: cfg.region_x ?? 0,
      y: cfg.region_y ?? 0,
      w: cfg.region_w ?? 0,
      h: cfg.region_h ?? 0,
    },
    selection_state: 'idle',
  });
  return cfg;
}
