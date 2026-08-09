import { apiFetch } from './transport.js';
import { t } from './i18n.js';
import { activateFocusTrap, deactivateFocusTrap } from './modal-focus-trap.js';
import {
  ACTIVE_JOB_STATUSES,
  JOB_POLL_INTERVAL_MS,
  currentPackageId,
  currentPackageSnapshot,
  jobPollPackageId,
  jobPollTimer,
  jobPollToken,
  notifiedTerminalJobIds,
  organizeModalDisplayName,
  organizeModalElapsedTimer,
  organizeModalJobId,
  organizeModalOpen,
  organizeModalStartTime,
  previousJobStatusById,
  showKnowledgeToast,
  setCurrentPackageId,
  setCurrentPackageSnapshot,
  setJobPollPackageId,
  setJobPollTimer,
  bumpJobPollToken,
  setOrganizeModalOpen,
  setOrganizeModalJobId,
  setOrganizeModalDisplayName,
  setOrganizeModalStartTime,
  setOrganizeModalElapsedTimer,
} from './app-knowledge-state.js';
import {
  humanizeJobError,
  isActiveToTerminalTransition,
  jobStatusBadgeClass,
  organizeStageKey,
  statusKey,
  formatElapsedMs,
} from './app-knowledge-status.js';
import { openKnowledgeConfirmModal } from './app-knowledge-modals.js';
import { fillPackageForm, updateOverview } from './app-knowledge-package-detail.js';
import { loadItems, scrollToItemsSection } from './app-knowledge-items.js';
import {
  focusAddSourceSection,
  syncImportFormState,
} from './app-knowledge-import.js';

let organizeTrapCleanup = null;
let lastJobsList = [];

