import { API, apiFetch, authHeaders } from './transport.js';
import { getLanguage, t } from './i18n.js';

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
let providerStatusCache = [];

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
  const hostname = extractHostname(endpoint);
  if (!hostname) return null;
  for (const entry of hostEntriesCache) {
    if (hostname === String(entry.fragment || '').toLowerCase()) return entry;
  }
  return null;
}

function extractHostname(endpoint) {
  const normalized = normalizeEndpointForMatch(endpoint);
  if (!normalized) return '';
  try {
    const parsed = new URL(normalized.includes('://') ? normalized : `https://${normalized}`);
    return (parsed.hostname || '').toLowerCase();
  } catch {
    return '';
  }
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

function isProviderVisibleForLanguage(provider) {
  const id = provider?.id;
  if (id === 'custom_doubao') return false;
  if (id === 'custom_openai') return true;
  if (provider.region === 'global') return true;
  const lang = getLanguage();
  if (lang === 'en') return provider.region === 'international';
  if (lang === 'zh') return provider.region === 'china';
  return true;
}

function getVisibleProviders() {
  return providersCache.filter(isProviderVisibleForLanguage);
}

function appendManualProviderOption(sel) {
  const opt = document.createElement('option');
  opt.value = '';
  opt.textContent = MANUAL_PROVIDER_LABEL;
  sel.appendChild(opt);
}

function fillProviderPresetSelect(sel, { mic = false } = {}) {
  sel.innerHTML = '';
  getVisibleProviders().forEach((p) => {
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

export function getProviderStatus(providerId) {
  return providerStatusCache.find((provider) => provider.id === providerId) || null;
}

function formatProviderStatusPart(value) {
  if (value == null || value === '') return '';
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (typeof value === 'object') return formatProviderSourcePart(value);
  return '';
}

function formatProviderSourcePart(source) {
  if (!source || typeof source !== 'object') return '';
  const kind = String(source.source_kind || '').trim().toLowerCase();
  if (kind && kind !== 'unknown') return String(source.source_kind || '').trim();
  return (
    String(source.url || '').trim()
    || String(source.website || '').trim()
    || String(source.docs_url || '').trim()
  );
}

function hasProviderWarningContext(provider) {
  const lifecycle = provider.lifecycle_status || provider.status;
  if (isActionableProviderStatus(lifecycle)) return true;
  if (formatProviderStatusPart(provider.notice)) return true;
  if (provider.migration_url) return true;
  if (provider.sunset_date) return true;
  if (provider.id === 'tencent_hunyuan' || provider.id === 'hunyuan') return true;
  if (String(provider.label || '').includes('混元')) return true;
  return false;
}

function isActionableProviderStatus(status) {
  const normalized = String(status || '').trim().toLowerCase();
  return Boolean(normalized) && normalized !== 'unknown' && normalized !== 'active';
}

export function renderProviderStatus(providerId) {
  const el = document.getElementById('providerStatus');
  if (!el) return;
  const provider = getProviderStatus(providerId);
  if (!provider) { el.classList.add('hidden'); el.textContent = ''; return; }
  const parts = [];
  const lifecycle = provider.lifecycle_status || provider.status;
  if (isActionableProviderStatus(lifecycle)) parts.push(formatProviderStatusPart(lifecycle));
  const notice = formatProviderStatusPart(provider.notice);
  if (notice) parts.push(notice);
  if (hasProviderWarningContext(provider)) {
    const sourcePart = formatProviderSourcePart(provider.source);
    if (sourcePart) parts.push(sourcePart);
  }
  if (provider.migration_url) parts.push(provider.migration_url);
  if (provider.sunset_date) parts.push(`${t('dynamic.settingsProviders.sunset')}: ${provider.sunset_date}`);
  if (provider.id === 'tencent_hunyuan' || provider.id === 'hunyuan' || String(provider.label || '').includes('混元')) {
    parts.unshift(t('dynamic.settingsProviders.hunyuanWarning'));
    parts.push('2026-09-30');
  }
  el.textContent = parts.join(' · ');
  el.classList.toggle('hidden', parts.length === 0);
  el.classList.toggle('border-red-300', provider.id === 'tencent_hunyuan' || provider.id === 'hunyuan');
}

export async function loadProviders() {
  const [providers, rules] = await Promise.all([
    fetch(`${API.base}/api/providers`).then((r) => r.json()),
    fetch(`${API.base}/api/provider-rules`).then((r) => r.json()),
  ]);
  providersCache = providers;
  providerStatusCache = Array.isArray(providers) ? providers : [];
  applyProviderRulesCache(rules);
  const sel = document.getElementById('providerPreset');
  if (sel) {
    fillProviderPresetSelect(sel);
  }
  const modelProv = document.getElementById('modelProvider');
  if (modelProv) {
    modelProv.innerHTML = '';
    getVisibleProviders().forEach((p) => {
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
  syncProviderPresetFromEndpoint();
  syncMicProviderPresetFromEndpoint();
  providersDeps.renderVisionModelPicker(
    resolveProviderIdForPicker(),
    document.getElementById('model')?.value || '',
  );
  providersDeps.renderMicModelPicker(
    resolveMicProviderIdForPicker(),
    document.getElementById('mic_model')?.value || '',
  );
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

export async function resolveProviderByEndpoint() {
  const endpoint = document.getElementById('api_endpoint')?.value || '';
  const apiMode = document.getElementById('api_mode')?.value || '';
  try {
    const data = await apiFetch('/api/model-api/resolve', {
      method: 'POST', headers: authHeaders(),
      body: JSON.stringify({ endpoint, api_mode: apiMode }),
    });
    const providerId = data.provider?.id || data.provider_id || '';
    const sel = document.getElementById('providerPreset');
    if (sel && providerId && Array.from(sel.options).some((option) => option.value === providerId)) sel.value = providerId;
    renderProviderStatus(providerId || guessProviderIdFromEndpoint(endpoint, apiMode));
    return data;
  } catch (_error) {
    syncProviderPresetFromEndpoint();
    renderProviderStatus(resolveProviderIdForPicker());
    return null;
  }
}

export function applyProviderPreset(providerId) {
  const provider = providersCache.find((item) => item.id === providerId);
  if (!provider) return;
  renderProviderStatus(providerId);
  document.getElementById('api_endpoint').value = provider.default_endpoint;
  applyApiModeValue(provider.mode === 'openai-compatible' ? 'openai' : provider.mode);
  syncApiModeLockState();
  const apiKeyEl = document.getElementById('api_key');
  if (apiKeyEl) apiKeyEl.value = '';
  const defaultModelId = providersDeps.pickDefaultCatalogModelId(providerId);
  providersDeps.renderVisionModelPicker(providerId, defaultModelId, { providerSwitch: true });
  providersDeps.showToast(t('dynamic.settingsProviders.已填入_provider_label_的默', {
    providerLabel: provider.label,
  }));
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
  providersDeps.showToast(t('dynamic.settingsProviders.已填入_provider_label_的默_2', {
    providerLabel: provider.label,
  }));
}

export function isCustomProvider(providerId) {
  return providerId === 'custom_openai' || providerId === 'custom_doubao';
}

export function getDefaultEndpoint(providerId) {
  const provider = findProvider(providerId);
  return provider?.default_endpoint ?? '';
}
