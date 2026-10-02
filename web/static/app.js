import { t } from './modules/i18n.js';
import {
  API,
  REALTIME,
  apiFetch,
  refreshSession,
  resumeRealtimeTransport,
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
import { onVirtualHostLogsTabActivated } from './modules/virtual-host-logs.js';
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
import { initOverviewQuickSettings } from './modules/overview-quick-settings.js';
import {
  initAppUpdateModal,
  initAppVersionAndUpdateCheck,
} from './modules/app-update-banner.js';
import {
  closeShellNavIfDrawer,
  initResponsiveShell,
} from './modules/responsive-shell.js';
import {
  initDanmuReadPage,
  loadDanmuReadPage,
} from './modules/app-danmu-read-page.js';

let danmuPoolPagesReady = false;
let virtualHostPageReady = false;
let vtuberPageReady = false;
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

async function ensureVirtualHostPage() {
  const mod = await import('./modules/app-virtual-host-page.js');
  if (!virtualHostPageReady) {
    mod.initVirtualHostPage({ showToast });
    virtualHostPageReady = true;
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
  el.setAttribute('role', isError ? 'alert' : 'status');
  el.setAttribute('aria-live', isError ? 'assertive' : 'polite');
  el.className = `toast show ${isError ? 'toast--error' : 'toast--success'}`;
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
  btn.classList.add('is-loading');
  btn.setAttribute('aria-busy', 'true');
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
    btn.classList.remove('is-loading');
    btn.removeAttribute('aria-busy');
  }
}

async function ensureVtuberPage() {
  const mod = await import('./modules/app-vtuber-page.js');
  if (!vtuberPageReady) {
    mod.initVtuberPage({ showToast });
    vtuberPageReady = true;
  }
  return mod;
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

function navigate(page) {
  if (page === 'danmu-read') {
    page = 'settings';
    switchSettingsTab('danmu-read');
  }
  if (
    page === 'tutorial' ||
    page === 'logs' ||
    page === 'mic-logs' ||
    page === 'virtual-host-logs' ||
    page === 'history-stats' ||
    page === 'session-runs' ||
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
  document.getElementById('btnHelpSystem')?.classList.remove('active');
  const panel = document.getElementById(`page-${page}`);
  if (panel) panel.classList.add('active');
  const btn = document.querySelector(`#nav [data-page="${page}"]`);
  const enhancedItems = document.getElementById('sidebarEnhancedItems');
  if (btn && enhancedItems?.contains(btn) && enhancedItems.hidden) {
    document.getElementById('btnSidebarEnhancedToggle')?.click();
  }
  if (btn) btn.classList.add('active');
  if (page === 'help-system') document.getElementById('btnHelpSystem')?.classList.add('active');
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
  if (page === 'virtual-host') {
    Promise.all([
      ensureVirtualHostPage().then((mod) => mod.loadVirtualHostPage()),
      ensureVtuberPage().then((mod) => mod.loadVtuberPage()),
    ])
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
    } else if (activeTab === 'virtual-host-logs') {
      onVirtualHostLogsTabActivated();
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

function initSidebarNavDisclosure() {
  const toggle = document.getElementById('btnSidebarEnhancedToggle');
  const enhancedItems = document.getElementById('sidebarEnhancedItems');
  if (!toggle || !enhancedItems) return;

  const labels = [...toggle.querySelectorAll('[data-sidebar-disclosure-label]')];
  const setExpanded = (expanded) => {
    enhancedItems.hidden = !expanded;
    toggle.setAttribute('aria-expanded', String(expanded));
    toggle.classList.toggle('is-expanded', expanded);
    toggle.setAttribute(
      'data-i18n-aria-label',
      expanded ? 'nav.collapseEnhanced' : 'nav.expandEnhanced',
    );
    labels.forEach((label) => {
      label.hidden = label.dataset.sidebarDisclosureLabel !== (expanded ? 'collapse' : 'expand');
    });
    const visibleLabel = labels.find((label) => !label.hidden);
    toggle.setAttribute('aria-label', visibleLabel?.textContent?.trim() || '');
  };

  toggle.addEventListener('click', () => setExpanded(enhancedItems.hidden));
  // 新会话默认只展示常用入口；增强入口通过明确的披露操作展开。
  setExpanded(false);
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
  initOverviewQuickSettings({ navigate, switchSettingsTab });

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
    onAuthFailure: ({ error }) => {
      recordBootstrapFailure('session', error);
    },
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
      } else if (tabId === 'virtual-host-logs') {
        onVirtualHostLogsTabActivated();
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

  document.getElementById('btnHelpSystem')?.addEventListener('click', () => {
    navigate('help-system');
  });
  document.querySelectorAll('[data-help-navigate]').forEach((el) => {
    el.addEventListener('click', () => {
      const target = el.dataset.helpNavigate;
      if (target === 'diagnostics') {
        navigate('overview');
        const banner = document.getElementById('errorBanner');
        if (banner && !banner.classList.contains('hidden')) {
          document.getElementById('btnProblemViewFromBanner')?.click();
        }
        return;
      }
      if (target) navigate(target);
    });
  });

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
  initSidebarNavDisclosure();
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
  document.getElementById('btnExportLogs')?.addEventListener('click', () => {
    const text = logBuffer
      .map((item) => `[${item.level}] ${item.message}`)
      .join('\n');
    if (!text) {
      showToast(t('common.noLogsToExport'), true);
      return;
    }
    const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `danmuai-logs-${new Date().toISOString().slice(0, 10)}.txt`;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
    showToast(t('common.logsExported'));
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
  void runBootstrapTask('vtuber-runtime', async () => {
    await ensureVtuberPage();
    const { refreshVtuberRuntimeState } = await import('./modules/vtuber-controller.js');
    await refreshVtuberRuntimeState();
  });
  initAppUpdateModal({ showToast });

  const statusPromise = runBootstrapTask('status', async () => {
    const status = await fetchBootstrapStatus();
    applyStatus(status);
    return status;
  });
  startRealtimeTransport();
  await statusPromise;

  initDanmuReadPage({
    showToast,
    withLoadingState,
    onCatalogBootstrapFailure: (error) => recordBootstrapFailure('danmu-read-catalog', error),
  });
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
  if (document.visibilityState !== 'visible') return;
  resumeRealtimeTransport()
    .then(() => clearBootstrapFailure('session'))
    .catch((error) => {
      console.warn('[realtime] visibility refresh failed', error);
      recordBootstrapFailure('session', error);
    });
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
