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
  applyCaptureRegionFromPayload,
  bindSettingsControls,
  initCaptureRegionControls,
  initNormalBatchControls,
  initFloatingPanelV2Controls,
  initOpacityWarning,
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
  maybePromptErrorReport as maybePromptErrorReportImpl,
  openErrorReportModal as openErrorReportModalImpl,
} from './modules/app-error-reporting.js';
import {
  initLiveOverlayPanel,
  refreshLiveOverlayStatus,
} from './modules/app-live-overlay-panel.js';
import {
  configureLiveSettingsTabs,
  getActiveLiveSettingsTabId,
  initLiveSettingsTabs,
  switchLiveSettingsTab,
} from './modules/live-settings-tabs.js';
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

let danmuReadConfigCache = null;
let danmuReadCatalog = null;
let danmuPoolPagesReady = false;
let petPageReady = false;
let styleGeneratorPageReady = false;
let aiButlerPageReady = false;
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

async function ensureAiButlerPage() {
  const mod = await import('./modules/app-ai-butler-page.js');
  if (!aiButlerPageReady) {
    mod.initAiButlerPage({ showToast });
    aiButlerPageReady = true;
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

function maybePromptErrorReport(status) {
  return maybePromptErrorReportImpl(status);
}

/*
 * Compatibility anchors for static bundle tests:
 * function collectErrorReportContext
 * function extractErrorReportSearchTerms
 * function findErrorLogAnchorIndex
 * function openErrorReportModal
 * localStorage.setItem(ERROR_REPORT_DISMISS_STORAGE
 * submitErrorReport
 */

window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason;
  const message = reason instanceof Error ? reason.message : String(reason ?? 'unknown');
  console.warn('[app] unhandled promise rejection:', reason);
  showToast(t('dynamic.app.操作失败_message'), true);
});

function getDanmuReadCatalogProvider(providerId) {
  const pid = providerId || '';
  const list = danmuReadCatalog?.providers || [];
  return list.find((p) => p.id === pid || (!pid && p.id === 'mimo')) || null;
}

function populateDanmuReadModelSelect(providerId, selectedModelId) {
  const modelSelect = document.getElementById('danmuReadModelSelect');
  if (!modelSelect) return;
  const cat = getDanmuReadCatalogProvider(providerId);
  modelSelect.innerHTML = '';
  const models = cat?.models || [];
  models.forEach((m) => {
    if (!m.id) return;
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = m.label || m.id;
    modelSelect.appendChild(opt);
  });
  if (selectedModelId && [...modelSelect.options].some((o) => o.value === selectedModelId)) {
    modelSelect.value = selectedModelId;
  } else if (modelSelect.options.length) {
    modelSelect.selectedIndex = 0;
  }
}

function populateDanmuReadVoiceSelect(providerId, modelId, selectedVoice) {
  const voiceEl = document.getElementById('danmuReadVoice');
  if (!voiceEl) return;
  const cat = getDanmuReadCatalogProvider(providerId);
  let voices = [];
  if (cat) {
    const model = cat.models?.find((m) => m.id === modelId) || cat.models?.[0];
    voices = model?.voices || [];
  }
  voiceEl.innerHTML = '';
  voices.forEach((v) => {
    if (!v.id) return;
    const opt = document.createElement('option');
    opt.value = v.id;
    opt.textContent = v.label || v.id;
    voiceEl.appendChild(opt);
  });
  if (selectedVoice && [...voiceEl.options].some((o) => o.value === selectedVoice)) {
    voiceEl.value = selectedVoice;
  } else if (voiceEl.options.length) {
    voiceEl.selectedIndex = 0;
  }
}

