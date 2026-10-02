import { apiFetch } from './transport.js';
import { createAutoSave } from './auto-save.js';
import { t } from './i18n.js';

const MAX_PROMPT_CHARS = 8000;

let toast = () => {};
let handlersBound = false;
let personaCache = null;
let personaSaveToken = 0;
let personaRequestInFlight = false;

function element(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  const target = element(id);
  if (target) target.textContent = value || '';
}

function renderPersonaStatus(message) {
  setText('vtuberPersonaStatus', message || '');
}

function applyPersonaForm(data) {
  const systemField = element('vtuberPersonaSystemPrompt');
  const voiceField = element('vtuberPersonaVoicePrompt');
  if (systemField) systemField.value = String(data?.system_prompt || '');
  if (voiceField) voiceField.value = String(data?.voice_dialogue_prompt || '');
}

function readPersonaForm() {
  return {
    system_prompt: String(element('vtuberPersonaSystemPrompt')?.value || '').trim(),
    voice_dialogue_prompt: String(element('vtuberPersonaVoicePrompt')?.value || '').trim(),
  };
}

function setPersonaControlsDisabled(disabled) {
  const saveButton = element('btnVtuberPersonaSave');
  const resetButton = element('btnVtuberPersonaReset');
  const systemField = element('vtuberPersonaSystemPrompt');
  const voiceField = element('vtuberPersonaVoicePrompt');
  if (saveButton) saveButton.disabled = disabled;
  if (resetButton) resetButton.disabled = disabled;
  if (systemField) systemField.disabled = disabled;
  if (voiceField) voiceField.disabled = disabled;
}

function validatePersonaPayload(payload) {
  for (const key of ['system_prompt', 'voice_dialogue_prompt']) {
    const value = String(payload[key] || '').trim();
    if (!value) throw new Error('Prompt 不能为空');
    if (value.length > MAX_PROMPT_CHARS) throw new Error(`Prompt 不能超过 ${MAX_PROMPT_CHARS} 个字符`);
  }
}

const vtuberPersonaAutoSave = createAutoSave({
  capture: readPersonaForm,
  save: (payload, options) => persistVtuberPersona(payload, options),
  onState: (state, error) => {
    if (state === 'saving') renderPersonaStatus(t('dynamic.autoSaveStatus.saving'));
    if (state === 'saved') renderPersonaStatus(t('dynamic.autoSaveStatus.saved'));
    if (state === 'error') {
      renderPersonaStatus(error?.message || t('dynamic.autoSaveStatus.error'));
      toast(error?.message || t('dynamic.autoSaveStatus.error'), true);
    }
  },
  delay: 800,
});

export async function loadVtuberPersonaPage({ silent = false } = {}) {
  try {
    const data = await apiFetch('/api/virtual-host/persona');
    personaCache = data;
    applyPersonaForm(data);
    if (!silent) renderPersonaStatus('已加载当前虚拟主播人格配置。');
    return data;
  } catch (error) {
    if (!silent) renderPersonaStatus(error?.message || '读取虚拟主播人格失败');
    throw error;
  }
}

async function persistVtuberPersona(payload, { isLatest = () => true, restoreOnError = false } = {}) {
  if (personaRequestInFlight) return null;
  validatePersonaPayload(payload);
  const token = ++personaSaveToken;
  personaRequestInFlight = true;
  setPersonaControlsDisabled(true);
  renderPersonaStatus('正在保存…');
  try {
    const data = await apiFetch('/api/virtual-host/persona', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (token !== personaSaveToken || !isLatest()) return data;
    personaCache = data;
    applyPersonaForm(data);
    renderPersonaStatus('虚拟主播人格已保存。');
    toast('虚拟主播人格已保存');
    return data;
  } catch (error) {
    if (restoreOnError && token === personaSaveToken && personaCache) applyPersonaForm(personaCache);
    renderPersonaStatus(error?.message || '保存虚拟主播人格失败');
    throw error;
  } finally {
    personaRequestInFlight = false;
    setPersonaControlsDisabled(false);
  }
}

async function saveVtuberPersona() {
  return persistVtuberPersona(readPersonaForm(), { restoreOnError: true });
}

async function resetVtuberPersona() {
  if (personaRequestInFlight) return null;
  if (!confirm(t('dynamic.autoSaveStatus.restoreConfirm'))) return null;
  const token = ++personaSaveToken;
  personaRequestInFlight = true;
  setPersonaControlsDisabled(true);
  renderPersonaStatus('正在恢复默认…');
  try {
    const data = await apiFetch('/api/virtual-host/persona?reset=true', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    if (token !== personaSaveToken) return data;
    personaCache = data;
    applyPersonaForm(data);
    renderPersonaStatus('已恢复默认虚拟主播人格。');
    toast('已恢复默认虚拟主播人格');
    return data;
  } catch (error) {
    if (token === personaSaveToken && personaCache) applyPersonaForm(personaCache);
    renderPersonaStatus(error?.message || '恢复默认失败');
    throw error;
  } finally {
    personaRequestInFlight = false;
    setPersonaControlsDisabled(false);
  }
}

export function initVtuberPersonaPage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;

  if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
    window.addEventListener('pagehide', () => vtuberPersonaAutoSave.cancel());
  }

  element('btnVtuberPersonaSave')?.addEventListener('click', () => {
    saveVtuberPersona().catch((error) => toast(error.message, true));
  });
  element('vtuberPersonaSystemPrompt')?.addEventListener('input', () => {
    vtuberPersonaAutoSave.schedule();
  });
  element('vtuberPersonaVoicePrompt')?.addEventListener('input', () => {
    vtuberPersonaAutoSave.schedule();
  });
  [element('vtuberPersonaSystemPrompt'), element('vtuberPersonaVoicePrompt')].forEach((field) => {
    field?.addEventListener('change', () => {
      vtuberPersonaAutoSave.schedule({ immediate: true });
      vtuberPersonaAutoSave.flush().catch(() => {});
    });
  });
  element('btnVtuberPersonaReset')?.addEventListener('click', () => {
    resetVtuberPersona().catch((error) => toast(error.message, true));
  });
}

export function onVtuberPersonaTabActivated() {
  loadVtuberPersonaPage({ silent: true }).catch(() => {});
}
