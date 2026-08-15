import { t } from './modules/i18n.js';
import {
  API,
  REALTIME,
  apiFetch,
  refreshSession,
  setRealtimeHandlers,
  startRealtimeTransport,
  stopRealtimeTransport,
} from './modules/transport.js';
import { applyStatus, configureStatus, getLastAppliedStatus } from './modules/status.js';
import {
  appendLog,
  bootstrapLogsFromServer,
  clearLogBuffer,
  closeLogView,
  logBuffer,
  logClosed,
  logLevelFilters,
  mergeLogItems,
  reopenLogView,
  renderLogView,
  replaceLogLevelFilters,
  setLogAutoScroll,
  setLogClosed,
  updateLogPanelState,
} from './modules/logs.js';
import {
  initMicLogsPage,
  navigateToDanmuLogs,
  navigateToMicLogs,
  onMicLogsTabActivated,
} from './modules/mic-logs.js';
import {
  applyCaptureRegionFromPayload,
  bindSettingsControls,
  initCaptureRegionControls,
  initNormalBatchControls,
  initRenderModeControls,
  initRestoreDefaultsControls,
  initContentPageFieldHints,
  initSettingsFieldHints,
  initSettingsTabs,
  initSidebarNavFloatingHints,
  loadConfigDefaults,
  loadCustomModels,
  loadModelCatalog,
  loadProviders,
  loadScreens,
  populateMicInputDevices,
  reloadConfigFromServer,
  switchSettingsTab,
  getActiveSettingsTabId,
} from './modules/settings.js?v=20260717-number-stepper-v1';
import { initNumberSteppers } from './modules/number-stepper.js?v=20260717-number-stepper-v1';
import {
  configureGuideTabs,
  getActiveGuideTabId,
  initGuideTabs,
  switchGuideTab,
} from './modules/guide-tabs.js';
import { isMaskedApiKey } from './modules/settings-defaults.js';
import { initTheme } from './modules/theme.js';
import { bootstrapI18n, initLanguage } from './modules/language.js';
import { applyI18n } from './modules/i18n.js';
import {
  bindContentPageControls,
  loadAnnouncementsPage,
  loadAnnouncementsReadState,
  refreshAnnouncementsUnreadBadge,
  startAnnouncementsBadgePolling,
  stopAnnouncementsBadgePolling,
  updateAnnouncementsNavBadge,
} from './modules/content-pages.js';
import {
  initErrorReporting,
  openErrorReportModal as openErrorReportModalImpl,
  openErrorReportModalFromProblem,
} from './modules/app-error-reporting.js';
import {
  initProblemDialog,
  maybeShowProblem,
  updateVisibleProblemOccurrence,
  buildFrontendInternalProblem,
} from './modules/app-problem-dialog.js';
import {
  initLiveOverlayPanel,
  refreshLiveOverlayStatus,
} from './modules/app-live-overlay-panel.js';
import {
  initPersonaTopicPage,
  loadOverviewGlobalFields,
  loadPersonaEditor,
  loadPersonaTemplate,
} from './modules/app-persona-topic-page.js';
import {
  initAppUpdateModal,
  initAppVersionAndUpdateCheck,
} from './modules/app-update-banner.js';
import {
  closeShellNavIfDrawer,
  initResponsiveShell,
} from './modules/responsive-shell.js';

let danmuReadConfigCache = null;
let danmuReadCatalog = null;
let danmuReadCredentialDrafts = {};
let danmuReadSavedCredentials = {};
let danmuReadVoices = [];
let danmuReadVoiceRequest = 0;
let danmuPoolPagesReady = false;
let petPageReady = false;
let styleGeneratorPageReady = false;
let knowledgePageReady = false;

async function ensureDanmuPoolPages() {
  const [poolMod, memeMod] = await Promise.all([
    import('./modules/app-danmu-pool-page.js'),
    import('./modules/app-meme-barrage-page.js'),
  ]);
  if (!danmuPoolPagesReady) {
    poolMod.initDanmuPoolPage({ showToast });
    memeMod.initMemeBarragePage({ showToast });
    danmuPoolPagesReady = true;
  }
  return { poolMod, memeMod };
}

async function ensurePetPage() {
  const mod = await import('./modules/app-pet-page.js');
  if (!petPageReady) {
    mod.initPetPage({ showToast });
    petPageReady = true;
  }
  return mod;
}

async function ensureKnowledgePage() {
  const mod = await import('./modules/app-knowledge-page.js');
  if (!knowledgePageReady) {
    mod.initKnowledgePage({ showToast });
    knowledgePageReady = true;
  }
  return mod;
}

async function ensureStyleGeneratorPage() {
  const mod = await import('./modules/app-style-generator-page.js');
  if (!styleGeneratorPageReady) {
    mod.initStyleGeneratorPage({ showToast, navigate });
    styleGeneratorPageReady = true;
  }
  return mod;
}

function invalidateDanmuReadCache() {
  danmuReadConfigCache = null;
  danmuReadCatalog = null;
}

let _toastExitTimer = null;
const BOOTSTRAP_TIMEOUT_MS = 10000;
const bootstrapErrors = new Map();

function showToast(message, isError = false) {
  const el = document.getElementById('toast');
  if (_toastExitTimer) {
    clearTimeout(_toastExitTimer);
    _toastExitTimer = null;
  }
  el.textContent = message;
  el.className = `toast show ${isError ? 'text-red-700' : 'text-warmText'}`;
  _toastExitTimer = setTimeout(() => {
    el.classList.add('toast-exit');
    el.classList.remove('show');
    _toastExitTimer = setTimeout(() => {
      el.classList.remove('toast-exit');
      el.className = 'toast';
      _toastExitTimer = null;
    }, 300);
  }, 3200);
}

function describeBootstrapError(error) {
  if (error?.code === 'BOOTSTRAP_TIMEOUT') return t('dynamic.transport.请求失败');
  if (error instanceof Error && error.message) return error.message;
  const message = String(error ?? '').trim();
  return message || t('dynamic.transport.请求失败');
}