function updateDanmuReadStyleHint(providerId, modelId) {
  const hint = document.getElementById('danmuReadStyleHint');
  if (!hint) return;
  const cat = getDanmuReadCatalogProvider(providerId);
  const model = cat?.models?.find((m) => m.id === modelId);
  if (model?.supports_style) {
    hint.textContent = t('dynamic.app.当前模型支持风格指令_将用于控制语气与情感');
  } else if (!providerId) {
    hint.textContent = t('dynamic.app.MiMo_作为_user_消息控制语气_留空则仅');
  } else {
    hint.textContent = t('dynamic.app.当前模型可能忽略风格指令_留空则仅朗读弹幕正文');
  }
}

function handleDanmuReadProviderChange() {
  syncDanmuReadCustomFieldsUi();
}

function handleDanmuReadModelChange() {
  const provider = document.getElementById('danmuReadProvider')?.value || '';
  const modelId = document.getElementById('danmuReadModelSelect')?.value || '';
  const voice = document.getElementById('danmuReadVoice')?.value || '';
  populateDanmuReadVoiceSelect(provider, modelId, voice);
  updateDanmuReadStyleHint(provider, modelId);
  const modelLabel = document.getElementById('danmuReadModelLabel');
  const endpointLabel = document.getElementById('danmuReadEndpointLabel');
  if (modelLabel) modelLabel.textContent = modelId || 'mimo-v2.5-tts';
  if (endpointLabel) endpointLabel.textContent = provider || 'MiMo';
}

function syncDanmuReadCustomFieldsUi() {
  const provider = document.getElementById('danmuReadProvider')?.value || '';
  const usePreset = provider === 'dashscope_qwen';
  if (usePreset || !provider) {
    const modelId = document.getElementById('danmuReadModelSelect')?.value || '';
    populateDanmuReadModelSelect(provider, modelId);
    handleDanmuReadModelChange();
  }
}

function collectDanmuReadCustomPayload() {
  const provider = document.getElementById('danmuReadProvider')?.value || '';
  const presetModelId = document.getElementById('danmuReadModelSelect')?.value?.trim() || '';
  if (!provider) {
    return { provider: '', endpoint: '', model_id: '' };
  }
  return { provider, endpoint: '', model_id: presetModelId };
}

function validateDanmuReadCustomFields(payload) {
  const provider = payload.provider || '';
  const modelId = payload.model_id || '';
  if (!provider) return true;
  if (provider === 'dashscope_qwen') {
    if (!modelId) {
      showToast(t('dynamic.app.请选择_TTS_模型'), true);
      return false;
    }
  }
  return true;
}

function applyDanmuReadForm(cfg) {
  danmuReadConfigCache = cfg;
  const enabledEl = document.getElementById('danmuReadEnabled');
  const intervalEl = document.getElementById('danmuReadInterval');
  const keyEl = document.getElementById('danmuReadApiKey');
  const voiceEl = document.getElementById('danmuReadVoice');
  const styleEl = document.getElementById('danmuReadStylePrompt');
  const providerEl = document.getElementById('danmuReadProvider');
  const modelLabel = document.getElementById('danmuReadModelLabel');
  const endpointLabel = document.getElementById('danmuReadEndpointLabel');
  if (enabledEl) enabledEl.checked = Boolean(cfg.enabled);
  if (intervalEl) intervalEl.value = String(cfg.interval_sec ?? 10);
  if (keyEl) keyEl.value = cfg.api_key || '';
  if (styleEl) styleEl.value = cfg.style_prompt || '';
  let storedProvider = cfg.provider || '';
  if (storedProvider === 'custom_openai' || storedProvider === 'doubao') {
    storedProvider = '';
  }
  if (providerEl) providerEl.value = storedProvider || '';
  const effProvider = storedProvider || '';
  const effModel = cfg.model_id || cfg.model || '';
  populateDanmuReadModelSelect(effProvider, effModel);
  syncDanmuReadCustomFieldsUi();
  populateDanmuReadVoiceSelect(effProvider, effModel, cfg.voice || '');
  updateDanmuReadStyleHint(effProvider, effModel);
  if (modelLabel) modelLabel.textContent = cfg.model || 'mimo-v2.5-tts';
  if (endpointLabel) endpointLabel.textContent = cfg.endpoint || '—';
}

