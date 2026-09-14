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

/**
 * 知识库 Web API 业务错误码 → i18n key。
 * HTTP 非 2xx 已由 transport.apiFetch() 抛错；这里的映射用于
 * 兜底识别历史上「200 + {error}」的响应体，避免再次出现假成功。
 */
export const KNOWLEDGE_API_ERROR_KEYS = {
  not_initialized: 'serviceUnavailable',
  runtime_unavailable: 'serviceUnavailable',
  service_unavailable: 'serviceUnavailable',
  orchestrator_not_ready: 'serviceUnavailable',
  retriever_not_ready: 'serviceUnavailable',
  orchestrator_stopping: 'stopping',
  not_found: 'notFound',
  package_not_found: 'notFound',
  not_found_or_completed: 'notFound',
  missing_query: 'missingQuery',
  missing_pasted_text: 'invalidRequest',
  missing_content_base64: 'invalidRequest',
  missing_source_url: 'invalidRequest',
  invalid_base64: 'invalidRequest',
  invalid_source_url: 'invalidRequest',
  unknown_source_type: 'invalidRequest',
  parameter_bad: 'invalidRequest',
  source_too_large: 'sourceTooLarge',
  internal_error: 'internal',
};

export function humanizeKnowledgeApiError(code) {
  const raw = String(code || '').trim();
  if (!raw) return '';
  const key = KNOWLEDGE_API_ERROR_KEYS[raw];
  if (key) {
    // 显式传空默认值：locale 分片未加载时 t() 会退化成 key 的末段
    // （如 'notFound'），那属于伪文案，必须回退到原始错误码。
    const localized = t(`dynamic.appKnowledgePage.apiErrors.${key}`, undefined, '');
    if (localized) return localized;
  }
  return raw;
}

/**
 * 知识库调用失败时的可读文案。
 *
 * HTTP 非 2xx 的响应体是 `{"detail": {"ok": false, "error": "<code>"}}`，
 * `formatApiError()` 会取到裸错误码；这里优先把它翻译成用户可理解的中文，
 * 未知错误码再回退到原始 message / 给定兜底文案。
 */
export function knowledgeErrorMessage(error, fallback = '') {
  const code = typeof error?.code === 'string' ? error.code : '';
  if (code && KNOWLEDGE_API_ERROR_KEYS[code]) {
    return humanizeKnowledgeApiError(code);
  }
  const message = String(error?.message || '').trim();
  return message || fallback;
}

/**
 * 防御性校验：业务失败不得被当作成功。
 *
 * 正常情况下非 2xx 已由 apiFetch() 抛错；此函数只处理旧接口返回
 * `200 + {"error": "xxx"}` 的残留形态，抛出的 Error 带 `code` 字段，
 * 便于调用方区分处理。始终返回原 payload（无 error 时）。
 */
export function assertKnowledgePayload(data) {
  if (data && typeof data === 'object' && !Array.isArray(data)) {
    const code = data.error;
    if (typeof code === 'string' && code) {
      const error = new Error(humanizeKnowledgeApiError(code));
      error.code = code;
      throw error;
    }
  }
  return data;
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
