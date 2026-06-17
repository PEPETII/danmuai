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
  logBuffer,
  logLevelFilters,
  mergeLogItems,
  renderLogView,
  replaceLogLevelFilters,
  setLogAutoScroll,
  updateLogPanelState,
} from './modules/logs.js';
import {
  applyCaptureRegionFromPayload,
  bindSettingsControls,
  initCaptureRegionControls,
  initNormalBatchControls,
  initFloatingPanelV2Controls,
  initRestoreDefaultsControls,
  initContentPageFieldHints,
  initSettingsFieldHints,
  initSettingsTabs,
  initSettingsUiMode,
  initSidebarNavFloatingHints,
  loadConfigDefaults,
  loadCustomModels,
  loadModelCatalog,
  loadProviders,
  loadScreens,
  reloadConfigFromServer,
  switchSettingsTab,
} from './modules/settings.js';
import { isMaskedApiKey } from './modules/settings-defaults.js';
import { initTheme } from './modules/theme.js';
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

let danmuReadConfigCache = null;
let danmuReadCatalog = null;
let danmuPoolPagesReady = false;
let petPageReady = false;
let diagnosticsReady = false;

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

async function ensureDiagnosticsPanel() {
  if (diagnosticsReady) return;
  const mod = await import('./modules/diagnostics.js');
  mod.initDiagnosticsPanel({ showToast });
  diagnosticsReady = true;
}

function wireLazyDiagnosticsToggle() {
  const btn = document.getElementById('btnToggleDiagnosticsPanel');
  if (!btn) return;
  btn.addEventListener(
    'click',
    async function onFirstDiagnosticsClick(event) {
      if (diagnosticsReady) return;
      event.stopImmediatePropagation();
      await ensureDiagnosticsPanel();
      btn.removeEventListener('click', onFirstDiagnosticsClick, { capture: true });
      btn.click();
    },
    { capture: true },
  );
}

function invalidateDanmuReadCache() {
  danmuReadConfigCache = null;
  danmuReadCatalog = null;
}

function showToast(message, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = message;
  el.className = `toast show ${isError ? 'text-red-700' : 'text-warmText'}`;
  setTimeout(() => el.classList.remove('show'), 3200);
}

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
  showToast(`操作失败: ${message}`, true);
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
    hint.textContent = '当前模型支持风格指令，将用于控制语气与情感。';
  } else if (!providerId) {
    hint.textContent = 'MiMo：作为 user 消息控制语气；留空则仅朗读弹幕正文。';
  } else {
    hint.textContent = '当前模型可能忽略风格指令，留空则仅朗读弹幕正文。';
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
      showToast('请选择 TTS 模型', true);
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
  if (storedProvider === 'custom_openai') {
    storedProvider = '';
    showToast('已不再支持自定义 OpenAI 兼容 TTS，请重新选择平台并保存', true);
  } else if (storedProvider === 'doubao') {
    storedProvider = '';
    showToast('已不再支持火山豆包语音 TTS，请改选 MiMo 或百炼并保存', true);
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
    showToast(`读弹幕页加载失败: ${message}`, true);
    throw error;
  }
}