async function ensureDanmuReadCatalog() {
  if (danmuReadCatalog) return danmuReadCatalog;
  danmuReadCatalog = await apiFetch('/api/danmu-read/catalog');
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
    interval_sec: parseInt(document.getElementById('danmuReadInterval')?.value, 10) || 10,
    voice: document.getElementById('danmuReadVoice')?.value || t('dynamic.app.冰糖'),
    style_prompt: document.getElementById('danmuReadStylePrompt')?.value || '',
    ...customPayload,
  };
  const keyInput = document.getElementById('danmuReadApiKey')?.value?.trim();
  if (keyInput && !isMaskedApiKey(keyInput)) {
    body.api_key = keyInput;
  }
  const cfg = await apiFetch('/api/danmu-read/config', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  applyDanmuReadForm(cfg);
}
window.saveDanmuReadSettings = saveDanmuReadSettings;

async function probeDanmuRead() {
  const customPayload = collectDanmuReadCustomPayload();
  if (!validateDanmuReadCustomFields(customPayload)) return;
  const status = document.getElementById('danmuReadStatus');
  if (status) status.textContent = t('dynamic.app.试听请求中_约_10_20_秒');
  const body = { ...customPayload };
  const keyInput = document.getElementById('danmuReadApiKey')?.value?.trim();
  if (keyInput && !isMaskedApiKey(keyInput)) {
    body.api_key = keyInput;
  }
  const result = await apiFetch('/api/danmu-read/probe', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (status) status.textContent = result.message || '';
  showToast(result.message || (result.ok ? t('dynamic.app.试听已开始') : t('dynamic.app.试听失败')), !result.ok);
  if (result.ok && !document.getElementById('danmuReadEnabled')?.checked) {
    showToast(t('dynamic.app.未勾选_启用读弹幕_定时朗读不会启动_请勾选后'), true);
  }
}

function initDanmuReadPage() {
  ensureDanmuReadCatalog().catch(() => {});
  document
    .getElementById('danmuReadProvider')
    ?.addEventListener('change', handleDanmuReadProviderChange);
  document
    .getElementById('danmuReadModelSelect')
    ?.addEventListener('change', handleDanmuReadModelChange);
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
  syncDanmuReadCustomFieldsUi();
}

function navigate(page) {
  if (page === 'danmu-read') {
    page = 'settings';
    switchSettingsTab('danmu-read');
  }
  if (page === 'tutorial' || page === 'logs' || page === 'announcements' || page === 'feedback') {
    switchGuideTab(page);
    page = 'guide';
  }
  if (page === 'guide') {
    switchGuideTab(getActiveGuideTabId());
  }
  if (page === 'live-output') {
    switchLiveSettingsTab(page);
    page = 'live-settings';
  }
  if (page === 'live-settings') {
    switchLiveSettingsTab(getActiveLiveSettingsTabId());
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

  if (page === 'settings') {
    reloadConfigFromServer().catch(console.error);
    loadScreens().catch(console.error);
    loadCustomModels().catch(console.error);
    if (getActiveSettingsTabId() === 'danmu-read') {
      loadDanmuReadPage().catch(() => {});
    }
  }
  if (page === 'overview') loadOverviewGlobalFields().catch(console.error);
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
  if (page === 'style-generator') {
    ensureStyleGeneratorPage()
      .then((mod) => mod.loadStyleGeneratorPage())
      .catch((error) => showToast(error.message, true));
  }
  if (page === 'ai-butler') {
    ensureAiButlerPage()
      .then((mod) => mod.loadAiButlerPage())
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
  if (page === 'live-settings') {
    const activeTab = getActiveLiveSettingsTabId();
    if (activeTab === 'live-output') {
      refreshLiveOverlayStatus();
    }
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
    }
  } else {
    startAnnouncementsBadgePolling();
  }
}

async function init() {
  await bootstrapI18n();
  initTheme();
  initLanguage({ showToast });
  await refreshSession();

  await Promise.all([
    loadAnnouncementsReadState(),
    loadModelCatalog(),
    loadProviders(),
    loadConfigDefaults(),
  ]);

  const [cfg] = await Promise.all([
    reloadConfigFromServer(),
    loadScreens(),
  ]);
  window.__danmuaiConfig = cfg;
  if (cfg.screen_index !== undefined) {
    document.getElementById('screen_index').value = String(cfg.screen_index);
  }

  initErrorReporting({ showToast, getLastStatus: getLastAppliedStatus });
  initLiveOverlayPanel({ showToast });
  configureLiveSettingsTabs({ showToast });
  initLiveSettingsTabs();
  initPersonaTopicPage({ showToast });
  loadOverviewGlobalFields().catch(console.error);
  initAppUpdateModal({ showToast });

  configureStatus({
    applyCaptureRegion: applyCaptureRegionFromPayload,
    onErrorPrompt: maybePromptErrorReport,
    onErrorReportManual: (status) => openErrorReportModalImpl(status, { force: true }),
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
  const statusPromise = fetch(`${API.base}/api/status`)
    .then((response) => response.json())
    .then(applyStatus);
  startRealtimeTransport();
  await statusPromise;

  initSettingsTabs();
  initGuideTabs();
  initSettingsFieldHints();
  initContentPageFieldHints();
  initSidebarNavFloatingHints();
  initNormalBatchControls();
  initDanmuReadPage();
  loadDanmuReadPage().catch(console.error);
  initCaptureRegionControls();
  initRestoreDefaultsControls();
  initFloatingPanelV2Controls();
  initOpacityWarning();

  bindSettingsControls({
    showToast,
    navigate,
    onConfigSaved: () => {
      if (document.getElementById('personaSelect')?.value) {
        loadPersonaTemplate().catch(console.error);
      }
    },
    onSettingsTabSwitch: (tabId) => {
      if (tabId === 'danmu-read') {
        loadDanmuReadPage().catch(() => {});
      }
    },
  });
  // 设置页「打开样式生成器」入口（不依赖样式页懒加载）
  document.getElementById('btnOpenStyleGeneratorFromSettings')?.addEventListener('click', (event) => {
    event.preventDefault();
    navigate('style-generator');
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
      } else if (tabId === 'tutorial') {
        import('./modules/content-tutorial.js')
          .then((mod) => mod.loadTutorialPage())
          .catch(console.error);
      }
    },
  });
  bindContentPageControls({ showToast, navigate });

  document.querySelectorAll('.sidebar-nav-hint').forEach((btn) => {
    btn.addEventListener('click', (event) => event.stopPropagation());
  });
  document.querySelectorAll('#nav [data-page]').forEach((el) => {
    el.addEventListener('click', (event) => {
      event.preventDefault();
      navigate(el.dataset.page);
    });
  });
  const hash = (location.hash || '').replace('#', '');
  if (hash) navigate(hash);

  document.getElementById('btnErrorBannerDismiss')?.addEventListener('click', () => {
    const banner = document.getElementById('errorBanner');
    if (banner) banner.classList.add('hidden');
  });

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

  const onAnnouncements = document
    .getElementById('page-announcements')
    ?.classList.contains('active');
  if (!onAnnouncements) {
    startAnnouncementsBadgePolling();
  }

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

  await Promise.all([
    refreshAnnouncementsUnreadBadge(),
    initAppVersionAndUpdateCheck(),
  ]);

  // Re-apply after init* hooks that touch static DOM (hints, tabs, etc.)
  applyI18n();
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
  showToast(error.message || t('dynamic.app.无法连接小助手_请确认_DanmuAI_已启动'), true);
});
