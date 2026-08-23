import { apiFetch } from './transport.js';
import { t } from './i18n.js';
import { computePackageCardState } from './app-knowledge-status.js';
import {
  currentPackageId,
  currentPackageSnapshot,
  jobPollPackageId,
  showKnowledgeToast,
  setCurrentPackageId,
  setCurrentPackageSnapshot,
  setJobPollPackageId,
  resetPreviousJobStatuses,
  setItemPage,
} from './app-knowledge-state.js';
import { openKnowledgeConfirmModal } from './app-knowledge-modals.js';
import { loadKnowledgePage } from './app-knowledge-package-list.js';
import {
  refreshJobs,
  startKnowledgeJobPolling,
  stopKnowledgeJobPolling,
  updateBackgroundJobBanner,
} from './app-knowledge-jobs.js';
import { cancelItemsLoad, loadItems } from './app-knowledge-items.js';
import { syncImportFormState } from './app-knowledge-import.js';

let detailLoadRequestId = 0;
let detailLoadAbortController = null;

function isAbortError(error) {
  return error?.name === 'AbortError';
}

function isCurrentDetailLoad(requestId, packageId, { requireVisible = true } = {}) {
  if (requestId !== detailLoadRequestId || packageId !== currentPackageId) return false;
  if (!requireVisible) return true;
  return !document.getElementById('knowledgePackageDetail')?.classList.contains('hidden');
}

export function cancelPackageDetailLoad() {
  detailLoadRequestId += 1;
  detailLoadAbortController?.abort();
  detailLoadAbortController = null;
  cancelItemsLoad();
}

export function fillPackageForm(pkg) {
  const set = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.value = value ?? '';
  };
  set('knowledgePackageName', pkg.name);
  set('knowledgePackagePriority', pkg.priority ?? 0);
  const enabledEl = document.getElementById('knowledgePackageEnabled');
  if (enabledEl) enabledEl.checked = Boolean(pkg.enabled);
}

export function updateOverview(pkg, jobs = []) {
  if (!pkg) return;
  const nameEl = document.getElementById('knowledgeOverviewName');
  const badgeEl = document.getElementById('knowledgeOverviewStatusBadge');
  const statsEl = document.getElementById('knowledgeOverviewStats');
  const saveStatusEl = document.getElementById('knowledgeOverviewSaveStatus');

  if (nameEl) nameEl.textContent = pkg.name || '';
  const cardState = computePackageCardState(pkg, jobs);
  if (badgeEl) {
    badgeEl.textContent = t(`dynamic.appKnowledgePage.cardStatus.${cardState.badgeKey}`);
    badgeEl.className = `knowledge-status-badge ${
      cardState.badgeKey === 'badgeEnabled'
        ? 'knowledge-status-badge--success'
        : cardState.badgeKey === 'badgeNeedsWork'
          ? 'knowledge-status-badge--warn'
          : 'knowledge-status-badge--muted'
    }`;
  }
  if (statsEl) {
    statsEl.textContent = [
      t('dynamic.appKnowledgePage.sourceCountLabel', { count: pkg.source_count ?? 0 }),
      t('dynamic.appKnowledgePage.itemCountLabel', { count: pkg.item_count ?? 0 }),
    ].join(' · ');
  }
  if (saveStatusEl && !saveStatusEl.dataset.dirty) {
    saveStatusEl.textContent = t('dynamic.appKnowledgePage.saveStatusSaved');
  }
}

export function markOverviewDirty() {
  const saveStatusEl = document.getElementById('knowledgeOverviewSaveStatus');
  if (saveStatusEl) {
    saveStatusEl.dataset.dirty = '1';
    saveStatusEl.textContent = t('dynamic.appKnowledgePage.saveStatusDirty');
  }
}

export function markOverviewSaved() {
  const saveStatusEl = document.getElementById('knowledgeOverviewSaveStatus');
  if (saveStatusEl) {
    delete saveStatusEl.dataset.dirty;
    saveStatusEl.textContent = t('dynamic.appKnowledgePage.saveStatusSaved');
  }
}

