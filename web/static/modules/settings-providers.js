import { API } from './transport.js';
import { t } from './i18n.js';

const MANUAL_PROVIDER_LABEL = t('dynamic.settingsProviders.手动填写');
const FALLBACK_DEFAULT_PROVIDER_ID = 'custom_openai';
const FALLBACK_EDITABLE_API_MODE_PROVIDER_IDS = new Set(['custom_openai', 'custom_doubao']);

export const API_MODE_OPTIONS = [
  { value: 'doubao', label: t('dynamic.settingsProviders.豆包_火山方舟') },
  { value: 'openai', label: t('dynamic.settingsProviders.OpenAI_兼容接口') },
];

// Mic tab only: suffix clarifies audio capability; API tab uses plain provider labels.
const MIC_LABEL_SUFFIX = {
  doubao: t('dynamic.settingsProviders.支持部分全模态模型'),
  mimo: '（mimo-v2.5）',
  custom_openai: t('dynamic.settingsProviders.需模型支持音频输入'),
  custom_doubao: t('dynamic.settingsProviders.需模型支持_input_audio'),
};

let providersDeps = {
  showToast: () => {},
  pickDefaultCatalogModelId: () => '',
  renderVisionModelPicker: () => {},
  pickDefaultMicCatalogModelId: () => '',
  renderMicModelPicker: () => {},
  updateMicModeHint: () => {},
};

let providersCache = [];
let hostEntriesCache = [];
let defaultProviderIdCache = FALLBACK_DEFAULT_PROVIDER_ID;
let editableApiModeProviderIds = new Set(FALLBACK_EDITABLE_API_MODE_PROVIDER_IDS);
let thinkingSupportedProviderIds = new Set(['doubao', 'custom_doubao']);

function normalizeEndpointForMatch(endpoint) {
  return String(endpoint || '').trim().toLowerCase().replace(/\/+$/, '');
}

function normalizeModeInput(apiMode) {
  const raw = String(apiMode ?? '').trim().toLowerCase();
  if (raw === 'doubao') return 'doubao';
  if (raw === 'openai' || raw === 'openai-compatible' || raw === 'openai_compatible') {
    return 'openai-compatible';
  }
  return raw;
}

function isDoubaoMode(apiMode) {
  return normalizeModeInput(apiMode) === 'doubao';
}

function matchHostEntry(endpoint) {
  const normalized = normalizeEndpointForMatch(endpoint);
  if (!normalized) return null;
  for (const entry of hostEntriesCache) {
    if (normalized.includes(entry.fragment)) return entry;
  }
  return null;
}

export function resolveApiTransport(endpoint, apiMode) {
  const entry = matchHostEntry(endpoint);
  if (entry) return entry.transport;
  if (isDoubaoMode(apiMode)) return 'doubao';
  return 'openai';
}

export function guessProviderIdFromEndpoint(endpoint, apiMode) {
  const entry = matchHostEntry(endpoint);
  if (entry) return entry.provider_id;
  const mode = apiMode ?? document.getElementById('api_mode')?.value ?? '';
  if (isDoubaoMode(mode)) return 'custom_doubao';
  return defaultProviderIdCache || FALLBACK_DEFAULT_PROVIDER_ID;
}

export function configureSettingsProviders(deps) {
  providersDeps = { ...providersDeps, ...deps };
}

export function initApiModeSelect() {
  const sel = document.getElementById('api_mode');
  if (!sel) return;
  sel.innerHTML = '';
  API_MODE_OPTIONS.forEach(({ value, label }) => {
    const opt = document.createElement('option');
    opt.value = value;
    opt.textContent = label;
    sel.appendChild(opt);
  });
}

export function normalizeApiModeForSelect(mode, endpoint = '') {
  const endpointVal = endpoint || document.getElementById('api_endpoint')?.value || '';
  const transport = resolveApiTransport(endpointVal, mode);
  return transport === 'doubao' ? 'doubao' : 'openai';
}

export function applyApiModeValue(mode) {
  initApiModeSelect();
  const sel = document.getElementById('api_mode');
  if (!sel) return;
  const endpoint = document.getElementById('api_endpoint')?.value || '';
  const normalized = normalizeApiModeForSelect(mode, endpoint);
  const hasOption = Array.from(sel.options).some((opt) => opt.value === normalized);
  if (hasOption) sel.value = normalized;
}

export function syncApiModeLockState() {
  const sel = document.getElementById('api_mode');
  if (!sel) return;
  const presetSel = document.getElementById('providerPreset');
  const presetId = (presetSel?.value || '').trim() || resolveProviderIdForPicker();
  const locked = Boolean(presetId && !editableApiModeProviderIds.has(presetId));
  sel.disabled = locked;
}

function appendManualProviderOption(sel) {
  const opt = document.createElement('option');
  opt.value = '';
  opt.textContent = MANUAL_PROVIDER_LABEL;
  sel.appendChild(opt);
}

function fillProviderPresetSelect(sel, { mic = false } = {}) {
  sel.innerHTML = '';
  providersCache.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.id;
    const suffix = mic ? (MIC_LABEL_SUFFIX[p.id] || '') : '';
    opt.textContent = `${p.label}${suffix}`;
    sel.appendChild(opt);
  });
  appendManualProviderOption(sel);
}

