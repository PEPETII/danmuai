/** DanmuAI Web Console — 温馨 Qwen 原型 */

import {
  API,
  REALTIME,
  apiFetch,
  formatApiError,
  refreshSession,
  setRealtimeHandlers,
  startRealtimeTransport,
} from './modules/transport.js';
import { applyStatus, configureStatus } from './modules/status.js';
import {
  appendLog,
  bootstrapLogsFromServer,
  logBuffer,
  logEntryKey,
  logLevelFilters,
  mergeLogItems,
  mergeLogItemsUnique,
  formatLogLine,
  renderLogView,
  replaceLogLevelFilters,
  setLogAutoScroll,
  updateLogPanelState,
} from './modules/logs.js';
import {
  buildDiagnosticReportText,
  initDiagnosticsPanel,
} from './modules/diagnostics.js';
import {
  applyCaptureRegionFromPayload,
  reloadConfigFromServer,
  loadConfigDefaults,
  loadScreens,
  loadCustomModels,
  loadProviders,
  loadModelCatalog,
  initSettingsTabs,
  initSettingsUiMode,
  initSettingsFieldHints,
  initRestoreDefaultsControls,
  initCaptureRegionControls,
  initNormalBatchControls,
  initSidebarNavFloatingHints,
  bindSettingsControls,
} from './modules/settings.js';
import {
  loadAnnouncementsReadState,
  refreshAnnouncementsUnreadBadge,
  startAnnouncementsBadgePolling,
  stopAnnouncementsBadgePolling,
  loadAnnouncementsPage,
  initFeedbackPage,
  initAiButlerPage,
  updateAnnouncementsNavBadge,
  bindContentPageControls,
} from './modules/content-pages.js';

let currentPersonaId = '';

const ERROR_REPORT_DISMISS_STORAGE = 'danmu_error_report_dismiss';
const ERROR_REPORT_DEDUP_MS = 24 * 60 * 60 * 1000;
const ERROR_REPORT_LOG_WINDOW_SEC = 90;
const ERROR_REPORT_LOG_LINE_RADIUS = 40;
let errorReportAnchor = null;
let errorReportSubmitting = false;

function enc(name) {
  return encodeURIComponent(name);
}

function showToast(msg, isError = false) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.className = `toast show ${isError ? 'text-red-700' : 'text-warmText'}`;
  setTimeout(() => el.classList.remove('show'), 3200);
}

window.addEventListener('unhandledrejection', (event) => {
  const reason = event.reason;
  const message = reason instanceof Error ? reason.message : String(reason ?? 'unknown');
  console.warn('[app] unhandled promise rejection:', reason);
  showToast(`操作失败: ${message}`, true);
});