export async function openPackageDetail(packageId) {
  cancelPackageDetailLoad();
  const requestId = ++detailLoadRequestId;
  detailLoadAbortController = new AbortController();
  const { signal } = detailLoadAbortController;
  if (jobPollPackageId && jobPollPackageId !== packageId) {
    stopKnowledgeJobPolling();
  }
  setCurrentPackageId(packageId);
  setJobPollPackageId(packageId);
  resetPreviousJobStatuses();
  setItemPage(1);
  const { showDetailView } = await import('./app-knowledge-page.js');
  if (!isCurrentDetailLoad(requestId, packageId, { requireVisible: false })) return;
  showDetailView();
  try {
    const data = await apiFetch(
      `/api/knowledge/packages/${encodeURIComponent(packageId)}?summary=true`,
      { signal },
    );
    if (!isCurrentDetailLoad(requestId, packageId)) return;
    setCurrentPackageSnapshot({
      source_count: data.sources?.length ?? 0,
      item_count: data.items?.total ?? 0,
      ...data,
    });
    fillPackageForm({
      ...data,
      source_count: data.sources?.length ?? 0,
      item_count: data.items?.total ?? 0,
    });
    updateOverview(
      {
        ...data,
        source_count: data.sources?.length ?? 0,
        item_count: data.items?.total ?? 0,
      },
      [],
    );
    const jobList = document.getElementById('knowledgeJobList');
    if (jobList) jobList.replaceChildren();
    await refreshJobs();
    if (!isCurrentDetailLoad(requestId, packageId)) return;
    await loadItems();
    if (!isCurrentDetailLoad(requestId, packageId)) return;
    startKnowledgeJobPolling(packageId);
    syncImportFormState();
    updateBackgroundJobBanner();
  } catch (error) {
    if (isAbortError(error) || !isCurrentDetailLoad(requestId, packageId)) return;
    showKnowledgeToast(error.message, true);
    console.warn('[knowledge] openPackageDetail failed', error);
  } finally {
    if (requestId === detailLoadRequestId) detailLoadAbortController = null;
  }
}

export async function savePackageSettings() {
  if (!currentPackageId) return;
  const body = {
    name: document.getElementById('knowledgePackageName')?.value || '',
    enabled: Boolean(document.getElementById('knowledgePackageEnabled')?.checked),
    priority: parseInt(document.getElementById('knowledgePackagePriority')?.value, 10) || 0,
  };
  try {
    const updated = await apiFetch(
      `/api/knowledge/packages/${encodeURIComponent(currentPackageId)}`,
      { method: 'PATCH', body: JSON.stringify(body) },
    );
    const snapshot = {
      ...updated,
      source_count: currentPackageSnapshot?.source_count ?? 0,
      item_count: currentPackageSnapshot?.item_count ?? 0,
    };
    setCurrentPackageSnapshot(snapshot);
    fillPackageForm(snapshot);
    markOverviewSaved();
    showKnowledgeToast(t('dynamic.appKnowledgePage.packageUpdated'));
  } catch (error) {
    showKnowledgeToast(error.message, true);
  }
}

export async function deleteCurrentPackage() {
  if (!currentPackageId) return;
  const ok = await openKnowledgeConfirmModal({
    title: t('dynamic.appKnowledgePage.dangerDeleteTitle'),
    message: t('dynamic.appKnowledgePage.confirmDeletePackage'),
    confirmLabel: t('dynamic.appKnowledgePage.confirm.delete'),
    danger: true,
  });
  if (!ok) return;
  try {
    await apiFetch(
      `/api/knowledge/packages/${encodeURIComponent(currentPackageId)}`,
      { method: 'DELETE' },
    );
    showKnowledgeToast(t('dynamic.appKnowledgePage.packageDeleted'));
    await loadKnowledgePage();
  } catch (error) {
    showKnowledgeToast(error.message, true);
  }
}

export function bindDetailFieldWatchers() {
  ['knowledgePackageName', 'knowledgePackagePriority'].forEach(
    (id) => {
      document.getElementById(id)?.addEventListener('input', () => markOverviewDirty());
    },
  );
  document.getElementById('knowledgePackageEnabled')?.addEventListener('change', () => {
    markOverviewDirty();
  });
}