function applyProviderRulesCache(rules) {
  hostEntriesCache = Array.isArray(rules?.host_entries) ? rules.host_entries : [];
  defaultProviderIdCache = rules?.default_provider_id || FALLBACK_DEFAULT_PROVIDER_ID;
  const editableIds = Array.isArray(rules?.editable_api_mode_provider_ids)
    ? rules.editable_api_mode_provider_ids
    : [...FALLBACK_EDITABLE_API_MODE_PROVIDER_IDS];
  editableApiModeProviderIds = new Set(editableIds);
  const thinkingIds = Array.isArray(rules?.thinking_supported_provider_ids)
    ? rules.thinking_supported_provider_ids
    : ['doubao', 'custom_doubao'];
  thinkingSupportedProviderIds = new Set(thinkingIds);
}

export function isThinkingSupportedForProvider(providerId) {
  return thinkingSupportedProviderIds.has((providerId || '').trim());
}

export async function loadProviders() {
  const [providers, rules] = await Promise.all([
    fetch(`${API.base}/api/providers`).then((r) => r.json()),
    fetch(`${API.base}/api/provider-rules`).then((r) => r.json()),
  ]);
  providersCache = providers;
  applyProviderRulesCache(rules);
  const sel = document.getElementById('providerPreset');
  if (sel) {
    fillProviderPresetSelect(sel);
  }
  const modelProv = document.getElementById('modelProvider');
  if (modelProv) {
    modelProv.innerHTML = '';
    providersCache.forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.label;
      modelProv.appendChild(opt);
    });
  }
  const micSel = document.getElementById('micProviderPreset');
  if (micSel) {
    fillProviderPresetSelect(micSel, { mic: true });
  }
  initApiModeSelect();
}

export function syncProviderPresetFromEndpoint() {
  const sel = document.getElementById('providerPreset');
  if (!sel) return;
  const endpoint = document.getElementById('api_endpoint')?.value || '';
  const apiMode = document.getElementById('api_mode')?.value || '';
  const guessed = guessProviderIdFromEndpoint(endpoint, apiMode);
  if (!guessed) {
    sel.value = '';
    syncApiModeLockState();
    return;
  }
  const hasOption = Array.from(sel.options).some((opt) => opt.value === guessed);
  sel.value = hasOption ? guessed : '';
  syncApiModeLockState();
}

export function syncProviderPresetAfterEndpointEdit() {
  syncProviderPresetFromEndpoint();
  applyApiModeValue(document.getElementById('api_mode')?.value || '');
  providersDeps.renderVisionModelPicker(resolveProviderIdForPicker(), document.getElementById('model')?.value || '');
}

export function applyProviderPreset(providerId) {
  const provider = providersCache.find((item) => item.id === providerId);
  if (!provider) return;
  document.getElementById('api_endpoint').value = provider.default_endpoint;
  applyApiModeValue(provider.mode === 'openai-compatible' ? 'openai' : provider.mode);
  syncApiModeLockState();
  const apiKeyEl = document.getElementById('api_key');
  if (apiKeyEl) apiKeyEl.value = '';
  const defaultModelId = providersDeps.pickDefaultCatalogModelId(providerId);
  providersDeps.renderVisionModelPicker(providerId, defaultModelId, { providerSwitch: true });
  providersDeps.showToast(t('dynamic.settingsProviders.已填入_provider_label_的默'));
}

export function resolveProviderIdForPicker() {
  const endpoint = document.getElementById('api_endpoint')?.value || '';
  const apiMode = document.getElementById('api_mode')?.value || '';
  return guessProviderIdFromEndpoint(endpoint, apiMode);
}

export function syncMicProviderPresetFromEndpoint() {
  const sel = document.getElementById('micProviderPreset');
  if (!sel) return;
  const endpoint = document.getElementById('mic_api_endpoint')?.value || '';
  const apiMode = document.getElementById('mic_api_mode')?.value || '';
  const guessed = guessProviderIdFromEndpoint(endpoint, apiMode);
  if (!guessed) {
    sel.value = '';
    return;
  }
  const hasOption = Array.from(sel.options).some((opt) => opt.value === guessed);
  sel.value = hasOption ? guessed : '';
}

export function resolveMicProviderIdForPicker() {
  const endpoint = document.getElementById('mic_api_endpoint')?.value || '';
  const apiMode = document.getElementById('mic_api_mode')?.value || '';
  return guessProviderIdFromEndpoint(endpoint, apiMode);
}

export function findProvider(id) {
  const target = (id || '').trim();
  if (!target) return undefined;
  return providersCache.find((item) => item.id === target);
}

export function getProviderWebsite(id) {
  const provider = findProvider(id);
  const website = provider?.website;
  return typeof website === 'string' && website.trim() ? website.trim() : null;
}

export function applyMicProviderPreset(providerId) {
  const provider = providersCache.find((item) => item.id === providerId);
  if (!provider) return;
  document.getElementById('mic_api_endpoint').value = provider.default_endpoint;
  document.getElementById('mic_api_mode').value = provider.mode === 'openai-compatible'
    ? 'openai'
    : provider.mode;
  const micKeyEl = document.getElementById('mic_api_key');
  if (micKeyEl) micKeyEl.value = '';
  const defaultModelId = providersDeps.pickDefaultMicCatalogModelId(providerId);
  providersDeps.renderMicModelPicker(providerId, defaultModelId, { providerSwitch: true });
  providersDeps.updateMicModeHint();
  providersDeps.showToast(t('dynamic.settingsProviders.已填入_provider_label_的默_2'));
}

export function isCustomProvider(providerId) {
  return providerId === 'custom_openai' || providerId === 'custom_doubao';
}

export function getDefaultEndpoint(providerId) {
  const provider = findProvider(providerId);
  return provider?.default_endpoint ?? '';
}
