import { apiFetch } from './transport.js';
import { t } from './i18n.js';
import {
  ACTIVE_JOB_STATUSES,
  currentPackageId,
  MAX_CLIENT_FILE_BYTES,
  previousJobStatusById,
  showKnowledgeToast,
} from './app-knowledge-state.js';
import {
  refreshJobs,
  startKnowledgeJobPolling,
  openOrganizeModalForJob,
} from './app-knowledge-jobs.js';

const IMPORT_BTN_KEYS = {
  pasted_text: 'importPastedText',
  txt: 'importTxt',
  markdown: 'importMarkdown',
  webpage: 'importWebpage',
};

function setFieldError(id, message) {
  const el = document.getElementById(id);
  if (!el) return;
  if (message) {
    el.textContent = message;
    el.classList.remove('hidden');
  } else {
    el.textContent = '';
    el.classList.add('hidden');
  }
}

function clearImportErrors() {
  setFieldError('knowledgePastedTextError', '');
  setFieldError('knowledgeSourceUrlError', '');
  setFieldError('knowledgeSourceFileError', '');
}

export function clearFileInput() {
  const fileEl = document.getElementById('knowledgeSourceFile');
  const nameEl = document.getElementById('knowledgeSourceFileName');
  if (fileEl) fileEl.value = '';
  if (nameEl) nameEl.textContent = '';
}

function updateSourceFileAccept(sourceType) {
  const fileEl = document.getElementById('knowledgeSourceFile');
  if (!fileEl) return;
  if (sourceType === 'txt') {
    fileEl.accept = '.txt,text/plain';
  } else if (sourceType === 'markdown') {
    fileEl.accept = '.md,.markdown,text/markdown,text/x-markdown';
  } else {
    fileEl.accept = '.txt,.md,.markdown,text/plain,text/markdown';
  }
}

export function syncSourceFormVisibility() {
  const type = document.getElementById('knowledgeSourceType')?.value || 'pasted_text';
  const urlWrap = document.getElementById('knowledgeSourceUrlWrap');
  const textWrap = document.getElementById('knowledgePastedTextWrap');
  const fileWrap = document.getElementById('knowledgeSourceFileWrap');
  if (urlWrap) urlWrap.classList.toggle('hidden', type !== 'webpage');
  if (textWrap) textWrap.classList.toggle('hidden', type !== 'pasted_text');
  if (fileWrap) fileWrap.classList.toggle('hidden', type !== 'txt' && type !== 'markdown');
  updateSourceFileAccept(type);
  updateImportButtonLabel(type);
  updatePastedTextCount();
}

function updateImportButtonLabel(sourceType) {
  const btn = document.getElementById('btnKnowledgeStartImport');
  if (!btn) return;
  const key = IMPORT_BTN_KEYS[sourceType] || 'startImport';
  btn.textContent = t(`dynamic.appKnowledgePage.${key}`);
}

export function updatePastedTextCount() {
  const textEl = document.getElementById('knowledgePastedText');
  const countEl = document.getElementById('knowledgePastedTextCount');
  if (!countEl) return;
  const len = (textEl?.value || '').length;
  countEl.textContent = t('dynamic.appKnowledgePage.pastedTextCount', { count: len });
}

export function onSourceTypeChange() {
  const type = document.getElementById('knowledgeSourceType')?.value || 'pasted_text';
  const textEl = document.getElementById('knowledgePastedText');
  const urlEl = document.getElementById('knowledgeSourceUrl');
  if (type !== 'pasted_text' && textEl) textEl.value = '';
  if (type !== 'webpage' && urlEl) urlEl.value = '';
  if (type !== 'txt' && type !== 'markdown') clearFileInput();
  clearImportErrors();
  syncSourceFormVisibility();
  document.querySelectorAll('[data-knowledge-source-type]').forEach((btn) => {
    const active = btn.getAttribute('data-knowledge-source-type') === type;
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-pressed', String(active));
  });
}

export function onSourceFileChange() {
  const fileEl = document.getElementById('knowledgeSourceFile');
  const nameEl = document.getElementById('knowledgeSourceFileName');
  const file = fileEl?.files?.[0];
  if (!nameEl) return;
  if (!file) {
    nameEl.textContent = '';
    return;
  }
  nameEl.textContent = t('dynamic.appKnowledgePage.fileSelected', { name: file.name });
  const displayName = document.getElementById('knowledgeDisplayName');
  if (displayName && !displayName.value.trim()) {
    displayName.value = file.name;
  }
}

function fileExtension(name) {
  const idx = String(name || '').lastIndexOf('.');
  if (idx < 0) return '';
  return String(name).slice(idx + 1).toLowerCase();
}

function isMatchingFileType(sourceType, fileName) {
  const ext = fileExtension(fileName);
  if (sourceType === 'txt') return ext === 'txt';
  if (sourceType === 'markdown') return ext === 'md' || ext === 'markdown';
  return false;
}

function arrayBufferToBase64(buffer) {
  const bytes = new Uint8Array(buffer);
  const chunkSize = 0x8000;
  let binary = '';
  for (let i = 0; i < bytes.length; i += chunkSize) {
    const chunk = bytes.subarray(i, i + chunkSize);
    binary += String.fromCharCode.apply(null, chunk);
  }
  return btoa(binary);
}

async function readFileAsBase64(file) {
  const buffer = await file.arrayBuffer();
  return arrayBufferToBase64(buffer);
}

