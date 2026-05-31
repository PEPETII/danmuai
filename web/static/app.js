/** DanmuAI Web Console — 温馨 Qwen 原型 */

const API = { token: null, base: '' };
const MASKED_API_KEY = '********';

const CONFIG_FIELDS = [
  'api_endpoint', 'api_mode', 'model', 'temperature', 'max_tokens',
  'danmu_speed', 'danmu_lines', 'danmu_max_chars', 'dedup_threshold',
  'screen_index', 'layout_mode', 'opacity', 'font_size', 'hotkey',
  'eviction_mode',
  'image_max_width', 'image_quality',
  'mic_window_sec', 'memory_mode', 'memory_window',
  'normal_recognition_interval_sec', 'normal_reply_count',
];

/**
 * 助手设置「恢复默认」按 Tab 划分的字段范围。
 * api_key 不参与；识图区域（capture）走独立 API，不在此恢复。
 * 默认值来自 GET /api/config/defaults，勿在此硬编码。
 */
const SETTINGS_RESTORE_GROUPS = {
  api: [
    'api_endpoint', 'api_mode', 'screen_index', 'model', 'temperature', 'max_tokens',
    'mic_window_sec', 'memory_mode', 'memory_window',
  ],
  capture: [],
  danmu: [
    'normal_recognition_interval_sec', 'normal_reply_count', 'danmu_speed', 'danmu_lines',
    'font_size', 'danmu_max_chars', 'opacity', 'dedup_threshold', 'layout_mode', 'hotkey',
    'eviction_mode',
  ],
  rhythm: ['image_max_width', 'image_quality'],
};

const SETTINGS_RESTORE_CHECKBOXES = {
  api: ['mic_mode_enabled'],
  capture: [],
  danmu: ['empty_accel'],
  rhythm: [],
};

let configDefaultsCache = null;
let activeSettingsTabId = 'api';

const NORMAL_REPLY_COUNT_MIN = 1;
const NORMAL_REPLY_COUNT_MAX = 20;
const DEFAULT_NORMAL_REPLY_COUNT = 5;

const REPLY_COUNT_MIN = 2;
const REPLY_COUNT_MAX = 7;
const DANMU_MAX_CHARS_MIN = 5;
const DANMU_MAX_CHARS_MAX = 80;
const DEFAULT_DANMU_MAX_CHARS_ZH = 15;
const DEFAULT_DANMU_MAX_CHARS_EN = 40;

let providersCache = [];
let catalogCache = { platforms: [] };
const VISION_MODEL_CUSTOM_VALUE = '__custom__';
const logBuffer = [];
let logLevelFilters = new Set(['INFO', 'WARNING', 'ERROR']);
let logAutoScroll = true;
let currentPersonaId = '';

const ERROR_REPORT_DISMISS_STORAGE = 'danmu_error_report_dismiss';
const ERROR_REPORT_DEDUP_MS = 24 * 60 * 60 * 1000;
const ERROR_REPORT_LOG_WINDOW_SEC = 90;
const ERROR_REPORT_LOG_LINE_RADIUS = 40;
let statusHadError = false;
let errorReportAnchor = null;
let errorReportSubmitting = false;

function authHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  if (API.token) headers.Authorization = `Bearer ${API.token}`;
  return headers;
}

/** Re-fetch session token (required after each `python main.py` restart). */
async function refreshSession() {
  const sessionUrl = new URL('/api/session', window.location.origin).href;
  const res = await fetch(sessionUrl, { cache: 'no-store' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const detail = formatApiError(err.detail, res.statusText);
    throw new Error(
      `无法获取控制台会话（HTTP ${res.status}）: ${detail}。`
      + '请确认终端有「Web 控制台 HTTP/WS 已监听」，且地址栏为 http://127.0.0.1:18765 后刷新页面。',
    );
  }
  const session = await res.json();
  if (!session?.token) {
    throw new Error('会话接口未返回 token，请重启 python main.py 并刷新页面');
  }
  API.token = session.token;
  API.base = (session.base_url || window.location.origin).replace(/\/$/, '');
  REALTIME.lastLogsPollTs = 0;
  return session;
}

function logEntryKey(item) {
  return `${item.ts}|${item.level}|${item.message}`;
}

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

function formatApiError(detail, fallback = '请求失败') {
  if (!detail) return fallback;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => {
        const loc = Array.isArray(d.loc) ? d.loc.filter((x) => x !== 'body').join('.') : '';
        const msg = d.msg || d.message || JSON.stringify(d);
        return loc ? `${loc}: ${msg}` : msg;
      })
      .join('；');
  }
  return String(detail);
}

