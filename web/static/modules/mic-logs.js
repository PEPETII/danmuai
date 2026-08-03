/**
 * 模块：mic-logs — 麦克风语音转文字日志（会话内内存 + WS/HTTP 同步）。
 */

import { API, authHeaders } from './transport.js';
import { t } from './i18n.js';

const MAX_MIC_LOG_ENTRIES = 200;
export const micLogBuffer = [];
const micLogIndex = new Map();
let micLogAutoScroll = true;
let micLogsTransportStarted = false;
let micLogsWs = null;
let micLogsOpen = false;
let micLogsPollingTimer = null;
let lastMicLogsPollTs = 0;

function wsUrl(path) {
  const base = API.base || window.location.origin.replace(/\/$/, '');
  const proto = base.startsWith('https') ? 'wss' : 'ws';
  const host = base.replace(/^https?:\/\//, '');
  return `${proto}://${host}${path}`;
}

async function authenticateWebSocket(ws) {
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(false), 2000);
    const onMessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        if (data.type === 'auth') {
          clearTimeout(timer);
          ws.removeEventListener('message', onMessage);
          resolve(Boolean(data.ok));
        }
      } catch {
        /* ignore */
      }
    };
    ws.addEventListener('message', onMessage);
    ws.send(JSON.stringify({ type: 'auth', token: API.token }));
  });
}

function statusLabel(status) {
  if (status === 'partial') return t('dynamic.micLogs.statusPartial');
  if (status === 'failed') return t('dynamic.micLogs.statusFailed');
  return t('dynamic.micLogs.statusSuccess');
}

function upsertMicLogEntry(entry) {
  if (!entry || !entry.id) return;
  const text = String(entry.text || '').trim();
  if (entry.status !== 'partial' && !text && entry.status !== 'failed') return;
  micLogIndex.set(entry.id, entry);
  const idx = micLogBuffer.findIndex((item) => item.id === entry.id);
  if (idx >= 0) micLogBuffer[idx] = entry;
  else micLogBuffer.push(entry);
  micLogBuffer.sort((a, b) => (Number(a.timestamp) || 0) - (Number(b.timestamp) || 0));
  while (micLogBuffer.length > MAX_MIC_LOG_ENTRIES) {
    const evicted = micLogBuffer.shift();
    if (evicted?.id) micLogIndex.delete(evicted.id);
  }
  if (entry.timestamp > lastMicLogsPollTs) lastMicLogsPollTs = entry.timestamp;
}

function removeMicLogEntry(entryId) {
  const idx = micLogBuffer.findIndex((item) => item.id === entryId);
  if (idx >= 0) micLogBuffer.splice(idx, 1);
  micLogIndex.delete(entryId);
}

export function isMicLogsTabVisible() {
  const guidePage = document.getElementById('page-guide');
  const panel = document.getElementById('guideTab-mic-logs');
  return Boolean(guidePage?.classList.contains('active') && panel && !panel.hidden);
}

export function updateMicLogPanelState() {
  const panel = document.querySelector('.mic-log-panel');
  const empty = document.getElementById('micLogViewEmpty');
  const view = document.getElementById('micLogView');
  if (!panel || !view) return;
  const visibleCount = view.childElementCount;
  panel.classList.toggle('has-logs', visibleCount > 0);
  if (empty && visibleCount === 0) {
    empty.textContent = t('dynamic.micLogs.empty');
  }
}

function createMicLogLineElement(entry) {
  const line = document.createElement('article');
  line.className = `mic-log-line mic-log-line--${entry.status || 'success'}`;
  line.dataset.micLogId = entry.id;
  const ts = entry.timestamp
    ? new Date(Number(entry.timestamp) * 1000).toLocaleString()
    : '—';
  const status = document.createElement('div');
  status.className = 'mic-log-line__meta';
  status.textContent = `${ts} · ${statusLabel(entry.status)}`;
  const body = document.createElement('div');
  body.className = 'mic-log-line__text';
  if (entry.status === 'partial') {
    body.textContent = t('dynamic.micLogs.recognizing');
  } else if (entry.status === 'failed') {
    body.textContent = entry.error
      ? t('dynamic.micLogs.failedWithReason', { reason: entry.error })
      : t('dynamic.micLogs.statusFailed');
  } else {
    body.textContent = entry.text || '';
  }
  line.append(status, body);
  return line;
}

export function renderMicLogView({ force = false } = {}) {
  const view = document.getElementById('micLogView');
  if (!view) return;
  if (force) {
    view.innerHTML = '';
    micLogBuffer.forEach((entry) => view.appendChild(createMicLogLineElement(entry)));
  } else {
    micLogBuffer.forEach((entry) => {
      const existing = view.querySelector(`[data-mic-log-id="${entry.id}"]`);
      if (existing) {
        existing.replaceWith(createMicLogLineElement(entry));
      } else {
        view.appendChild(createMicLogLineElement(entry));
      }
    });
    while (view.childElementCount > MAX_MIC_LOG_ENTRIES) {
      view.removeChild(view.firstChild);
    }
  }
  if (micLogAutoScroll) view.scrollTop = view.scrollHeight;
  updateMicLogPanelState();
}