function loadErrorReportDismissMap() {
  try {
    let raw = localStorage.getItem(ERROR_REPORT_DISMISS_STORAGE);
    if (!raw) {
      raw = sessionStorage.getItem(ERROR_REPORT_DISMISS_STORAGE);
      if (raw) {
        localStorage.setItem(ERROR_REPORT_DISMISS_STORAGE, raw);
        sessionStorage.removeItem(ERROR_REPORT_DISMISS_STORAGE);
      }
    }
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

function saveErrorReportDismissMap(map) {
  try {
    const now = Date.now();
    const pruned = {};
    Object.entries(map).forEach(([key, entry]) => {
      if (entry && now - Number(entry.at || 0) < ERROR_REPORT_DEDUP_MS) {
        pruned[key] = entry;
      }
    });
    localStorage.setItem(ERROR_REPORT_DISMISS_STORAGE, JSON.stringify(pruned));
  } catch {
    /* ignore */
  }
}

function isErrorReportSuppressed(fingerprint) {
  const entry = loadErrorReportDismissMap()[fingerprint];
  if (!entry) return false;
  return Date.now() - Number(entry.at || 0) < ERROR_REPORT_DEDUP_MS;
}

function markErrorReportHandled(fingerprint, kind) {
  const map = loadErrorReportDismissMap();
  map[fingerprint] = { at: Date.now(), kind };
  saveErrorReportDismissMap(map);
}

async function hashErrorFingerprint(message) {
  const text = String(message || '');
  if (globalThis.crypto?.subtle) {
    const data = new TextEncoder().encode(text);
    const buf = await crypto.subtle.digest('SHA-256', data);
    return Array.from(new Uint8Array(buf))
      .map((b) => b.toString(16).padStart(2, '0'))
      .join('');
  }
  let h = 0;
  for (let i = 0; i < text.length; i += 1) {
    h = ((h << 5) - h + text.charCodeAt(i)) | 0;
  }
  return `fallback_${(h >>> 0).toString(16)}`;
}

function extractErrorReportSearchTerms(errorMessage) {
  const msg = String(errorMessage || '').trim();
  const terms = [];
  if (!msg) return terms;
  const inner = msg.match(/最近错误[：:]\s*(.+)$/);
  if (inner && inner[1]) {
    terms.push(String(inner[1]).trim().slice(0, 120));
  }
  terms.push(msg.slice(0, 120));
  const httpMatch = msg.match(/HTTP\s+(\d{3})/i);
  if (httpMatch) terms.push(`HTTP ${httpMatch[1]}`);
  return [...new Set(terms.filter(Boolean))];
}

function findErrorLogAnchorIndex(merged, anchorMsg, anchorTs) {
  const terms = extractErrorReportSearchTerms(anchorMsg);
  for (const term of terms) {
    const idx = merged.findIndex(
      (x) =>
        (x.level === 'ERROR' || x.level === 'WARNING') &&
        String(x.message || '').includes(term),
    );
    if (idx >= 0) return idx;
  }
  const httpMatch = String(anchorMsg || '').match(/HTTP\s+(\d{3})/i);
  if (httpMatch) {
    const code = httpMatch[1];
    const codeRe = new RegExp(`HTTP\\s+${code}\\b|status[=:]\\s*${code}\\b`, 'i');
    const idx = merged.findIndex(
      (x) => x.level === 'ERROR' && codeRe.test(String(x.message || '')),
    );
    if (idx >= 0) return idx;
  }
  const nearestError = merged.reduce(
    (best, item, idx) => {
      if (item.level !== 'ERROR' && item.level !== 'WARNING') return best;
      const delta = Math.abs((Number(item.ts) || 0) - anchorTs);
      if (best.idx < 0 || delta < best.delta) return { idx, delta };
      return best;
    },
    { idx: -1, delta: Infinity },
  );
  if (nearestError.idx >= 0) return nearestError.idx;
  return merged.reduce(
    (best, item, idx) => {
      const delta = Math.abs((Number(item.ts) || 0) - anchorTs);
      if (best.idx < 0 || delta < best.delta) return { idx, delta };
      return best;
    },
    { idx: -1, delta: Infinity },
  ).idx;
}

function pickErrorLogExcerpt(merged, anchor) {
  const anchorTs = Number(anchor.ts) || Date.now() / 1000;
  const anchorMsg = String(anchor.errorMessage || '');

  let anchorIdx = findErrorLogAnchorIndex(merged, anchorMsg, anchorTs);
  if (anchorIdx < 0) anchorIdx = Math.max(0, merged.length - 1);

  const windowStart = anchorTs - ERROR_REPORT_LOG_WINDOW_SEC;
  const windowEnd = anchorTs + ERROR_REPORT_LOG_WINDOW_SEC;
  const byTime = merged.filter((x) => {
    const ts = Number(x.ts) || 0;
    return ts >= windowStart && ts <= windowEnd;
  });
  const errorsInWindow = merged.filter((x) => {
    const ts = Number(x.ts) || 0;
    return (
      ts >= windowStart &&
      ts <= windowEnd &&
      (x.level === 'ERROR' || x.level === 'WARNING')
    );
  });
  const lineStart = Math.max(0, anchorIdx - ERROR_REPORT_LOG_LINE_RADIUS);
  const lineEnd = Math.min(merged.length, anchorIdx + ERROR_REPORT_LOG_LINE_RADIUS + 1);
  const byLines = merged.slice(lineStart, lineEnd);
  const picked = mergeLogItemsUnique([...byTime, ...byLines, ...errorsInWindow]);
  const structuredKeys = new Set();
  const structured = picked.filter((x) => {
    const match = /reason=|screenshot_id|scene_generation/i.test(x.message || '');
    if (match) structuredKeys.add(logEntryKey(x));
    return match;
  });
  const rest = picked.filter((x) => !structuredKeys.has(logEntryKey(x)));
  return [...structured, ...rest].map(formatLogLine).join('\n');
}

async function collectErrorReportContext(anchor) {
  const anchorTs = Number(anchor.ts) || Date.now() / 1000;
  const sinceTs = Math.max(0, anchorTs - ERROR_REPORT_LOG_WINDOW_SEC);

  let serverItems = [];
  try {
    const base = API.base || window.location.origin.replace(/\/$/, '');
    const res = await fetch(
      `${base}/api/logs/recent?since_ts=${encodeURIComponent(sinceTs)}`,
      { cache: 'no-store' },
    );
    if (res.ok) {
      const data = await res.json();
      serverItems = data.items || [];
    }
  } catch (e) {
    console.warn('[error-report] logs/recent failed', e);
  }

  const merged = mergeLogItemsUnique([...logBuffer, ...serverItems]);
  let logsExcerpt = pickErrorLogExcerpt(merged, { ...anchor, ts: anchorTs });

  let diagnosticsJson = null;
  try {
    const diagRes = await apiFetch('/api/diagnostics');
    diagnosticsJson = diagRes.diagnostics || diagRes;
    const diagText = buildDiagnosticReportText(diagnosticsJson);
    if (diagText) {
      logsExcerpt = `${logsExcerpt}\n\n--- diagnostics ---\n${diagText}`;
    }
  } catch (e) {
    console.warn('[error-report] diagnostics failed', e);
  }

  if (anchor.statusSnapshot) {
    const snap = anchor.statusSnapshot;
    const meta = [
      `active_model_id: ${snap.active_model_id || '—'}`,
      `personae: ${(snap.persona_names || []).join(' · ') || '—'}`,
    ].join('\n');
    logsExcerpt = `${logsExcerpt}\n\n--- status ---\n${meta}`;
  }

  if (logsExcerpt.length > 8000) {
    logsExcerpt = `${logsExcerpt.slice(0, 7990)}\n…[truncated]`;
  }

  const summary = String(anchor.errorMessage || '未知错误').trim().slice(0, 500);
  const errorFingerprint = anchor.fingerprint || (await hashErrorFingerprint(summary));
  return { summary, logsExcerpt, diagnosticsJson, errorFingerprint };
}

function showErrorReportModal(anchor) {
  const modal = document.getElementById('errorReportModal');
  const msgEl = document.getElementById('errorReportModalMessage');
  if (!modal || !msgEl) return;
  const preview = String(anchor.errorMessage || '').trim();
  msgEl.textContent = preview.length > 200 ? `${preview.slice(0, 200)}…` : preview;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  const submitBtn = document.getElementById('btnErrorReportSubmit');
  if (submitBtn) {
    submitBtn.disabled = false;
    submitBtn.textContent = '发送反馈';
  }
}

function closeErrorReportModal() {
  const modal = document.getElementById('errorReportModal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

async function maybePromptErrorReport(st) {
  if (!window.DanmuSupabase?.isConfigured?.()) return;
  const msg = String(st.error_message || '').trim();
  if (!msg) return;
  const fingerprint = await hashErrorFingerprint(msg);
  if (isErrorReportSuppressed(fingerprint)) return;
  errorReportAnchor = {
    errorMessage: msg,
    ts: Date.now() / 1000,
    fingerprint,
    statusSnapshot: {
      active_model_id: st.active_model_id,
      persona_names: st.persona_names,
    },
  };
  showErrorReportModal(errorReportAnchor);
}

async function submitErrorReportFromModal() {
  if (!errorReportAnchor || errorReportSubmitting) return;
  if (!window.DanmuSupabase?.isConfigured?.()) {
    showToast('未配置云端反馈服务', true);
    return;
  }
  const submitBtn = document.getElementById('btnErrorReportSubmit');
  errorReportSubmitting = true;
  if (submitBtn) {
    submitBtn.disabled = true;
    submitBtn.textContent = '发送中…';
  }
  try {
    const payload = await collectErrorReportContext(errorReportAnchor);
    await window.DanmuSupabase.submitErrorReport(payload);
    markErrorReportHandled(errorReportAnchor.fingerprint, 'sent');
    closeErrorReportModal();
    showToast('错误反馈已发送，感谢！');
    errorReportAnchor = null;
  } catch (err) {
    showToast(err.message || '发送失败', true);
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.textContent = '发送反馈';
    }
  } finally {
    errorReportSubmitting = false;
  }
}

function dismissErrorReportModal() {
  if (errorReportAnchor?.fingerprint) {
    markErrorReportHandled(errorReportAnchor.fingerprint, 'dismiss');
  }
  errorReportAnchor = null;
  closeErrorReportModal();
}

let liveOverlayStatusTimer = null;

function formatLiveOverlayLastBroadcast(ts) {
  if (ts == null || Number.isNaN(Number(ts))) {
    return '—';
  }
  const d = new Date(Number(ts) * 1000);
  if (Number.isNaN(d.getTime())) {
    return '—';
  }
  return d.toLocaleTimeString();
}

async function refreshLiveOverlayStatus() {
  const connEl = document.getElementById('liveOverlayConnections');
  const lastEl = document.getElementById('liveOverlayLastBroadcast');
  const urlEl = document.getElementById('liveOverlayUrl');
  if (!connEl || !API.base) {
    return;
  }
  try {
    const st = await fetch(`${API.base}/api/live-overlay/status`, { cache: 'no-store' }).then((r) => {
      if (!r.ok) {
        throw new Error(String(r.status));
      }
      return r.json();
    });
    connEl.textContent = String(st.connections ?? 0);
    lastEl.textContent = formatLiveOverlayLastBroadcast(st.last_broadcast_at);
    if (urlEl && st.overlay_url) {
      urlEl.value = st.overlay_url;
    }
  } catch (_e) {
    connEl.textContent = '—';
    if (lastEl) {
      lastEl.textContent = '—';
    }
  }
}

function initLiveOverlayPanel() {
  const panel = document.getElementById('liveOverlayPanel');
  if (!panel) {
    return;
  }
  document.getElementById('btnCopyLiveOverlayUrl')?.addEventListener('click', () => {
    const url = document.getElementById('liveOverlayUrl')?.value || '';
    if (!url) {
      showToast('暂无直播地址');
      return;
    }
    navigator.clipboard.writeText(url).then(
      () => showToast('直播地址已复制~'),
      () => showToast('复制失败，请手动选择复制'),
    );
  });
  document.getElementById('btnLiveOverlayTest')?.addEventListener('click', async () => {
    try {
      await apiFetch('/api/live-overlay/test', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      showToast('测试弹幕已发送~');
      await refreshLiveOverlayStatus();
    } catch (e) {
      showToast(`发送失败：${e.message || e}`);
    }
  });
  refreshLiveOverlayStatus();
  if (liveOverlayStatusTimer) {
    clearInterval(liveOverlayStatusTimer);
  }
  liveOverlayStatusTimer = setInterval(() => {
    if (document.hidden) {
      return;
    }
    refreshLiveOverlayStatus();
  }, 2000);
}


let danmuPoolMeta = null;

function poolEffectiveEnabledLocal() {
  const builtin = document.getElementById('poolBuiltinEnabled')?.checked;
  const custom = document.getElementById('poolCustomEnabled')?.checked;
  return Boolean(builtin || custom);
}

function updatePoolMinOnScreenControl() {
  const enabled = danmuPoolMeta?.effective_pool_enabled ?? poolEffectiveEnabledLocal();
  const minEl = document.getElementById('poolMinOnScreen');
  const wrap = document.getElementById('poolMinOnScreenWrap');
  if (minEl) minEl.disabled = !enabled;
  if (wrap) wrap.classList.toggle('is-disabled', !enabled);
  const hint = document.getElementById('poolBothOffHint');
  if (hint) hint.classList.toggle('hidden', Boolean(enabled));
}

function parseCustomDanmuTextarea(value) {
  return String(value || '')
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
}

function renderCustomDanmuPoolList(items) {
  const list = document.getElementById('poolCustomList');
  const countEl = document.getElementById('poolCustomCount');
  if (countEl) countEl.textContent = `共 ${items.length} 条`;
  if (!list) return;
  list.replaceChildren();
  items.forEach((text) => {
    const li = document.createElement('li');
    li.className = 'danmu-pool-custom-item';
    const label = document.createElement('label');
    label.className = 'flex items-start gap-2 text-warmText';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'pool-custom-cb accent-warmPink mt-1';
    const span = document.createElement('span');
    span.textContent = text;
    label.append(cb, span);
    li.append(label);
    list.append(li);
  });
  const selectAll = document.getElementById('poolCustomSelectAll');
  if (selectAll) selectAll.checked = false;
}

async function loadDanmuPoolPage() {
  const [meta, custom] = await Promise.all([
    apiFetch('/api/danmu-pool/meta'),
    apiFetch('/api/danmu-pool/custom'),
  ]);
  danmuPoolMeta = meta;
  const builtinEl = document.getElementById('poolBuiltinEnabled');
  const customEl = document.getElementById('poolCustomEnabled');
  const minEl = document.getElementById('poolMinOnScreen');
  const countHint = document.getElementById('poolBuiltinCountHint');
  if (builtinEl) builtinEl.checked = Boolean(meta.builtin_enabled);
  if (customEl) customEl.checked = Boolean(meta.custom_enabled);
  if (minEl) minEl.value = String(meta.min_on_screen ?? 5);
  if (countHint) countHint.textContent = meta.builtin_count ? `（内置约 ${meta.builtin_count} 条）` : '';
  renderCustomDanmuPoolList(custom.items || []);
  updatePoolMinOnScreenControl();
}

async function saveDanmuPoolSettings() {
  const body = {
    builtin_enabled: Boolean(document.getElementById('poolBuiltinEnabled')?.checked),
    custom_enabled: Boolean(document.getElementById('poolCustomEnabled')?.checked),
    min_on_screen: parseInt(document.getElementById('poolMinOnScreen')?.value, 10) || 0,
  };
  await apiFetch('/api/danmu-pool/settings', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');
  updatePoolMinOnScreenControl();
  showToast('公式化弹幕库设置已保存~');
}

async function addCustomDanmuPoolItems() {
  const textarea = document.getElementById('poolCustomTextarea');
  const text = textarea?.value || '';
  if (!text.trim()) {
    showToast('请先输入要追加的弹幕句', true);
    return;
  }
  const result = await apiFetch('/api/danmu-pool/custom', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
  renderCustomDanmuPoolList(result.items || []);
  danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');
  if (textarea) textarea.value = '';
  const skipped = result.skipped || 0;
  if (skipped > 0) {
    showToast(`已追加 ${result.added} 条，跳过 ${skipped} 条`, skipped > 0 && !result.added);
  } else {
    showToast(`已追加 ${result.added} 条~`);
  }
}

async function deleteSelectedCustomDanmuPoolItems() {
  const texts = [...document.querySelectorAll('#poolCustomList .pool-custom-cb:checked')]
    .map((cb) => cb.closest('label')?.querySelector('span')?.textContent)
    .filter(Boolean);
  if (!texts.length) {
    showToast('请先勾选要删除的句子', true);
    return;
  }
  const result = await apiFetch('/api/danmu-pool/custom', {
    method: 'DELETE',
    body: JSON.stringify({ texts }),
  });
  renderCustomDanmuPoolList(result.items || []);
  danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');
  showToast(`已删除 ${result.removed} 条~`);
}

let danmuReadConfigCache = null;

function applyDanmuReadForm(cfg) {
  danmuReadConfigCache = cfg;
  const enabledEl = document.getElementById('danmuReadEnabled');
  const intervalEl = document.getElementById('danmuReadInterval');
  const keyEl = document.getElementById('danmuReadApiKey');
  const voiceEl = document.getElementById('danmuReadVoice');
  const styleEl = document.getElementById('danmuReadStylePrompt');
  const modelLabel = document.getElementById('danmuReadModelLabel');
  const endpointLabel = document.getElementById('danmuReadEndpointLabel');
  if (enabledEl) enabledEl.checked = Boolean(cfg.enabled);
  if (intervalEl) intervalEl.value = String(cfg.interval_sec ?? 10);
  if (keyEl) keyEl.value = cfg.api_key || '';
  if (voiceEl && cfg.voice) voiceEl.value = cfg.voice;
  if (styleEl) styleEl.value = cfg.style_prompt || '';
  if (modelLabel) modelLabel.textContent = cfg.model || 'mimo-v2.5-tts';
  if (endpointLabel) endpointLabel.textContent = cfg.endpoint || '—';
}

async function loadDanmuReadPage() {
  const cfg = await apiFetch('/api/danmu-read/config');
  applyDanmuReadForm(cfg);
  const status = document.getElementById('danmuReadStatus');
  if (status) status.textContent = '';
}

async function saveDanmuReadSettings() {
  const body = {
    enabled: Boolean(document.getElementById('danmuReadEnabled')?.checked),
    interval_sec: parseInt(document.getElementById('danmuReadInterval')?.value, 10) || 10,
    voice: document.getElementById('danmuReadVoice')?.value || '冰糖',
    style_prompt: document.getElementById('danmuReadStylePrompt')?.value || '',
  };
  const keyInput = document.getElementById('danmuReadApiKey')?.value?.trim();
  if (keyInput && keyInput !== '********') {
    body.api_key = keyInput;
  }
  const cfg = await apiFetch('/api/danmu-read/config', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  applyDanmuReadForm(cfg);
  showToast('读弹幕设置已保存~');
}

async function probeDanmuRead() {
  const status = document.getElementById('danmuReadStatus');
  if (status) status.textContent = '试听请求中（约 10–20 秒）…';
  const body = {};
  const keyInput = document.getElementById('danmuReadApiKey')?.value?.trim();
  if (keyInput && keyInput !== '********') {
    body.api_key = keyInput;
  }
  const result = await apiFetch('/api/danmu-read/probe', {
    method: 'POST',
    body: JSON.stringify(body),
  });
  if (status) status.textContent = result.message || '';
  showToast(result.message || (result.ok ? '试听已开始' : '试听失败'), !result.ok);
}

function initDanmuReadPage() {
  document.getElementById('btnSaveDanmuRead')?.addEventListener('click', () => {
    saveDanmuReadSettings().catch((e) => showToast(e.message, true));
  });
  document.getElementById('btnDanmuReadProbe')?.addEventListener('click', () => {
    probeDanmuRead().catch((e) => {
      const status = document.getElementById('danmuReadStatus');
      if (status) status.textContent = '';
      showToast(e.message, true);
    });
  });
}

function initDanmuPoolPage() {
  document.getElementById('btnSavePoolSettings')?.addEventListener('click', () => {
    saveDanmuPoolSettings().catch((e) => showToast(e.message, true));
  });
  document.getElementById('btnPoolCustomAppend')?.addEventListener('click', () => {
    addCustomDanmuPoolItems().catch((e) => showToast(e.message, true));
  });
  document.getElementById('btnPoolCustomClearInput')?.addEventListener('click', () => {
    const textarea = document.getElementById('poolCustomTextarea');
    if (textarea) textarea.value = '';
  });
  document.getElementById('btnPoolCustomDelete')?.addEventListener('click', () => {
    deleteSelectedCustomDanmuPoolItems().catch((e) => showToast(e.message, true));
  });
  document.getElementById('poolCustomSelectAll')?.addEventListener('change', (e) => {
    const checked = e.target.checked;
    document.querySelectorAll('#poolCustomList .pool-custom-cb').forEach((cb) => {
      cb.checked = checked;
    });
  });
  ['poolBuiltinEnabled', 'poolCustomEnabled'].forEach((id) => {
    document.getElementById(id)?.addEventListener('change', () => {
      if (danmuPoolMeta) {
        danmuPoolMeta.effective_pool_enabled = poolEffectiveEnabledLocal();
      }
      updatePoolMinOnScreenControl();
    });
  });
}

async function personaFetch(path) {
  if (!API.base) await refreshSession();
  const res = await fetch(`${API.base}${path}`, { cache: 'no-store' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(formatApiError(err.detail, res.statusText));
  }
  return res.json();
}

async function deletePersonaByName(name) {
  if (!confirm(`确定删除人格「${name}」吗？`)) return;
  try {
    await apiFetch(`/api/personae/${enc(name)}`, { method: 'DELETE' });
    if (currentPersonaId === name) currentPersonaId = '';
    showToast('已删除~');
    await loadPersonaEditor();
  } catch (err) {
    showToast(err.message, true);
  }
}

async function loadPersonaeCheckboxes(containerId) {
  const data = await personaFetch('/api/personae');
  const box = document.getElementById(containerId);
  if (!box) return data;
  box.innerHTML = '';
  data.items.forEach((item) => {
    const row = document.createElement('div');
    row.className = 'flex items-center gap-2 px-3 py-2 bg-cream rounded-xl text-sm font-semibold text-warmText';
    const label = document.createElement('label');
    label.className = 'flex items-center gap-2 flex-1 min-w-0 cursor-pointer';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = item.id;
    cb.checked = !!item.active;
    cb.className = 'rounded accent-[#FFA5A5] shrink-0';
    const span = document.createElement('span');
    span.className = 'truncate';
    span.textContent = item.label;
    label.append(cb, span);
    row.appendChild(label);
    if (!item.builtin) {
      const delBtn = document.createElement('button');
      delBtn.type = 'button';
      delBtn.className = 'shrink-0 px-2 py-1 border border-red-200 rounded-lg text-xs text-red-600 hover:bg-red-50';
      delBtn.textContent = '删除';
      delBtn.title = `删除人格「${item.label}」`;
      delBtn.addEventListener('click', (e) => {
        e.preventDefault();
        deletePersonaByName(item.id);
      });
      row.appendChild(delBtn);
    }
    box.appendChild(row);
  });
  return data;
}




async function loadPersonaEditor() {
  const data = await personaFetch('/api/personae');
  const sel = document.getElementById('personaSelect');
  sel.innerHTML = '';
  data.items.forEach((item) => {
    const opt = document.createElement('option');
    opt.value = item.id;
    opt.textContent = item.label;
    sel.appendChild(opt);
  });
  if (!currentPersonaId && data.items.length) currentPersonaId = data.items[0].id;
  if (currentPersonaId) sel.value = currentPersonaId;
  await loadPersonaTemplate();
  await loadPersonaeCheckboxes('personaActiveList');
}

async function loadPersonaTemplate() {
  const name = document.getElementById('personaSelect').value;
  if (!name) return;
  currentPersonaId = name;
  const tpl = await personaFetch(`/api/personae/${enc(name)}/template`);
  document.getElementById('personaContract').value = tpl.reply_contract || '';
  document.getElementById('personaSystemCustom').value = tpl.system_custom || '';
  const systemEditable = tpl.system_editable ?? tpl.editable;
  document.getElementById('personaSystemCustom').readOnly = !systemEditable;
  document.getElementById('btnSavePersona').disabled = tpl.can_save === false;
  document.getElementById('btnDeletePersona').style.display = tpl.builtin ? 'none' : '';
}


/** 默认 GitHub Releases（Supabase release_url 为空时回退） */
const DEFAULT_RELEASE_URL = 'https://github.com/PEPETII/danmuai/releases';
const APP_UPDATE_DISMISS_LOCAL_KEY = 'danmu_app_update_dismissed_latest';

const appVersionState = {
  current: '',
  latest: '',
  releaseUrl: DEFAULT_RELEASE_URL,
  message: '',
  checkStatus: 'pending', // pending | up_to_date | update_available | check_failed
};

const appUpdateDismissState = {
  dismissedLatestVersion: '',
};

let pendingAppUpdatePrompt = null;


/** 与 app/version_compare.py 一致：数字段比较，禁止字符串 > */
function normalizeVersionString(raw) {
  let s = String(raw || '').trim();
  if (s.length > 1 && (s[0] === 'v' || s[0] === 'V') && /\d/.test(s[1])) {
    s = s.slice(1);
  }
  return s;
}

function parseVersionSegments(raw) {
  const normalized = normalizeVersionString(raw);
  if (!normalized) throw new Error('empty version');
  let core = normalized;
  let prerelease = null;
  const dash = normalized.indexOf('-');
  if (dash >= 0) {
    core = normalized.slice(0, dash);
    prerelease = normalized.slice(dash + 1).trim() || null;
  }
  if (!core) return { segments: [0], prerelease };
  const segments = core.split('.').map((piece) => {
    const m = /^(\d*)/.exec(piece.trim());
    if (!m || m[1] === '') throw new Error(`invalid segment: ${piece}`);
    return parseInt(m[1], 10);
  });
  return { segments, prerelease };
}

function compareVersions(a, b) {
  const pa = parseVersionSegments(a);
  const pb = parseVersionSegments(b);
  const len = Math.max(pa.segments.length, pb.segments.length);
  for (let i = 0; i < len; i += 1) {
    const va = pa.segments[i] ?? 0;
    const vb = pb.segments[i] ?? 0;
    if (va !== vb) return va < vb ? -1 : 1;
  }
  if (pa.prerelease === null && pb.prerelease === null) return 0;
  if (pa.prerelease === null && pb.prerelease !== null) return 1;
  if (pa.prerelease !== null && pb.prerelease === null) return -1;
  if (pa.prerelease === pb.prerelease) return 0;
  return pa.prerelease < pb.prerelease ? -1 : 1;
}

function readAppUpdateDismissFromLocal() {
  try {
    return String(localStorage.getItem(APP_UPDATE_DISMISS_LOCAL_KEY) || '').trim();
  } catch {
    return '';
  }
}

function writeAppUpdateDismissToLocal(version) {
  try {
    localStorage.setItem(APP_UPDATE_DISMISS_LOCAL_KEY, version ? String(version) : '');
  } catch {
    /* ignore */
  }
}

function mergeAppUpdateDismissState(remote, localDismissed) {
  const remoteDismissed =
    typeof remote?.dismissedLatestVersion === 'string'
      ? remote.dismissedLatestVersion.trim()
      : '';
  appUpdateDismissState.dismissedLatestVersion = remoteDismissed || localDismissed || '';
}

async function loadAppUpdateDismissState() {
  const localDismissed = readAppUpdateDismissFromLocal();
  let remote = null;
  try {
    if (API.base) {
      remote = await fetch(`${API.base}/api/app-update-state`, { cache: 'no-store' }).then((r) =>
        r.ok ? r.json() : null,
      );
    }
  } catch {
    remote = null;
  }
  mergeAppUpdateDismissState(remote, localDismissed);
  writeAppUpdateDismissToLocal(appUpdateDismissState.dismissedLatestVersion);
}

async function persistAppUpdateDismiss(latestVersion) {
  const normalized = normalizeVersionString(latestVersion);
  appUpdateDismissState.dismissedLatestVersion = normalized;
  writeAppUpdateDismissToLocal(normalized);
  try {
    await apiFetch('/api/app-update-state', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dismissedLatestVersion: normalized }),
    });
  } catch {
    /* localStorage remains */
  }
}

function refreshAppVersionFooter() {
  const currentEl = document.getElementById('appVersionCurrent');
  const latestEl = document.getElementById('appVersionLatest');
  if (!currentEl || !latestEl) return;
  currentEl.textContent = appVersionState.current || '—';
  latestEl.classList.remove('version-latest-ok', 'version-latest-update', 'version-latest-failed');
  if (appVersionState.checkStatus === 'check_failed') {
    latestEl.textContent = '检查失败';
    latestEl.classList.add('version-latest-failed');
    return;
  }
  if (appVersionState.checkStatus === 'update_available') {
    latestEl.textContent = appVersionState.latest || '—';
    latestEl.classList.add('version-latest-update');
    return;
  }
  if (appVersionState.checkStatus === 'up_to_date') {
    latestEl.textContent = '已是最新';
    latestEl.classList.add('version-latest-ok');
    return;
  }
  latestEl.textContent = '—';
}

function showAppUpdateModal(latest, message) {
  const modal = document.getElementById('appUpdateModal');
  const msgEl = document.getElementById('appUpdateModalMessage');
  if (!modal || !msgEl) return;
  let text = `发现新版本 ${latest}，是否前往下载？`;
  if (message) text += `\n\n${message}`;
  msgEl.textContent = text;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeAppUpdateModal() {
  const modal = document.getElementById('appUpdateModal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function maybeShowAppUpdateModal() {
  if (!pendingAppUpdatePrompt) return;
  const { latest, message } = pendingAppUpdatePrompt;
  // 同一 remote latest 用户点「否」后不再弹；Supabase 升到更新版本后会再弹
  if (appUpdateDismissState.dismissedLatestVersion === normalizeVersionString(latest)) {
    pendingAppUpdatePrompt = null;
    return;
  }
  showAppUpdateModal(latest, message);
  pendingAppUpdatePrompt = null;
}

async function initAppVersionAndUpdateCheck() {
  try {
    if (!API.base) {
      appVersionState.checkStatus = 'check_failed';
      refreshAppVersionFooter();
      return;
    }
    const verRes = await fetch(`${API.base}/api/version`, { cache: 'no-store' });
    if (!verRes.ok) throw new Error('version api failed');
    const verData = await verRes.json();
    const current = String(verData.current_version || '').trim();
    appVersionState.current = current;
    window.DANMU_APP_VERSION = current;
    refreshAppVersionFooter();

    let remoteRow = null;
    try {
      if (window.DanmuSupabase?.isConfigured?.()) {
        remoteRow = await window.DanmuSupabase.fetchAppUpdate();
      }
    } catch (e) {
      console.warn('[version] supabase check failed', e);
      remoteRow = null;
    }

    if (!remoteRow?.latest_version) {
      appVersionState.checkStatus = 'check_failed';
      refreshAppVersionFooter();
      await loadAppUpdateDismissState();
      return;
    }

    const latest = normalizeVersionString(remoteRow.latest_version);
    appVersionState.latest = latest;
    appVersionState.releaseUrl = remoteRow.release_url || DEFAULT_RELEASE_URL;
    appVersionState.message = remoteRow.message || '';

    if (compareVersions(latest, current) > 0) {
      appVersionState.checkStatus = 'update_available';
      pendingAppUpdatePrompt = { latest, message: appVersionState.message };
    } else {
      appVersionState.checkStatus = 'up_to_date';
      pendingAppUpdatePrompt = null;
    }
    refreshAppVersionFooter();

    await loadAppUpdateDismissState();
    maybeShowAppUpdateModal();
  } catch (e) {
    console.warn('[version] init check failed', e);
    appVersionState.checkStatus = 'check_failed';
    refreshAppVersionFooter();
  }
}


function navigate(page) {
  document.querySelectorAll('.page-panel').forEach((p) => p.classList.remove('active'));
  document.querySelectorAll('#nav .sidebar-item').forEach((n) => n.classList.remove('active'));
  const panel = document.getElementById(`page-${page}`);
  if (panel) panel.classList.add('active');
  const btn = document.querySelector(`#nav [data-page="${page}"]`);
  if (btn) btn.classList.add('active');
  if (page === 'ai-butler') initAiButlerPage();
  if (page === 'settings') {
    loadScreens().catch(console.error);
    loadCustomModels().catch(console.error);
  }
  if (page === 'persona') loadPersonaEditor().catch(console.error);
  if (page === 'danmu-pool') loadDanmuPoolPage().catch((e) => showToast(e.message, true));
  if (page === 'danmu-read') loadDanmuReadPage().catch((e) => showToast(e.message, true));
  if (page === 'announcements') {
    stopAnnouncementsBadgePolling();
    updateAnnouncementsNavBadge(false);
    loadAnnouncementsPage().catch((e) => showToast(e.message, true));
  } else {
    startAnnouncementsBadgePolling();
  }
  if (page === 'feedback') initFeedbackPage();
  if (page === 'logs') {
    renderLogView();
    updateLogPanelState();
    bootstrapLogsFromServer(REALTIME.lastLogsPollTs).catch((e) => {
      console.warn('[realtime] logs bootstrap on navigate failed', e);
    });
  }
}

async function init() {
  await refreshSession();
  await loadAnnouncementsReadState();

  await loadModelCatalog();
  await loadProviders();
  await loadConfigDefaults();
  const cfg = await reloadConfigFromServer();
  await loadScreens();
  if (cfg.screen_index !== undefined) {
    document.getElementById('screen_index').value = String(cfg.screen_index);
  }
  configureStatus({
    applyCaptureRegion: applyCaptureRegionFromPayload,
    onErrorPrompt: maybePromptErrorReport,
  });
  setRealtimeHandlers({
    onStatus: applyStatus,
    onLog: appendLog,
    onLogBatch: mergeLogItems,
    updateLogPanelState,
    showToast,
    bootstrapLogs: bootstrapLogsFromServer,
  });
  applyStatus(await fetch(`${API.base}/api/status`).then((r) => r.json()));
  initDiagnosticsPanel({ showToast });
  initLiveOverlayPanel();
  startRealtimeTransport();

  initSettingsTabs();
  initSettingsUiMode();
  initSettingsFieldHints();
  initSidebarNavFloatingHints();
  initNormalBatchControls();
  initDanmuPoolPage();
  initDanmuReadPage();
  initCaptureRegionControls();
  initRestoreDefaultsControls();

  bindSettingsControls({
    showToast,
    navigate,
    onConfigSaved: () => {
      if (document.getElementById('personaSelect')?.value) {
        loadPersonaTemplate().catch(console.error);
      }
    },
  });
  bindContentPageControls({ showToast, navigate });

  document.querySelectorAll('.sidebar-nav-hint').forEach((btn) => {
    btn.addEventListener('click', (e) => e.stopPropagation());
  });

  document.querySelectorAll('#nav [data-page]').forEach((btn) => {
    btn.addEventListener('click', () => navigate(btn.dataset.page));
  });
  const hash = (location.hash || '').replace('#', '');
  if (hash) navigate(hash);

  document.querySelectorAll('.log-level-cb').forEach((cb) => {
    cb.addEventListener('change', () => {
      replaceLogLevelFilters(
        new Set([...document.querySelectorAll('.log-level-cb:checked')].map((c) => c.value)),
      );
      renderLogView();
    });
  });
  document.getElementById('logAutoScroll')?.addEventListener('change', (e) => {
    setLogAutoScroll(e.target.checked);
  });
  document.getElementById('btnCopyLogs')?.addEventListener('click', () => {
    const text = logBuffer
      .filter((x) => logLevelFilters.has(x.level))
      .map((x) => `[${x.level}] ${x.message}`)
      .join('\n');
    navigator.clipboard.writeText(text).then(() => showToast('已复制到剪贴板~'));
  });
  document.getElementById('btnClearLogs')?.addEventListener('click', () => {
    logBuffer.length = 0;
    document.getElementById('logView').innerHTML = '';
    updateLogPanelState();
    showToast('日志视图已清空~');
  });

  updateLogPanelState();

  await refreshAnnouncementsUnreadBadge();
  const onAnnouncements = document
    .getElementById('page-announcements')
    ?.classList.contains('active');
  if (!onAnnouncements) {
    startAnnouncementsBadgePolling();
  }

  document.getElementById('btnToggle').addEventListener('click', async () => {
    try {
      const st = await fetch(`${API.base}/api/status`).then((r) => r.json());
      if (st.running) {
        await apiFetch('/api/stop', { method: 'POST' });
        showToast('小助手已休息~');
      } else {
        await apiFetch('/api/start', { method: 'POST' });
        showToast('弹幕生成已开启！');
      }
    } catch (e) {
      showToast(e.message || '小助手遇到了一点问题', true);
    }
  });

  document.getElementById('btnErrorReportDismiss')?.addEventListener('click', dismissErrorReportModal);
  document.getElementById('btnErrorReportSubmit')?.addEventListener('click', () => {
    submitErrorReportFromModal().catch((e) => showToast(e.message || '发送失败', true));
  });
  document.getElementById('errorReportModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'errorReportModal') dismissErrorReportModal();
  });
  document.getElementById('personaSelect')?.addEventListener('change', () => loadPersonaTemplate());
  document.getElementById('btnSavePersona')?.addEventListener('click', async () => {
    const name = document.getElementById('personaSelect').value;
    try {
      await apiFetch(`/api/personae/${enc(name)}/template`, {
        method: 'PUT',
        body: JSON.stringify({
          system_custom: document.getElementById('personaSystemCustom').value,
        }),
      });
      showToast('人格已保存~');
      loadPersonaTemplate();
    } catch (err) {
      showToast(err.message, true);
    }
  });
  document.getElementById('btnRestorePersona')?.addEventListener('click', async () => {
    const name = document.getElementById('personaSelect').value;
    try {
      const data = await apiFetch(`/api/personae/${enc(name)}/restore`, { method: 'POST' });
      document.getElementById('personaSystemCustom').value = data.system_custom || '';
      showToast('已恢复默认~');
    } catch (err) {
      showToast(err.message, true);
    }
  });
  document.getElementById('btnNewPersona')?.addEventListener('click', async () => {
    const name = prompt('新人格名称：');
    if (!name?.trim()) return;
    try {
      await apiFetch('/api/personae', { method: 'POST', body: JSON.stringify({ name: name.trim() }) });
      currentPersonaId = name.trim();
      showToast('新人格已创建~');
      loadPersonaEditor();
    } catch (err) {
      showToast(err.message, true);
    }
  });
  document.getElementById('btnDeletePersona')?.addEventListener('click', async () => {
    const name = document.getElementById('personaSelect').value;
    if (name) await deletePersonaByName(name);
  });

  document.getElementById('btnAppUpdateYes')?.addEventListener('click', () => {
    const url = appVersionState.releaseUrl || DEFAULT_RELEASE_URL;
    closeAppUpdateModal();
    try {
      const opened = window.open(url, '_blank', 'noopener,noreferrer');
      if (!opened) {
        navigator.clipboard?.writeText(url);
        showToast('请手动打开下载页：已复制链接到剪贴板', false);
      }
    } catch {
      showToast(`请前往下载：${url}`, false);
    }
  });
  document.getElementById('btnAppUpdateNo')?.addEventListener('click', async () => {
    const latest = appVersionState.latest;
    closeAppUpdateModal();
    if (latest) {
      await persistAppUpdateDismiss(latest);
    }
  });
  document.getElementById('appUpdateModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'appUpdateModal') closeAppUpdateModal();
  });

  document.getElementById('btnSavePersonaActive')?.addEventListener('click', async () => {
    const active = [];
    document.querySelectorAll('#personaActiveList input:checked').forEach((cb) => active.push(cb.value));
    try {
      await apiFetch('/api/personae/active', { method: 'PUT', body: JSON.stringify({ active }) });
      showToast('激活人格已更新~');
    } catch (err) {
      showToast(err.message, true);
    }
  });

  await initAppVersionAndUpdateCheck();
}

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState !== 'visible' || !API.base) return;
  refreshSession()
    .then(() => {
      REALTIME.statusAttempt = 0;
      REALTIME.logsAttempt = 0;
      startRealtimeTransport();
      return bootstrapLogsFromServer(0);
    })
    .catch((e) => console.warn('[realtime] visibility refresh failed', e));
});

init().catch((e) => {
  console.error(e);
  showToast(e.message || '无法连接小助手，请确认 DanmuAI 已启动', true);
});