async function apiFetch(path, options = {}, retried = false) {
  if (!API.base) await refreshSession();
  const res = await fetch(`${API.base}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if ((res.status === 401 || res.status === 403) && !retried) {
    await refreshSession();
    return apiFetch(path, options, true);
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const fallback =
      res.status === 404
        ? '接口不存在，请完全退出并重新运行 python main.py 后再试'
        : res.statusText;
    throw new Error(formatApiError(err.detail, fallback));
  }
  return res.json();
}

async function apiFormFetch(path, formData) {
  const res = await fetch(`${API.base}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${API.token}` },
    body: formData,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(formatApiError(err.detail, res.statusText));
  }
  return res.json();
}

let _previewOrigUrl = null;
let _previewCompressedUrl = null;

function revokePreviewUrls() {
  if (_previewOrigUrl) {
    URL.revokeObjectURL(_previewOrigUrl);
    _previewOrigUrl = null;
  }
  if (_previewCompressedUrl) {
    URL.revokeObjectURL(_previewCompressedUrl);
    _previewCompressedUrl = null;
  }
}

function blobUrlFromDataUrl(dataUrl) {
  const comma = dataUrl.indexOf(',');
  if (comma < 0) return null;
  const header = dataUrl.slice(0, comma);
  const mime = header.match(/data:([^;]+)/)?.[1] || 'image/jpeg';
  const b64 = dataUrl.slice(comma + 1);
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return URL.createObjectURL(new Blob([bytes], { type: mime }));
}

function setPreviewSlot(img, placeholder, src, onBlobUrl) {
  if (!img) return;
  img.classList.remove('hidden');
  if (placeholder) placeholder.classList.add('hidden');
  img.onerror = () => {
    if (src.startsWith('data:') && onBlobUrl) {
      const blobUrl = blobUrlFromDataUrl(src);
      if (blobUrl) {
        onBlobUrl(blobUrl);
        img.onerror = null;
        img.src = blobUrl;
      }
    }
  };
  img.src = src;
}

function resetCompressedPreview() {
  const compressed = document.getElementById('previewImageCompressed');
  const pending = document.getElementById('previewCompressedPlaceholder');
  if (compressed) {
    compressed.classList.add('hidden');
    compressed.removeAttribute('src');
  }
  if (pending) {
    pending.classList.remove('hidden');
    pending.textContent = '正在压缩…';
  }
}

function formatRuntime(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

/** Single 1s tick for session/lifetime runtime; avoids skip when status WS/poll is irregular. */
const RUNTIME_CLOCK = {
  tickTimer: null,
  session: null,
  lifetime: null,
};

const DIAGNOSTICS = {
  pollTimer: null,
  inFlight: false,
  last: null,
};

function stopRuntimeTick() {
  if (RUNTIME_CLOCK.tickTimer) {
    clearInterval(RUNTIME_CLOCK.tickTimer);
    RUNTIME_CLOCK.tickTimer = null;
  }
}

function currentAnchoredSec(anchor) {
  if (!anchor) return 0;
  if (!anchor.running) return anchor.baseSec;
  const elapsed = Math.floor((Date.now() - anchor.anchorMs) / 1000);
  return anchor.baseSec + Math.max(0, elapsed);
}

function paintRuntimeDisplays() {
  const runtimeEl = document.getElementById('statRuntime');
  if (runtimeEl) {
    runtimeEl.textContent = formatRuntime(currentAnchoredSec(RUNTIME_CLOCK.session));
  }
  const lifetimeEl = document.getElementById('statLifetimeRuntime');
  if (lifetimeEl) {
    lifetimeEl.textContent = formatRuntimeLong(currentAnchoredSec(RUNTIME_CLOCK.lifetime));
  }
}

function startRuntimeTick() {
  stopRuntimeTick();
  paintRuntimeDisplays();
  RUNTIME_CLOCK.tickTimer = setInterval(() => {
    if (!RUNTIME_CLOCK.session?.running) {
      stopRuntimeTick();
      return;
    }
    paintRuntimeDisplays();
  }, 1000);
}

/**
 * Anchor runtime to last server snapshot; while running, advance locally every 1s.
 * Re-anchors only on start/stop or when server drifts ahead by >1s (clock correction).
 */
function syncRuntimeClocks(st) {
  const running = !!st.running;
  const serverSessionSec = Math.max(0, Math.floor(st.runtime_sec || 0));
  const serverLifetimeSec = Math.max(0, Math.floor(st.lifetime_runtime_sec || 0));
  const now = Date.now();
  const wasRunning = !!RUNTIME_CLOCK.session?.running;

  if (running) {
    if (!wasRunning) {
      RUNTIME_CLOCK.session = { baseSec: serverSessionSec, anchorMs: now, running: true };
      RUNTIME_CLOCK.lifetime = { baseSec: serverLifetimeSec, anchorMs: now, running: true };
      startRuntimeTick();
      return;
    }
    const localSession = currentAnchoredSec(RUNTIME_CLOCK.session);
    const localLifetime = currentAnchoredSec(RUNTIME_CLOCK.lifetime);
    if (serverSessionSec > localSession + 1) {
      RUNTIME_CLOCK.session = { baseSec: serverSessionSec, anchorMs: now, running: true };
    }
    if (serverLifetimeSec > localLifetime + 1) {
      RUNTIME_CLOCK.lifetime = { baseSec: serverLifetimeSec, anchorMs: now, running: true };
    }
    if (!RUNTIME_CLOCK.tickTimer) startRuntimeTick();
    return;
  }

  stopRuntimeTick();
  RUNTIME_CLOCK.session = { baseSec: serverSessionSec, anchorMs: now, running: false };
  RUNTIME_CLOCK.lifetime = { baseSec: serverLifetimeSec, anchorMs: now, running: false };
  paintRuntimeDisplays();
}

function formatRuntimeLong(sec) {
  const s = Math.floor(sec || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}小时${m}分`;
  if (m > 0) return `${m}:${String(r).padStart(2, '0')}`;
  return `${r}秒`;
}

function formatSessionTimestamp(unixSec) {
  if (!unixSec) return '—';
  const d = new Date(unixSec * 1000);
  const pad = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function formatSessionRunLine(run) {
  const start = formatSessionTimestamp(run.started_at);
  const end = formatSessionTimestamp(run.ended_at);
  const model = run.model || '—';
  const input = run.input_tokens ?? 0;
  const output = run.output_tokens ?? 0;
  const total = run.total_tokens ?? (input + output);
  return `${start} - ${end}  ${model}  输入 ${input}  输出 ${output}  总 ${total}`;
}

function renderSessionRuns(runs) {
  const container = document.getElementById('sessionRunLog');
  const empty = document.getElementById('sessionRunLogEmpty');
  if (!container) return;
  const list = Array.isArray(runs) ? runs : [];
  container.querySelectorAll('.session-run-line').forEach((el) => el.remove());
  if (!list.length) {
    if (empty) empty.classList.remove('hidden');
    return;
  }
  if (empty) empty.classList.add('hidden');
  list.forEach((run) => {
    const line = document.createElement('p');
    line.className = 'session-run-line';
    line.textContent = formatSessionRunLine(run);
    container.appendChild(line);
  });
}

function formatTokenCount(n) {
  const v = Number(n) || 0;
  return v >= 10000 ? v.toLocaleString('zh-CN') : String(v);
}

function applyStatus(st) {
  const running = st.running;
  const dot = document.getElementById('statusDot');
  const pill = document.getElementById('statusPill');
  const sub = document.getElementById('statusSub');
  const btn = document.getElementById('btnToggle');

  if (running) {
    dot.className = 'w-3 h-3 bg-green-400 rounded-full animate-pulse';
    pill.textContent = '生成中';
    sub.textContent = st.live_message || '小助手正在为你生成暖心弹幕~';
    btn.textContent = '停止弹幕';
    btn.classList.remove('btn-primary', 'text-white');
    btn.classList.add('bg-white', 'border', 'border-gray-200', 'text-warmText');
  } else {
    dot.className = 'w-3 h-3 bg-gray-300 rounded-full';
    pill.textContent = '待命';
    sub.textContent = '小助手正在待命，随时为你生成暖心弹幕~';
    btn.textContent = '生成弹幕';
    btn.classList.remove('bg-white', 'border', 'border-gray-200', 'text-warmText');
    btn.classList.add('btn-primary', 'text-white');
  }

  document.getElementById('statDanmu').textContent = String(st.danmu_count ?? 0);
  document.getElementById('statQueue').textContent = String(st.queue_count ?? 0);
  syncRuntimeClocks(st);
  const displayEl = document.getElementById('statDisplay');
  if (displayEl) displayEl.textContent = String(st.display_count ?? 0);
  const lifetimeDanmuEl = document.getElementById('statLifetimeDanmu');
  const lifetimeInputEl = document.getElementById('statLifetimeInputTokens');
  const lifetimeOutputEl = document.getElementById('statLifetimeOutputTokens');
  if (lifetimeDanmuEl) lifetimeDanmuEl.textContent = String(st.lifetime_danmu_count ?? 0);
  if (lifetimeInputEl) {
    lifetimeInputEl.textContent = formatTokenCount(st.lifetime_input_tokens ?? 0);
  }
  if (lifetimeOutputEl) {
    lifetimeOutputEl.textContent = formatTokenCount(st.lifetime_output_tokens ?? 0);
  }
  if (st.capture_region_mode !== undefined || st.region_selection_state !== undefined) {
    applyCaptureRegionFromPayload({
      mode: st.capture_region_mode,
      region: {
        x: st.region_x ?? 0,
        y: st.region_y ?? 0,
        w: st.region_w ?? 0,
        h: st.region_h ?? 0,
      },
      selection_state: st.region_selection_state || 'idle',
    });
  }

  const lifetimeNoteEl = document.getElementById('statLifetimeTokenNote');
  if (lifetimeNoteEl) {
    const lifetimeTotal = Number(st.lifetime_total_tokens) || 0;
    const lifetimeIn = Number(st.lifetime_input_tokens) || 0;
    const lifetimeOut = Number(st.lifetime_output_tokens) || 0;
    const legacyExtra = lifetimeTotal - lifetimeIn - lifetimeOut;
    if (legacyExtra > 0) {
      lifetimeNoteEl.textContent =
        `另有升级前累计 ${formatTokenCount(legacyExtra)} Token（尚未区分输入/输出，已计入历史合计）`;
      lifetimeNoteEl.classList.remove('hidden');
    } else {
      lifetimeNoteEl.textContent = '';
      lifetimeNoteEl.classList.add('hidden');
    }
  }
  document.getElementById('activePersonae').textContent =
    (st.persona_names && st.persona_names.length) ? st.persona_names.join(' · ') : '—';
  document.getElementById('liveStatusLine').textContent = st.live_message || '';
  renderSessionRuns(st.session_runs);
  if (st.provider_model_mismatch && st.active_model_id) {
    const mismatchNote = document.getElementById('modelActiveSourceBanner');
    if (mismatchNote && mismatchNote.classList.contains('hidden')) {
      mismatchNote.textContent =
        `当前 API 地址与模型「${st.active_model_id}」不匹配，请在助手设置中重新选择视觉模型并保存。`;
      mismatchNote.classList.remove('hidden');
    }
  }

  const banner = document.getElementById('errorBanner');
  if (st.error_message) {
    banner.textContent = st.error_message;
    banner.classList.remove('hidden');
    banner.classList.toggle('text-red-700', st.is_error);
  } else {
    banner.classList.add('hidden');
  }

  const isError = !!st.is_error;
  if (isError && !statusHadError) {
    maybePromptErrorReport(st).catch((e) => console.warn('[error-report] prompt failed', e));
  }
  statusHadError = isError;
}

function loadErrorReportDismissMap() {
  try {
    const raw = sessionStorage.getItem(ERROR_REPORT_DISMISS_STORAGE);
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
    sessionStorage.setItem(ERROR_REPORT_DISMISS_STORAGE, JSON.stringify(pruned));
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

function formatLogLine(item) {
  const ts = Number(item.ts) || 0;
  const iso = ts > 0 ? new Date(ts * 1000).toISOString() : '—';
  return `${iso} [${item.level || 'INFO'}] ${item.message || ''}`;
}

function mergeLogItemsUnique(items) {
  const map = new Map();
  items.forEach((item) => {
    if (!item || item.message == null) return;
    map.set(logEntryKey(item), item);
  });
  return Array.from(map.values()).sort((a, b) => (Number(a.ts) || 0) - (Number(b.ts) || 0));
}

function pickErrorLogExcerpt(merged, anchor) {
  const anchorTs = Number(anchor.ts) || Date.now() / 1000;
  const anchorMsg = String(anchor.errorMessage || '');
  const snippet = anchorMsg.slice(0, 80);

  let anchorIdx = merged.findIndex(
    (x) => x.level === 'ERROR' && snippet && String(x.message || '').includes(snippet),
  );
  if (anchorIdx < 0) {
    anchorIdx = merged.reduce((best, item, idx) => {
      const delta = Math.abs((Number(item.ts) || 0) - anchorTs);
      if (best.idx < 0 || delta < best.delta) return { idx, delta };
      return best;
    }, { idx: -1, delta: Infinity }).idx;
  }
  if (anchorIdx < 0) anchorIdx = Math.max(0, merged.length - 1);

  const windowStart = anchorTs - ERROR_REPORT_LOG_WINDOW_SEC;
  const windowEnd = anchorTs + ERROR_REPORT_LOG_WINDOW_SEC;
  const byTime = merged.filter((x) => {
    const ts = Number(x.ts) || 0;
    return ts >= windowStart && ts <= windowEnd;
  });
  const lineStart = Math.max(0, anchorIdx - ERROR_REPORT_LOG_LINE_RADIUS);
  const lineEnd = Math.min(merged.length, anchorIdx + ERROR_REPORT_LOG_LINE_RADIUS + 1);
  const byLines = merged.slice(lineStart, lineEnd);
  const picked = mergeLogItemsUnique([...byTime, ...byLines]);
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

function formatDiagSeconds(value) {
  const num = Number(value) || 0;
  return `${num.toFixed(2)}s`;
}

function formatDiagMs(value) {
  return `${Math.max(0, Math.round(Number(value) || 0))}ms`;
}

function buildDiagnosticReportText(diag) {
  if (!diag) return '等待诊断数据...';
  const scheduler = diag.scheduler || {};
  const timing = diag.timing || {};
  const runtimeState = diag.runtime_state || {};
  const diagnosis = diag.diagnosis || {};
  const webRuntime = runtimeState.web_runtime || {};
  const stats = runtimeState.stats || {};
  const generation = runtimeState.generation_pipeline || {};
  const suggestions = [];
  if (diagnosis.scheduler_blocked) {
    suggestions.push(`- 检查调度阻塞原因：${scheduler.block_reason || 'unknown'}`);
  }
  if (diagnosis.high_rtt) {
    suggestions.push('- 检查弱网、上游模型响应时间或过慢的视觉请求');
  }
  if (diagnosis.has_pending_timing) {
    suggestions.push('- 检查请求 timing 是否长时间未消费，重点看 reply/error 清理路径');
  }
  if (!suggestions.length) {
    suggestions.push('- 当前快照未发现明显调度或 timing 异常');
  }
  return [
    'DanmuAI Diagnostic Report',
    '',
    '[scheduler]',
    `scheduler_blocked: ${!!diagnosis.scheduler_blocked}`,
    `block_reason: ${scheduler.block_reason || ''}`,
    `seconds_since_last_trigger: ${scheduler.seconds_since_last_trigger ?? 0}`,
    '',
    '[timing]',
    `request_started_count: ${timing.request_started_count ?? 0}`,
    `avg_rtt: ${timing.avg_rtt ?? 0}`,
    `smart_cooldown_ms: ${timing.smart_cooldown_ms ?? 0}`,
    `recent_rtt_samples: ${(timing.recent_rtt_samples || []).join(', ') || '[]'}`,
    '',
    '[runtime]',
    `danmu_count: ${stats.danmu_count ?? 0}`,
    `runtime_sec: ${stats.runtime_sec ?? 0}`,
    `cached_layout_mode: ${webRuntime.cached_layout_mode || 'fullscreen'}`,
    `latest_displayed_round: ${generation.latest_displayed_round ?? 0}`,
    '',
    '[next_steps]',
    ...suggestions,
  ].join('\n');
}

function renderDiagnostics(diag) {
  DIAGNOSTICS.last = diag || null;
  const scheduler = diag?.scheduler || {};
  const timing = diag?.timing || {};
  const diagnosis = diag?.diagnosis || {};
  const stats = diag?.runtime_state?.stats || {};

  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  setText('diagSchedulerBlocked', diagnosis.scheduler_blocked ? '是' : '否');
  setText('diagBlockReason', scheduler.block_reason || '-');
  setText('diagTriggerGap', formatDiagSeconds(scheduler.seconds_since_last_trigger));
  setText('diagPendingTiming', String(timing.request_started_count ?? 0));
  setText('diagAvgRtt', formatDiagSeconds(timing.avg_rtt));
  setText('diagCooldown', formatDiagMs(timing.smart_cooldown_ms));
  setText('diagHighRtt', diagnosis.high_rtt ? '是' : '否');
  setText('diagRttHistoryLen', String(timing.rtt_history_len ?? 0));
  setText(
    'diagRecentRttSamples',
    JSON.stringify(timing.recent_rtt_samples || []),
  );
  setText(
    'diagRuntimeStats',
    `danmu=${stats.danmu_count ?? 0} · input=${stats.total_input_tokens ?? 0} · output=${stats.total_output_tokens ?? 0} · runtime=${formatDiagSeconds(stats.runtime_sec)}`,
  );
  setText('diagnosticReportPreview', buildDiagnosticReportText(diag));
}

async function refreshDiagnostics() {
  if (DIAGNOSTICS.inFlight || !API.base) return;
  DIAGNOSTICS.inFlight = true;
  try {
    const payload = await apiFetch('/api/diagnostics', { method: 'GET' });
    if (payload?.ok && payload.diagnostics) {
      renderDiagnostics(payload.diagnostics);
    }
  } catch (err) {
    console.warn('[diagnostics] refresh failed', err);
  } finally {
    DIAGNOSTICS.inFlight = false;
  }
}

function startDiagnosticsPolling() {
  if (DIAGNOSTICS.pollTimer) clearInterval(DIAGNOSTICS.pollTimer);
  refreshDiagnostics();
  DIAGNOSTICS.pollTimer = setInterval(refreshDiagnostics, 2500);
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

function initDiagnosticsPanel() {
  document.getElementById('btnCopyDiagnosticsReport')?.addEventListener('click', async () => {
    const text = buildDiagnosticReportText(DIAGNOSTICS.last);
    try {
      await navigator.clipboard.writeText(text);
      showToast('诊断报告已复制');
    } catch (err) {
      console.warn('[diagnostics] copy failed', err);
      showToast('复制诊断报告失败', true);
    }
  });
}

function updateLogPanelState() {
  const panel = document.querySelector('.log-panel');
  const empty = document.getElementById('logViewEmpty');
  const view = document.getElementById('logView');
  if (!panel || !view) return;
  const visibleCount = view.childElementCount;
  panel.classList.toggle('has-logs', visibleCount > 0);
  if (empty && visibleCount === 0) {
    if (REALTIME.logsOpen) {
      empty.textContent =
        '等待日志… 点击「生成弹幕」后，截图、AI 请求与弹幕事件会在此实时显示。';
    } else if (REALTIME.degradedLogsPolling) {
      empty.textContent =
        '正在通过 HTTP 同步日志… 若长时间仍为空，请确认已点击「生成弹幕」并有截图/AI 活动。';
    } else {
      empty.textContent =
        '日志通道连接中… 若超过数秒仍无内容，请点左侧「温馨控制台」查看顶栏连接状态，或重启 DanmuAI。';
    }
  }
}

function renderLogView() {
  const view = document.getElementById('logView');
  if (!view) return;
  view.innerHTML = '';
  logBuffer
    .filter((x) => logLevelFilters.has(x.level))
    .forEach((item) => {
      const line = document.createElement('div');
      const ts = item.ts ? new Date(item.ts * 1000).toLocaleTimeString() : '';
      line.className = `log-line ${item.level || 'INFO'}`;
      line.textContent = `[${ts}] ${item.message}`;
      view.appendChild(line);
    });
  if (logAutoScroll) view.scrollTop = view.scrollHeight;
  updateLogPanelState();
}

function appendLog(item) {
  const key = logEntryKey(item);
  if (logBuffer.some((x) => logEntryKey(x) === key)) return;
  logBuffer.push(item);
  while (logBuffer.length > 400) logBuffer.shift();
  if (logLevelFilters.has(item.level || 'INFO')) {
    const view = document.getElementById('logView');
    if (!view) return;
    const line = document.createElement('div');
    const ts = item.ts ? new Date(item.ts * 1000).toLocaleTimeString() : '';
    line.className = `log-line ${item.level || 'INFO'}`;
    line.textContent = `[${ts}] ${item.message}`;
    view.appendChild(line);
    while (view.childElementCount > 400) view.removeChild(view.firstChild);
    if (logAutoScroll) view.scrollTop = view.scrollHeight;
    updateLogPanelState();
  }
}

function clampReplyCount(value, fallback = 2) {
  const n = parseInt(value, 10);
  if (Number.isNaN(n)) return fallback;
  return Math.max(REPLY_COUNT_MIN, Math.min(REPLY_COUNT_MAX, n));
}

function resolveDanmuMaxCharsPreview(lang = 'zh') {
  const el = document.getElementById('danmu_max_chars');
  const raw = parseInt(el?.value ?? '', 10);
  const fallback = lang === 'en' ? DEFAULT_DANMU_MAX_CHARS_EN : DEFAULT_DANMU_MAX_CHARS_ZH;
  const value = Number.isNaN(raw) || raw <= 0 ? fallback : raw;
  return Math.max(DANMU_MAX_CHARS_MIN, Math.min(value, DANMU_MAX_CHARS_MAX));
}

function clampNormalReplyCount(value, fallback = DEFAULT_NORMAL_REPLY_COUNT) {
  const n = parseInt(value, 10);
  if (Number.isNaN(n)) return fallback;
  return Math.max(NORMAL_REPLY_COUNT_MIN, Math.min(NORMAL_REPLY_COUNT_MAX, n));
}

function clampNormalIntervalSec(value, fallback = 5) {
  const n = parseInt(value, 10);
  if (Number.isNaN(n)) return fallback;
  return Math.max(1, Math.min(60, n));
}

function buildNormalReplyContractPreviewZh(count, maxChars) {
  const total = clampNormalReplyCount(count, DEFAULT_NORMAL_REPLY_COUNT);
  const limit = maxChars ?? resolveDanmuMaxCharsPreview('zh');
  const examples = Array.from({ length: total }, (_, i) => `弹幕${i + 1}`);
  return (
    '你是直播弹幕评论员。必须且只能返回 JSON 字符串数组，不要解释，不要 Markdown。'
    + `固定返回 ${total} 条弹幕，必须与当前画面或直播氛围相关，避免重复。`
    + `每条不超过 ${limit} 个字，输出格式：`
    + `["${examples.join('", "')}"]。`
  );
}

function updateNormalBatchPreview() {
  const countEl = document.getElementById('normal_reply_count');
  if (!countEl) return;
  const count = clampNormalReplyCount(countEl.value, DEFAULT_NORMAL_REPLY_COUNT);
  countEl.value = String(count);
  const hint = document.getElementById('normalBatchTotalHint');
  if (hint) {
    hint.textContent = `每次固定 ${count} 条 · 保存后会同步到人格工坊的「输出契约」`;
  }
  const maxChars = resolveDanmuMaxCharsPreview('zh');
  const preview = buildNormalReplyContractPreviewZh(count, maxChars);
  const previewEl = document.getElementById('normalBatchContractPreview');
  if (previewEl) previewEl.textContent = preview;
  const contractEl = document.getElementById('personaContract');
  if (contractEl) contractEl.value = preview;
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

const SETTINGS_UI_MODE_KEY = 'danmu_settings_ui_mode';

function getSettingsUiMode() {
  try {
    const v = localStorage.getItem(SETTINGS_UI_MODE_KEY);
    return v === 'full' ? 'full' : 'simplified';
  } catch {
    return 'simplified';
  }
}

function setSettingsUiMode(mode) {
  const normalized = mode === 'full' ? 'full' : 'simplified';
  try {
    localStorage.setItem(SETTINGS_UI_MODE_KEY, normalized);
  } catch {
    /* ignore quota / private mode */
  }
  applySettingsUiMode();
}

function applySettingsUiMode() {
  const mode = getSettingsUiMode();
  const form = document.getElementById('settingsForm');
  if (form) {
    form.classList.toggle('settings-ui-simplified', mode === 'simplified');
    form.classList.toggle('settings-ui-full', mode === 'full');
  }
  document.querySelectorAll('.settings-ui-mode-btn').forEach((btn) => {
    const active = btn.dataset.settingsUiMode === mode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
}

function initSettingsUiMode() {
  applySettingsUiMode();
  document.querySelectorAll('.settings-ui-mode-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      setSettingsUiMode(btn.dataset.settingsUiMode);
    });
  });
}

function initNormalBatchControls() {
  ['normal_reply_count', 'normal_recognition_interval_sec', 'danmu_max_chars'].forEach((id) => {
    document.getElementById(id)?.addEventListener('input', updateNormalBatchPreview);
    document.getElementById(id)?.addEventListener('change', updateNormalBatchPreview);
  });
  updateNormalBatchPreview();
}

function configDefaultValue(key) {
  if (configDefaultsCache && configDefaultsCache[key] !== undefined && configDefaultsCache[key] !== '') {
    return String(configDefaultsCache[key]);
  }
  return '';
}

async function loadConfigDefaults() {
  try {
    configDefaultsCache = await apiFetch('/api/config/defaults');
  } catch {
    configDefaultsCache = {};
  }
}

function allRestorableSettingKeys() {
  const keys = new Set();
  Object.values(SETTINGS_RESTORE_GROUPS).forEach((group) => {
    group.forEach((key) => keys.add(key));
  });
  Object.values(SETTINGS_RESTORE_CHECKBOXES).forEach((group) => {
    group.forEach((key) => keys.add(key));
  });
  return [...keys];
}

function restorableKeysForScope(scope) {
  if (scope === 'all') return allRestorableSettingKeys();
  const fields = SETTINGS_RESTORE_GROUPS[activeSettingsTabId] || [];
  const checkboxes = SETTINGS_RESTORE_CHECKBOXES[activeSettingsTabId] || [];
  return [...fields, ...checkboxes];
}

function applyDefaultToField(key, rawValue) {
  const value = rawValue === undefined || rawValue === null ? '' : String(rawValue);
  if (key === 'mic_mode_enabled' || key === 'empty_accel') {
    const el = document.getElementById(key);
    if (el) el.checked = value === '1';
    return;
  }
  const el = document.getElementById(key);
  if (!el) return;
  if (key === 'memory_mode') {
    const allowed = ['off', 'dedup_only', 'scene_card', 'strong'];
    el.value = allowed.includes(value) ? value : 'off';
    return;
  }
  if (key === 'layout_mode') {
    const allowed = ['fullscreen', '3/4', '1/2', '1/4'];
    el.value = allowed.includes(value) ? value : 'fullscreen';
    return;
  }
  if (key === 'eviction_mode') {
    el.value = value === 'accelerate' ? 'accelerate' : 'natural';
    return;
  }
  el.value = value;
}

/**
 * 恢复默认只改表单、不 POST /api/config，避免误点直接覆盖持久化配置。
 * api_key 不参与恢复：保留当前输入（含掩码 ******** 或用户刚输入的新密钥）。
 */
function applySettingsDefaults(scope) {
  if (!configDefaultsCache || !Object.keys(configDefaultsCache).length) {
    showToast('无法加载默认配置，请刷新页面后重试', true);
    return;
  }
  const keys = restorableKeysForScope(scope);
  if (scope === 'current' && keys.length === 0) {
    showToast('当前分组无可恢复的表单项', true);
    closeRestoreDefaultsModal();
    return;
  }
  const apiKeyEl = document.getElementById('api_key');
  const apiKeySnapshot = apiKeyEl?.value ?? '';
  keys.forEach((key) => {
    applyDefaultToField(key, configDefaultsCache[key]);
  });
  if (apiKeyEl) apiKeyEl.value = apiKeySnapshot;
  syncProviderPresetFromEndpoint();
  const modelId = configDefaultsCache.model || document.getElementById('model')?.value || '';
  syncVisionModelPickerFromForm(modelId);
  updateMicModeHint();
  updateNormalBatchPreview();
  closeRestoreDefaultsModal();
  showToast('已恢复默认值，请点击「保存配置」生效');
}

function openRestoreDefaultsModal() {
  const modal = document.getElementById('restoreDefaultsModal');
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeRestoreDefaultsModal() {
  const modal = document.getElementById('restoreDefaultsModal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function initRestoreDefaultsControls() {
  document.getElementById('btnRestoreSettingsDefaults')?.addEventListener('click', openRestoreDefaultsModal);
  document.getElementById('btnRestoreDefaultsCurrent')?.addEventListener('click', () => {
    applySettingsDefaults('current');
  });
  document.getElementById('btnRestoreDefaultsAll')?.addEventListener('click', () => {
    applySettingsDefaults('all');
  });
  document.getElementById('btnRestoreDefaultsCancel')?.addEventListener('click', closeRestoreDefaultsModal);
  const modal = document.getElementById('restoreDefaultsModal');
  modal?.addEventListener('click', (e) => {
    if (e.target === modal) closeRestoreDefaultsModal();
  });
}

function collectFormData() {
  syncVisionModelToHidden();
  const data = {};
  CONFIG_FIELDS.forEach((name) => {
    const el = document.getElementById(name);
    if (el) data[name] = el.value;
  });
  data.empty_accel = document.getElementById('empty_accel')?.checked ? '1' : '0';
  data.mic_mode_enabled = document.getElementById('mic_mode_enabled')?.checked ? '1' : '0';
  const key = (document.getElementById('api_key')?.value || '').trim();
  if (key && key !== MASKED_API_KEY) data.api_key = key;
  return data;
}

let micAudioLikelySupported = true;

function catalogModelSupportsMic(modelId) {
  const id = (modelId || '').trim();
  if (!id) return false;
  for (const platform of catalogCache.platforms || []) {
    const hit = (platform.models || []).find((m) => m.id === id);
    if (hit) return Boolean(hit.supports_mic);
  }
  return false;
}

function micModeConfigSupported() {
  const apiMode = document.getElementById('api_mode')?.value || 'doubao';
  const modelId = (document.getElementById('model')?.value || '').trim();
  const endpoint = document.getElementById('api_endpoint')?.value || '';
  const providerId = guessProviderIdFromEndpoint(endpoint, apiMode);
  if (apiMode === 'doubao' || providerId === 'doubao') {
    return micAudioLikelySupported || catalogModelSupportsMic(modelId);
  }
  if (providerId === 'mimo') {
    return micAudioLikelySupported
      || (modelId === 'mimo-v2.5' && catalogModelSupportsMic(modelId));
  }
  return false;
}

function updateMicModeHint() {
  const hint = document.getElementById('micModeHint');
  const micOn = document.getElementById('mic_mode_enabled')?.checked;
  if (!hint) return;
  if (!micOn) {
    hint.classList.add('hidden');
    hint.textContent = '';
    return;
  }
  const apiMode = document.getElementById('api_mode')?.value || 'doubao';
  const modelId = document.getElementById('model')?.value || '';
  const endpoint = document.getElementById('api_endpoint')?.value || '';
  const providerId = guessProviderIdFromEndpoint(endpoint, apiMode);
  if (micModeConfigSupported()) {
    hint.classList.add('hidden');
    hint.textContent = '';
    return;
  }
  hint.classList.remove('hidden');
  if (providerId === 'mimo') {
    hint.textContent = `麦克风模式需使用 MiMo-V2.5（mimo-v2.5）。当前模型「${modelId || '未选'}」不支持开麦；请改选目录中的 mimo-v2.5，保存配置后再开始弹幕。对着麦克风说话，句末停顿约半秒；「测试发送」不检测停顿。`;
    return;
  }
  if (apiMode !== 'doubao' && providerId !== 'doubao') {
    hint.textContent = '麦克风模式需使用火山方舟豆包（API 模式 doubao）或小米 MiMo（mimo-v2.5）。当前为其他 OpenAI 兼容配置，保存后对着麦克风说话也不会生成接话弹幕。';
    return;
  }
  hint.textContent = `当前模型「${modelId || '未选'}」可能听不懂麦克风。请改选列表里带「支持麦克风」的模型（例如 doubao-seed-2-0-mini），勾选后先点「保存配置」再开始弹幕。使用时对着麦克风说话，句末停顿约半秒；「测试发送」按钮不检测停顿。`;
}

function fillForm(cfg) {
  CONFIG_FIELDS.forEach((name) => {
    const el = document.getElementById(name);
    if (el && cfg[name] !== undefined) el.value = cfg[name];
  });
  const setIfEmpty = (id) => {
    const el = document.getElementById(id);
    const fallback = configDefaultValue(id);
    if (el && fallback && (cfg[id] === undefined || cfg[id] === '' || cfg[id] === null)) {
      el.value = fallback;
    }
  };
  setIfEmpty('danmu_speed');
  setIfEmpty('danmu_lines');
  setIfEmpty('font_size');
  setIfEmpty('opacity');
  setIfEmpty('dedup_threshold');
  setIfEmpty('hotkey');
  setIfEmpty('image_max_width');
  setIfEmpty('temperature');
  setIfEmpty('max_tokens');
  setIfEmpty('image_quality');
  setIfEmpty('danmu_max_chars');
  const evictionMode = document.getElementById('eviction_mode');
  if (evictionMode && !cfg.eviction_mode) {
    evictionMode.value = configDefaultValue('eviction_mode') || 'natural';
  }
  const emptyAccel = document.getElementById('empty_accel');
  if (emptyAccel) emptyAccel.checked = cfg.empty_accel !== '0';
  const memoryMode = document.getElementById('memory_mode');
  if (memoryMode) {
    const allowed = ['off', 'dedup_only', 'scene_card', 'strong'];
    const fallback = configDefaultValue('memory_mode') || 'off';
    memoryMode.value = allowed.includes(cfg.memory_mode) ? cfg.memory_mode : fallback;
  }
  const memoryWindow = document.getElementById('memory_window');
  if (memoryWindow && !cfg.memory_window) memoryWindow.value = configDefaultValue('memory_window') || '10';
  micAudioLikelySupported = cfg.mic_audio_likely_supported !== false;
  const micMode = document.getElementById('mic_mode_enabled');
  if (micMode) micMode.checked = cfg.mic_mode_enabled === '1';
  updateMicModeHint();
  const micWindow = document.getElementById('mic_window_sec');
  if (micWindow && !cfg.mic_window_sec) micWindow.value = configDefaultValue('mic_window_sec') || '5';
  const layoutMode = document.getElementById('layout_mode');
  if (layoutMode) {
    const allowed = ['fullscreen', '3/4', '1/2', '1/4'];
    const fallback = configDefaultValue('layout_mode') || 'fullscreen';
    layoutMode.value = allowed.includes(cfg.layout_mode) ? cfg.layout_mode : fallback;
  }
  const normalInterval = document.getElementById('normal_recognition_interval_sec');
  if (normalInterval && !cfg.normal_recognition_interval_sec) {
    normalInterval.value = configDefaultValue('normal_recognition_interval_sec') || '5';
  }
  const normalCount = document.getElementById('normal_reply_count');
  if (normalCount && !cfg.normal_reply_count) {
    normalCount.value = configDefaultValue('normal_reply_count') || String(DEFAULT_NORMAL_REPLY_COUNT);
  }
  updateNormalBatchPreview();
  const modelId = cfg.active_model_id || cfg.default_model_id || cfg.model || '';
  const modelEl = document.getElementById('model');
  if (modelEl) modelEl.value = modelId;
  syncVisionModelPickerFromForm(modelId);
  updateModelActiveSourceBanner(cfg);
  document.getElementById('api_key').value = cfg.has_api_key ? MASKED_API_KEY : '';
}

function updateModelActiveSourceBanner(cfg) {
  const banner = document.getElementById('modelActiveSourceBanner');
  if (!banner) return;
  const usesCustom = cfg?.uses_custom_credentials === true;
  if (!usesCustom) {
    banner.classList.add('hidden');
    banner.textContent = '';
    return;
  }
  const name = cfg.model_display_name || cfg.active_model_id || '';
  const id = cfg.active_model_id || '';
  banner.textContent =
    `当前默认模型来自自定义模型「${name}」（${id}）。助手设置中的 API 地址与密钥不用于生成弹幕，请在自定义模型列表中维护。`;
  banner.classList.remove('hidden');
  if (cfg.provider_model_mismatch) {
    banner.textContent +=
      ' 另外：当前 API 地址与已选模型目录不一致，保存配置时可能被拒绝，请重新选择视觉模型。';
  }
}

async function reloadConfigFromServer() {
  const cfg = await apiFetch('/api/config');
  fillForm(cfg);
  syncProviderPresetFromEndpoint();
  const modelId = cfg.active_model_id || cfg.default_model_id || cfg.model || '';
  syncVisionModelPickerFromForm(modelId);
  updateModelActiveSourceBanner(cfg);
  await loadCustomModels();
  applyCaptureRegionFromPayload({
    mode: cfg.capture_region_mode || (cfg.region_w > 0 && cfg.region_h > 0 ? 'custom' : 'full'),
    region: {
      x: cfg.region_x ?? 0,
      y: cfg.region_y ?? 0,
      w: cfg.region_w ?? 0,
      h: cfg.region_h ?? 0,
    },
    selection_state: 'idle',
  });
  return cfg;
}

let captureRegionPollTimer = null;

function applyCaptureRegionFromPayload(data) {
  const modeEl = document.getElementById('captureRegionModeLabel');
  const coordsEl = document.getElementById('captureRegionCoords');
  const resetBtn = document.getElementById('btnCaptureRegionReset');
  const selectBtn = document.getElementById('btnCaptureRegionSelect');
  if (!modeEl || !data) return;

  const mode = data.mode || 'full';
  const region = data.region || {};
  const state = data.selection_state || 'idle';
  const selecting = state === 'selecting';

  if (selectBtn) {
    selectBtn.disabled = selecting;
    selectBtn.textContent = selecting ? '正在框选…' : '鼠标框选识图范围';
  }

  if (selecting) {
    modeEl.textContent = '正在框选…请在识图显示器上拖动鼠标（Esc 取消）';
    coordsEl?.classList.add('hidden');
    return;
  }

  if (mode === 'custom' && region.w > 0 && region.h > 0) {
    modeEl.textContent = '自定义区域识图';
    if (coordsEl) {
      coordsEl.textContent = `区域：x=${region.x}, y=${region.y}, 宽=${region.w}, 高=${region.h}`;
      coordsEl.classList.remove('hidden');
    }
    resetBtn?.classList.remove('hidden');
    return;
  }

  modeEl.textContent = '全屏识图';
  coordsEl?.classList.add('hidden');
  resetBtn?.classList.add('hidden');
}

async function fetchCaptureRegionStatus() {
  return apiFetch('/api/capture-region');
}

function stopCaptureRegionPoll() {
  if (captureRegionPollTimer) {
    clearTimeout(captureRegionPollTimer);
    captureRegionPollTimer = null;
  }
}

async function pollCaptureRegionUntilDone() {
  stopCaptureRegionPoll();
  const maxMs = 120000;
  const intervalMs = 500;
  const start = Date.now();

  return new Promise((resolve) => {
    const tick = async () => {
      try {
        const data = await fetchCaptureRegionStatus();
        applyCaptureRegionFromPayload(data);
        const state = data.selection_state || 'idle';
        if (state !== 'selecting') {
          stopCaptureRegionPoll();
          resolve(data);
          return;
        }
        if (Date.now() - start >= maxMs) {
          stopCaptureRegionPoll();
          showToast('框选等待超时，请重试', true);
          resolve(data);
          return;
        }
        captureRegionPollTimer = setTimeout(tick, intervalMs);
      } catch (e) {
        stopCaptureRegionPoll();
        showToast(e.message || '获取识图区域状态失败', true);
        resolve(null);
      }
    };
    tick();
  });
}

function initCaptureRegionControls() {
  document.getElementById('btnCaptureRegionSelect')?.addEventListener('click', async () => {
    try {
      const res = await apiFetch('/api/capture-region/select', { method: 'POST' });
      applyCaptureRegionFromPayload({
        mode: 'full',
        region: { x: 0, y: 0, w: 0, h: 0 },
        selection_state: res.selection_state || 'selecting',
      });
      showToast('请在识图显示器上拖动鼠标框选区域~');
      const done = await pollCaptureRegionUntilDone();
      if (!done) return;
      if (done.selection_state === 'saved') {
        showToast('识图区域已保存~');
      } else if (done.selection_state === 'cancelled') {
        showToast('已取消框选');
      } else if (done.selection_state === 'invalid') {
        showToast('区域无效或过小，请重新框选', true);
      }
    } catch (e) {
      showToast(e.message || '无法启动框选', true);
    }
  });

  document.getElementById('btnCaptureRegionReset')?.addEventListener('click', async () => {
    try {
      await apiFetch('/api/capture-region/reset', { method: 'POST' });
      const data = await fetchCaptureRegionStatus();
      applyCaptureRegionFromPayload(data);
      showToast('已恢复全屏识图~');
    } catch (e) {
      showToast(e.message || '恢复全屏失败', true);
    }
  });

  fetchCaptureRegionStatus()
    .then(applyCaptureRegionFromPayload)
    .catch(() => {});
}

async function loadScreens() {
  const screens = await fetch(`${API.base}/api/screens`).then((r) => r.json());
  const sel = document.getElementById('screen_index');
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = '';
  screens.forEach((s) => {
    const opt = document.createElement('option');
    opt.value = String(s.index);
    opt.textContent = s.label;
    sel.appendChild(opt);
  });
  if (current !== '') sel.value = current;
  sel.disabled = screens.length <= 1;
}

async function loadProviders() {
  providersCache = await fetch(`${API.base}/api/providers`).then((r) => r.json());
  const sel = document.getElementById('providerPreset');
  if (!sel) return;
  sel.innerHTML = '<option value="">自定义</option>';
  providersCache.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.label;
    sel.appendChild(opt);
  });
  const modelProv = document.getElementById('modelProvider');
  if (modelProv) {
    modelProv.innerHTML = '';
    providersCache.forEach((p) => {
      const opt = document.createElement('option');
      opt.value = p.id;
      opt.textContent = p.label;
      modelProv.appendChild(opt);
    });
  }
}

function pickDefaultCatalogModelId(providerId) {
  const platform = resolveCatalogPlatform(providerId);
  if (!platform?.models?.length) return '';
  const preferred = platform.default_model_id;
  if (preferred && platform.models.some((m) => m.id === preferred)) {
    return preferred;
  }
  const cheapest = platform.models.find((m) => m.cheapest);
  return (cheapest || platform.models[0]).id;
}

function syncProviderPresetFromEndpoint() {
  const sel = document.getElementById('providerPreset');
  if (!sel) return;
  const endpoint = document.getElementById('api_endpoint')?.value || '';
  const apiMode = document.getElementById('api_mode')?.value || '';
  const guessed = guessProviderIdFromEndpoint(endpoint, apiMode);
  if (!guessed) {
    sel.value = '';
    return;
  }
  const hasOption = Array.from(sel.options).some((opt) => opt.value === guessed);
  sel.value = hasOption ? guessed : '';
}

/** Catalog platform for vision picker: endpoint + api_mode only (not providerPreset). */
function resolveProviderIdForPicker() {
  const endpoint = document.getElementById('api_endpoint')?.value || '';
  const apiMode = document.getElementById('api_mode')?.value || '';
  return guessProviderIdFromEndpoint(endpoint, apiMode);
}

function syncProviderPresetAfterEndpointEdit() {
  syncProviderPresetFromEndpoint();
  syncVisionModelPickerFromForm(document.getElementById('model')?.value || '');
}

// 切换服务商预设：填 endpoint/mode、清空 API Key 输入、重置为 catalog 默认视觉模型。
// 仅影响表单；运行中配置以 PUT /api/config 为准，与 Qt Overlay 无关。
function applyProviderPreset(providerId) {
  const p = providersCache.find((x) => x.id === providerId);
  if (!p) return;
  document.getElementById('api_endpoint').value = p.default_endpoint;
  document.getElementById('api_mode').value = p.mode === 'openai-compatible' ? 'openai' : p.mode;
  const apiKeyEl = document.getElementById('api_key');
  if (apiKeyEl) apiKeyEl.value = '';
  const defaultModelId = pickDefaultCatalogModelId(providerId);
  renderVisionModelPicker(providerId, defaultModelId, { providerSwitch: true });
  showToast(`已填入 ${p.label} 的默认地址，请填写对应 API 密钥~`);
}

async function loadModelCatalog() {
  try {
    catalogCache = await fetch(`${API.base}/api/model-catalog`).then((r) => r.json());
  } catch {
    catalogCache = { platforms: [] };
  }
  if (!catalogCache.platforms) catalogCache.platforms = [];
}

function resolveCatalogPlatform(providerId) {
  if (!providerId) return null;
  return catalogCache.platforms.find((p) => p.provider_id === providerId) || null;
}

function guessProviderIdFromEndpoint(endpoint, apiMode) {
  const value = (endpoint || '').toLowerCase();
  const ordered = [
    ['ark.cn-beijing.volces.com', 'doubao'],
    ['dashscope.aliyuncs.com', 'dashscope'],
    ['open.bigmodel.cn', 'zhipu'],
    ['api.moonshot.cn', 'moonshot'],
    ['api.siliconflow.cn', 'siliconflow'],
    ['api.xiaomimimo.com', 'mimo'],
  ];
  for (const [fragment, id] of ordered) {
    if (value.includes(fragment)) return id;
  }
  const mode = apiMode ?? document.getElementById('api_mode')?.value ?? '';
  if (mode === 'doubao') return 'doubao';
  return '';
}

function formatTokenPrice(value) {
  if (value === null || value === undefined) return '-';
  const num = Number(value);
  if (Number.isNaN(num)) return '-';
  const text = Number.isInteger(num) ? String(num) : String(num);
  return `${text} 元 / M tokens`;
}

function buildModelRowBadges(model) {
  const wrap = document.createElement('span');
  wrap.className = 'vision-model-badges shrink-0';
  const add = (text) => {
    const badge = document.createElement('span');
    badge.className = 'vision-model-badge';
    badge.textContent = text;
    wrap.appendChild(badge);
  };
  if (model.cheapest && model.supports_mic) {
    add('最便宜+麦克风');
    return wrap;
  }
  if (model.cheapest) add('本平台最便宜');
  if (model.supports_mic) add('支持麦克风');
  return wrap.childElementCount ? wrap : null;
}

function buildModelTooltipHtml(model) {
  const price = model.price || {};
  return (
    `<span class="model-tooltip-line">模型名称：${model.name}</span>`
    + `<span class="model-tooltip-line">模型 ID：${model.id}</span>`
    + `<span class="model-tooltip-line">输入价格：${formatTokenPrice(price.input)}</span>`
    + `<span class="model-tooltip-line">音频价格：${formatTokenPrice(price.audio)}</span>`
    + `<span class="model-tooltip-line">输出价格：${formatTokenPrice(price.output)}</span>`
  );
}

let floatingTooltipEl = null;
let floatingTooltipDismissBound = false;

function ensureFloatingTooltip() {
  if (!floatingTooltipEl) {
    floatingTooltipEl = document.createElement('div');
    floatingTooltipEl.id = 'uiTooltipFloat';
    floatingTooltipEl.className = 'ui-tooltip-float';
    floatingTooltipEl.setAttribute('role', 'tooltip');
    document.body.appendChild(floatingTooltipEl);
  }
  return floatingTooltipEl;
}

function bindFloatingTooltipDismiss() {
  if (floatingTooltipDismissBound) return;
  floatingTooltipDismissBound = true;
  const hide = () => hideFloatingTooltip();
  window.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
  document.getElementById('settingsForm')?.addEventListener('scroll', hide, true);
}

function positionFloatingTooltip(anchor) {
  const tip = ensureFloatingTooltip();
  tip.style.visibility = 'hidden';
  tip.style.display = 'block';
  const anchorRect = anchor.getBoundingClientRect();
  const tipRect = tip.getBoundingClientRect();
  const margin = 10;
  let top = anchorRect.bottom + margin;
  let left = anchorRect.left + anchorRect.width / 2 - tipRect.width / 2;
  if (top + tipRect.height > window.innerHeight - margin) {
    top = anchorRect.top - tipRect.height - margin;
  }
  left = Math.max(margin, Math.min(left, window.innerWidth - tipRect.width - margin));
  top = Math.max(margin, Math.min(top, window.innerHeight - tipRect.height - margin));
  tip.style.top = `${Math.round(top)}px`;
  tip.style.left = `${Math.round(left)}px`;
  tip.style.visibility = 'visible';
}

function showFloatingTooltip(anchor, content, options = {}) {
  bindFloatingTooltipDismiss();
  const { html = false, wide = false, tipId = '' } = options;
  const tip = ensureFloatingTooltip();
  tip.classList.toggle('ui-tooltip-float--wide', Boolean(wide));
  if (tipId) tip.id = tipId;
  else tip.removeAttribute('id');
  if (html) tip.innerHTML = content;
  else tip.textContent = content;
  positionFloatingTooltip(anchor);
}

function hideFloatingTooltip() {
  if (!floatingTooltipEl) return;
  floatingTooltipEl.style.display = 'none';
  floatingTooltipEl.style.visibility = '';
  floatingTooltipEl.classList.remove('ui-tooltip-float--wide');
}

function wireFloatingTooltipButton(btn, onShow) {
  btn.addEventListener('click', (e) => e.preventDefault());
  btn.addEventListener('mouseenter', onShow);
  btn.addEventListener('mouseleave', hideFloatingTooltip);
  btn.addEventListener('focus', onShow);
  btn.addEventListener('blur', hideFloatingTooltip);
}

function createModelPriceHint(model) {
  const wrap = document.createElement('span');
  wrap.className = 'field-hint-wrap relative shrink-0';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'field-hint-btn';
  btn.setAttribute('aria-label', `查看 ${model.id} 的价格说明`);
  btn.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="#i-info"></use></svg>';
  wireFloatingTooltipButton(btn, () => {
    showFloatingTooltip(btn, buildModelTooltipHtml(model), { html: true, wide: true });
  });
  wrap.append(btn);
  return wrap;
}

function appendVisionModelRowMeta(row, model) {
  const badges = buildModelRowBadges(model);
  if (badges) row.appendChild(badges);
  row.appendChild(createModelPriceHint(model));
}

function setVisionModelValue(modelId) {
  const hidden = document.getElementById('model');
  if (hidden) hidden.value = modelId || '';
  updateMicModeHint();
}

function syncVisionModelToHidden() {
  const customWrap = document.getElementById('visionModelCustom');
  const customInput = document.getElementById('modelCustom');
  const checked = document.querySelector('input[name="vision_model_choice"]:checked');
  if (checked?.value === VISION_MODEL_CUSTOM_VALUE) {
    setVisionModelValue(customInput?.value?.trim() || '');
    return;
  }
  if (checked) {
    setVisionModelValue(checked.value);
    return;
  }
  if (customWrap && !customWrap.classList.contains('hidden') && customInput) {
    setVisionModelValue(customInput.value.trim());
  }
}

function showVisionModelCustom(show, initialValue = '') {
  const wrap = document.getElementById('visionModelCustom');
  const input = document.getElementById('modelCustom');
  if (!wrap || !input) return;
  if (show) {
    wrap.classList.remove('hidden');
    if (initialValue !== undefined && initialValue !== null) input.value = initialValue;
    input.oninput = () => setVisionModelValue(input.value.trim());
  } else {
    wrap.classList.add('hidden');
    input.oninput = null;
  }
}

function setVisionModelPickerVisible(visible) {
  const picker = document.getElementById('visionModelPicker');
  if (!picker) return;
  if (visible) picker.classList.remove('hidden');
  else picker.classList.add('hidden');
}

// providerSwitch=true 时强制选平台最便宜模型；否则保留已保存的 model（含「自定义」行）
function renderVisionModelPicker(providerId, selectedModelId, options = {}) {
  const picker = document.getElementById('visionModelPicker');
  if (!picker) return;

  const { providerSwitch = false } = options;
  const platform = resolveCatalogPlatform(providerId);
  if (!platform || !platform.models?.length) {
    picker.innerHTML = '';
    setVisionModelPickerVisible(false);
    const customInitial = providerSwitch ? '' : (selectedModelId || '');
    showVisionModelCustom(true, customInitial);
    setVisionModelValue(customInitial);
    return;
  }

  setVisionModelPickerVisible(true);
  picker.innerHTML = '';
  const knownIds = new Set(platform.models.map((m) => m.id));
  const defaultId = pickDefaultCatalogModelId(providerId);
  let selected;
  let useCustom;
  if (providerSwitch) {
    selected = defaultId || platform.models[0].id;
    useCustom = false;
  } else {
    selected = selectedModelId && knownIds.has(selectedModelId)
      ? selectedModelId
      : (defaultId || platform.models[0].id);
    useCustom = Boolean(selectedModelId && !knownIds.has(selectedModelId));
  }

  platform.models.forEach((model) => {
    const row = document.createElement('label');
    row.className = 'vision-model-row';
    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = 'vision_model_choice';
    radio.value = model.id;
    radio.checked = !useCustom && model.id === selected;
    radio.addEventListener('change', () => {
      if (radio.checked) {
        showVisionModelCustom(false);
        setVisionModelValue(model.id);
      }
    });

    const textWrap = document.createElement('span');
    textWrap.className = 'vision-model-id flex flex-col min-w-0';
    const nameSpan = document.createElement('span');
    nameSpan.className = 'font-semibold text-warmText truncate';
    nameSpan.textContent = model.name || model.id;
    const idSpan = document.createElement('span');
    idSpan.className = 'text-xs text-gray-400 truncate';
    idSpan.textContent = model.id;
    textWrap.append(nameSpan, idSpan);

    row.append(radio, textWrap);
    appendVisionModelRowMeta(row, model);
    picker.appendChild(row);
  });

  const otherRow = document.createElement('label');
  otherRow.className = 'vision-model-row';
  const otherRadio = document.createElement('input');
  otherRadio.type = 'radio';
  otherRadio.name = 'vision_model_choice';
  otherRadio.value = VISION_MODEL_CUSTOM_VALUE;
  otherRadio.checked = useCustom;
  otherRadio.addEventListener('change', () => {
    const current = document.getElementById('model')?.value || '';
    showVisionModelCustom(true, useCustom ? (selectedModelId || current) : '');
    syncVisionModelToHidden();
  });
  const otherLabel = document.createElement('span');
  otherLabel.className = 'vision-model-id';
  otherLabel.textContent = '自定义模型';
  otherRow.append(otherRadio, otherLabel);
  picker.appendChild(otherRow);

  if (useCustom) {
    showVisionModelCustom(true, selectedModelId);
  } else {
    setVisionModelValue(selected);
  }
}

function syncVisionModelPickerFromForm(selectedModelId) {
  renderVisionModelPicker(resolveProviderIdForPicker(), selectedModelId || '');
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

// 自定义模型 CRUD：掩码 apiKey 在服务端保留；设为默认会同步 global model（ConfigService 双写规则）
async function loadCustomModels() {
  const data = await apiFetch('/api/custom-models');
  const list = document.getElementById('customModelsList');
  if (!list) return;
  list.innerHTML = '';
  if (!data.items.length) {
    list.innerHTML = '<p class="text-sm text-gray-400">暂无自定义模型，点击上方新增~</p>';
    return;
  }
  data.items.forEach((m, index) => {
    const row = document.createElement('div');
    row.className = 'flex flex-wrap items-center gap-2 p-3 bg-cream rounded-xl text-sm';
    const isDefault = m.modelId === data.default_model_id;
    row.innerHTML = `
      <span class="font-semibold text-warmText">${m.name || '未命名'}</span>
      <span class="text-gray-400">${m.modelId}</span>
      ${isDefault ? '<span class="text-green-600 text-xs font-bold">默认</span>' : ''}
      ${m.complete === false ? '<span class="text-amber-600 text-xs font-bold">配置不完整</span>' : ''}
    `;
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'px-3 py-1 border border-gray-200 rounded-lg text-xs';
    editBtn.textContent = '编辑';
    editBtn.onclick = () => openModelModal(index, m);
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'px-3 py-1 border border-red-200 rounded-lg text-xs text-red-600';
    delBtn.textContent = '删除';
    delBtn.onclick = async () => {
      if (!confirm(`确定删除模型「${m.name}」吗？`)) return;
      try {
        await apiFetch(`/api/custom-models/${index}`, { method: 'DELETE' });
        showToast('已删除~');
        loadCustomModels();
      } catch (e) {
        showToast(e.message, true);
      }
    };
    row.appendChild(editBtn);
    row.appendChild(delBtn);
    if (!isDefault) {
      const defBtn = document.createElement('button');
      defBtn.type = 'button';
      defBtn.className = 'px-3 py-1 border border-gray-200 rounded-lg text-xs';
      defBtn.textContent = '设为默认';
      defBtn.onclick = async () => {
        const res = await apiFetch(`/api/custom-models/${index}/default`, { method: 'POST' });
        const modelEl = document.getElementById('model');
        if (modelEl && res.default_model_id) {
          modelEl.value = res.default_model_id;
          syncVisionModelPickerFromForm(res.default_model_id);
        }
        const cfg = await reloadConfigFromServer();
        updateModelActiveSourceBanner(cfg);
        showToast(`已设为默认模型：${res.default_model_id || m.modelId}`);
        loadCustomModels();
      };
      row.appendChild(defBtn);
    }
    list.appendChild(row);
  });
}

function openModelModal(index, model = {}) {
  document.getElementById('modelEditIndex').value = String(index);
  document.getElementById('modelModalTitle').textContent = index >= 0 ? '编辑模型' : '新增模型';
  document.getElementById('modelName').value = model.name || '';
  document.getElementById('modelId').value = model.modelId || '';
  document.getElementById('modelMode').value = model.mode || 'doubao';
  document.getElementById('modelEndpoint').value = model.endpoint || '';
  document.getElementById('modelApiKey').value = model.apiKey === '********' ? '********' : (model.apiKey || '');
  document.getElementById('modelDescription').value = model.description || '';
  const modal = document.getElementById('modelModal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeModelModal() {
  const modal = document.getElementById('modelModal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function openRewardModal() {
  const modal = document.getElementById('rewardModal');
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeRewardModal() {
  const modal = document.getElementById('rewardModal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function collectModelForm() {
  return {
    name: document.getElementById('modelName').value,
    modelId: document.getElementById('modelId').value,
    mode: document.getElementById('modelMode').value,
    endpoint: document.getElementById('modelEndpoint').value,
    apiKey: document.getElementById('modelApiKey').value,
    description: document.getElementById('modelDescription').value,
    provider: document.getElementById('modelProvider').value,
  };
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

/** 助手设置表单字段说明（悬停 Label 旁 ⓘ 显示） */
const SETTINGS_FIELD_TIPS = {
  providerPreset:
    '选一个常见 AI 平台，会自动填好接口地址和模式；选「自定义」则需自己逐项设置。',
  api_endpoint:
    '视觉模型服务的网址。火山方舟豆包一般填到 /api/v3；多数 OpenAI 兼容服务填到 /v1。',
  api_mode:
    'doubao：火山方舟豆包。openai：其他兼容 Chat 接口的服务（如部分第三方中转）。麦克风模式需选 doubao。',
  model:
    '实际调用的模型名称或接入点 ID。也可在下方「自定义模型」里保存多套配置。',
  screen_index:
    '截图和弹幕叠在哪块显示器上。编号无效时会自动改用主屏。',
  temperature:
    '创意程度（0–2）。越高弹幕用词越发散，越低越稳定、越像固定话术。',
  max_tokens:
    '单次 AI 回复允许的最长输出。开启「思考」类模型时，程序会自动提高实际下限。',
  memory_mode:
    '关闭：不额外记忆。轻量：只避免重复弹幕。标准：记住画面要点并防重复。强记忆：注入更多上下文，换场景时保留更多内容。',
  memory_window:
    '记住最近几条已成功显示的 AI 弹幕（1–20 条），用来提醒模型别再说同样的话。',
  mic_mode_enabled:
    '实验功能：说完一句话后额外生成几条接话弹幕，插队显示，不影响看屏识图节奏。需豆包接口且模型支持麦克风；默认关，录音仅在内存、不落盘。使用 Windows「设置 → 系统 → 声音 → 输入」里的默认麦克风；换耳机后建议先停弹幕再开或重启应用。',
  mic_window_sec:
    '每次说话时，附带最近多少秒的麦克风录音发给 AI（1–30 秒，默认 5）。',
  btnMicTest:
    '录大约 3 秒，检查麦克风是否有声音。不联网、不上传、不保存文件。',
  btnMicTestSend:
    '录大约 3 秒后，把声音和占位图发给 AI，确认模型能收到你的麦克风输入。',
  api_key:
    '访问 AI 的密钥，保存在本机并加密。留空点「保存配置」不会覆盖已有密钥。',
  normal_recognition_interval_sec:
    '普通模式下，每隔多少秒识图并生成一批弹幕（1–60 秒）。',
  normal_reply_count:
    '普通模式下，每次识图固定生成几条弹幕（1–20 条）。',
  danmu_speed:
    '弹幕横向移动快慢（约 0.5–5）。数字越大滚得越快。',
  danmu_lines:
    '屏幕上最多几行弹幕轨道（12–20 行）。',
  danmu_max_chars:
    '单条弹幕最多显示多少字（5–80），超出会截断并加省略号。未填写时默认中文约 15、英文约 40。',
  font_size:
    '弹幕字号，约 12–72 像素。',
  opacity:
    '弹幕透明度 0–100%，100 为完全不透明。',
  dedup_threshold:
    '和最近弹幕有多像就算重复（0–1）。越高越容易判重复并丢掉，默认约 0.5。',
  layout_mode:
    '弹幕显示区域占整块屏幕的比例（全屏、四分之三、一半、四分之一）。',
  hotkey:
    '全局快捷键，随时开始或停止生成弹幕。首次使用可能需在系统里允许本程序监听键盘。',
  eviction_mode:
    '自然：按正常速度滚出屏幕。加速：换场景或清屏时让旧弹幕更快消失。',
  empty_accel:
    '某行轨道空了时，暂时加快滚动，让新弹幕更快占满空位。',
  image_max_width:
    '发给 AI 前把截图缩到多宽。越小越省流量和费用，越大越清晰。',
  image_quality:
    'JPEG 压缩质量 1–100，默认 85。越高图越清楚、文件越大。',
  btnProbe:
    '用当前填写的地址、模式和密钥试连一次 AI，不开始弹幕，也不改其它设置。',
};

const SETTINGS_HEADING_TIPS = {
  'custom-models':
    '为不同接口地址、模型、密钥保存多套配置，可指定默认；这里的密钥与上方全局密钥分开管理。',
  'compress-preview':
    '上传一张样图，预览当前「最大宽度」和「JPEG 质量」下的压缩效果。图片只在内存里处理，不会保存到硬盘。',
};

function createFieldHintWrap(tipText, tipId) {
  const wrap = document.createElement('span');
  wrap.className = 'field-hint-wrap relative shrink-0';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'field-hint-btn';
  btn.setAttribute('aria-label', '字段说明');
  if (tipId) btn.setAttribute('aria-describedby', tipId);
  btn.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="#i-info"></use></svg>';
  wireFloatingTooltipButton(btn, () => {
    showFloatingTooltip(btn, tipText, { tipId });
  });
  wrap.append(btn);
  return wrap;
}

function attachHintToLabel(label, tipText, tipId) {
  if (!label || label.querySelector('.field-hint-wrap')) return;
  const wrap = createFieldHintWrap(tipText, tipId);

  if (label.classList.contains('flex') && label.querySelector('input, select, textarea')) {
    label.appendChild(wrap);
    return;
  }

  const row = document.createElement('div');
  row.className = 'field-label-row flex items-center gap-1';
  const useBlockSpacing =
    label.classList.contains('block') || label.classList.contains('settings-field-label');
  if (useBlockSpacing) {
    row.classList.add('mb-2');
    label.classList.remove('block', 'mb-2');
  }
  if (label.classList.contains('mb-1')) {
    row.classList.add('mb-1');
    label.classList.remove('mb-1');
  }
  label.classList.add('flex-1', 'min-w-0');
  label.parentNode.insertBefore(row, label);
  row.append(label, wrap);
}

function attachHintToHeading(heading, tipText, tipId) {
  if (!heading || heading.querySelector('.field-hint-wrap')) return;
  const row = document.createElement('div');
  row.className = 'field-label-row flex items-center gap-1 mb-4';
  const title = document.createElement('span');
  title.className = `${heading.className} flex-1 min-w-0 mb-0`;
  title.innerHTML = heading.innerHTML;
  heading.replaceWith(row);
  row.append(title, createFieldHintWrap(tipText, tipId));
}

function resolveSettingsLabel(fieldEl) {
  if (!fieldEl) return null;
  const id = fieldEl.id;
  if (id) {
    const byFor = document.querySelector(`#settingsForm label[for="${id}"]`);
    if (byFor) return byFor;
  }
  const inLabel = fieldEl.closest('#settingsForm label');
  if (inLabel) return inLabel;
  const parent = fieldEl.parentElement;
  if (parent) {
    const prev = fieldEl.previousElementSibling;
    if (prev && prev.tagName === 'LABEL') return prev;
    const labelInParent = parent.querySelector(':scope > label');
    if (labelInParent) return labelInParent;
  }
  return null;
}

function initSidebarNavFloatingHints() {
  document.querySelectorAll('.sidebar-nav-hint-wrap').forEach((wrap) => {
    const btn = wrap.querySelector('.sidebar-nav-hint');
    const inlineTip = wrap.querySelector('.warm-tooltip');
    if (!btn || !inlineTip || btn.dataset.floatingTip === '1') return;
    const html = inlineTip.innerHTML;
    const tipId = inlineTip.id || '';
    if (tipId) btn.setAttribute('aria-describedby', tipId);
    inlineTip.remove();
    btn.dataset.floatingTip = '1';
    wireFloatingTooltipButton(btn, () => {
      showFloatingTooltip(btn, html, { html: true, wide: true, tipId });
    });
  });
}

const SETTINGS_CONTROL_HINT_IDS = new Set(['btnMicTest', 'btnMicTestSend', 'btnProbe']);

function attachHintAfterControl(control, tipText, tipId) {
  if (!control || control.dataset.hintAttached === '1') return;
  control.insertAdjacentElement('afterend', createFieldHintWrap(tipText, tipId));
  control.dataset.hintAttached = '1';
}

function initSettingsFieldHints() {
  const form = document.getElementById('settingsForm');
  if (!form) return;

  Object.entries(SETTINGS_FIELD_TIPS).forEach(([fieldId, tip]) => {
    const field = document.getElementById(fieldId);
    if (!field) return;
    if (SETTINGS_CONTROL_HINT_IDS.has(fieldId)) {
      attachHintAfterControl(field, tip, `tip-field-${fieldId}`);
      return;
    }
    const label = resolveSettingsLabel(field);
    if (label) attachHintToLabel(label, tip, `tip-field-${fieldId}`);
  });

  attachHintToHeading(
    document.querySelector('#customModelsSection h4'),
    SETTINGS_HEADING_TIPS['custom-models'],
    'tip-heading-custom-models',
  );
  const compressTitle = document.querySelector('#compressPreviewSection > .settings-section-title');
  if (compressTitle) {
    attachHintToHeading(
      compressTitle,
      SETTINGS_HEADING_TIPS['compress-preview'],
      'tip-heading-compress-preview',
    );
  }
}

function switchSettingsTab(tabId) {
  activeSettingsTabId = tabId;
  document.querySelectorAll('.settings-tab').forEach((tab) => {
    const active = tab.dataset.settingsTab === tabId;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('.settings-tab-panel').forEach((panel) => {
    const active = panel.dataset.settingsPanel === tabId;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
}

function initSettingsTabs() {
  document.querySelectorAll('.settings-tab').forEach((tab) => {
    tab.addEventListener('click', () => switchSettingsTab(tab.dataset.settingsTab));
  });
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

const ANNOUNCEMENTS_READ_IDS_KEY = 'danmu_announcements_read_ids';
const ANNOUNCEMENTS_LAST_SEEN_MS_KEY = 'danmu_announcements_last_seen_ms';
/** @deprecated migrated to ID set + ms; removed after one-time migration */
const ANNOUNCEMENTS_LAST_SEEN_KEY = 'danmu_announcements_last_seen_at';
const ANNOUNCEMENTS_OVERVIEW_BANNER_DISMISSED_ID_KEY =
  'danmu_announcements_overview_banner_dismissed_id';
const ANNOUNCEMENTS_BADGE_POLL_MS = 5 * 60 * 1000;
const ANNOUNCEMENTS_READ_IDS_MAX = 200;
const ANNOUNCEMENT_SNIPPET_MAX_CHARS = 30;
let announcementsBadgePollTimer = null;
let announcementsReadStateLoaded = false;
let announcementsLegacyMigrated = false;
let overviewBannerLatestId = null;

const announcementsReadState = {
  readIds: new Set(),
  lastSeenMs: 0,
  overviewBannerDismissedId: '',
};

function readAnnouncementsReadIdsFromLocal() {
  try {
    const raw = localStorage.getItem(ANNOUNCEMENTS_READ_IDS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'string' && id) : [];
  } catch {
    return [];
  }
}

function readAnnouncementsLastSeenMsFromLocal() {
  try {
    const raw = localStorage.getItem(ANNOUNCEMENTS_LAST_SEEN_MS_KEY);
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? Math.floor(n) : 0;
  } catch {
    return 0;
  }
}

function readOverviewBannerDismissedIdFromLocal() {
  try {
    return localStorage.getItem(ANNOUNCEMENTS_OVERVIEW_BANNER_DISMISSED_ID_KEY) || '';
  } catch {
    return '';
  }
}

function writeOverviewBannerDismissedIdToLocal(id) {
  try {
    if (id) {
      localStorage.setItem(ANNOUNCEMENTS_OVERVIEW_BANNER_DISMISSED_ID_KEY, id);
    } else {
      localStorage.removeItem(ANNOUNCEMENTS_OVERVIEW_BANNER_DISMISSED_ID_KEY);
    }
  } catch {
    /* ignore quota / private mode */
  }
}

function writeAnnouncementsReadStateToLocal() {
  try {
    const ids = [...announcementsReadState.readIds];
    const trimmed =
      ids.length > ANNOUNCEMENTS_READ_IDS_MAX
        ? ids.slice(-ANNOUNCEMENTS_READ_IDS_MAX)
        : ids;
    localStorage.setItem(ANNOUNCEMENTS_READ_IDS_KEY, JSON.stringify(trimmed));
    localStorage.setItem(
      ANNOUNCEMENTS_LAST_SEEN_MS_KEY,
      String(announcementsReadState.lastSeenMs),
    );
    writeOverviewBannerDismissedIdToLocal(
      announcementsReadState.overviewBannerDismissedId,
    );
  } catch {
    /* ignore quota / private mode */
  }
}

function mergeAnnouncementsReadState(remote, localIds, localMs, localOverviewDismissedId) {
  const mergedIds = new Set();
  if (Array.isArray(remote?.readIds)) {
    for (const id of remote.readIds) {
      if (typeof id === 'string' && id) mergedIds.add(id);
    }
  }
  for (const id of localIds) mergedIds.add(id);
  let lastSeenMs = 0;
  if (remote && Number.isFinite(Number(remote.lastSeenMs))) {
    lastSeenMs = Math.max(0, Math.floor(Number(remote.lastSeenMs)));
  }
  lastSeenMs = Math.max(lastSeenMs, localMs);
  const remoteDismissed =
    typeof remote?.overviewBannerDismissedId === 'string'
      ? remote.overviewBannerDismissedId.trim()
      : '';
  const overviewBannerDismissedId = remoteDismissed || localOverviewDismissedId || '';
  announcementsReadState.readIds = mergedIds;
  announcementsReadState.lastSeenMs = lastSeenMs;
  announcementsReadState.overviewBannerDismissedId = overviewBannerDismissedId;
}

function serializeAnnouncementsReadState() {
  const readIds = [...announcementsReadState.readIds];
  const trimmed =
    readIds.length > ANNOUNCEMENTS_READ_IDS_MAX
      ? readIds.slice(-ANNOUNCEMENTS_READ_IDS_MAX)
      : readIds;
  return {
    readIds: trimmed,
    lastSeenMs: announcementsReadState.lastSeenMs,
    overviewBannerDismissedId: announcementsReadState.overviewBannerDismissedId || '',
  };
}

async function loadAnnouncementsReadState() {
  const localIds = readAnnouncementsReadIdsFromLocal();
  const localMs = readAnnouncementsLastSeenMsFromLocal();
  const localOverviewDismissedId = readOverviewBannerDismissedIdFromLocal();
  let remote = null;
  try {
    if (API.base) {
      remote = await fetch(`${API.base}/api/announcements-read-state`, {
        cache: 'no-store',
      }).then((r) => (r.ok ? r.json() : null));
    }
  } catch {
    remote = null;
  }
  mergeAnnouncementsReadState(remote, localIds, localMs, localOverviewDismissedId);
  writeAnnouncementsReadStateToLocal();
  announcementsReadStateLoaded = true;
}

async function persistAnnouncementsReadState() {
  writeAnnouncementsReadStateToLocal();
  try {
    await apiFetch('/api/announcements-read-state', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(serializeAnnouncementsReadState()),
    });
  } catch {
    /* localStorage remains; next GET will merge */
  }
}

function maxAnnouncementCreatedMs(rows) {
  let maxMs = 0;
  for (const row of rows || []) {
    const t = Date.parse(row.created_at || '');
    if (!Number.isNaN(t) && t > maxMs) maxMs = t;
  }
  return maxMs;
}

function migrateLegacyAnnouncementsLastSeen(rows) {
  if (announcementsLegacyMigrated) return;
  announcementsLegacyMigrated = true;
  let legacyIso = '';
  try {
    legacyIso = localStorage.getItem(ANNOUNCEMENTS_LAST_SEEN_KEY) || '';
  } catch {
    legacyIso = '';
  }
  if (!legacyIso) return;
  const seenMs = Date.parse(legacyIso);
  if (!Number.isNaN(seenMs)) {
    for (const row of rows || []) {
      const t = Date.parse(row.created_at || '');
      if (row.id && !Number.isNaN(t) && t <= seenMs) {
        announcementsReadState.readIds.add(row.id);
      }
    }
    announcementsReadState.lastSeenMs = Math.max(announcementsReadState.lastSeenMs, seenMs);
  }
  try {
    localStorage.removeItem(ANNOUNCEMENTS_LAST_SEEN_KEY);
  } catch {
    /* ignore */
  }
}

function hasUnreadAnnouncements(rows) {
  if (!rows?.length) return false;
  return rows.some((row) => row.id && !announcementsReadState.readIds.has(row.id));
}

function markAnnouncementsRead(rows) {
  migrateLegacyAnnouncementsLastSeen(rows);
  for (const row of rows || []) {
    if (row.id) announcementsReadState.readIds.add(row.id);
  }
  const maxMs = maxAnnouncementCreatedMs(rows);
  if (maxMs > 0) {
    announcementsReadState.lastSeenMs = Math.max(announcementsReadState.lastSeenMs, maxMs);
  }
  if (announcementsReadState.readIds.size > ANNOUNCEMENTS_READ_IDS_MAX) {
    const trimmed = [...announcementsReadState.readIds].slice(-ANNOUNCEMENTS_READ_IDS_MAX);
    announcementsReadState.readIds = new Set(trimmed);
  }
  persistAnnouncementsReadState().catch(console.error);
}

function updateAnnouncementsNavBadge(show) {
  const badge = document.getElementById('announcementsNavBadge');
  if (!badge) return;
  badge.classList.toggle('hidden', !show);
  badge.setAttribute('aria-hidden', show ? 'false' : 'true');
}

function getOverviewBannerDismissedId() {
  return announcementsReadState.overviewBannerDismissedId || '';
}

function setOverviewBannerDismissedId(id) {
  announcementsReadState.overviewBannerDismissedId = id ? String(id) : '';
  writeOverviewBannerDismissedIdToLocal(announcementsReadState.overviewBannerDismissedId);
  persistAnnouncementsReadState().catch(console.error);
}

function buildAnnouncementSnippetParts(row) {
  const title = String(row?.title ?? '').trim();
  const body = String(row?.body ?? '').trim();
  let combined;
  let titleCharCount;

  if (title && body) {
    combined = `${title}：${body}`;
    titleCharCount = Array.from(title).length + 1;
  } else if (title) {
    combined = title;
    titleCharCount = Array.from(title).length;
  } else if (body) {
    combined = body;
    titleCharCount = 0;
  } else {
    return null;
  }

  const chars = Array.from(combined);
  const overLimit = chars.length > ANNOUNCEMENT_SNIPPET_MAX_CHARS;
  const truncatedChars = overLimit ? chars.slice(0, ANNOUNCEMENT_SNIPPET_MAX_CHARS) : chars;
  const suffix = overLimit ? '…' : '';

  if (!title || !body) {
    if (title) {
      return { hasTitle: true, titlePart: truncatedChars.join('') + suffix, restPart: '' };
    }
    return { hasTitle: false, titlePart: '', restPart: truncatedChars.join('') + suffix };
  }

  const titleOnlyLen = Array.from(title).length;
  if (truncatedChars.length <= titleOnlyLen) {
    return { hasTitle: true, titlePart: truncatedChars.join('') + suffix, restPart: '' };
  }

  return {
    hasTitle: true,
    titlePart: title,
    restPart: truncatedChars.slice(titleCharCount).join('') + suffix,
  };
}

function buildAnnouncementSnippet(row) {
  const parts = buildAnnouncementSnippetParts(row);
  if (!parts) return '';
  return (parts.hasTitle ? parts.titlePart : '') + parts.restPart;
}

function renderOverviewAnnouncementBannerText(textEl, parts) {
  if (!parts || (!parts.titlePart && !parts.restPart)) {
    textEl.textContent = '';
    return;
  }
  if (parts.hasTitle && parts.titlePart) {
    textEl.innerHTML =
      `<strong class="overview-announcement-banner-title">${escapeHtml(parts.titlePart)}</strong>` +
      escapeHtml(parts.restPart);
  } else {
    textEl.textContent = parts.restPart;
  }
}

function hideOverviewAnnouncementBanner() {
  const banner = document.getElementById('overviewAnnouncementBanner');
  if (!banner) return;
  banner.classList.add('hidden');
  overviewBannerLatestId = null;
}

function updateOverviewAnnouncementBanner(rows) {
  const banner = document.getElementById('overviewAnnouncementBanner');
  const textEl = document.getElementById('overviewAnnouncementBannerText');
  if (!banner || !textEl) return;

  if (!window.DanmuSupabase?.isConfigured?.() || !rows?.length) {
    hideOverviewAnnouncementBanner();
    return;
  }

  const latest = rows[0];
  if (!latest?.id) {
    hideOverviewAnnouncementBanner();
    return;
  }

  const parts = buildAnnouncementSnippetParts(latest);
  if (!parts || (!parts.titlePart && !parts.restPart)) {
    hideOverviewAnnouncementBanner();
    return;
  }

  if (latest.id === getOverviewBannerDismissedId()) {
    hideOverviewAnnouncementBanner();
    return;
  }

  overviewBannerLatestId = latest.id;
  const level = ['info', 'warning', 'critical'].includes(latest.level) ? latest.level : 'info';
  banner.classList.remove('hidden', 'announcement-level-warning', 'announcement-level-critical');
  if (level === 'warning' || level === 'critical') {
    banner.classList.add(`announcement-level-${level}`);
  }
  renderOverviewAnnouncementBannerText(textEl, parts);
}

function dismissOverviewAnnouncementBanner(id) {
  if (id) setOverviewBannerDismissedId(id);
  hideOverviewAnnouncementBanner();
}

async function refreshAnnouncementsUnreadBadge() {
  if (!announcementsReadStateLoaded) {
    await loadAnnouncementsReadState();
  }
  if (!window.DanmuSupabase?.isConfigured?.()) {
    updateAnnouncementsNavBadge(false);
    hideOverviewAnnouncementBanner();
    return;
  }
  try {
    const rows = await window.DanmuSupabase.listAnnouncements();
    const list = Array.isArray(rows) ? rows : [];
    migrateLegacyAnnouncementsLastSeen(list);
    updateOverviewAnnouncementBanner(list);
    const onAnnouncementsPage = document.getElementById('page-announcements')?.classList.contains('active');
    if (onAnnouncementsPage) {
      markAnnouncementsRead(list);
      updateAnnouncementsNavBadge(false);
      return;
    }
    updateAnnouncementsNavBadge(hasUnreadAnnouncements(list));
  } catch {
    hideOverviewAnnouncementBanner();
    /* keep current badge state */
  }
}

function startAnnouncementsBadgePolling() {
  if (announcementsBadgePollTimer) return;
  announcementsBadgePollTimer = setInterval(() => {
    refreshAnnouncementsUnreadBadge().catch(console.error);
  }, ANNOUNCEMENTS_BADGE_POLL_MS);
}

function formatAnnouncementDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return String(iso);
  }
}

function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderAnnouncementsList(items) {
  const list = document.getElementById('announcementsList');
  if (!list) return;
  if (!window.DanmuSupabase?.isConfigured?.()) {
    list.innerHTML =
      '<p class="announcements-error">未配置云端公告服务。请将 supabase-config.example.js 复制为 supabase-config.js 并填入项目地址与密钥。</p>';
    return;
  }
  if (!items?.length) {
    list.innerHTML = '<p class="announcements-empty">暂无公告</p>';
    return;
  }
  list.innerHTML = items
    .map((row) => {
      const level = ['info', 'warning', 'critical'].includes(row.level) ? row.level : 'info';
      const pinned = row.pinned
        ? '<span class="announcement-pinned-badge">置顶</span>'
        : '';
      const meta = formatAnnouncementDate(row.created_at);
      return `<article class="announcement-card announcement-level-${level}">
        <header class="announcement-card-header">
          <h3 class="announcement-card-title">${escapeHtml(row.title)}</h3>
          ${pinned}
          <time class="announcement-card-meta" datetime="${escapeHtml(row.created_at || '')}">${escapeHtml(meta)}</time>
        </header>
        <div class="announcement-card-body">${escapeHtml(row.body)}</div>
      </article>`;
    })
    .join('');
}

async function loadAnnouncementsPage() {
  const list = document.getElementById('announcementsList');
  if (!list) return;
  if (!window.DanmuSupabase?.isConfigured?.()) {
    renderAnnouncementsList([]);
    return;
  }
  list.innerHTML = '<p class="text-gray-500 text-sm">正在加载公告…</p>';
  try {
    const rows = await window.DanmuSupabase.listAnnouncements();
    const list = Array.isArray(rows) ? rows : [];
    renderAnnouncementsList(list);
    markAnnouncementsRead(list);
    updateAnnouncementsNavBadge(false);
  } catch (err) {
    list.innerHTML = `<p class="announcements-error">${escapeHtml(err.message || '加载失败')} <button type="button" class="underline font-semibold" id="btnAnnouncementsRetry">重试</button></p>`;
    document.getElementById('btnAnnouncementsRetry')?.addEventListener('click', () => {
      loadAnnouncementsPage().catch(console.error);
    });
  }
}

function updateFeedbackQuotaHint(quota) {
  const el = document.getElementById('feedbackQuotaHint');
  if (!el) return;
  if (!quota) {
    el.textContent = '暂时无法查询提交额度';
    return;
  }
  const remaining = Number(quota.remaining ?? 0);
  const limit = Number(quota.limit ?? 2);
  const hint = quota.resets_hint || `每 3 小时最多提交 ${limit} 条`;
  if (remaining <= 0) {
    el.textContent = hint;
    el.classList.add('text-red-600');
  } else {
    el.textContent = `本机还可提交 ${remaining} / ${limit} 条（${hint}）`;
    el.classList.remove('text-red-600');
  }
  const submitBtn = document.getElementById('btnFeedbackSubmit');
  if (submitBtn) submitBtn.disabled = remaining <= 0;
}

async function refreshFeedbackQuota() {
  const el = document.getElementById('feedbackQuotaHint');
  if (!el) return;
  if (!window.DanmuSupabase?.isConfigured?.()) {
    el.textContent = '未配置云端反馈服务，无法在线提交（仍可通过下方社群联系）';
    const submitBtn = document.getElementById('btnFeedbackSubmit');
    if (submitBtn) submitBtn.disabled = true;
    return;
  }
  el.textContent = '正在查询提交额度…';
  el.classList.remove('text-red-600');
  try {
    const quota = await window.DanmuSupabase.getFeedbackQuota();
    updateFeedbackQuotaHint(quota);
  } catch (err) {
    el.textContent = err.message || '无法查询提交额度';
  }
}

let feedbackPageInitialized = false;

function initFeedbackPage() {
  refreshFeedbackQuota().catch(console.error);
  if (feedbackPageInitialized) return;
  feedbackPageInitialized = true;
  document.getElementById('feedbackForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!window.DanmuSupabase?.isConfigured?.()) {
      showToast('未配置云端反馈服务', true);
      return;
    }
    const content = document.getElementById('feedbackContent')?.value ?? '';
    const contact = document.getElementById('feedbackContact')?.value ?? '';
    const btn = document.getElementById('btnFeedbackSubmit');
    if (btn) btn.disabled = true;
    try {
      await window.DanmuSupabase.submitFeedback({ content, contact });
      showToast('反馈已提交，感谢你的帮助~');
      const ta = document.getElementById('feedbackContent');
      const inp = document.getElementById('feedbackContact');
      if (ta) ta.value = '';
      if (inp) inp.value = '';
      await refreshFeedbackQuota();
    } catch (err) {
      showToast(err.message || '提交失败', true);
    } finally {
      await refreshFeedbackQuota();
    }
  });
}

const AI_BUTLER_STATE = {
  messages: [],
  pendingPatch: null,
  pendingReasons: null,
  pendingCurrent: null,
  sending: false,
};

const AI_BUTLER_FIELD_LABELS = {
  temperature: '创意程度 (temperature)',
  max_tokens: '输出 token 上限',
  danmu_speed: '弹幕速度',
  danmu_lines: '弹幕行数',
  danmu_max_chars: '单条字数上限',
  dedup_threshold: '去重阈值',
  layout_mode: '显示区域',
  opacity: '透明度',
  font_size: '字号',
  eviction_mode: '退场模式',
  empty_accel: '空轨道加速',
  image_max_width: '截图最大宽度',
  image_quality: 'JPEG 质量',
  memory_mode: '记忆模式',
  memory_window: '记忆窗口',
  normal_recognition_interval_sec: '识图间隔（秒）',
  normal_reply_count: '每批弹幕条数',
};

function aiButlerFieldLabel(key) {
  return AI_BUTLER_FIELD_LABELS[key] || key;
}

function appendAiButlerMessage(role, text) {
  const box = document.getElementById('aiButlerMessages');
  if (!box) return;
  const row = document.createElement('div');
  row.className =
    role === 'user' ? 'ai-butler-msg ai-butler-msg-user' : 'ai-butler-msg ai-butler-msg-assistant';
  const bubble = document.createElement('div');
  bubble.className = 'ai-butler-msg-bubble';
  bubble.textContent = text;
  row.appendChild(bubble);
  box.appendChild(row);
  box.scrollTop = box.scrollHeight;
}

function showAiButlerThinking() {
  removeAiButlerThinking();
  const box = document.getElementById('aiButlerMessages');
  if (!box) return;
  const row = document.createElement('div');
  row.id = 'aiButlerThinkingRow';
  row.className = 'ai-butler-msg ai-butler-msg-assistant ai-butler-msg-thinking';
  row.setAttribute('aria-busy', 'true');
  const bubble = document.createElement('div');
  bubble.className = 'ai-butler-msg-bubble ai-butler-thinking-bubble';
  bubble.textContent = '正在思考中…';
  row.appendChild(bubble);
  box.appendChild(row);
  box.scrollTop = box.scrollHeight;
}

function removeAiButlerThinking() {
  document.getElementById('aiButlerThinkingRow')?.remove();
}

function setAiButlerInputBusy(busy) {
  const input = document.getElementById('aiButlerInput');
  const sendBtn = document.getElementById('btnAiButlerSend');
  if (input) input.disabled = busy;
  if (sendBtn) {
    sendBtn.disabled = busy;
    sendBtn.textContent = busy ? '思考中…' : '发送';
  }
}

function clearAiButlerSuggestionPanel() {
  AI_BUTLER_STATE.pendingPatch = null;
  AI_BUTLER_STATE.pendingReasons = null;
  AI_BUTLER_STATE.pendingCurrent = null;
  const panel = document.getElementById('aiButlerSuggestionPanel');
  const body = document.getElementById('aiButlerPatchBody');
  const hint = document.getElementById('aiButlerDiscardedHint');
  if (body) body.replaceChildren();
  if (hint) {
    hint.textContent = '';
    hint.classList.add('hidden');
  }
  panel?.classList.add('hidden');
}

function renderAiButlerSuggestion(data) {
  const patch = data.patch || {};
  const keys = Object.keys(patch);
  if (!keys.length) {
    clearAiButlerSuggestionPanel();
    return;
  }
  AI_BUTLER_STATE.pendingPatch = { ...patch };
  AI_BUTLER_STATE.pendingReasons = { ...(data.reasons || {}) };
  AI_BUTLER_STATE.pendingCurrent = { ...(data.current_values || {}) };

  const body = document.getElementById('aiButlerPatchBody');
  if (!body) return;
  body.replaceChildren();
  keys.forEach((key) => {
    const tr = document.createElement('tr');
    const cells = [
      aiButlerFieldLabel(key),
      String(AI_BUTLER_STATE.pendingCurrent[key] ?? '—'),
      String(patch[key] ?? ''),
      String((data.reasons && data.reasons[key]) || '—'),
    ];
    cells.forEach((text) => {
      const td = document.createElement('td');
      td.className = 'py-2 pr-3 align-top';
      td.textContent = text;
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });

  const discarded = data.discarded_fields || [];
  const hint = document.getElementById('aiButlerDiscardedHint');
  if (hint && discarded.length) {
    hint.textContent = `已忽略不允许修改的字段：${discarded.join('、')}`;
    hint.classList.remove('hidden');
  } else if (hint) {
    hint.classList.add('hidden');
  }

  document.getElementById('aiButlerSuggestionPanel')?.classList.remove('hidden');
}

async function updateAiButlerApiHint() {
  const hint = document.getElementById('aiButlerApiHint');
  if (!hint) return;
  try {
    const cfg = await apiFetch('/api/config');
    const hasKey = cfg.api_key === MASKED_API_KEY || Boolean((cfg.api_key || '').trim());
    const hasModel = Boolean((cfg.model || '').trim());
    const hasEndpoint = Boolean((cfg.api_endpoint || '').trim());
    if (hasKey && hasModel && hasEndpoint) {
      hint.classList.add('hidden');
    } else {
      hint.classList.remove('hidden');
    }
  } catch {
    hint.classList.remove('hidden');
  }
}

async function sendAiButlerMessage() {
  if (AI_BUTLER_STATE.sending) return;
  const input = document.getElementById('aiButlerInput');
  const text = (input?.value || '').trim();
  if (!text) {
    showToast('请输入消息', true);
    return;
  }

  AI_BUTLER_STATE.sending = true;
  setAiButlerInputBusy(true);
  clearAiButlerSuggestionPanel();
  appendAiButlerMessage('user', text);
  AI_BUTLER_STATE.messages.push({ role: 'user', content: text });
  if (input) input.value = '';
  showAiButlerThinking();

  try {
    const history = AI_BUTLER_STATE.messages.slice(0, -1).slice(-20);
    const data = await apiFetch('/api/ai-butler/chat', {
      method: 'POST',
      body: JSON.stringify({ message: text, history }),
    });
    removeAiButlerThinking();
    const reply = data.reply || '（无回复）';
    appendAiButlerMessage('assistant', reply);
    AI_BUTLER_STATE.messages.push({ role: 'assistant', content: reply });
    renderAiButlerSuggestion(data);
    await updateAiButlerApiHint();
  } catch (err) {
    removeAiButlerThinking();
    appendAiButlerMessage('assistant', err.message || '请求失败');
    showToast(err.message || 'AI 管家请求失败', true);
  } finally {
    AI_BUTLER_STATE.sending = false;
    setAiButlerInputBusy(false);
  }
}

async function applyAiButlerPatch() {
  const patch = AI_BUTLER_STATE.pendingPatch;
  if (!patch || !Object.keys(patch).length) {
    showToast('没有可应用的配置建议', true);
    return;
  }
  const applyBtn = document.getElementById('btnAiButlerApply');
  if (applyBtn) applyBtn.disabled = true;
  try {
    await apiFetch('/api/config', {
      method: 'POST',
      body: JSON.stringify({ data: patch }),
    });
    await reloadConfigFromServer();
    clearAiButlerSuggestionPanel();
    showToast('配置已应用并同步到助手设置~');
  } catch (err) {
    showToast(err.message || '保存配置失败', true);
  } finally {
    if (applyBtn) applyBtn.disabled = false;
  }
}

function initAiButlerPage() {
  updateAiButlerApiHint().catch(console.error);
}

function bindAiButlerControls() {
  document.getElementById('btnAiButlerSend')?.addEventListener('click', () => {
    sendAiButlerMessage().catch(console.error);
  });
  document.getElementById('aiButlerInput')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendAiButlerMessage().catch(console.error);
    }
  });
  document.getElementById('btnAiButlerApply')?.addEventListener('click', () => {
    applyAiButlerPatch().catch(console.error);
  });
  document.getElementById('btnAiButlerCancel')?.addEventListener('click', () => {
    clearAiButlerSuggestionPanel();
    showToast('已取消配置建议');
  });
  document.getElementById('btnAiButlerGoSettings')?.addEventListener('click', () => {
    navigate('settings');
  });
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
    updateAnnouncementsNavBadge(false);
    loadAnnouncementsPage().catch((e) => showToast(e.message, true));
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

/** @typedef {'connecting'|'connected'|'reconnecting'|'polling'|'failed'} RealtimeConnMode */

const REALTIME = {
  statusWs: null,
  logsWs: null,
  statusReconnectTimer: null,
  logsReconnectTimer: null,
  pollingTimer: null,
  pollingGraceTimer: null,
  logsPollingTimer: null,
  logsPollingGraceTimer: null,
  statusAttempt: 0,
  logsAttempt: 0,
  statusOpen: false,
  logsOpen: false,
  degradedPolling: false,
  degradedLogsPolling: false,
  statusWsDownAt: 0,
  logsWsDownAt: 0,
  lastStatusPollToastAt: 0,
  lastLogsPollTs: 0,
  baseBackoffMs: 1000,
  maxBackoffMs: 16000,
  pollIntervalMs: 1500,
  pollToastCooldownMs: 30000,
  wsGraceMs: 2500,
  logsWsGraceMs: 800,
};

function wsUrl(path) {
  // 与当前页面同源优先，避免 session 与地址栏 host 不一致时 WS 连错主机。
  const pageOrigin = `${location.protocol}//${location.host}`;
  const base = API.base && new URL(API.base).host === location.host ? API.base : pageOrigin;
  const parsed = new URL(base);
  const proto = parsed.protocol === 'https:' ? 'wss' : 'ws';
  const url = new URL(`${proto}://${parsed.host}${path}`);
  if (API.token) {
    url.searchParams.set('ws_token', API.token);
  }
  return url.toString();
}

/** @param {RealtimeConnMode} mode */
function setRealtimeConnUI(mode) {
  const labels = {
    connecting: '连接中',
    connected: '已连接',
    reconnecting: '重连中',
    polling: '已降级轮询',
    failed: '连接失败',
  };
  const text = labels[mode] || labels.connecting;
  document.querySelectorAll('[data-realtime-conn]').forEach((el) => {
    el.textContent = text;
    el.className = `text-xs font-normal border-l border-gray-200 pl-2 ml-0.5 conn-${mode}`;
    el.setAttribute('data-conn', mode);
  });
}

function setLogsConnUI(mode) {
  const labels = {
    connecting: '连接中',
    connected: '实时',
    reconnecting: '重连中',
    polling: 'HTTP 同步',
    failed: '连接失败',
  };
  const el = document.querySelector('#page-logs [data-realtime-conn]');
  if (!el) return;
  const text = labels[mode] || labels.connecting;
  el.textContent = text;
  el.className = `text-xs font-normal border-l border-gray-200 pl-2 conn-${mode}`;
  el.setAttribute('data-conn', mode);
}

function statusBackoffMs() {
  const exp = Math.min(REALTIME.statusAttempt, 5);
  return Math.min(REALTIME.baseBackoffMs * 2 ** exp, REALTIME.maxBackoffMs);
}

function logsBackoffMs() {
  const exp = Math.min(REALTIME.logsAttempt, 5);
  return Math.min(REALTIME.baseBackoffMs * 2 ** exp, REALTIME.maxBackoffMs);
}

function clearStatusReconnect() {
  if (REALTIME.statusReconnectTimer) {
    clearTimeout(REALTIME.statusReconnectTimer);
    REALTIME.statusReconnectTimer = null;
  }
}

function clearLogsReconnect() {
  if (REALTIME.logsReconnectTimer) {
    clearTimeout(REALTIME.logsReconnectTimer);
    REALTIME.logsReconnectTimer = null;
  }
}

function updateRealtimeConnUI() {
  updateLogPanelState();
  if (REALTIME.logsOpen) {
    setLogsConnUI('connected');
  } else if (REALTIME.degradedLogsPolling) {
    setLogsConnUI('polling');
  } else if (
    REALTIME.logsReconnectTimer
    || (REALTIME.logsWs && REALTIME.logsWs.readyState === WebSocket.CONNECTING)
  ) {
    setLogsConnUI('reconnecting');
  } else if (REALTIME.logsAttempt >= 6) {
    setLogsConnUI('failed');
  } else {
    setLogsConnUI('connecting');
  }

  if (REALTIME.statusOpen && (REALTIME.logsOpen || REALTIME.degradedLogsPolling)) {
    setRealtimeConnUI('connected');
    return;
  }
  if (REALTIME.degradedPolling) {
    setRealtimeConnUI('polling');
    return;
  }
  if (
    REALTIME.statusReconnectTimer
    || REALTIME.logsReconnectTimer
    || (REALTIME.statusWs && REALTIME.statusWs.readyState === WebSocket.CONNECTING)
    || (REALTIME.logsWs && REALTIME.logsWs.readyState === WebSocket.CONNECTING)
  ) {
    setRealtimeConnUI('reconnecting');
    return;
  }
  if (!REALTIME.statusOpen && REALTIME.statusAttempt >= 6) {
    setRealtimeConnUI('failed');
    return;
  }
  setRealtimeConnUI('connecting');
}

function detachWebSocket(ws) {
  if (!ws) return;
  ws.onopen = null;
  ws.onclose = null;
  ws.onerror = null;
  ws.onmessage = null;
  if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
    try {
      ws.close();
    } catch (_) {
      /* ignore */
    }
  }
}

async function pollStatusOnce() {
  const res = await fetch(`${API.base}/api/status`);
  if (!res.ok) throw new Error(res.statusText);
  applyStatus(await res.json());
}

function startStatusPolling() {
  if (REALTIME.pollingTimer) return;
  REALTIME.degradedPolling = true;
  updateRealtimeConnUI();
  const tick = () => {
    pollStatusOnce()
      .then(() => {
        if (REALTIME.statusOpen) stopStatusPolling();
      })
      .catch((e) => {
        console.warn('[realtime] status poll failed', e);
        const now = Date.now();
        if (now - REALTIME.lastStatusPollToastAt >= REALTIME.pollToastCooldownMs) {
          REALTIME.lastStatusPollToastAt = now;
          showToast('状态轮询失败，界面可能不是最新', true);
        }
      });
  };
  tick();
  REALTIME.pollingTimer = setInterval(tick, REALTIME.pollIntervalMs);
}

function stopStatusPolling() {
  if (REALTIME.pollingTimer) {
    clearInterval(REALTIME.pollingTimer);
    REALTIME.pollingTimer = null;
  }
  if (REALTIME.pollingGraceTimer) {
    clearTimeout(REALTIME.pollingGraceTimer);
    REALTIME.pollingGraceTimer = null;
  }
  REALTIME.degradedPolling = false;
}

function schedulePollingGraceCheck() {
  if (REALTIME.statusOpen || REALTIME.pollingTimer) return;
  if (!REALTIME.statusWsDownAt) REALTIME.statusWsDownAt = Date.now();
  const elapsed = Date.now() - REALTIME.statusWsDownAt;
  const wait = Math.max(0, REALTIME.wsGraceMs - elapsed);
  if (REALTIME.pollingGraceTimer) clearTimeout(REALTIME.pollingGraceTimer);
  REALTIME.pollingGraceTimer = setTimeout(() => {
    REALTIME.pollingGraceTimer = null;
    if (!REALTIME.statusOpen) startStatusPolling();
    updateRealtimeConnUI();
  }, wait);
}

async function pollLogsOnce() {
  const res = await fetch(
    `${API.base}/api/logs/recent?since_ts=${encodeURIComponent(REALTIME.lastLogsPollTs)}`,
    { cache: 'no-store' },
  );
  if (!res.ok) throw new Error(res.statusText);
  const data = await res.json();
  mergeLogItems(data.items || []);
}

/** Pull ring buffer from server (works when WS is down or page opened after events). */
async function bootstrapLogsFromServer(sinceTs = 0) {
  const base = API.base || window.location.origin.replace(/\/$/, '');
  const res = await fetch(
    `${base}/api/logs/recent?since_ts=${encodeURIComponent(sinceTs)}`,
    { cache: 'no-store' },
  );
  if (!res.ok) throw new Error(res.statusText);
  const data = await res.json();
  mergeLogItems(data.items || []);
  const onLogsPage = document.getElementById('page-logs')?.classList.contains('active');
  if (onLogsPage) renderLogView();
  else updateLogPanelState();
}

function mergeLogItems(items) {
  if (!items.length) return;
  items.forEach((item) => {
    appendLog(item);
    if (item.ts > REALTIME.lastLogsPollTs) REALTIME.lastLogsPollTs = item.ts;
  });
}

function startLogsPolling() {
  if (REALTIME.logsPollingTimer || REALTIME.logsOpen) return;
  REALTIME.degradedLogsPolling = true;
  updateRealtimeConnUI();
  const tick = () => {
    pollLogsOnce()
      .then(() => {
        if (REALTIME.logsOpen) stopLogsPolling();
      })
      .catch((e) => console.warn('[realtime] logs poll failed', e));
  };
  tick();
  REALTIME.logsPollingTimer = setInterval(tick, REALTIME.pollIntervalMs);
}

function stopLogsPolling() {
  if (REALTIME.logsPollingTimer) {
    clearInterval(REALTIME.logsPollingTimer);
    REALTIME.logsPollingTimer = null;
  }
  if (REALTIME.logsPollingGraceTimer) {
    clearTimeout(REALTIME.logsPollingGraceTimer);
    REALTIME.logsPollingGraceTimer = null;
  }
  REALTIME.degradedLogsPolling = false;
}

function scheduleLogsPollingGraceCheck() {
  if (REALTIME.logsOpen || REALTIME.logsPollingTimer) return;
  if (!REALTIME.logsWsDownAt) REALTIME.logsWsDownAt = Date.now();
  const elapsed = Date.now() - REALTIME.logsWsDownAt;
  const wait = Math.max(0, REALTIME.logsWsGraceMs - elapsed);
  if (REALTIME.logsPollingGraceTimer) clearTimeout(REALTIME.logsPollingGraceTimer);
  REALTIME.logsPollingGraceTimer = setTimeout(() => {
    REALTIME.logsPollingGraceTimer = null;
    if (!REALTIME.logsOpen) startLogsPolling();
    updateRealtimeConnUI();
  }, wait);
}

function scheduleStatusReconnect() {
  clearStatusReconnect();
  REALTIME.statusAttempt += 1;
  const delay = statusBackoffMs();
  console.debug(
    `[realtime] status WS reconnect in ${delay}ms (attempt ${REALTIME.statusAttempt})`,
  );
  REALTIME.statusReconnectTimer = setTimeout(() => {
    REALTIME.statusReconnectTimer = null;
    connectStatusWebSocket();
  }, delay);
  schedulePollingGraceCheck();
  updateRealtimeConnUI();
}

function scheduleLogsReconnect() {
  clearLogsReconnect();
  REALTIME.logsAttempt += 1;
  const delay = logsBackoffMs();
  console.debug(
    `[realtime] logs WS reconnect in ${delay}ms (attempt ${REALTIME.logsAttempt})`,
  );
  REALTIME.logsReconnectTimer = setTimeout(() => {
    REALTIME.logsReconnectTimer = null;
    connectLogsWebSocket();
  }, delay);
  scheduleLogsPollingGraceCheck();
  updateRealtimeConnUI();
}

// /ws/status 只驱动控制台统计与运行态 UI，不控制 Overlay 弹幕渲染
function connectStatusWebSocket() {
  clearStatusReconnect();
  detachWebSocket(REALTIME.statusWs);
  const url = wsUrl('/ws/status');
  console.debug('[realtime] status WS connecting', url);
  updateRealtimeConnUI();
  const ws = new WebSocket(url);
  REALTIME.statusWs = ws;

  ws.onopen = () => {
    console.debug('[realtime] status WS open');
    REALTIME.statusAttempt = 0;
    REALTIME.statusOpen = true;
    REALTIME.statusWsDownAt = 0;
    stopStatusPolling();
    updateRealtimeConnUI();
  };

  ws.onmessage = (ev) => {
    try {
      applyStatus(JSON.parse(ev.data));
    } catch (e) {
      console.error('[realtime] status message parse error', e);
    }
  };

  ws.onerror = () => {
    console.warn('[realtime] status WS error');
    if (REALTIME.statusAttempt >= 3) {
      console.warn(
        '[realtime] 无法连接后端 WebSocket。请确认已运行 python main.py，'
        + '终端有「Web 控制台 HTTP/WS 已监听」，且已安装 uvicorn[standard]（含 websockets）。'
        + ' 可刷新页面或重启 DanmuAI。',
      );
    }
  };

  ws.onclose = (ev) => {
    console.debug('[realtime] status WS close', ev.code, ev.reason || '');
    REALTIME.statusOpen = false;
    if (!REALTIME.statusWsDownAt) REALTIME.statusWsDownAt = Date.now();
    if (ev.code === 1008) {
      refreshSession()
        .catch((e) => console.warn('[realtime] session refresh after WS 1008 failed', e))
        .finally(() => scheduleStatusReconnect());
      return;
    }
    scheduleStatusReconnect();
  };
}

function connectLogsWebSocket() {
  clearLogsReconnect();
  detachWebSocket(REALTIME.logsWs);
  const url = wsUrl('/ws/logs');
  console.debug('[realtime] logs WS connecting', url);
  const ws = new WebSocket(url);
  REALTIME.logsWs = ws;

  ws.onopen = () => {
    console.debug('[realtime] logs WS open');
    REALTIME.logsAttempt = 0;
    REALTIME.logsOpen = true;
    REALTIME.logsWsDownAt = 0;
    stopLogsPolling();
    bootstrapLogsFromServer(REALTIME.lastLogsPollTs).catch((e) => {
      console.warn('[realtime] logs bootstrap after WS open failed', e);
    });
    updateRealtimeConnUI();
  };

  ws.onmessage = (ev) => {
    try {
      appendLog(JSON.parse(ev.data));
    } catch (e) {
      console.error('[realtime] log message parse error', e);
    }
  };

  ws.onerror = () => {
    console.warn('[realtime] logs WS error');
    if (REALTIME.logsAttempt >= 3) {
      console.warn(
        '[realtime] 日志 WebSocket 未连接；约 1s 内会改用 HTTP 轮询同步日志。',
      );
    }
    if (!REALTIME.logsWsDownAt) REALTIME.logsWsDownAt = Date.now();
    scheduleLogsPollingGraceCheck();
  };

  ws.onclose = (ev) => {
    console.debug('[realtime] logs WS close', ev.code, ev.reason || '');
    REALTIME.logsOpen = false;
    if (!REALTIME.logsWsDownAt) REALTIME.logsWsDownAt = Date.now();
    if (ev.code === 1008) {
      refreshSession()
        .catch((e) => console.warn('[realtime] session refresh after WS 1008 failed', e))
        .finally(() => scheduleLogsReconnect());
      return;
    }
    scheduleLogsReconnect();
    updateRealtimeConnUI();
  };
}

function startRealtimeTransport() {
  setRealtimeConnUI('connecting');
  setLogsConnUI('connecting');
  REALTIME.logsWsDownAt = Date.now();
  scheduleLogsPollingGraceCheck();
  bootstrapLogsFromServer(0).catch((e) => {
    console.warn('[realtime] initial logs bootstrap failed', e);
  });
  connectStatusWebSocket();
  connectLogsWebSocket();
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
  applyStatus(await fetch(`${API.base}/api/status`).then((r) => r.json()));
  initDiagnosticsPanel();
  initLiveOverlayPanel();
  startRealtimeTransport();

  initSettingsTabs();
  initSettingsUiMode();
  initSettingsFieldHints();
  initSidebarNavFloatingHints();
  initNormalBatchControls();
  initDanmuPoolPage();
  initDanmuReadPage();
  bindAiButlerControls();
  initCaptureRegionControls();
  initRestoreDefaultsControls();

  document.querySelectorAll('.sidebar-nav-hint').forEach((btn) => {
    btn.addEventListener('click', (e) => e.stopPropagation());
  });

  document.querySelectorAll('#nav [data-page]').forEach((btn) => {
    btn.addEventListener('click', () => navigate(btn.dataset.page));
  });
  const hash = (location.hash || '').replace('#', '');
  if (hash) navigate(hash);

  document.getElementById('providerPreset')?.addEventListener('change', (e) => {
    if (e.target.value) applyProviderPreset(e.target.value);
    else syncProviderPresetAfterEndpointEdit();
  });

  document.getElementById('api_endpoint')?.addEventListener('change', syncProviderPresetAfterEndpointEdit);
  document.getElementById('api_mode')?.addEventListener('change', () => {
    syncProviderPresetAfterEndpointEdit();
    updateMicModeHint();
  });

  document.querySelectorAll('.log-level-cb').forEach((cb) => {
    cb.addEventListener('change', () => {
      logLevelFilters = new Set(
        [...document.querySelectorAll('.log-level-cb:checked')].map((c) => c.value),
      );
      renderLogView();
    });
  });
  document.getElementById('logAutoScroll')?.addEventListener('change', (e) => {
    logAutoScroll = e.target.checked;
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
  startAnnouncementsBadgePolling();

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

  document.getElementById('mic_mode_enabled')?.addEventListener('change', updateMicModeHint);

  // POST /api/config → bridge.save_config → 主线程 ConfigService（勿期望 HTTP 线程直接改 engine）
  document.getElementById('settingsForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await apiFetch('/api/config', { method: 'POST', body: JSON.stringify({ data: collectFormData() }) });
      const cfg = await reloadConfigFromServer();
      const active = cfg.active_model_id || cfg.model || '';
      const label = cfg.model_display_name && cfg.model_display_name !== active
        ? `${cfg.model_display_name}（${active}）`
        : active;
      showToast(label ? `配置已保存，当前生效模型：${label}` : '配置已保存~');
      if (document.getElementById('personaSelect')?.value) {
        loadPersonaTemplate().catch(console.error);
      }
      const keyInput = document.getElementById('api_key');
      if (keyInput?.value && keyInput.value !== MASKED_API_KEY) {
        keyInput.value = MASKED_API_KEY;
      }
    } catch (err) {
      showToast(err.message || '保存时出了点小状况', true);
    }
  });

  document.getElementById('btnSaveAndStart').addEventListener('click', async () => {
    try {
      await apiFetch('/api/config', { method: 'POST', body: JSON.stringify({ data: collectFormData() }) });
      await apiFetch('/api/start', { method: 'POST' });
      showToast('已保存并开始生成弹幕！');
      navigate('overview');
    } catch (err) {
      showToast(err.message, true);
    }
  });

  document.getElementById('btnProbe').addEventListener('click', async () => {
    const data = collectFormData();
    const keyField = (document.getElementById('api_key')?.value || '').trim();
    try {
      const res = await apiFetch('/api/probe', {
        method: 'POST',
        body: JSON.stringify({
          api_endpoint: data.api_endpoint,
          api_key: keyField === MASKED_API_KEY ? MASKED_API_KEY : (data.api_key || ''),
          model: data.model,
          api_mode: data.api_mode,
        }),
      });
      showToast(res.message || (res.ok ? '连接成功' : '连接失败'), !res.ok);
    } catch (err) {
      showToast(err.message || '网络连接似乎睡着了', true);
    }
  });

  document.getElementById('btnMicTest')?.addEventListener('click', async () => {
    const btn = document.getElementById('btnMicTest');
    const sendBtn = document.getElementById('btnMicTestSend');
    const statusEl = document.getElementById('micTestStatus');
    if (!btn) return;
    btn.disabled = true;
    if (sendBtn) sendBtn.disabled = true;
    if (statusEl) statusEl.textContent = '录音中…请对着麦克风随便念几句话';
    showToast('请对着麦克风随便念几句话（约 3 秒）');
    try {
      const res = await apiFetch('/api/mic/test', {
        method: 'POST',
        body: JSON.stringify({ duration_sec: 3 }),
      });
      const detail = `pcm=${res.pcm_bytes || 0}B · rms=${res.rms ?? 0} · ${res.level || 'unknown'}`;
      if (statusEl) {
        statusEl.textContent = res.default_input
          ? `${res.default_input} · ${detail}`
          : detail;
      }
      showToast(res.message || (res.ok ? '麦克风测试通过' : '麦克风测试未通过'), !res.ok);
    } catch (err) {
      if (statusEl) statusEl.textContent = '测试失败';
      showToast(err.message || '麦克风测试失败', true);
    } finally {
      btn.disabled = false;
      if (sendBtn) sendBtn.disabled = false;
    }
  });

  document.getElementById('btnMicTestSend')?.addEventListener('click', async () => {
    const btn = document.getElementById('btnMicTestSend');
    const micBtn = document.getElementById('btnMicTest');
    const statusEl = document.getElementById('micTestStatus');
    if (!btn) return;
    btn.disabled = true;
    if (micBtn) micBtn.disabled = true;
    if (statusEl) statusEl.textContent = '录音并发送中…请对着麦克风念几句话';
    showToast('录音约 3 秒后将发送到 AI，请对着麦克风说话');
    try {
      const res = await apiFetch('/api/mic/test', {
        method: 'POST',
        body: JSON.stringify({ duration_sec: 3, send_to_ai: true }),
      });
      const detail = `input=${res.input_tokens ?? 0} · output=${res.output_tokens ?? 0} · pcm=${res.pcm_bytes || 0}B`;
      if (statusEl) {
        statusEl.textContent = res.reply_preview
          ? `${detail} · ${res.reply_preview}`
          : detail;
      }
      showToast(res.message || (res.ok ? '测试发送成功' : '测试发送失败'), !res.ok);
    } catch (err) {
      if (statusEl) statusEl.textContent = '测试发送失败';
      showToast(err.message || '测试发送失败', true);
    } finally {
      btn.disabled = false;
      if (micBtn) micBtn.disabled = false;
    }
  });

  document.getElementById('toggleKey').addEventListener('click', () => {
    const inp = document.getElementById('api_key');
    inp.type = inp.type === 'password' ? 'text' : 'password';
  });

  document.getElementById('previewImageFile')?.addEventListener('change', async (e) => {
    const file = e.target.files?.[0];
    const info = document.getElementById('previewImageInfo');
    const origImg = document.getElementById('previewImageOrig');
    const origPh = document.getElementById('previewOrigPlaceholder');
    const compressedImg = document.getElementById('previewImageCompressed');
    const compressedPh = document.getElementById('previewCompressedPlaceholder');
    if (!file || !info || !origImg) return;

    revokePreviewUrls();
    resetCompressedPreview();
    _previewOrigUrl = URL.createObjectURL(file);
    setPreviewSlot(origImg, origPh, _previewOrigUrl);
    info.textContent = `已选择 ${file.name}，正在压缩预览…`;

    const fd = new FormData();
    fd.append('file', file);
    fd.append('max_width', document.getElementById('image_max_width')?.value || '768');
    fd.append('quality', document.getElementById('image_quality')?.value || '85');
    try {
      if (!API.token) {
        throw new Error('未获取会话令牌，请刷新页面或重启 DanmuAI');
      }
      const data = await apiFormFetch('/api/preview/compress', fd);
      info.textContent =
        `原图 ${data.orig_w}×${data.orig_h} → ${data.out_w}×${data.out_h}，JPEG ${(data.jpeg_bytes / 1024).toFixed(1)} KB（Base64 ${data.base64_kb?.toFixed?.(1) ?? '?'} KB）`;
      setPreviewSlot(compressedImg, compressedPh, data.preview_data_url, (blobUrl) => {
        if (_previewCompressedUrl) URL.revokeObjectURL(_previewCompressedUrl);
        _previewCompressedUrl = blobUrl;
      });
    } catch (err) {
      const msg = err.message || '压缩预览失败';
      info.textContent = `${msg}（左侧为原图；请重启 DanmuAI 后重试）`;
      if (compressedPh) {
        compressedPh.classList.remove('hidden');
        compressedPh.textContent = '压缩失败';
      }
      if (compressedImg) compressedImg.classList.add('hidden');
      showToast(msg, true);
    }
  });

  document.getElementById('btnAddCustomModel')?.addEventListener('click', () => openModelModal(-1));
  document.getElementById('btnModelCancel')?.addEventListener('click', closeModelModal);
  document.getElementById('btnAnnouncementsRefresh')?.addEventListener('click', () => {
    loadAnnouncementsPage().catch((e) => showToast(e.message, true));
  });
  document.getElementById('btnOverviewAnnouncementDismiss')?.addEventListener('click', () => {
    dismissOverviewAnnouncementBanner(overviewBannerLatestId);
  });
  document.querySelectorAll('.js-reward-fab').forEach((btn) => {
    btn.addEventListener('click', openRewardModal);
  });
  document.getElementById('btnRewardClose')?.addEventListener('click', closeRewardModal);
  document.getElementById('rewardModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'rewardModal') closeRewardModal();
  });
  document.getElementById('btnErrorReportDismiss')?.addEventListener('click', dismissErrorReportModal);
  document.getElementById('btnErrorReportSubmit')?.addEventListener('click', () => {
    submitErrorReportFromModal().catch((e) => showToast(e.message || '发送失败', true));
  });
  document.getElementById('errorReportModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'errorReportModal') dismissErrorReportModal();
  });
  document.getElementById('modelModalForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const index = parseInt(document.getElementById('modelEditIndex').value, 10);
    const body = collectModelForm();
    try {
      if (index >= 0) {
        await apiFetch(`/api/custom-models/${index}`, { method: 'PUT', body: JSON.stringify(body) });
      } else {
        await apiFetch('/api/custom-models', { method: 'POST', body: JSON.stringify(body) });
      }
      closeModelModal();
      showToast('模型已保存~');
      loadCustomModels();
    } catch (err) {
      showToast(err.message, true);
    }
  });
  document.getElementById('btnModelProbe')?.addEventListener('click', async () => {
    try {
      const res = await apiFetch('/api/custom-models/probe', {
        method: 'POST',
        body: JSON.stringify(collectModelForm()),
      });
      showToast(res.message, !res.ok);
    } catch (err) {
      showToast(err.message, true);
    }
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
