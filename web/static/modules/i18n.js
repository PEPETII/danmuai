/**
 * Web console i18n — locale JSON shards + DOM apply.
 */
import { API, apiFetch } from './transport.js';

const LANG_STORAGE_KEY = 'danmu_console_language';
const LOCALE_SHARDS = [
  'common', 'nav', 'overview', 'settings', 'content', 'modals', 'hints', 'dynamic',
];
const SUPPORTED_LANGUAGES = ['zh', 'en'];
const DEFAULT_LANGUAGE = 'zh';

/** @type {Record<string, string>} */
let _dict = {};
/** @type {Record<string, string>} cached zh flat dict for source-text lookup */
let _zhDict = {};
/** @type {Record<string, string>} cached en flat dict for bidirectional reverse lookup */
let _enDict = {};
let _lang = 'zh';
let _ready = false;
/** Maps any known locale string (zh or en) -> i18n key */
let _sourceTextToKey = new Map();
/** Trimmed zh+en locale values for acceptNode fallback */
let _knownLocaleTexts = new Set();
/** @type {Set<(lang: string) => void>} */
const _languageChangeListeners = new Set();

function normalizeLanguage(value) {
  if (typeof value === 'string' && SUPPORTED_LANGUAGES.includes(value)) {
    return value;
  }
  return DEFAULT_LANGUAGE;
}

function getStoredLangLocal() {
  try {
    const value = localStorage.getItem(LANG_STORAGE_KEY);
    return normalizeLanguage(value);
  } catch {
    return 'zh';
  }
}

function storeLangLocal(lang) {
  try {
    localStorage.setItem(LANG_STORAGE_KEY, normalizeLanguage(lang));
  } catch {
    /* ignore */
  }
}

function flattenDict(nested, prefix = '') {
  const out = {};
  for (const [key, val] of Object.entries(nested || {})) {
    const full = prefix ? `${prefix}.${key}` : key;
    if (val && typeof val === 'object' && !Array.isArray(val)) {
      Object.assign(out, flattenDict(val, full));
    } else {
      out[full] = String(val ?? '');
    }
  }
  return out;
}

async function fetchShard(lang, name) {
  const res = await fetch(`/static/locales/${lang}/${name}.json`);
  if (!res.ok) throw new Error(`locale shard missing: ${lang}/${name}.json`);
  return res.json();
}

async function loadFlatDict(lang) {
  const shards = await Promise.all(LOCALE_SHARDS.map((n) => fetchShard(lang, n)));
  const dict = {};
  for (const shard of shards) {
    Object.assign(dict, flattenDict(shard));
  }
  return dict;
}

async function loadLocaleDictsIfNeeded() {
  if (Object.keys(_zhDict).length === 0) {
    _zhDict = await loadFlatDict('zh');
  }
  if (Object.keys(_enDict).length === 0) {
    _enDict = await loadFlatDict('en');
  }
}

function rebuildSourceTextToKey() {
  _sourceTextToKey = new Map();
  _knownLocaleTexts = new Set();
  for (const dict of [_zhDict, _enDict]) {
    for (const [key, text] of Object.entries(dict)) {
      const trimmed = String(text ?? '').trim();
      if (!trimmed) continue;
      _knownLocaleTexts.add(trimmed);
      if (!_sourceTextToKey.has(trimmed)) {
        _sourceTextToKey.set(trimmed, key);
      }
    }
  }
}

export function onLanguageChanged(fn) {
  _languageChangeListeners.add(fn);
  return () => _languageChangeListeners.delete(fn);
}

export function notifyLanguageChanged(lang = _lang) {
  for (const listener of _languageChangeListeners) {
    try {
      listener(lang);
    } catch (err) {
      console.warn('[i18n] language listener failed', err);
    }
  }
}