function renderBootstrapErrors() {
  const banner = document.getElementById('errorBanner');
  const bannerMessage = document.getElementById('errorBannerMessage');
  if (!banner) return;
  const messages = [...bootstrapErrors.values()];
  if (!messages.length) {
    if (banner.dataset.bootstrapError === '1') {
      banner.classList.add('hidden');
      banner.classList.remove('ui-status-banner--danger', 'text-red-700');
      delete banner.dataset.bootstrapError;
    }
    return;
  }
  const text = messages.join(' · ');
  if (bannerMessage) bannerMessage.textContent = text;
  else banner.textContent = text;
  banner.dataset.bootstrapError = '1';
  banner.classList.remove('hidden');
  banner.classList.add('ui-status-banner--danger', 'text-red-700');
}

function recordBootstrapFailure(label, error) {
  const detail = describeBootstrapError(error);
  const message = `${label}: ${detail}`;
  bootstrapErrors.set(label, message);
  console.warn(`[bootstrap] ${message}`, error);
  renderBootstrapErrors();
  showToast(message, true);
}

function clearBootstrapFailure(label) {
  if (bootstrapErrors.delete(label)) renderBootstrapErrors();
}

async function runBootstrapTask(label, task) {
  try {
    const value = await task();
    clearBootstrapFailure(label);
    return value;
  } catch (error) {
    recordBootstrapFailure(label, error);
    return null;
  }
}

function createBootstrapTimeout(path) {
  const error = new Error(`Bootstrap request timed out: ${path}`);
  error.code = 'BOOTSTRAP_TIMEOUT';
  return error;
}