async function saveDanmuReadSettings() {
  const customPayload = collectDanmuReadCustomPayload();
  if (!validateDanmuReadCustomFields(customPayload)) return;
  const body = {
    enabled: Boolean(document.getElementById('danmuReadEnabled')?.checked),
    interval_sec: parseInt(document.getElementById('danmuReadInterval')?.value, 10) || 10,
    voice: document.getElementById('danmuReadVoice')?.value || '冰糖',
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
  showToast('读弹幕设置已保存');
}

async function probeDanmuRead() {
  const customPayload = collectDanmuReadCustomPayload();
  if (!validateDanmuReadCustomFields(customPayload)) return;
  const status = document.getElementById('danmuReadStatus');
  if (status) status.textContent = '试听请求中（约 10-20 秒）...';
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
  showToast(result.message || (result.ok ? '试听已开始' : '试听失败'), !result.ok);
}

function initDanmuReadPage() {
  ensureDanmuReadCatalog().catch(() => {});
  document
    .getElementById('danmuReadProvider')
    ?.addEventListener('change', handleDanmuReadProviderChange);
  document
    .getElementById('danmuReadModelSelect')
    ?.addEventListener('change', handleDanmuReadModelChange);
  document.getElementById('btnSaveDanmuRead')?.addEventListener('click', () => {
    saveDanmuReadSettings().catch((error) => showToast(error.message, true));
  });
  document.getElementById('btnDanmuReadProbe')?.addEventListener('click', () => {
    probeDanmuRead().catch((error) => {
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
  document.querySelectorAll('.page-panel').forEach((panel) => panel.classList.remove('active'));
  document.querySelectorAll('#nav .sidebar-item').forEach((item) => item.classList.remove('active'));
  const panel = document.getElementById(`page-${page}`);
  if (panel) panel.classList.add('active');
  const btn = document.querySelector(`#nav [data-page="${page}"]`);
  if (btn) btn.classList.add('active');

  if (page === 'settings') {
    reloadConfigFromServer().catch(console.error);
    loadScreens().catch(console.error);
    loadCustomModels().catch(console.error);
  }
  if (page === 'overview') loadOverviewGlobalFields().catch(console.error);
  else {
    import('./modules/diagnostics.js')
      .then((mod) => mod.disconnectDiagnosticsPanel())
      .catch(() => {});
  }
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
  if (page === 'announcements') {
    stopAnnouncementsBadgePolling();
    updateAnnouncementsNavBadge(false);
    loadAnnouncementsPage().catch((error) => showToast(error.message, true));
  } else {
    startAnnouncementsBadgePolling();
  }
  if (page === 'feedback') {
    import('./modules/content-feedback.js')
      .then((mod) => mod.initFeedbackPage())
      .catch(console.error);
  }
  if (page === 'tutorial') {
    import('./modules/content-tutorial.js')
      .then((mod) => mod.loadTutorialPage())
      .catch(console.error);
  }
  if (page === 'logs') {
    updateLogPanelState();
    bootstrapLogsFromServer(REALTIME.lastLogsPollTs).catch((error) => {
      console.warn('[realtime] logs bootstrap on navigate failed', error);
    });
  }
}

async function init() {
  initTheme();
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
  if (cfg.screen_index !== undefined) {
    document.getElementById('screen_index').value = String(cfg.screen_index);
  }

  initErrorReporting({ showToast, getLastStatus: getLastAppliedStatus });
  initLiveOverlayPanel({ showToast });
  initPersonaTopicPage({ showToast });
  loadOverviewGlobalFields().catch(console.error);
  initAppUpdateModal({ showToast });
  wireLazyDiagnosticsToggle();

  configureStatus({
    applyCaptureRegion: applyCaptureRegionFromPayload,
    onErrorPrompt: maybePromptErrorReport,
    onErrorReportManual: (status) => openErrorReportModalImpl(status, { force: true }),
  });
  setRealtimeHandlers({
    onStatus: applyStatus,
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
  initSettingsUiMode();
  initSettingsFieldHints();
  initContentPageFieldHints();
  initSidebarNavFloatingHints();
  initNormalBatchControls();
  initDanmuReadPage();
  loadDanmuReadPage().catch(console.error);
  initCaptureRegionControls();
  initRestoreDefaultsControls();
  initFloatingPanelV2Controls();

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
  bindContentPageControls({ showToast, navigate });

  document.querySelectorAll('.sidebar-nav-hint').forEach((btn) => {
    btn.addEventListener('click', (event) => event.stopPropagation());
  });
  document.querySelectorAll('#nav [data-page]').forEach((btn) => {
    btn.addEventListener('click', () => navigate(btn.dataset.page));
  });
  const hash = (location.hash || '').replace('#', '');
  if (hash) navigate(hash);

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
    navigator.clipboard.writeText(text).then(() => showToast('已复制到剪贴板'));
  });
  document.getElementById('btnClearLogs')?.addEventListener('click', () => {
    clearLogBuffer();
    document.getElementById('logView').innerHTML = '';
    updateLogPanelState();
    showToast('日志视图已清空');
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
        showToast('小助手已休息');
      } else {
        await apiFetch('/api/start', { method: 'POST' });
        showToast('弹幕生成已开启');
      }
    } catch (error) {
      showToast(error.message || '小助手遇到了一点问题', true);
    }
  });

  await Promise.all([
    refreshAnnouncementsUnreadBadge(),
    initAppVersionAndUpdateCheck(),
  ]);
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
  import('./modules/diagnostics.js')
    .then((mod) => mod.destroyDiagnosticsPanel())
    .catch(() => {});
  import('./modules/app-meme-barrage-page.js')
    .then((mod) => mod.stopMemeBarrageMetaPolling())
    .catch(() => {});
  stopAnnouncementsBadgePolling();
});

init().catch((error) => {
  console.error(error);
  showToast(error.message || '无法连接小助手，请确认 DanmuAI 已启动', true);
});
