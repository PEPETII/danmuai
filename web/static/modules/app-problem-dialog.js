/**
 * Problem detail modal — explains issues independently from error feedback.
 */
import { t } from './i18n.js';
import { activateFocusTrap, deactivateFocusTrap } from './modal-focus-trap.js';

const DISMISS_STORAGE_KEY = 'danmu_problem_dialog_dismissed_events';
const MAX_QUEUE = 10;

let deps = {
  showToast: () => {},
  navigate: () => {},
  switchSettingsTab: () => {},
  openErrorReport: async () => {},
  retryProblemAction: async () => {},
  getLastStatus: () => null,
  isFeedbackSubmitting: () => false,
  probeConnection: async () => {},
};

let activeProblem = null;
let lastFocusTrigger = null;
const problemQueue = [];
let handlersBound = false;

function readDismissedEvents() {
  try {
    const raw = sessionStorage.getItem(DISMISS_STORAGE_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch {
    return [];
  }
}

function writeDismissedEvents(events) {
  try {
    sessionStorage.setItem(DISMISS_STORAGE_KEY, JSON.stringify(events.slice(-50)));
  } catch {
    /* ignore */
  }
}

function isDismissed(eventId) {
  return readDismissedEvents().includes(String(eventId || ''));
}

function markDismissed(eventId) {
  const id = String(eventId || '').trim();
  if (!id) return;
  const events = readDismissedEvents().filter((item) => item !== id);
  events.push(id);
  writeDismissedEvents(events);
}

function severityRank(severity) {
  const ranks = { info: 0, warning: 1, error: 2, fatal: 3 };
  return ranks[String(severity || '').toLowerCase()] ?? 1;
}

function categoryLabel(category) {
  const key = `dynamic.problem.category.${category}`;
  const text = t(key);
  return text !== key ? text : category;
}

function occurrenceText(count) {
  const n = Number(count) || 1;
  if (n <= 1) return '';
  return t('dynamic.problem.occurrenceCount', { count: n });
}

function shouldAutoOpen(problem) {
  const severity = String(problem?.severity || 'error').toLowerCase();
  if (severity === 'info') return false;
  if (severity === 'fatal' || severity === 'error') return true;
  if (severity === 'warning') return !isDismissed(problem.event_id);
  return false;
}

function enqueueProblem(problem) {
  if (!problem?.event_id) return;
  if (problemQueue.some((item) => item.event_id === problem.event_id)) return;
  problemQueue.push(problem);
  problemQueue.sort((a, b) => severityRank(b.severity) - severityRank(a.severity));
  while (problemQueue.length > MAX_QUEUE) {
    problemQueue.pop();
  }
}

function processQueue() {
  if (activeProblem || !problemQueue.length) return;
  const next = problemQueue.shift();
  if (next) showProblemDialog(next);
}

function renderActions(problem) {
  const container = document.getElementById('problemDetailActions');
  if (!container) return;
  container.replaceChildren();
  const actions = Array.isArray(problem?.actions) ? problem.actions : [];
  actions.forEach((action) => {
    if (!action?.type || !action?.label) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'ui-button ui-button--secondary ui-button--sm';
    btn.textContent = String(action.label);
    btn.addEventListener('click', () => handleAction(action));
    container.appendChild(btn);
  });
}

function renderProblemContent(problem) {
  const titleEl = document.getElementById('problemDetailTitle');
  const metaEl = document.getElementById('problemDetailMeta');
  const countEl = document.getElementById('problemDetailOccurrence');
  const summaryEl = document.getElementById('problemDetailSummary');
  const causeEl = document.getElementById('problemDetailCause');
  const impactEl = document.getElementById('problemDetailImpact');
  const suggestionsEl = document.getElementById('problemDetailSuggestions');
  const technicalWrap = document.getElementById('problemDetailTechnicalWrap');
  const technicalEl = document.getElementById('problemTechnicalDetail');
  const severityEl = document.getElementById('problemDetailSeverity');
  const reportBtn = document.getElementById('btnProblemReportFromModal');

  if (titleEl) titleEl.textContent = problem.title || problem.code || '';
  if (metaEl) {
    metaEl.textContent = `${categoryLabel(problem.category)} · ${problem.code || ''}`;
  }
  if (countEl) {
    const text = occurrenceText(problem.occurrence_count);
    countEl.textContent = text;
    countEl.classList.toggle('hidden', !text);
  }
  if (summaryEl) summaryEl.textContent = problem.summary || '';
  if (causeEl) causeEl.textContent = problem.cause || '';
  if (impactEl) impactEl.textContent = problem.impact || '';
  if (suggestionsEl) {
    suggestionsEl.replaceChildren();
    (problem.suggestions || []).forEach((item) => {
      const li = document.createElement('li');
      li.textContent = String(item);
      suggestionsEl.appendChild(li);
    });
  }
  const technical = String(problem.technical_detail || '').trim();
  if (technicalWrap && technicalEl) {
    if (technical) {
      technicalEl.textContent = technical;
      technicalWrap.classList.remove('hidden');
    } else {
      technicalEl.textContent = '';
      technicalWrap.classList.add('hidden');
    }
  }
  if (severityEl) {
    severityEl.className = `problem-detail-severity problem-detail-severity--${String(problem.severity || 'error').toLowerCase()}`;
    severityEl.textContent = categoryLabel(problem.category);
  }
  if (reportBtn) {
    const feedbackAllowed = problem.feedback_allowed !== false;
    const supabaseReady = !!window.DanmuSupabase?.isConfigured?.();
    reportBtn.classList.toggle('hidden', !feedbackAllowed);
    reportBtn.disabled = !supabaseReady;
    reportBtn.title = supabaseReady
      ? ''
      : t('dynamic.problem.feedbackUnavailable');
  }
  renderActions(problem);
}

function handleNavigateTarget(target) {
  const text = String(target || '').trim();
  if (!text) return;
  if (text.startsWith('settings/')) {
    const tab = text.split('/')[1] || 'api';
    deps.navigate('settings');
    deps.switchSettingsTab(tab);
    return;
  }
  if (text.startsWith('content/')) {
    const page = text.split('/')[1] || 'knowledge';
    deps.navigate(page);
    return;
  }
  if (text.startsWith('guide/')) {
    deps.navigate(text.split('/')[1] || 'logs');
    return;
  }
  deps.navigate(text);
}

async function handleAction(action) {
  const type = String(action?.type || '');
  if (type === 'navigate') {
    handleNavigateTarget(action.target);
    return;
  }
  if (type === 'probe_connection') {
    await deps.probeConnection();
    return;
  }
  if (type === 'open_logs') {
    deps.navigate('logs');
    return;
  }
  if (type === 'retry') {
    await deps.retryProblemAction(activeProblem);
    return;
  }
  if (type === 'dismiss') {
    closeProblemDialog({ dismissed: true });
  }
}

export function getActiveDisplayedProblem() {
  return activeProblem;
}

export function showProblemDialog(problem, options = {}) {
  if (!problem?.event_id) return;
  const modal = document.getElementById('problemDetailModal');
  if (!modal) return;
  renderProblemContent(problem);
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  activeProblem = problem;
  const allowEscape = String(problem.severity || '').toLowerCase() !== 'fatal';
  activateFocusTrap(modal, () => {
    if (allowEscape || options.force) {
      closeProblemDialog({ dismissed: !options.force });
    }
  });
}

export function closeProblemDialog(options = {}) {
  const modal = document.getElementById('problemDetailModal');
  if (options.dismissed && activeProblem?.event_id) {
    markDismissed(activeProblem.event_id);
  }
  deactivateFocusTrap();
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
  activeProblem = null;
  if (lastFocusTrigger && typeof lastFocusTrigger.focus === 'function') {
    lastFocusTrigger.focus();
  }
  processQueue();
}

export function updateVisibleProblemOccurrence(problem) {
  if (!problem?.event_id || activeProblem?.event_id !== problem.event_id) return;
  activeProblem = { ...activeProblem, ...problem };
  const countEl = document.getElementById('problemDetailOccurrence');
  if (!countEl) return;
  const text = occurrenceText(problem.occurrence_count);
  countEl.textContent = text;
  countEl.classList.toggle('hidden', !text);
}

export function maybeShowProblem(problem) {
  if (!problem?.event_id) return;
  if (deps.isFeedbackSubmitting()) {
    enqueueProblem(problem);
    return;
  }
  if (!shouldAutoOpen(problem)) return;
  if (isDismissed(problem.event_id) && String(problem.severity).toLowerCase() !== 'fatal') {
    return;
  }
  if (
    activeProblem &&
    activeProblem.event_id !== problem.event_id &&
    severityRank(problem.severity) < severityRank(activeProblem.severity)
  ) {
    enqueueProblem(problem);
    return;
  }
  showProblemDialog(problem);
}

function bindHandlers() {
  if (handlersBound) return;
  handlersBound = true;
  document.getElementById('btnProblemDetailClose')?.addEventListener('click', () => {
    closeProblemDialog({ dismissed: true });
  });
  document.getElementById('btnProblemReportFromModal')?.addEventListener('click', () => {
    if (!activeProblem) return;
    deps.openErrorReport(activeProblem, { fromProblemDialog: true }).catch(console.warn);
  });
  document.getElementById('problemDetailModal')?.addEventListener('click', (event) => {
    if (event.target.id === 'problemDetailModal') {
      const severity = String(activeProblem?.severity || '').toLowerCase();
      if (severity !== 'fatal') closeProblemDialog({ dismissed: true });
    }
  });
  document.getElementById('btnProblemViewFromBanner')?.addEventListener('click', (event) => {
    lastFocusTrigger = event.currentTarget;
    const st = deps.getLastStatus();
    const problem = st?.active_problem;
    if (problem?.event_id) {
      showProblemDialog(problem, { force: true });
      return;
    }
    if (st?.error_message) {
      showProblemDialog(
        {
          event_id: `legacy-${Date.now()}`,
          code: 'LEGACY',
          severity: st.is_error ? 'error' : 'warning',
          category: 'internal',
          title: t('dynamic.problem.legacyTitle'),
          summary: st.error_message,
          cause: '',
          impact: '',
          suggestions: [],
          actions: [],
          feedback_allowed: true,
          occurrence_count: 1,
        },
        { force: true },
      );
    }
  });
  document.getElementById('btnProblemBannerDismiss')?.addEventListener('click', () => {
    const banner = document.getElementById('errorBanner');
    banner?.classList.add('hidden');
  });
}

export function initProblemDialog(injectedDeps = {}) {
  deps = { ...deps, ...injectedDeps };
  bindHandlers();
}

export function buildFrontendInternalProblem(message, detail = '') {
  return {
    event_id: `frontend-${Date.now()}`,
    code: 'INTERNAL-001',
    severity: 'error',
    category: 'internal',
    title: t('dynamic.problem.internalTitle'),
    summary: message || t('dynamic.problem.internalSummary'),
    cause: t('dynamic.problem.internalCause'),
    impact: t('dynamic.problem.internalImpact'),
    suggestions: [t('dynamic.problem.internalSuggestionReload')],
    actions: [{ type: 'dismiss', label: t('dynamic.problem.action.close') }],
    technical_detail: detail,
    feedback_allowed: true,
    occurrence_count: 1,
    source: 'frontend',
  };
}
