/** 知识包页面共享运行态（跨子模块）。 */

export const JOB_POLL_INTERVAL_MS = 2000;
export const ITEMS_PAGE_SIZE = 50;
export const ACTIVE_JOB_STATUSES = new Set(['pending', 'running']);
export const TERMINAL_JOB_STATUSES = new Set([
  'completed',
  'completed_with_errors',
  'failed',
  'cancelled',
  'interrupted',
]);
export const MAX_CLIENT_FILE_BYTES = 5 * 1024 * 1024;

export const JOB_ERROR_CODE_KEYS = {
  empty_content: 'emptyContent',
  decode_failed: 'decodeFailed',
  source_too_large: 'sourceTooLarge',
  ssrf_blocked: 'ssrfBlocked',
  timeout: 'timeout',
  http_error: 'httpError',
  unsupported_content_type: 'unsupportedContentType',
  no_items_generated: 'noItemsGenerated',
  no_chunks_generated: 'noChunksGenerated',
  cancelled: 'cancelled',
};

let toastFn = () => {};

export function setKnowledgeToast(fn) {
  toastFn = fn || toastFn;
}

export function showKnowledgeToast(message, isError = false) {
  toastFn(message, isError);
}

export let currentPackageId = null;
export let currentPackageSnapshot = null;
export let jobPollTimer = null;
export let jobPollPackageId = null;
export let jobPollToken = 0;
export let previousJobStatusById = new Map();
export let itemPage = 1;
export let itemTotalPages = 1;

export let organizeModalJobId = null;
export let organizeModalOpen = false;
export let organizeModalDisplayName = '';
export let organizeModalStartTime = 0;
export let organizeModalElapsedTimer = null;
export const notifiedTerminalJobIds = new Set();

export function resetPackageContext() {
  currentPackageId = null;
  currentPackageSnapshot = null;
  jobPollPackageId = null;
  previousJobStatusById = new Map();
  itemPage = 1;
  itemTotalPages = 1;
  clearOrganizeModalTracking();
}

export function clearOrganizeModalTracking() {
  organizeModalJobId = null;
  organizeModalOpen = false;
  organizeModalDisplayName = '';
  organizeModalStartTime = 0;
  if (organizeModalElapsedTimer) {
    window.clearInterval(organizeModalElapsedTimer);
    organizeModalElapsedTimer = null;
  }
}

export function setCurrentPackageId(id) {
  currentPackageId = id;
}

export function setCurrentPackageSnapshot(snapshot) {
  currentPackageSnapshot = snapshot;
}

export function setJobPollPackageId(id) {
  jobPollPackageId = id;
}

export function bumpJobPollToken() {
  jobPollToken += 1;
}

export function setItemPage(page) {
  itemPage = page;
}

export function setItemTotalPages(pages) {
  itemTotalPages = pages;
}

export function resetPreviousJobStatuses() {
  previousJobStatusById = new Map();
}

export function setOrganizeModalOpen(open) {
  organizeModalOpen = open;
}

export function setOrganizeModalJobId(id) {
  organizeModalJobId = id;
}

export function setOrganizeModalDisplayName(name) {
  organizeModalDisplayName = name;
}

export function setJobPollTimer(timer) {
  jobPollTimer = timer;
}

export function setOrganizeModalStartTime(ms) {
  organizeModalStartTime = ms;
}

export function setOrganizeModalElapsedTimer(timer) {
  organizeModalElapsedTimer = timer;
}