function showOrganizeModalShell() {
  const modal = document.getElementById('knowledgeOrganizeModal');
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function hideOrganizeModalShell() {
  const modal = document.getElementById('knowledgeOrganizeModal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
  deactivateFocusTrap();
  if (typeof organizeTrapCleanup === 'function') {
    organizeTrapCleanup();
    organizeTrapCleanup = null;
  }
}

function setOrganizeActionsMode(mode) {
  document
    .getElementById('knowledgeOrganizeActionsActive')
    ?.classList.toggle('hidden', mode !== 'active');
  document
    .getElementById('knowledgeOrganizeActionsDone')
    ?.classList.toggle('hidden', mode !== 'done');
  document
    .getElementById('knowledgeOrganizeActionsFailed')
    ?.classList.toggle('hidden', mode !== 'failed');
}

function updateOrganizeElapsed() {
  const el = document.getElementById('knowledgeOrganizeElapsed');
  if (!el || !organizeModalStartTime) return;
  el.textContent = t('dynamic.appKnowledgePage.organizeModal.elapsed', {
    time: formatElapsedMs(Date.now() - organizeModalStartTime),
  });
}

function startOrganizeElapsedTimer() {
  if (organizeModalElapsedTimer) window.clearInterval(organizeModalElapsedTimer);
  setOrganizeModalStartTime(Date.now());
  updateOrganizeElapsed();
  setOrganizeModalElapsedTimer(window.setInterval(updateOrganizeElapsed, 1000));
}

function backgroundContinueOrganize() {
  setOrganizeModalOpen(false);
  hideOrganizeModalShell();
  updateBackgroundJobBanner();
}

function bindOrganizeModalOnce() {
  const bgBtn = document.getElementById('btnKnowledgeOrganizeBackground');
  const cancelBtn = document.getElementById('btnKnowledgeOrganizeCancel');
  const viewItemsBtn = document.getElementById('btnKnowledgeOrganizeViewItems');
  const addMoreBtn = document.getElementById('btnKnowledgeOrganizeAddMore');
  const retryBtn = document.getElementById('btnKnowledgeOrganizeRetry');
  const closeFailedBtn = document.getElementById('btnKnowledgeOrganizeCloseFailed');

  if (bgBtn && !bgBtn.dataset.bound) {
    bgBtn.dataset.bound = '1';
    bgBtn.addEventListener('click', () => backgroundContinueOrganize());
  }
  if (cancelBtn && !cancelBtn.dataset.bound) {
    cancelBtn.dataset.bound = '1';
    cancelBtn.addEventListener('click', () => void cancelOrganizeJob());
  }
  if (viewItemsBtn && !viewItemsBtn.dataset.bound) {
    viewItemsBtn.dataset.bound = '1';
    viewItemsBtn.addEventListener('click', () => {
      backgroundContinueOrganize();
      scrollToItemsSection();
      void loadItems();
    });
  }
  if (addMoreBtn && !addMoreBtn.dataset.bound) {
    addMoreBtn.dataset.bound = '1';
    addMoreBtn.addEventListener('click', () => {
      backgroundContinueOrganize();
      focusAddSourceSection();
    });
  }
  if (retryBtn && !retryBtn.dataset.bound) {
    retryBtn.dataset.bound = '1';
    retryBtn.addEventListener('click', () => {
      backgroundContinueOrganize();
      focusAddSourceSection();
    });
  }
  if (closeFailedBtn && !closeFailedBtn.dataset.bound) {
    closeFailedBtn.dataset.bound = '1';
    closeFailedBtn.addEventListener('click', () => backgroundContinueOrganize());
  }
}

export function openOrganizeModalForJob(jobId, displayName = '') {
  bindOrganizeModalOnce();
  setOrganizeModalJobId(jobId);
  setOrganizeModalOpen(true);
  setOrganizeModalDisplayName(displayName || '');
  const titleEl = document.getElementById('knowledgeOrganizeModalTitle');
  if (titleEl) {
    titleEl.textContent = displayName
      ? t('dynamic.appKnowledgePage.organizeModal.titleWithName', { name: displayName })
      : t('dynamic.appKnowledgePage.organizeModal.title');
  }
  setOrganizeActionsMode('active');
  const tech = document.getElementById('knowledgeOrganizeTechnical');
  if (tech) tech.classList.add('hidden');
  showOrganizeModalShell();
  startOrganizeElapsedTimer();

  const modal = document.getElementById('knowledgeOrganizeModal');
  if (modal) {
    const closeFn = () => backgroundContinueOrganize();
    activateFocusTrap(modal, closeFn);
    const title = document.getElementById('knowledgeOrganizeModalTitle');
    if (title) title.focus();
  }

  const job = lastJobsList.find((j) => j.public_id === jobId);
  if (job) updateOrganizeModalFromJob(job);
}

function updateOrganizeProgressBar(job) {
  const bar = document.getElementById('knowledgeOrganizeProgressBar');
  const indeterminate = document.getElementById('knowledgeOrganizeProgressIndeterminate');
  const textEl = document.getElementById('knowledgeOrganizeProgressText');
  const total = job.total_chunks ?? 0;
  const processed = job.processed_chunks ?? 0;
  if (total > 0) {
    if (bar) {
      bar.classList.remove('hidden');
      const pct = Math.min(100, Math.round((processed / total) * 100));
      bar.value = pct;
      bar.max = 100;
    }
    if (indeterminate) indeterminate.classList.add('hidden');
    if (textEl) {
      textEl.textContent = t('dynamic.appKnowledgePage.organizeModal.progress', {
        processed,
        total,
        percent: Math.min(100, Math.round((processed / total) * 100)),
      });
    }
  } else {
    if (bar) bar.classList.add('hidden');
    if (indeterminate) indeterminate.classList.remove('hidden');
    if (textEl) textEl.textContent = '';
  }
}

function updateOrganizeModalFromJob(job) {
  if (!job || job.public_id !== organizeModalJobId) return;

  const stageEl = document.getElementById('knowledgeOrganizeStage');
  const descEl = document.getElementById('knowledgeOrganizeModalDesc');
  const liveEl = document.getElementById('knowledgeOrganizeStatusLive');
  const resultEl = document.getElementById('knowledgeOrganizeResult');
  const bar = document.getElementById('knowledgeOrganizeProgressBar');
  const stageKeyName = organizeStageKey(job.stage);
  const stageLabel = stageKeyName
    ? t(`dynamic.appKnowledgePage.${stageKeyName}`)
    : job.stage || '';

  if (stageEl) {
    stageEl.textContent = t('dynamic.appKnowledgePage.organizeModal.currentStep', {
      step: stageLabel,
    });
  }
  if (descEl && ACTIVE_JOB_STATUSES.has(job.status)) {
    const hintKey = stageKeyName ? `${stageKeyName}Hint` : 'organizeModal.desc';
    const hint = t(`dynamic.appKnowledgePage.organizeModal.${hintKey}`);
    descEl.textContent =
      hint && !hint.includes('organizeModal.')
        ? hint
        : t('dynamic.appKnowledgePage.organizeModal.desc');
  }
  if (liveEl) {
    liveEl.textContent = `${t(`dynamic.appKnowledgePage.${statusKey(job.status)}`)} · ${stageLabel}`;
  }

  if (ACTIVE_JOB_STATUSES.has(job.status)) {
    setOrganizeActionsMode('active');
    updateOrganizeProgressBar(job);
    if (resultEl) resultEl.textContent = '';
    return;
  }

  if (organizeModalElapsedTimer) {
    window.clearInterval(organizeModalElapsedTimer);
    setOrganizeModalElapsedTimer(null);
  }

  const count = job.generated_items ?? 0;
  if (job.status === 'completed') {
    setOrganizeActionsMode('done');
    if (resultEl) {
      resultEl.textContent =
        count > 0
          ? t('dynamic.appKnowledgePage.organizeModal.completed', { count })
          : t('dynamic.appKnowledgePage.organizeModal.completedEmpty');
    }
    if (bar) document.getElementById('knowledgeOrganizeProgressBar')?.classList.add('hidden');
    document.getElementById('knowledgeOrganizeProgressIndeterminate')?.classList.add('hidden');
  } else if (job.status === 'completed_with_errors') {
    setOrganizeActionsMode('done');
    if (resultEl) {
      resultEl.textContent = t('dynamic.appKnowledgePage.organizeModal.completedPartial', {
        count,
        failed: job.failed_chunks ?? 0,
      });
    }
  } else if (
    job.status === 'failed' ||
    job.status === 'interrupted' ||
    job.status === 'cancelled'
  ) {
    setOrganizeActionsMode('failed');
    const human = humanizeJobError(job.error_message || '');
    if (resultEl) {
      resultEl.textContent =
        job.status === 'cancelled'
          ? t('dynamic.appKnowledgePage.organizeModal.cancelled')
          : human || t('dynamic.appKnowledgePage.jobFailed');
    }
    const tech = document.getElementById('knowledgeOrganizeTechnical');
    const techPre = document.getElementById('knowledgeOrganizeTechnicalPre');
    if (tech && techPre && job.error_message) {
      tech.classList.remove('hidden');
      techPre.textContent = job.error_message;
    }
  }
}

async function cancelOrganizeJob() {
  if (!organizeModalJobId) return;
  const ok = await openKnowledgeConfirmModal({
    title: t('dynamic.appKnowledgePage.organizeModal.cancelTitle'),
    message: t('dynamic.appKnowledgePage.organizeModal.cancelMessage'),
    confirmLabel: t('dynamic.appKnowledgePage.organizeModal.cancelConfirm'),
    danger: true,
  });
  if (!ok) return;
  const liveEl = document.getElementById('knowledgeOrganizeStatusLive');
  if (liveEl) liveEl.textContent = t('dynamic.appKnowledgePage.organizeModal.cancelling');
  try {
    await apiFetch(
      `/api/knowledge/jobs/${encodeURIComponent(organizeModalJobId)}/cancel`,
      { method: 'POST' },
    );
    await refreshJobs();
  } catch (error) {
    showKnowledgeToast(error.message, true);
  }
}

export function updateBackgroundJobBanner() {
  const banner = document.getElementById('knowledgeBackgroundJobBanner');
  const textEl = document.getElementById('knowledgeBackgroundJobText');
  const active = lastJobsList.find(
    (j) => ACTIVE_JOB_STATUSES.has(j.status) && !organizeModalOpen,
  );
  if (!banner) return;
  if (active) {
    banner.classList.remove('hidden');
    if (textEl) textEl.textContent = t('dynamic.appKnowledgePage.backgroundOrganizing');
  } else {
    banner.classList.add('hidden');
  }
}

export function renderJobs(jobs) {
  lastJobsList = jobs || [];
  const listEl = document.getElementById('knowledgeJobList');
  const emptyEl = document.getElementById('knowledgeJobEmpty');
  if (!listEl) return;
  listEl.replaceChildren();

  syncImportFormState(lastJobsList);
  updateBackgroundJobBanner();

  if (organizeModalOpen && organizeModalJobId) {
    const focused = lastJobsList.find((j) => j.public_id === organizeModalJobId);
    if (focused) updateOrganizeModalFromJob(focused);
  }

  if (!jobs || jobs.length === 0) {
    if (emptyEl) emptyEl.classList.remove('hidden');
    return;
  }
  if (emptyEl) emptyEl.classList.add('hidden');

  jobs.forEach((job) => {
    const row = document.createElement('div');
    row.className = 'knowledge-job-row p-3 bg-cream border border-softPeach rounded-xl space-y-2';

    const top = document.createElement('div');
    top.className = 'flex flex-wrap items-center gap-2 text-sm min-w-0';

    const name = document.createElement('span');
    name.className = 'font-semibold text-warmText break-words min-w-0';
    name.textContent = job.source_id || job.public_id;
    top.append(name);

    const badge = document.createElement('span');
    badge.className = `knowledge-status-badge ${jobStatusBadgeClass(job.status)}`;
    badge.textContent = t(`dynamic.appKnowledgePage.${statusKey(job.status)}`);
    top.append(badge);

    if (job.stage) {
      const stageKeyName = organizeStageKey(job.stage);
      const stageLabel = stageKeyName
        ? t(`dynamic.appKnowledgePage.${stageKeyName}`)
        : job.stage;
      const stageEl = document.createElement('span');
      stageEl.className = 'text-xs text-gray-500';
      stageEl.textContent = t('dynamic.appKnowledgePage.stageLabel', { stage: stageLabel });
      top.append(stageEl);
    }

    if (ACTIVE_JOB_STATUSES.has(job.status)) {
      const viewBtn = document.createElement('button');
      viewBtn.type = 'button';
      viewBtn.className =
        'px-3 py-1 bg-white border border-gray-200 rounded-lg text-xs font-semibold text-warmText hover:bg-gray-50 ui-button ui-button--secondary ui-button--sm';
      viewBtn.textContent = t('dynamic.appKnowledgePage.viewProgress');
      viewBtn.addEventListener('click', () => {
        openOrganizeModalForJob(job.public_id, job.source_id || '');
      });
      top.append(viewBtn);

      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className =
        'px-3 py-1 bg-white border border-gray-200 rounded-lg text-xs font-semibold text-warmText hover:bg-gray-50 ui-button ui-button--secondary ui-button--sm';
      cancelBtn.textContent = t('dynamic.appKnowledgePage.cancelJob');
      cancelBtn.addEventListener('click', () => void cancelJobById(job.public_id));
      top.append(cancelBtn);
    }

    row.append(top);

    if (job.total_chunks != null && job.processed_chunks != null && job.total_chunks > 0) {
      const progressWrap = document.createElement('div');
      progressWrap.className = 'knowledge-job-progress';
      const progressBar = document.createElement('progress');
      progressBar.className = 'knowledge-progress-bar';
      progressBar.max = job.total_chunks;
      progressBar.value = job.processed_chunks;
      progressWrap.append(progressBar);
      const progressText = document.createElement('span');
      progressText.className = 'text-xs text-gray-500';
      progressText.textContent = t('dynamic.appKnowledgePage.progress', {
        processed: job.processed_chunks,
        total: job.total_chunks,
      });
      progressWrap.append(progressText);
      row.append(progressWrap);
    }

    const metaParts = [];
    if (job.failed_chunks != null && job.failed_chunks > 0) {
      metaParts.push(t('dynamic.appKnowledgePage.failedChunks', { count: job.failed_chunks }));
    }
    if (job.generated_items != null) {
      metaParts.push(t('dynamic.appKnowledgePage.generatedItems', { count: job.generated_items }));
    }
    if (metaParts.length > 0) {
      const meta = document.createElement('p');
      meta.className = 'text-xs text-gray-500';
      meta.textContent = metaParts.join(' · ');
      row.append(meta);
    }

    if (job.error_message) {
      const human = humanizeJobError(job.error_message);
      const err = document.createElement('p');
      err.className = 'text-xs text-red-600 break-words';
      err.textContent = human;
      row.append(err);
      if (human !== job.error_message) {
        const details = document.createElement('details');
        details.className = 'text-xs text-gray-500';
        const summary = document.createElement('summary');
        summary.textContent = t('dynamic.appKnowledgePage.technicalDetails');
        const pre = document.createElement('code');
        pre.className = 'break-all';
        pre.textContent = job.error_message;
        details.append(summary, pre);
        row.append(details);
      }
    }

    listEl.append(row);
  });
}

async function cancelJobById(jobId) {
  const ok = await openKnowledgeConfirmModal({
    title: t('dynamic.appKnowledgePage.cancelJob'),
    message: t('dynamic.appKnowledgePage.organizeModal.cancelMessage'),
    confirmLabel: t('dynamic.appKnowledgePage.organizeModal.cancelConfirm'),
    danger: true,
  });
  if (!ok) return;
  try {
    await apiFetch(`/api/knowledge/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
    });
    showKnowledgeToast(t('dynamic.appKnowledgePage.jobCancelled'));
    await refreshJobs();
  } catch (error) {
    showKnowledgeToast(error.message, true);
  }
}

function notifyJobTerminalTransition(job) {
  if (notifiedTerminalJobIds.has(job.public_id)) return;
  if (organizeModalOpen && organizeModalJobId === job.public_id) {
    notifiedTerminalJobIds.add(job.public_id);
    return;
  }

  notifiedTerminalJobIds.add(job.public_id);
  const status = job?.status;
  const count = job?.generated_items ?? 0;
  if (status === 'completed') {
    showKnowledgeToast(t('dynamic.appKnowledgePage.jobCompleted', { count }), false);
    return;
  }
  if (status === 'completed_with_errors') {
    showKnowledgeToast(t('dynamic.appKnowledgePage.jobCompletedWithErrors', { count }), false);
    return;
  }
  if (status === 'cancelled') {
    showKnowledgeToast(t('dynamic.appKnowledgePage.jobCancelled'), false);
    return;
  }
  if (status === 'interrupted') {
    showKnowledgeToast(t('dynamic.appKnowledgePage.jobInterrupted'), true);
    return;
  }
  const errText = humanizeJobError(job?.error_message || '');
  showKnowledgeToast(
    errText
      ? t('dynamic.appKnowledgePage.jobFailedWithError', { error: errText })
      : t('dynamic.appKnowledgePage.jobFailed'),
    true,
  );
}

export function openFirstActiveJobModal() {
  const active = lastJobsList.find((j) => ACTIVE_JOB_STATUSES.has(j.status));
  if (active) {
    openOrganizeModalForJob(active.public_id, active.source_id || '');
  }
}

export async function refreshJobs() {
  if (!currentPackageId) return;
  const packageId = currentPackageId;
  const token = jobPollToken;
  try {
    const data = await apiFetch(
      `/api/knowledge/jobs?package_id=${encodeURIComponent(packageId)}`,
    );
    if (token !== jobPollToken || packageId !== currentPackageId) return;

    const jobs = data.jobs || [];
    let anyTerminalTransition = false;
    const transitionedJobs = [];

    jobs.forEach((job) => {
      const id = job.public_id;
      if (!id) return;
      const prev = previousJobStatusById.get(id);
      if (isActiveToTerminalTransition(prev, job.status)) {
        anyTerminalTransition = true;
        transitionedJobs.push(job);
      }
      previousJobStatusById.set(id, job.status);
    });

    renderJobs(jobs);
    if (currentPackageSnapshot) {
      updateOverview(currentPackageSnapshot, jobs);
    }

    if (anyTerminalTransition) {
      for (const job of transitionedJobs) {
        notifyJobTerminalTransition(job);
        if (organizeModalOpen && organizeModalJobId === job.public_id) {
          updateOrganizeModalFromJob(job);
        }
      }
      await loadItems();
      try {
        if (currentPackageId === packageId) {
          const pkg = await apiFetch(
            `/api/knowledge/packages/${encodeURIComponent(packageId)}`,
          );
          if (currentPackageId === packageId && pkg) {
            const snapshot = {
              ...pkg,
              source_count: pkg.sources?.length ?? currentPackageSnapshot?.source_count ?? 0,
              item_count: pkg.items?.total ?? currentPackageSnapshot?.item_count ?? 0,
            };
            setCurrentPackageSnapshot(snapshot);
            fillPackageForm(snapshot);
            updateOverview(snapshot, jobs);
          }
        }
      } catch (error) {
        console.warn('[knowledge] refresh package after job terminal failed', error);
      }
    }

    const anyActive = jobs.some((j) => ACTIVE_JOB_STATUSES.has(j.status));
    if (!anyActive) {
      stopKnowledgeJobPolling();
    }
  } catch (error) {
    console.warn('[knowledge] refreshJobs failed', error);
  }
}

export function startKnowledgeJobPolling(packagePublicId) {
  if (jobPollTimer) {
    if (jobPollPackageId !== packagePublicId) {
      stopKnowledgeJobPolling();
    } else {
      return;
    }
  }
  setCurrentPackageId(packagePublicId);
  setJobPollPackageId(packagePublicId);
  setJobPollTimer(
    window.setInterval(() => {
      refreshJobs().catch((error) => {
        console.warn('[knowledge] job poll failed', error);
      });
    }, JOB_POLL_INTERVAL_MS),
  );
}

export function stopKnowledgeJobPolling() {
  bumpJobPollToken();
  if (!jobPollTimer) return;
  window.clearInterval(jobPollTimer);
  setJobPollTimer(null);
}