function handleMicLogEvent(event) {
  if (!event || typeof event !== 'object') return;
  if (event.type === 'clear') {
    micLogBuffer.length = 0;
    micLogIndex.clear();
    const view = document.getElementById('micLogView');
    if (view) view.innerHTML = '';
    updateMicLogPanelState();
    return;
  }
  if (event.type === 'discard') {
    removeMicLogEntry(event.id);
    document.querySelector(`[data-mic-log-id="${event.id}"]`)?.remove();
    updateMicLogPanelState();
    return;
  }
  const entry = event.entry;
  if (!entry) return;
  upsertMicLogEntry(entry);
  if (isMicLogsTabVisible()) renderMicLogView();
  else updateMicLogPanelState();
}

async function bootstrapMicLogsFromServer(sinceTs = 0) {
  const base = API.base || window.location.origin.replace(/\/$/, '');
  const res = await fetch(
    `${base}/api/mic-logs/recent?since_ts=${encodeURIComponent(sinceTs)}`,
    { cache: 'no-store', headers: authHeaders() },
  );
  if (!res.ok) throw new Error(res.statusText);
  const data = await res.json();
  (data.items || []).forEach((entry) => upsertMicLogEntry(entry));
  if (isMicLogsTabVisible()) renderMicLogView({ force: true });
  else updateMicLogPanelState();
}

async function pollMicLogsOnce() {
  await bootstrapMicLogsFromServer(lastMicLogsPollTs);
}

function startMicLogsPolling() {
  if (micLogsPollingTimer || micLogsOpen) return;
  pollMicLogsOnce().catch((error) => console.warn('[mic-logs] poll failed', error));
  micLogsPollingTimer = setInterval(() => {
    pollMicLogsOnce().catch((error) => console.warn('[mic-logs] poll failed', error));
  }, 1500);
}

function stopMicLogsPolling() {
  if (micLogsPollingTimer) {
    clearInterval(micLogsPollingTimer);
    micLogsPollingTimer = null;
  }
}

function setMicLogsConnUI(mode) {
  const labels = {
    connecting: t('common.connecting'),
    connected: t('common.realtime'),
    polling: t('common.httpSync'),
    failed: t('common.connectionFailed'),
  };
  document.querySelectorAll('[data-mic-log-conn]').forEach((el) => {
    const text = labels[mode] || labels.connecting;
    el.textContent = text;
    el.className = `text-xs font-normal border-l border-gray-200 pl-2 conn-${mode}`;
    el.setAttribute('data-conn', mode);
  });
}

function connectMicLogsWebSocket() {
  if (micLogsWs) {
    try {
      micLogsWs.close();
    } catch {
      /* ignore */
    }
  }
  setMicLogsConnUI('connecting');
  const ws = new WebSocket(wsUrl('/ws/mic-logs'));
  micLogsWs = ws;
  ws.onopen = async () => {
    const authOk = await authenticateWebSocket(ws);
    if (!authOk) {
      ws.close();
      return;
    }
    micLogsOpen = true;
    stopMicLogsPolling();
    setMicLogsConnUI('connected');
    bootstrapMicLogsFromServer(lastMicLogsPollTs).catch((error) => {
      console.warn('[mic-logs] bootstrap after WS open failed', error);
    });
  };
  ws.onmessage = (ev) => {
    try {
      const data = JSON.parse(ev.data);
      if (data.type === 'auth') return;
      handleMicLogEvent(data);
    } catch (error) {
      console.warn('[mic-logs] message parse failed', error);
    }
  };
  ws.onerror = () => {
    if (!micLogsOpen) setMicLogsConnUI('polling');
    startMicLogsPolling();
  };
  ws.onclose = () => {
    micLogsOpen = false;
    setMicLogsConnUI('polling');
    startMicLogsPolling();
  };
}

export function ensureMicLogsTransport() {
  if (micLogsTransportStarted) return;
  micLogsTransportStarted = true;
  connectMicLogsWebSocket();
}

export async function clearMicLogs() {
  await fetch(`${API.base}/api/mic-logs/clear`, {
    method: 'POST',
    headers: authHeaders(),
  });
  handleMicLogEvent({ type: 'clear' });
}

export function initMicLogsPage({ showToast } = {}) {
  document.getElementById('btnClearMicLogs')?.addEventListener('click', async () => {
    try {
      await clearMicLogs();
      showToast?.(t('dynamic.micLogs.cleared'));
    } catch (error) {
      showToast?.(error.message || t('common.requestFailed'), true);
    }
  });
}

export function onMicLogsTabActivated() {
  ensureMicLogsTransport();
  renderMicLogView({ force: true });
  bootstrapMicLogsFromServer(lastMicLogsPollTs).catch((error) => {
    console.warn('[mic-logs] bootstrap on tab switch failed', error);
  });
}

export function navigateToMicLogs(navigate) {
  navigate('mic-logs');
}

export function navigateToDanmuLogs(navigate) {
  navigate('logs');
}