async function fetchBootstrapStatus() {
  if (typeof AbortController === 'undefined') return apiFetch('/api/status');
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), BOOTSTRAP_TIMEOUT_MS);
  try {
    const status = await apiFetch('/api/status', { signal: controller.signal });
    if (
      status === null
      || typeof status !== 'object'
      || Array.isArray(status)
      || typeof status.running !== 'boolean'
    ) {
      throw new Error('Invalid /api/status payload: running is missing');
    }
    return status;
  } catch (error) {
    if (controller.signal.aborted) throw createBootstrapTimeout('/api/status');
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

async function withLoadingState(btn, originalText, asyncFn, successText = null, successDurationMs = 2000) {
  if (!btn) return asyncFn();
  const loadingText = originalText ? t('dynamic.app.originalText_中', { originalText }) : t('common.processing');
  const savedOriginal = originalText || btn.textContent;
  btn.disabled = true;
  btn.textContent = loadingText;
  btn.style.opacity = '0.7';
  let succeeded = false;
  try {
    const result = await asyncFn();
    succeeded = true;
    if (successText) {
      btn.textContent = successText;
      btn.style.opacity = '';
      setTimeout(() => {
        if (btn.textContent === successText) btn.textContent = savedOriginal;
      }, successDurationMs);
    }
    return result;
  } finally {
    if (!successText || !succeeded) {
      btn.textContent = savedOriginal;
      btn.style.opacity = '';
    }
    btn.disabled = false;
  }
}
window.withLoadingState = withLoadingState;

function maybePromptErrorReport(_status) {
  return Promise.resolve();
}

let frontendProblemReporting = false;

window.addEventListener('unhandledrejection', (event) => {
  if (frontendProblemReporting) return;
  const reason = event.reason;
  const message = reason instanceof Error ? reason.message : String(reason ?? 'unknown');
  console.warn('[app] unhandled promise rejection:', reason);
  frontendProblemReporting = true;
  try {
    maybeShowProblem(buildFrontendInternalProblem(message));
  } finally {
    frontendProblemReporting = false;
  }
});

window.addEventListener('error', (event) => {
  if (frontendProblemReporting) return;
  const message = String(event.message || '');
  if (!message || message === 'Script error.') return;
  if (message.includes('ResizeObserver')) return;
  console.warn('[app] window error:', event);
  frontendProblemReporting = true;
  try {
    maybeShowProblem(buildFrontendInternalProblem(message));
  } finally {
    frontendProblemReporting = false;
  }
});

const DANMU_READ_PROVIDER_ALIASES = { dashscope_qwen: 'dashscope' };
const DANMU_READ_FALLBACK_CATALOG = {
  providers: [
    { id: 'mimo', label: '小米 MiMo', auth_schema: { fields: [{ id: 'api_key', label: 'MiMo API Key', secret: true }] }, models: [{ id: 'mimo-v2.5-tts', label: 'MiMo V2.5 TTS', recommended: true, tags: ['推荐'], pricing: { kind: 'promotional_free', display: '限时免费' }, capabilities: { streaming: true, style_prompt: true, voice_list: true, output_formats: ['wav'] }, voices: [{ id: '冰糖', name: '冰糖' }, { id: '茉莉', name: '茉莉' }, { id: '苏打', name: '苏打' }, { id: '白桦', name: '白桦' }] }] },
    { id: 'dashscope', label: '阿里百炼 DashScope', auth_schema: { fields: [{ id: 'api_key', label: 'DashScope API Key', secret: true }] }, models: [{ id: 'qwen3-tts-flash', label: 'Qwen3-TTS Flash', recommended: true, tags: ['推荐'], capabilities: { voice_list: true }, voices: [{ id: 'Cherry', name: '芊悦' }, { id: 'Serena', name: '苏瑶' }, { id: 'Ethan', name: '晨煦' }] }] },
    { id: 'minimax', label: 'MiniMax', auth_schema: { fields: [{ id: 'api_key', label: 'MiniMax API Key', secret: true }] }, models: [{ id: 'speech-2.8-turbo', label: 'Speech 2.8 Turbo', recommended: true, tags: ['推荐', '低延迟'], capabilities: { emotion: true, speed: true, pitch: true, volume: true, voice_list: true, custom_voice_id: true }, voices: [{ id: 'male-qn-qingse', name: '青涩男声' }] }] },
    { id: 'doubao', label: '火山引擎豆包', auth_schema: { fields: [{ id: 'api_key', label: 'TTS API Key', secret: true }, { id: 'access_key_id', label: 'Access Key ID', required: false, secret: true }, { id: 'secret_access_key', label: 'Secret Access Key', required: false, secret: true }] }, models: [{ id: 'seed-tts-2.0', label: 'Doubao Seed TTS 2.0', recommended: true, tags: ['V3'], capabilities: { streaming: true, voice_list: true, voice_preview: true, custom_voice_id: true }, voices: [] }] },
  ],
};

function danmuReadCanonicalProviderId(value) {
  const raw = String(value || '').trim();
  return DANMU_READ_PROVIDER_ALIASES[raw] || raw;
}

function danmuReadProviderLabel(provider) {
  const language = document.documentElement.lang === 'en' ? 'en' : 'zh';
  return provider?.[`label_${language}`] || provider?.label || provider?.id || '';
}

function danmuReadNormalizeVoice(voice) {
  if (!voice || !voice.id) return null;
  return { ...voice, name: voice.name || voice.label || voice.id, tags: voice.tags || [] };
}

function danmuReadNormalizeModel(model) {
  if (!model?.id) return null;
  const capabilities = { ...(model.capabilities || {}) };
  if (model.supports_style != null && capabilities.style_prompt == null) capabilities.style_prompt = Boolean(model.supports_style);
  const voices = (model.voices || []).map(danmuReadNormalizeVoice).filter(Boolean);
  return { ...model, label: model.label || model.name || model.id, tags: model.tags || [], capabilities, voices };
}

function danmuReadNormalizeProvider(provider) {
  if (!provider?.id) return null;
  const id = danmuReadCanonicalProviderId(provider.id);
  const authSchema = provider.auth_schema || provider.auth || { fields: [] };
  const fields = Array.isArray(authSchema) ? authSchema : (authSchema.fields || []);
  return {
    ...provider,
    id,
    wire_id: provider.wire_id || provider.id,
    label: provider.label || provider.name || id,
    auth_schema: { ...authSchema, fields },
    models: (provider.models || []).map(danmuReadNormalizeModel).filter(Boolean),
  };
}

function normalizeDanmuReadCatalog(raw) {
  const source = Array.isArray(raw?.providers) ? raw.providers : [];
  const merged = new Map();
  [...source, ...DANMU_READ_FALLBACK_CATALOG.providers].forEach((provider) => {
    const normalized = danmuReadNormalizeProvider(provider);
    if (!normalized || merged.has(normalized.id)) return;
    merged.set(normalized.id, normalized);
  });
  return { providers: [...merged.values()] };
}

function getDanmuReadCatalogProvider(providerId) {
  const pid = danmuReadCanonicalProviderId(providerId || 'mimo');
  return danmuReadCatalog?.providers?.find((provider) => provider.id === pid) || null;
}

function currentDanmuReadProvider() {
  const value = document.getElementById('danmuReadProvider')?.value || 'mimo';
  return getDanmuReadCatalogProvider(value) || getDanmuReadCatalogProvider('mimo');
}

function currentDanmuReadModel() {
  const provider = currentDanmuReadProvider();
  const value = document.getElementById('danmuReadModelSelect')?.value || '';
  return provider?.models?.find((model) => model.id === value) || provider?.models?.[0] || null;
}

function setHidden(element, hidden) {
  if (!element) return;
  element.hidden = Boolean(hidden);
  element.classList.toggle('hidden', Boolean(hidden));
}

function renderDanmuReadProviderCards() {
  const container = document.getElementById('danmuReadProviderCards');
  const select = document.getElementById('danmuReadProvider');
  if (!container || !select) return;
  const selected = danmuReadCanonicalProviderId(select.value || 'mimo');
  container.replaceChildren();
  select.replaceChildren();
  (danmuReadCatalog?.providers || []).forEach((provider) => {
    const option = new Option(danmuReadProviderLabel(provider), provider.wire_id || provider.id);
    select.appendChild(option);
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'tts-provider-card ui-card ui-card--interactive';
    button.dataset.providerId = provider.id;
    button.setAttribute('role', 'radio');
    button.setAttribute('aria-checked', String(provider.id === selected));
    button.addEventListener('click', () => {
      select.value = provider.wire_id || provider.id;
      handleDanmuReadProviderChange();
    });
    const name = document.createElement('strong');
    name.textContent = danmuReadProviderLabel(provider);
    const meta = document.createElement('span');
    meta.className = 'tts-provider-card__meta';
    meta.textContent = provider.credential_status?.configured ? t('settings.text.凭据已保存') : t('settings.text.按需填写凭据');
    button.append(name, meta);
    container.appendChild(button);
  });
  select.value = (danmuReadCatalog?.providers || []).find((provider) => provider.id === selected)?.wire_id || select.options[0]?.value || '';
}

function formatDanmuReadPricing(model) {
  const pricing = model?.pricing || {};
  if (pricing.display) return pricing.display;
  if (pricing.kind === 'promotional_free') return t('settings.text.限时免费');
  return t('settings.text.价格以目录为准');
}

function renderDanmuReadModelCards() {
  const provider = currentDanmuReadProvider();
  const select = document.getElementById('danmuReadModelSelect');
  const container = document.getElementById('danmuReadModelCards');
  if (!select || !container) return;
  const selected = select.value || provider?.models?.find((model) => model.recommended)?.id || provider?.models?.[0]?.id || '';
  select.replaceChildren();
  container.replaceChildren();
  (provider?.models || []).forEach((model) => {
    const option = new Option(model.label || model.id, model.id);
    select.appendChild(option);
    const card = document.createElement('button');
    card.type = 'button';
    card.className = 'tts-model-card ui-card ui-card--interactive';
    card.dataset.modelId = model.id;
    card.setAttribute('role', 'radio');
    card.setAttribute('aria-checked', String(model.id === selected));
    card.addEventListener('click', () => {
      select.value = model.id;
      handleDanmuReadModelChange();
    });
    const title = document.createElement('strong');
    title.textContent = model.label || model.id;
    const id = document.createElement('code');
    id.textContent = model.id;
    const price = document.createElement('span');
    price.className = 'tts-model-card__price';
    price.textContent = formatDanmuReadPricing(model);
    const tags = document.createElement('span');
    tags.className = 'tts-model-card__tags';
    tags.textContent = (model.tags || []).join(' · ');
    const use = document.createElement('span');
    use.className = 'tts-model-card__use';
    use.textContent = model.use_case || model.description || t('settings.text.适合当前语音场景');
    const verified = document.createElement('small');
    const verifiedAt = model.verified_at || model.pricing?.verified_at;
    verified.textContent = verifiedAt ? `${t('settings.text.核验日期')} ${verifiedAt}` : t('settings.text.价格核验日期待目录提供');
    card.append(title, id, price, tags, use, verified);
    container.appendChild(card);
  });
  if (selected && [...select.options].some((option) => option.value === selected)) select.value = selected;
  else if (select.options.length) select.selectedIndex = 0;
}

function credentialFieldsFor(provider) {
  const fields = provider?.auth_schema?.fields || [];
  return fields.length ? fields : [{ id: 'api_key', label: t('settings.text.API密钥'), secret: true }];
}

function isDanmuReadMasked(value) {
  return isMaskedApiKey(value) || /^([•*]){4,}$/.test(String(value || '').trim());
}

function captureDanmuReadCredentialDraft() {
  const provider = currentDanmuReadProvider();
  if (!provider) return;
  const values = { ...(danmuReadCredentialDrafts[provider.id] || {}) };
  credentialFieldsFor(provider).forEach((field) => {
    const input = document.getElementById(`danmuReadCredential-${field.id}`);
    if (input) values[field.id] = input.value;
  });
  danmuReadCredentialDrafts[provider.id] = values;
}

function renderDanmuReadCredentials() {
  const provider = currentDanmuReadProvider();
  const container = document.getElementById('danmuReadCredentials');
  const help = document.getElementById('danmuReadCredentialsHelp');
  if (!provider || !container) return;
  captureDanmuReadCredentialDraft();
  container.replaceChildren();
  const saved = danmuReadSavedCredentials[provider.id] || {};
  const draft = danmuReadCredentialDrafts[provider.id] || {};
  credentialFieldsFor(provider).forEach((field) => {
    const wrapper = document.createElement('div');
    wrapper.className = 'tts-credential-field';
    const label = document.createElement('label');
    label.className = 'settings-field-label';
    label.htmlFor = `danmuReadCredential-${field.id}`;
    label.textContent = field.label || field.id;
    const input = document.createElement('input');
    input.id = `danmuReadCredential-${field.id}`;
    input.type = field.secret === false ? 'text' : 'password';
    input.autocomplete = 'off';
    input.className = 'settings-field-control w-full ui-control ui-input';
    input.placeholder = field.placeholder || '';
    input.value = draft[field.id] ?? saved[field.id] ?? '';
    input.addEventListener('input', () => {
      danmuReadCredentialDrafts[provider.id] = { ...(danmuReadCredentialDrafts[provider.id] || {}), [field.id]: input.value };
    });
    if (field.id === 'api_key') input.dataset.legacyApiKey = 'true';
    const status = document.createElement('small');
    status.className = 'settings-section-hint';
    status.textContent = isDanmuReadMasked(input.value) || saved[field.id] === true ? t('settings.text.凭据已保存') : t('settings.text.试听可使用当前值');
    wrapper.append(label, input, status);
    container.appendChild(wrapper);
  });
  if (help) {
    const url = provider.auth_schema?.help_url || provider.help_url || '';
    setHidden(help, !/^https?:\/\//i.test(url));
    if (/^https?:\/\//i.test(url)) help.href = url;
  }
}

function populateDanmuReadVoiceSelect(providerId, modelId, selectedVoice) {
  const voiceEl = document.getElementById('danmuReadVoice');
  const provider = getDanmuReadCatalogProvider(providerId);
  const model = provider?.models?.find((item) => item.id === modelId) || provider?.models?.[0];
  danmuReadVoices = [...(model?.voices || [])];
  if (!voiceEl) return;
  voiceEl.replaceChildren();
  danmuReadVoices.forEach((voice) => voiceEl.appendChild(new Option(voice.name || voice.id, voice.id)));
  if (selectedVoice && [...voiceEl.options].some((option) => option.value === selectedVoice)) voiceEl.value = selectedVoice;
  else if (voiceEl.options.length) voiceEl.selectedIndex = 0;
  renderDanmuReadVoiceList();
}

function renderDanmuReadVoiceList() {
  const container = document.getElementById('danmuReadVoiceList');
  const search = document.getElementById('danmuReadVoiceSearch')?.value.trim().toLowerCase() || '';
  const selected = document.getElementById('danmuReadVoice')?.value || '';
  if (!container) return;
  container.replaceChildren();
  const filtered = danmuReadVoices.filter((voice) => `${voice.name} ${voice.id} ${(voice.tags || []).join(' ')}`.toLowerCase().includes(search));
  if (!filtered.length) {
    const empty = document.createElement('p');
    empty.className = 'settings-section-hint';
    empty.textContent = t('settings.text.暂无匹配音色');
    container.appendChild(empty);
    return;
  }
  filtered.forEach((voice) => {
    const row = document.createElement('div');
    row.className = `tts-voice-row${voice.id === selected ? ' is-selected' : ''}`;
    const choose = document.createElement('button');
    choose.type = 'button';
    choose.className = 'tts-voice-row__select';
    choose.setAttribute('aria-pressed', String(voice.id === selected));
    choose.addEventListener('click', () => {
      const select = document.getElementById('danmuReadVoice');
      if (select) select.value = voice.id;
      renderDanmuReadVoiceList();
    });
    const name = document.createElement('strong');
    name.textContent = voice.name || voice.id;
    const meta = document.createElement('span');
    meta.textContent = [voice.gender, voice.age_group, ...(voice.tags || [])].filter(Boolean).join(' · ') || voice.id;
    choose.append(name, meta);
    const preview = document.createElement('button');
    preview.type = 'button';
    preview.className = 'ui-button ui-button--secondary ui-button--sm';
    preview.textContent = t('settings.text.试听音色');
    preview.addEventListener('click', (event) => {
      event.stopPropagation();
      withLoadingState(preview, preview.textContent, () => probeDanmuRead(voice.id)).catch((error) => showToast(error.message, true));
    });
    row.append(choose, preview);
    container.appendChild(row);
  });
}

async function refreshDanmuReadVoices(forceRefresh = true) {
  const provider = currentDanmuReadProvider();
  const model = currentDanmuReadModel();
  const status = document.getElementById('danmuReadVoiceStatus');
  const requestId = ++danmuReadVoiceRequest;
  if (!provider || !model) return;
  if (status) status.textContent = t('settings.text.正在获取音色');
  try {
    const params = `?provider=${encodeURIComponent(provider.wire_id || provider.id)}&model_id=${encodeURIComponent(model.id)}&force_refresh=${forceRefresh ? '1' : '0'}`;
    const response = await apiFetch(`/api/danmu-read/voices${params}`);
    const voices = Array.isArray(response) ? response : response?.voices;
    if (requestId !== danmuReadVoiceRequest || !Array.isArray(voices)) return;
    danmuReadVoices = voices.map(danmuReadNormalizeVoice).filter(Boolean);
    populateDanmuReadVoiceSelect(provider.id, model.id, document.getElementById('danmuReadVoice')?.value || '');
    if (status) status.textContent = t('settings.text.音色已刷新');
  } catch {
    if (status) status.textContent = t('settings.text.在线音色不可用已使用目录');
    renderDanmuReadVoiceList();
  }
}

function updateDanmuReadStyleHint(model) {
  const hint = document.getElementById('danmuReadStyleHint');
  if (hint) hint.textContent = model?.capabilities?.style_prompt ? t('settings.text.当前模型支持风格指令') : t('settings.text.当前模型不提供风格指令');
}

function syncDanmuReadCapabilities() {
  const model = currentDanmuReadModel();
  const capabilities = model?.capabilities || {};
  document.querySelectorAll('#danmuReadAdvancedFields [data-tts-capability]').forEach((field) => {
    const capability = field.dataset.ttsCapability;
    setHidden(field, capabilities[capability] !== true);
  });
  const anyVisible = [...document.querySelectorAll('#danmuReadAdvancedFields [data-tts-capability]')].some((field) => !field.hidden);
  setHidden(document.getElementById('danmuReadAdvancedSection'), !anyVisible);
  const customVoice = document.getElementById('danmuReadCustomVoiceWrap');
  setHidden(customVoice, capabilities.custom_voice_id !== true);
  updateDanmuReadStyleHint(model);
}

function handleDanmuReadProviderChange() {
  captureDanmuReadCredentialDraft();
  renderDanmuReadProviderCards();
  const provider = currentDanmuReadProvider();
  const modelId = document.getElementById('danmuReadModelSelect')?.value || provider?.models?.find((model) => model.recommended)?.id || '';
  populateDanmuReadModelSelect(provider?.id, modelId);
  renderDanmuReadCredentials();
  handleDanmuReadModelChange();
}

function populateDanmuReadModelSelect(providerId, selectedModelId) {
  const modelSelect = document.getElementById('danmuReadModelSelect');
  if (!modelSelect) return;
  const provider = getDanmuReadCatalogProvider(providerId);
  const selected = selectedModelId || provider?.models?.find((model) => model.recommended)?.id || provider?.models?.[0]?.id || '';
  modelSelect.replaceChildren();
  (provider?.models || []).forEach((model) => modelSelect.appendChild(new Option(model.label || model.id, model.id)));
  if (selected && [...modelSelect.options].some((option) => option.value === selected)) modelSelect.value = selected;
  else if (modelSelect.options.length) modelSelect.selectedIndex = 0;
  renderDanmuReadModelCards();
}

function handleDanmuReadModelChange() {
  const provider = currentDanmuReadProvider();
  const model = currentDanmuReadModel();
  const voice = document.getElementById('danmuReadVoice')?.value || '';
  renderDanmuReadModelCards();
  populateDanmuReadVoiceSelect(provider?.id, model?.id, voice);
  syncDanmuReadCapabilities();
}

function collectDanmuReadCredentials() {
  captureDanmuReadCredentialDraft();
  const provider = currentDanmuReadProvider();
  const credentials = {};
  credentialFieldsFor(provider).forEach((field) => {
    const value = danmuReadCredentialDrafts[provider?.id]?.[field.id] ?? document.getElementById(`danmuReadCredential-${field.id}`)?.value ?? '';
    if (value && !isDanmuReadMasked(value)) credentials[field.id] = value.trim();
  });
  return credentials;
}

function collectDanmuReadCustomPayload(voiceOverride = null) {
  const provider = currentDanmuReadProvider();
  const model = currentDanmuReadModel();
  const capabilities = model?.capabilities || {};
  const customVoice = capabilities.custom_voice_id === true
    ? document.getElementById('danmuReadCustomVoice')?.value?.trim()
    : '';
  const voice = voiceOverride ?? customVoice ?? document.getElementById('danmuReadVoice')?.value ?? '';
  const body = { provider: provider?.wire_id || provider?.id || '', model_id: model?.id || '', voice, credentials: collectDanmuReadCredentials() };
  const legacyKey = body.credentials.api_key;
  if (legacyKey) body.api_key = legacyKey;
  document.querySelectorAll('#danmuReadAdvancedFields [data-tts-field]').forEach((field) => {
    const capabilityWrap = field.closest('[data-tts-capability]');
    if (field.hidden || capabilityWrap?.hidden || !field.id) return;
    const key = field.dataset.ttsField;
    if (!key) return;
    body[key] = field.type === 'number' ? (field.value === '' ? null : Number(field.value)) : field.value;
  });
  return body;
}

function validateDanmuReadCustomFields(payload) {
  if (!payload.provider || !payload.model_id) {
    showToast(t('settings.text.请选择语音服务和模型'), true);
    return false;
  }
  return true;
}

function applyDanmuReadForm(cfg, { preserveDraft = false } = {}) {
  danmuReadConfigCache = cfg || {};
  if (!preserveDraft) {
    danmuReadCredentialDrafts = {};
    danmuReadSavedCredentials = {};
  }
  const enabledEl = document.getElementById('danmuReadEnabled');
  const intervalEl = document.getElementById('danmuReadInterval');
  const styleEl = document.getElementById('danmuReadStylePrompt');
  const providerEl = document.getElementById('danmuReadProvider');
  if (enabledEl) enabledEl.checked = Boolean(cfg?.enabled);
  if (intervalEl) intervalEl.value = String(cfg?.interval_sec ?? 15);
  if (styleEl) styleEl.value = cfg?.style_prompt || '';
  const storedProvider = danmuReadCanonicalProviderId(cfg?.provider || 'mimo');
  const provider = getDanmuReadCatalogProvider(storedProvider) || getDanmuReadCatalogProvider('mimo');
  if (providerEl) providerEl.value = provider?.wire_id || provider?.id || '';
  const rawCredentials = cfg?.credentials || cfg?.provider_credentials || cfg?.auth || {};
  danmuReadSavedCredentials[provider?.id || storedProvider] = { ...(rawCredentials || {}) };
  if (cfg?.api_key) danmuReadSavedCredentials[provider?.id || storedProvider].api_key = cfg.api_key;
  renderDanmuReadProviderCards();
  renderDanmuReadCredentials();
  populateDanmuReadModelSelect(provider?.id, cfg?.model_id || cfg?.model || '');
  const selectedVoice = cfg?.voice || '';
  document.querySelectorAll('[data-tts-field]').forEach((field) => {
    const value = cfg?.[field.dataset.ttsField] ?? cfg?.advanced?.[field.dataset.ttsField];
    if (value != null) field.value = value;
  });
  handleDanmuReadModelChange();
  const voiceEl = document.getElementById('danmuReadVoice');
  if (voiceEl && selectedVoice && [...voiceEl.options].some((option) => option.value === selectedVoice)) voiceEl.value = selectedVoice;
  renderDanmuReadVoiceList();
}

async function ensureDanmuReadCatalog() {
  if (danmuReadCatalog) return danmuReadCatalog;
  try {
    danmuReadCatalog = normalizeDanmuReadCatalog(await apiFetch('/api/danmu-read/catalog'));
  } catch {
    danmuReadCatalog = normalizeDanmuReadCatalog(null);
  }
  return danmuReadCatalog;
}

async function loadDanmuReadPage() {
  invalidateDanmuReadCache();
  try {
    await ensureDanmuReadCatalog();
    const cfg = await apiFetch('/api/danmu-read/config');
    applyDanmuReadForm(cfg);
    const status = document.getElementById('danmuReadStatus');
    if (status) status.textContent = '';
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error ?? 'unknown');
    showToast(t('dynamic.app.读弹幕页加载失败_message'), true);
    throw error;
  }
}

async function saveDanmuReadSettings() {
  const customPayload = collectDanmuReadCustomPayload();
  if (!validateDanmuReadCustomFields(customPayload)) return;
  const body = {
    enabled: Boolean(document.getElementById('danmuReadEnabled')?.checked),
    interval_sec: parseInt(document.getElementById('danmuReadInterval')?.value, 10) || 15,
    voice: customPayload.voice || '',
    style_prompt: document.getElementById('danmuReadStylePrompt')?.value || '',
    ...customPayload,
  };
  const cfg = await apiFetch('/api/danmu-read/config', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  applyDanmuReadForm(cfg, { preserveDraft: true });
}
window.saveDanmuReadSettings = saveDanmuReadSettings;

async function probeDanmuRead(voiceOverride = null) {
  const customPayload = collectDanmuReadCustomPayload(voiceOverride);
  if (!validateDanmuReadCustomFields(customPayload)) return;
  const status = document.getElementById('danmuReadStatus');
  if (status) status.textContent = t('settings.text.试听处理中');
  const body = { ...customPayload };
  const result = await apiFetch('/api/danmu-read/probe', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (status) status.textContent = result.message || (result.ok ? t('settings.text.试听成功') : t('settings.text.试听失败'));
  showToast(result.message || (result.ok ? t('dynamic.app.试听已开始') : t('dynamic.app.试听失败')), !result.ok);
  if (result.ok && !document.getElementById('danmuReadEnabled')?.checked) {
    showToast(t('dynamic.app.未勾选_启用读弹幕_定时朗读不会启动_请勾选后'), true);
  }
}

function initDanmuReadPage() {
  ensureDanmuReadCatalog().catch((error) => recordBootstrapFailure('danmu-read-catalog', error));
  document
    .getElementById('danmuReadProvider')
    ?.addEventListener('change', handleDanmuReadProviderChange);
  document
    .getElementById('danmuReadModelSelect')
    ?.addEventListener('change', handleDanmuReadModelChange);
  document.getElementById('danmuReadVoiceSearch')?.addEventListener('input', renderDanmuReadVoiceList);
  document.getElementById('btnDanmuReadVoiceRefresh')?.addEventListener('click', (event) => {
    withLoadingState(event.currentTarget, event.currentTarget.textContent, () => refreshDanmuReadVoices(true)).catch((error) => showToast(error.message, true));
  });
  document.querySelectorAll('[data-style-prompt]').forEach((chip) => chip.addEventListener('click', () => {
    const style = document.getElementById('danmuReadStylePrompt');
    if (style) style.value = chip.dataset.stylePrompt || '';
  }));
  document.getElementById('btnDanmuReadProbe')?.addEventListener('click', (e) => {
    const btn = e.currentTarget;
    withLoadingState(btn, btn.textContent, () =>
      probeDanmuRead()
    ).catch((error) => {
      const status = document.getElementById('danmuReadStatus');
      if (status) status.textContent = '';
      showToast(error.message, true);
    });
  });
  ensureDanmuReadCatalog().then(() => {
    renderDanmuReadProviderCards();
    handleDanmuReadProviderChange();
  });
}

function navigate(page) {
  if (page === 'danmu-read') {
    page = 'settings';
    switchSettingsTab('danmu-read');
  }
  if (
    page === 'tutorial' ||
    page === 'logs' ||
    page === 'mic-logs' ||
    page === 'announcements' ||
    page === 'feedback' ||
    page === 'live-output' ||
    page === 'live-settings'
  ) {
    if (page === 'live-settings') {
      page = 'live-output';
    }
    switchGuideTab(page);
    page = 'guide';
  }
  if (page === 'guide') {
    switchGuideTab(getActiveGuideTabId());
  }
  document.querySelectorAll('.page-panel').forEach((panel) => panel.classList.remove('active'));
  document.querySelectorAll('#nav .sidebar-item').forEach((item) => item.classList.remove('active'));
  const panel = document.getElementById(`page-${page}`);
  if (panel) panel.classList.add('active');
  const btn = document.querySelector(`#nav [data-page="${page}"]`);
  if (btn) btn.classList.add('active');
  // 保持 hash 与当前页一致，支持刷新深链接
  try {
    const desired = `#${page}`;
    if ((location.hash || '') !== desired) {
      history.replaceState(null, '', desired);
    }
  } catch {
    /* ignore */
  }
  closeShellNavIfDrawer();

  if (page === 'settings') {
    void runBootstrapTask('config', reloadConfigFromServer);
    void runBootstrapTask('screens', loadScreens);
    void runBootstrapTask('custom-models', loadCustomModels);
    if (getActiveSettingsTabId() === 'danmu-read') {
      void runBootstrapTask('danmu-read', loadDanmuReadPage);
    }
  }
  if (page === 'overview') void runBootstrapTask('overview', loadOverviewGlobalFields);
  if (page === 'persona') loadPersonaEditor().catch(console.error);
  if (page === 'danmu-pool') {
    ensureDanmuPoolPages()
      .then(({ poolMod, memeMod }) =>
        Promise.all([memeMod.loadMemeBarragePage(), poolMod.loadDanmuPoolPage()]).then(
          () => memeMod.startMemeBarrageMetaPolling(),
        ),
      )
      .catch((error) => showToast(error.message, true));
  } else {
    import('./modules/app-meme-barrage-page.js')
      .then((mod) => mod.stopMemeBarrageMetaPolling())
      .catch(() => {});
  }
  if (page === 'pet') {
    ensurePetPage()
      .then((mod) => mod.loadPetPage())
      .catch((error) => showToast(error.message, true));
  }
  if (page === 'knowledge') {
    ensureKnowledgePage()
      .then((mod) => mod.loadKnowledgePage())
      .catch((error) => showToast(error.message, true));
  } else {
    import('./modules/app-knowledge-page.js')
      .then((mod) => mod.stopKnowledgeJobPolling())
      .catch(() => {});
  }
  if (page === 'style-generator') {
    ensureStyleGeneratorPage()
      .then((mod) => mod.loadStyleGeneratorPage())
      .catch((error) => showToast(error.message, true));
  }
  if (page === 'guide') {
    const activeTab = getActiveGuideTabId();
    if (activeTab === 'logs') {
      updateLogPanelState();
      if (!logClosed) {
        renderLogView({ force: true });
        bootstrapLogsFromServer(REALTIME.lastLogsPollTs).catch((error) => {
          console.warn('[realtime] logs bootstrap on navigate failed', error);
        });
      }
    } else if (activeTab === 'mic-logs') {
      onMicLogsTabActivated();
    } else if (activeTab === 'tutorial') {
      import('./modules/content-tutorial.js')
        .then((mod) => mod.loadTutorialPage())
        .catch(console.error);
    } else if (activeTab === 'announcements') {
      stopAnnouncementsBadgePolling();
      updateAnnouncementsNavBadge(false);
      loadAnnouncementsPage().catch((error) => showToast(error.message, true));
    } else if (activeTab === 'feedback') {
      import('./modules/content-feedback.js')
        .then((mod) => mod.initFeedbackPage())
        .catch(console.error);
    } else if (activeTab === 'live-output') {
      refreshLiveOverlayStatus();
    }
  } else {
    startAnnouncementsBadgePolling();
  }
}

function bindCoreInteractions() {
  initErrorReporting({ showToast, getLastStatus: getLastAppliedStatus });
  initProblemDialog({
    showToast,
    navigate,
    switchSettingsTab,
    openErrorReport: (problem, options) =>
      openErrorReportModalFromProblem(problem, {
        ...options,
        statusSnapshot: getLastAppliedStatus(),
      }),
    retryProblemAction: async () => {
      showToast(t('dynamic.problem.action.retry'), false);
    },
    getLastStatus: getLastAppliedStatus,
    isFeedbackSubmitting: () => false,
    probeConnection: async () => {
      navigate('settings');
      switchSettingsTab('api');
    },
  });
  initLiveOverlayPanel({ showToast });
  initPersonaTopicPage({ showToast });

  configureStatus({
    applyCaptureRegion: applyCaptureRegionFromPayload,
    onProblemShow: maybeShowProblem,
    onProblemOccurrenceUpdate: updateVisibleProblemOccurrence,
  });
  setRealtimeHandlers({
    onStatus: (status) => {
      applyStatus(status);
    },
    onLog: appendLog,
    onLogBatch: mergeLogItems,
    updateLogPanelState,
    showToast,
    bootstrapLogs: bootstrapLogsFromServer,
  });

  initSettingsTabs();
  initGuideTabs();
  initMicLogsPage({ showToast });
  initSettingsFieldHints();
  initContentPageFieldHints();
  initSidebarNavFloatingHints();
  initNormalBatchControls();
  initRestoreDefaultsControls();
  initRenderModeControls();

  bindSettingsControls({
    showToast,
    navigate,
    onConfigSaved: () => {
      if (document.getElementById('personaSelect')?.value) {
        void runBootstrapTask('persona-template', loadPersonaTemplate);
      }
    },
    onSettingsTabSwitch: (tabId) => {
      if (tabId === 'danmu-read') {
        void runBootstrapTask('danmu-read', loadDanmuReadPage);
      }
    },
  });
  initNumberSteppers(document);
  configureGuideTabs({
    onGuideTabSwitch: (tabId) => {
      if (tabId === 'logs') {
        updateLogPanelState();
        if (!logClosed) {
          renderLogView({ force: true });
          bootstrapLogsFromServer(REALTIME.lastLogsPollTs).catch((error) => {
            console.warn('[realtime] logs bootstrap on tab switch failed', error);
          });
        }
      } else if (tabId === 'mic-logs') {
        onMicLogsTabActivated();
      } else if (tabId === 'tutorial') {
        import('./modules/content-tutorial.js')
          .then((mod) => mod.loadTutorialPage())
          .catch(console.error);
      } else if (tabId === 'live-output') {
        refreshLiveOverlayStatus();
      }
    },
  });
  bindContentPageControls({ showToast, navigate });

  document.querySelectorAll('.sidebar-nav-hint').forEach((btn) => {
    btn.addEventListener('click', (event) => event.stopPropagation());
  });
  document.getElementById('btnGoAnnouncements')?.addEventListener('click', () => {
    navigate('announcements');
  });
  document.getElementById('btnGoDanmuLogs')?.addEventListener('click', () => {
    navigateToDanmuLogs(navigate);
  });
  document.getElementById('btnGoMicLogs')?.addEventListener('click', () => {
    navigateToMicLogs(navigate);
  });

  document.querySelectorAll('#nav [data-page]').forEach((el) => {
    el.addEventListener('click', (event) => {
      event.preventDefault();
      navigate(el.dataset.page);
    });
  });
  initResponsiveShell();

  document.querySelectorAll('.log-level-cb').forEach((cb) => {
    cb.addEventListener('change', () => {
      replaceLogLevelFilters(
        new Set([...document.querySelectorAll('.log-level-cb:checked')].map((item) => item.value)),
      );
      renderLogView({ force: true });
    });
  });
  document.getElementById('logAutoScroll')?.addEventListener('change', (event) => {
    setLogAutoScroll(event.target.checked);
  });
  document.getElementById('btnCopyLogs')?.addEventListener('click', () => {
    const text = logBuffer
      .filter((item) => logLevelFilters.has(item.level))
      .map((item) => `[${item.level}] ${item.message}`)
      .join('\n');
    navigator.clipboard.writeText(text).then(() => showToast(t('common.copied')));
  });
  document.getElementById('btnClearLogs')?.addEventListener('click', () => {
    clearLogBuffer();
    document.getElementById('logView').innerHTML = '';
    updateLogPanelState();
    showToast(t('dynamic.app.日志视图已清空'));
  });
  document.getElementById('btnCloseLogs')?.addEventListener('click', () => {
    if (logClosed) {
      reopenLogView();
      showToast(t('dynamic.app.日志已重新打开'));
    } else {
      closeLogView();
      showToast(t('dynamic.app.日志已关闭'));
    }
  });
  updateLogPanelState();

  document.getElementById('btnToggle').addEventListener('click', async () => {
    try {
      const running = getLastAppliedStatus()?.running ?? false;
      if (running) {
        await apiFetch('/api/stop', { method: 'POST' });
        showToast(t('dynamic.app.小助手已休息'));
      } else {
        await apiFetch('/api/start', { method: 'POST' });
        showToast(t('dynamic.app.弹幕生成已开启'));
      }
    } catch (error) {
      showToast(error.message || t('dynamic.app.小助手遇到了一点问题'), true);
    }
  });
}

async function init() {
  let i18nError = null;
  try {
    await bootstrapI18n();
  } catch (error) {
    i18nError = error;
    console.warn('[bootstrap] i18n bootstrap failed; continuing with fallback text', error);
  }

  initTheme();
  initLanguage({ showToast });
  bindCoreInteractions();
  if (i18nError) recordBootstrapFailure('i18n', i18nError);

  try {
    await refreshSession();
  } catch (error) {
    recordBootstrapFailure('session', error);
    applyI18n();
    return;
  }

  await Promise.all([
    ['announcements', loadAnnouncementsReadState],
    ['model-catalog', loadModelCatalog],
    ['providers', loadProviders],
    ['config-defaults', loadConfigDefaults],
  ].map(([label, task]) => runBootstrapTask(label, task)));

  const [cfg] = await Promise.all([
    runBootstrapTask('config', reloadConfigFromServer),
    runBootstrapTask('screens', loadScreens),
  ]);
  if (cfg) {
    window.__danmuaiConfig = cfg;
    if (cfg.screen_index !== undefined) {
      document.getElementById('screen_index').value = String(cfg.screen_index);
    }
  }

  void runBootstrapTask('overview', loadOverviewGlobalFields);
  initAppUpdateModal({ showToast });

  const statusPromise = runBootstrapTask('status', async () => {
    const status = await fetchBootstrapStatus();
    applyStatus(status);
    return status;
  });
  startRealtimeTransport();
  await statusPromise;

  initDanmuReadPage();
  void runBootstrapTask('danmu-read', loadDanmuReadPage);
  initCaptureRegionControls();

  const hash = (location.hash || '').replace('#', '');
  if (hash) navigate(hash);

  const onAnnouncements = document
    .getElementById('page-announcements')
    ?.classList.contains('active');
  if (!onAnnouncements) {
    startAnnouncementsBadgePolling();
  }

  await Promise.all([
    runBootstrapTask('announcement-badge', refreshAnnouncementsUnreadBadge),
    runBootstrapTask('app-update', initAppVersionAndUpdateCheck),
  ]);

  // Re-apply after init* hooks that touch static DOM (hints, tabs, etc.)
  applyI18n();
  renderBootstrapErrors();
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible' || !API.base) return;
  refreshSession()
    .then(() => {
      REALTIME.statusAttempt = 0;
      REALTIME.logsAttempt = 0;
      startRealtimeTransport();
      return bootstrapLogsFromServer(0);
    })
    .catch((error) => console.warn('[realtime] visibility refresh failed', error));
});

window.addEventListener('pagehide', () => {
  stopRealtimeTransport();
  import('./modules/app-meme-barrage-page.js')
    .then((mod) => mod.stopMemeBarrageMetaPolling())
    .catch(() => {});
  import('./modules/app-knowledge-page.js')
    .then((mod) => mod.stopKnowledgeJobPolling())
    .catch(() => {});
  stopAnnouncementsBadgePolling();
});

init().catch((error) => {
  console.error(error);
  recordBootstrapFailure('init', error);
});
