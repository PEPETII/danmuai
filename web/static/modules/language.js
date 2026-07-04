/**
 * Language preference sync + live Web i18n apply.
 */
import { API, apiFetch, authHeaders } from './transport.js';
import {
  applyI18n,
  getLanguage,
  initI18n,
  LANG_STORAGE_KEY,
  normalizeLanguage,
  setLanguage,
  storeLangLocal,
  t,
} from './i18n.js';

export { LANG_STORAGE_KEY, normalizeLanguage };

function getStoredLangLocal() {
  try {
    const value = localStorage.getItem(LANG_STORAGE_KEY);
    return normalizeLanguage(value);
  } catch {
    return 'zh';
  }
}

function applySelectValue(lang) {
  const select = document.getElementById('languageSelect');
  if (!select) return;
  select.value = normalizeLanguage(lang);
}

async function syncLanguageFromServer() {
  try {
    const body = await apiFetch('/api/language');
    const serverLang = normalizeLanguage(body?.language);
    storeLangLocal(serverLang);
    applySelectValue(serverLang);
    if (serverLang !== getLanguage()) {
      await setLanguage(serverLang);
      applyI18n();
    }
  } catch (e) {
    applySelectValue(getStoredLangLocal());
    console.warn('[language] sync from server failed', e);
  }
}

async function persistLanguageToServer(lang) {
  try {
    await fetch(`${API.base}/api/language`, {
      method: 'PUT',
      headers: authHeaders(),
      body: JSON.stringify({ language: lang }),
    });
  } catch (e) {
    console.warn('[language] persist to server failed', e);
  }
}

async function onChange(event, showToast) {
  const next = normalizeLanguage(event.target.value);
  const prev = getStoredLangLocal();
  if (next === prev) return;
  storeLangLocal(next);
  applySelectValue(next);
  await persistLanguageToServer(next);
  await setLanguage(next);
  applyI18n();
  const msg = t('dynamic.language.switched');
  if (typeof showToast === 'function') showToast(msg);
}

export function initLanguage({ showToast } = {}) {
  applySelectValue(getStoredLangLocal());
  const select = document.getElementById('languageSelect');
  if (select) {
    select.addEventListener('change', (e) => onChange(e, showToast));
  }
  syncLanguageFromServer();
}

export async function bootstrapI18n() {
  await initI18n();
  applyI18n();
}
