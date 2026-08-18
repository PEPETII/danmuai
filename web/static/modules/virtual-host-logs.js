/**
 * 模块：virtual-host-logs — 虚拟主播说话内容日志（当前进程内存 + HTTP 轮询）。
 */

import { API, authHeaders } from './transport.js';
import { t } from './i18n.js';

const MAX_SPEECH_LOG_ENTRIES = 200;
let speechLogBuffer = [];
let pollingTimer = null;
let requestInFlight = false;

function isVirtualHostLogsTabVisible() {
  const guidePage = document.getElementById('page-guide');
  const panel = document.getElementById('guideTab-virtual-host-logs');
  return Boolean(guidePage?.classList.contains('active') && panel && !panel.hidden);
}

function setConnectionState(mode) {
  const labels = {
    polling: t('dynamic.virtualHostLogs.polling'),
    failed: t('dynamic.virtualHostLogs.failed'),
  };
  document.querySelectorAll('[data-virtual-host-log-conn]').forEach((el) => {
    el.textContent = labels[mode] || labels.polling;
    el.className = `text-xs font-normal border-l border-gray-200 pl-2 conn-${mode}`;
    el.dataset.conn = mode;
  });
}

function sourceLabel(source) {
  if (source === 'user_mic') return t('dynamic.virtualHostLogs.sourceUserMic');
  return t('dynamic.virtualHostLogs.sourceAutoReply');
}

function updatePanelState() {
  const panel = document.querySelector('.virtual-host-log-panel');
  const empty = document.getElementById('virtualHostSpeechLogEmpty');
  const view = document.getElementById('virtualHostSpeechLogView');
  if (!panel || !empty || !view) return;
  const hasLogs = view.childElementCount > 0;
  panel.classList.toggle('has-logs', hasLogs);
  if (!hasLogs) empty.textContent = t('dynamic.virtualHostLogs.empty');
}

function createSpeechLogLine(entry) {
  const line = document.createElement('article');
  line.className = 'virtual-host-log-line mic-log-line';
  line.dataset.virtualHostSpeechLogId = String(entry.id || '');

  const timestamp = Number(entry.timestamp);
  const timeText = Number.isFinite(timestamp) && timestamp > 0
    ? new Date(timestamp * 1000).toLocaleString()
    : '—';
  const turnText = entry.turn_id
    ? t('dynamic.virtualHostLogs.turn', { turnId: entry.turn_id })
    : '';
  const meta = document.createElement('div');
  meta.className = 'virtual-host-log-line__meta mic-log-line__meta';
  meta.textContent = [timeText, sourceLabel(entry.source), turnText].filter(Boolean).join(' · ');

  const body = document.createElement('div');
  body.className = 'virtual-host-log-line__text mic-log-line__text';
  body.textContent = String(entry.text || '');
  line.append(meta, body);
  return line;
}

function renderSpeechLogView() {
  const view = document.getElementById('virtualHostSpeechLogView');
  if (!view) return;
  view.replaceChildren(...speechLogBuffer.map(createSpeechLogLine));
  updatePanelState();
  view.scrollTop = view.scrollHeight;
}

async function loadSpeechLogs() {
  if (requestInFlight || !isVirtualHostLogsTabVisible()) return;
  requestInFlight = true;
  try {
    const base = API.base || window.location.origin.replace(/\/$/, '');
    const response = await fetch(`${base}/api/virtual-host/speech-logs`, {
      cache: 'no-store',
      headers: authHeaders(),
    });
    if (!response.ok) throw new Error(response.statusText);
    const payload = await response.json();
    speechLogBuffer = Array.isArray(payload.items)
      ? payload.items.filter((entry) => entry && entry.id && entry.text).slice(-MAX_SPEECH_LOG_ENTRIES)
      : [];
    renderSpeechLogView();
    setConnectionState('polling');
  } catch (error) {
    setConnectionState('failed');
    console.warn('[virtual-host-logs] load failed', error);
  } finally {
    requestInFlight = false;
  }
}

function ensureSpeechLogPolling() {
  if (pollingTimer) return;
  pollingTimer = setInterval(() => {
    void loadSpeechLogs();
  }, 1500);
}

export function onVirtualHostLogsTabActivated() {
  ensureSpeechLogPolling();
  void loadSpeechLogs();
}