export async function loadLocale(lang) {
  const normalized = normalizeLanguage(lang);
  await loadLocaleDictsIfNeeded();
  const shards = await Promise.all(LOCALE_SHARDS.map((n) => fetchShard(normalized, n)));
  _dict = {};
  for (const shard of shards) {
    Object.assign(_dict, flattenDict(shard));
  }
  _lang = normalized;
  _ready = true;
  rebuildSourceTextToKey();
  const htmlLang = normalized === 'zh' ? 'zh-CN' : 'en';
  document.documentElement.lang = htmlLang;
  return normalized;
}

export function getLanguage() {
  return _lang;
}

export function isI18nReady() {
  return _ready;
}

/**
 * @param {string} key dot-separated key
 * @param {Record<string, string|number>|undefined} params
 */
export function t(key, params) {
  let text = _dict[key];
  if (text == null || text === '') {
    text = key;
  }
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      text = text.replace(new RegExp(`\\{${k}\\}`, 'g'), String(v));
    }
  }
  return text;
}

function applyToElement(el) {
  const key = el.getAttribute('data-i18n');
  if (key) {
    const val = t(key);
    if (el.hasAttribute('data-i18n-html')) {
      el.innerHTML = val;
    } else {
      el.textContent = val;
    }
  }
  const phKey = el.getAttribute('data-i18n-placeholder');
  if (phKey) el.placeholder = t(phKey);
  const ariaKey = el.getAttribute('data-i18n-aria-label');
  if (ariaKey) el.setAttribute('aria-label', t(ariaKey));
  const titleKey = el.getAttribute('data-i18n-title');
  if (titleKey) el.title = t(titleKey);
}

function applyTextNodeWalk(root) {
  if (_sourceTextToKey.size === 0) return;
  const body = root.body || root;
  if (!body) return;
  const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT, {
    acceptNode(node) {
      const p = node.parentElement;
      if (!p || p.closest('script, style, textarea, pre, code')) {
        return NodeFilter.FILTER_REJECT;
      }
      const trimmed = (node.textContent || '').trim();
      if (!trimmed) return NodeFilter.FILTER_REJECT;
      if (_sourceTextToKey.has(trimmed)) return NodeFilter.FILTER_ACCEPT;
      if (_knownLocaleTexts.has(trimmed)) return NodeFilter.FILTER_ACCEPT;
      if (/[\u4e00-\u9fff]/.test(node.textContent || '')) return NodeFilter.FILTER_ACCEPT;
      return NodeFilter.FILTER_REJECT;
    },
  });
  const nodes = [];
  while (walker.nextNode()) nodes.push(walker.currentNode);
  for (const node of nodes) {
    const trimmed = (node.textContent || '').trim();
    if (!trimmed) continue;
    const key = _sourceTextToKey.get(trimmed);
    if (!key) continue;
    const translated = t(key);
    if (translated === trimmed) continue;
    node.textContent = (node.textContent || '').replace(trimmed, translated);
  }
}

export function applyI18n(root = document) {
  if (!_ready) return;
  root.querySelectorAll('[data-i18n], [data-i18n-placeholder], [data-i18n-aria-label], [data-i18n-title]').forEach(applyToElement);
  const titleEl = document.querySelector('title[data-i18n]');
  if (titleEl) {
    document.title = t(titleEl.getAttribute('data-i18n'));
  }
  applyTextNodeWalk(root.body || root);
}

export async function setLanguage(lang) {
  await loadLocale(lang);
  storeLangLocal(lang);
  applyI18n();
  notifyLanguageChanged(_lang);
  return _lang;
}

async function resolveInitialLanguage() {
  try {
    const body = await apiFetch('/api/language');
    return normalizeLanguage(body?.language || getStoredLangLocal());
  } catch {
    return getStoredLangLocal();
  }
}

export async function initI18n() {
  const lang = await resolveInitialLanguage();
  await setLanguage(lang);
  return lang;
}

export { storeLangLocal, normalizeLanguage, LANG_STORAGE_KEY };