function clearImportInputs() {
  const textEl = document.getElementById('knowledgePastedText');
  const urlEl = document.getElementById('knowledgeSourceUrl');
  const nameEl = document.getElementById('knowledgeDisplayName');
  if (textEl) textEl.value = '';
  if (urlEl) urlEl.value = '';
  if (nameEl) nameEl.value = '';
  clearFileInput();
  updatePastedTextCount();
}

export function syncImportFormState(activeJobs = []) {
  const hint = document.getElementById('knowledgeImportActiveHint');
  const btn = document.getElementById('btnKnowledgeStartImport');
  const hasActive = activeJobs.some((j) => ACTIVE_JOB_STATUSES.has(j.status));
  if (hint) {
    hint.classList.toggle('hidden', !hasActive);
    if (hasActive) {
      hint.textContent = t('dynamic.appKnowledgePage.importBlockedActive');
    }
  }
  if (btn) btn.disabled = hasActive;
}

export async function startImport() {
  if (!currentPackageId) return;
  clearImportErrors();
  const sourceType = document.getElementById('knowledgeSourceType')?.value || 'pasted_text';
  let displayName = (document.getElementById('knowledgeDisplayName')?.value || '').trim();
  const body = {
    source_type: sourceType,
    display_name: displayName,
  };

  if (sourceType === 'pasted_text') {
    const pasted = (document.getElementById('knowledgePastedText')?.value || '').trim();
    if (!pasted) {
      setFieldError(
        'knowledgePastedTextError',
        t('dynamic.appKnowledgePage.pastedTextRequired'),
      );
      return;
    }
    body.pasted_text = pasted;
    if (!displayName) {
      const stamp = new Date().toLocaleString();
      body.display_name = t('dynamic.appKnowledgePage.pastedTextDefaultName', { time: stamp });
    }
  } else if (sourceType === 'webpage') {
    const url = (document.getElementById('knowledgeSourceUrl')?.value || '').trim();
    if (!url) {
      setFieldError('knowledgeSourceUrlError', t('dynamic.appKnowledgePage.urlRequired'));
      return;
    }
    try {
      const parsed = new URL(url);
      if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') {
        setFieldError('knowledgeSourceUrlError', t('dynamic.appKnowledgePage.urlInvalid'));
        return;
      }
    } catch {
      setFieldError('knowledgeSourceUrlError', t('dynamic.appKnowledgePage.urlInvalid'));
      return;
    }
    body.source_url = url;
  } else if (sourceType === 'txt' || sourceType === 'markdown') {
    const fileEl = document.getElementById('knowledgeSourceFile');
    const file = fileEl?.files?.[0];
    if (!file) {
      setFieldError('knowledgeSourceFileError', t('dynamic.appKnowledgePage.fileRequired'));
      return;
    }
    if (!isMatchingFileType(sourceType, file.name)) {
      setFieldError('knowledgeSourceFileError', t('dynamic.appKnowledgePage.fileTypeMismatch'));
      return;
    }
    if (file.size <= 0) {
      setFieldError('knowledgeSourceFileError', t('dynamic.appKnowledgePage.fileEmpty'));
      return;
    }
    if (file.size > MAX_CLIENT_FILE_BYTES) {
      setFieldError('knowledgeSourceFileError', t('dynamic.appKnowledgePage.fileTooLarge'));
      return;
    }
    if (!displayName) {
      displayName = file.name;
      body.display_name = displayName;
    }
    try {
      body.content_base64 = await readFileAsBase64(file);
    } catch (error) {
      setFieldError(
        'knowledgeSourceFileError',
        error.message || t('dynamic.appKnowledgePage.fileEmpty'),
      );
      return;
    }
  } else {
    showKnowledgeToast(t('dynamic.appKnowledgePage.loadFailed'), true);
    return;
  }

  try {
    const result = await apiFetch(
      `/api/knowledge/packages/${encodeURIComponent(currentPackageId)}/imports`,
      { method: 'POST', body: JSON.stringify(body) },
    );
    if (result?.job_id) {
      previousJobStatusById.set(result.job_id, 'pending');
      openOrganizeModalForJob(result.job_id, body.display_name || displayName);
    }
    clearImportInputs();
    await refreshJobs();
    startKnowledgeJobPolling(currentPackageId);
  } catch (error) {
    showKnowledgeToast(error.message, true);
  }
}

export function bindSourceTypeCards() {
  document.querySelectorAll('[data-knowledge-source-type]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const type = btn.getAttribute('data-knowledge-source-type');
      const select = document.getElementById('knowledgeSourceType');
      if (select && type) {
        select.value = type;
        onSourceTypeChange();
      }
    });
  });
  document.getElementById('knowledgeSourceType')?.addEventListener('change', () => {
    onSourceTypeChange();
  });
  document.getElementById('knowledgeSourceFile')?.addEventListener('change', () => {
    onSourceFileChange();
  });
  document.getElementById('knowledgePastedText')?.addEventListener('input', () => {
    updatePastedTextCount();
    setFieldError('knowledgePastedTextError', '');
  });
  document.getElementById('knowledgeSourceUrl')?.addEventListener('input', () => {
    setFieldError('knowledgeSourceUrlError', '');
  });
}

export function focusAddSourceSection() {
  const section = document.getElementById('knowledgeAddSource');
  section?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  document.getElementById('knowledgeDisplayName')?.focus();
}
