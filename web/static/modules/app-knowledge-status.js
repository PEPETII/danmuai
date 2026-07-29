import { t } from './i18n.js';
import {
  ACTIVE_JOB_STATUSES,
  JOB_ERROR_CODE_KEYS,
  TERMINAL_JOB_STATUSES,
} from './app-knowledge-state.js';

/**
 * 检测 job 是否从 ACTIVE 转入 TERMINAL。
 * @param {string|undefined|null} previousStatus
 * @param {string|undefined|null} nextStatus
 */
export function isActiveToTerminalTransition(previousStatus, nextStatus) {
  if (!TERMINAL_JOB_STATUSES.has(nextStatus)) return false;
  if (previousStatus == null || previousStatus === '') return false;
  return ACTIVE_JOB_STATUSES.has(previousStatus);
}

export function statusKey(status) {
  const map = {
    pending: 'userStatusPending',
    running: 'userStatusRunning',
    completed: 'userStatusCompleted',
    completed_with_errors: 'userStatusCompletedWithErrors',
    failed: 'userStatusFailed',
    cancelled: 'userStatusCancelled',
    interrupted: 'userStatusInterrupted',
  };
  return map[status] || 'userStatusPending';
}

export function stageKey(stage) {
  const map = {
    queued: 'organizeStageQueued',
    extracting: 'organizeStageExtracting',
    chunking: 'organizeStageChunking',
    organizing: 'organizeStageOrganizing',
    finished: 'organizeStageFinished',
    failed: 'organizeStageFailed',
    cancelled: 'organizeStageCancelled',
  };
  return map[stage] || '';
}

export function organizeStageKey(stage) {
  return stageKey(stage);
}

function extractErrorCode(errorMessage) {
  if (!errorMessage) return '';
  const raw = String(errorMessage).trim();
  if (!raw) return '';
  if (Object.prototype.hasOwnProperty.call(JOB_ERROR_CODE_KEYS, raw)) return raw;
  for (const code of Object.keys(JOB_ERROR_CODE_KEYS)) {
    if (raw === code || raw.startsWith(`${code}:`) || raw.includes(code)) {
      return code;
    }
  }
  return '';
}

export function humanizeJobError(errorMessage) {
  if (!errorMessage) return '';
  const code = extractErrorCode(errorMessage);
  if (code) {
    const key = JOB_ERROR_CODE_KEYS[code];
    const localized = t(`dynamic.appKnowledgePage.errors.${key}`);
    if (localized && !localized.includes('errors.')) {
      return localized;
    }
  }
  return String(errorMessage);
}

export function kindKey(kind) {
  const map = {
    fact: 'kindFact',
    reaction_pattern: 'kindReaction',
    meme: 'kindMeme',
    style_example: 'kindStyle',
  };
  return map[kind] || 'kindFact';
}

export function jobStatusBadgeClass(status) {
  if (status === 'completed') return 'knowledge-status-badge--success';
  if (status === 'running') return 'knowledge-status-badge--running';
  if (status === 'pending') return 'knowledge-status-badge--muted';
  if (status === 'failed' || status === 'interrupted') return 'knowledge-status-badge--error';
  if (status === 'completed_with_errors') return 'knowledge-status-badge--warn';
  if (status === 'cancelled') return 'knowledge-status-badge--muted';
  return 'knowledge-status-badge--muted';
}

/**
 * 列表卡片状态（纯函数）。
 * @param {object} pkg
 * @param {object[]} packageJobs
 */
export function computePackageCardState(pkg, packageJobs = []) {
  const sourceCount = pkg.source_count ?? 0;
  const itemCount = pkg.item_count ?? 0;
  const enabled = Boolean(pkg.enabled);

  const hasActiveJob = packageJobs.some((j) => ACTIVE_JOB_STATUSES.has(j.status));
  const hasFailureJob = packageJobs.some(
    (j) =>
      j.status === 'failed' ||
      j.status === 'completed_with_errors' ||
      j.status === 'interrupted',
  );

  let statusKeyName = 'readyComplete';
  let nextStepKey = 'enableToUse';

  if (hasActiveJob) {
    statusKeyName = 'processing';
    nextStepKey = 'processingSub';
  } else if (sourceCount === 0) {
    statusKeyName = 'noSources';
    nextStepKey = 'addFirstSource';
  } else if (hasFailureJob) {
    statusKeyName = 'partialFail';
    nextStepKey = 'checkFailures';
  } else if (itemCount > 0 && !enabled) {
    statusKeyName = 'readyComplete';
    nextStepKey = 'enableToUse';
  } else if (enabled && itemCount > 0) {
    statusKeyName = 'activeRetrieval';
    nextStepKey = 'activeRetrievalSub';
  } else if (enabled && itemCount === 0) {
    statusKeyName = 'enabledEmpty';
    nextStepKey = 'addSource';
  }

  const badgeKey =
    enabled
      ? 'badgeEnabled'
      : itemCount > 0 || sourceCount > 0
        ? 'badgeNotEnabled'
        : 'badgeNeedsWork';

  return {
    statusKey: statusKeyName,
    nextStepKey,
    badgeKey,
    hasActiveJob,
  };
}

export function formatElapsedMs(ms) {
  const totalSec = Math.max(0, Math.floor(ms / 1000));
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return `${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

export function parseCommaList(text) {
  if (!text) return [];
  return String(text)
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}
