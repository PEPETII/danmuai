/**
 * 模块：logs — 实时日志环形缓冲 + 弹幕日志页渲染 + 历史 bootstrap。
 *
 * 数据流：
 *   接收 → logBuffer（数组，按 ts 升序）
 *     - WebSocket：onLog（单条）/ onLogBatch（批量）
 *     - HTTP bootstrap：bootstrapLogsFromServer(lastLogsPollTs) 拉
 *       GET /api/logs/recent?since_ts=... 用于首屏补齐 + 降级轮询
 *   渲染 → 弹幕日志 Tab（#page-guide + #guideTab-logs；兼容旧 #page-logs）
 *     - renderLogView() 按 logLevelFilters 过滤后写到 DOM
 *     - mergeLogItemsUnique() 按 (ts|level|message) 去重
 *
 * 用户偏好：
 *   - logLevelFilters：Set<'INFO' | 'WARNING' | 'ERROR'>（默认 3 档全开）
 *   - logAutoScroll：是否粘底
 *
 * 注意：logBuffer 只在本会话内存，不做持久化；err_report 的摘录走
 * /api/logs/recent 服务端近期 + 内存缓冲（见 app.js collectErrorReportContext）。
 */

import { API, REALTIME } from './transport.js';

export const logBuffer = [];
const logKeySet = new Set();
export let logLevelFilters = new Set(['INFO', 'WARNING', 'ERROR']);
export let logAutoScroll = true;

export function replaceLogLevelFilters(next) {
  logLevelFilters = next;
}

export function setLogAutoScroll(value) {
  logAutoScroll = value;
}

export function logEntryKey(item) {
  return `${item.ts}|${item.level}|${item.message}`;
}

export function formatLogLine(item) {
  const ts = Number(item.ts) || 0;
  const iso = ts > 0 ? new Date(ts * 1000).toISOString() : '—';
  return `${iso} [${item.level || 'INFO'}] ${item.message || ''}`;
}

export function mergeLogItemsUnique(items) {
  const map = new Map();
  items.forEach((item) => {
    if (!item || item.message == null) return;
    map.set(logEntryKey(item), item);
  });
  return Array.from(map.values()).sort((a, b) => (Number(a.ts) || 0) - (Number(b.ts) || 0));
}

export function clearLogBuffer() {
  logBuffer.length = 0;
  logKeySet.clear();
}

function filteredLogBuffer() {
  return logBuffer.filter((x) => logLevelFilters.has(x.level));
}

function createLogLineElement(item) {
  const line = document.createElement('div');
  const ts = item.ts ? new Date(item.ts * 1000).toLocaleTimeString() : '';
  line.className = `log-line ${item.level || 'INFO'}`;
  line.textContent = `[${ts}] ${item.message}`;
  return line;
}

function trimLogBuffer() {
  while (logBuffer.length > 400) {
    const evicted = logBuffer.shift();
    if (evicted) logKeySet.delete(logEntryKey(evicted));
  }
}

/** 弹幕日志 Tab 是否当前可见（guide-tabs 合并后激活的是 #page-guide，非 #page-logs）。 */
export function isLogsTabVisible() {
  const guidePage = document.getElementById('page-guide');
  const logsPanel = document.getElementById('guideTab-logs');
  if (guidePage?.classList.contains('active') && logsPanel && !logsPanel.hidden) {
    return true;
  }
  return document.getElementById('page-logs')?.classList.contains('active') ?? false;
}

export function updateLogPanelState() {
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

export function renderLogView({ force = false } = {}) {
  const view = document.getElementById('logView');
  if (!view) return;
  const filtered = filteredLogBuffer();

  if (force) {
    view.innerHTML = '';
    filtered.forEach((item) => view.appendChild(createLogLineElement(item)));
  } else {
    const rendered = view.childElementCount;
    if (rendered > filtered.length) {
      view.innerHTML = '';
      filtered.forEach((item) => view.appendChild(createLogLineElement(item)));
    } else {
      for (let i = rendered; i < filtered.length; i += 1) {
        view.appendChild(createLogLineElement(filtered[i]));
      }
    }
  }

  if (logAutoScroll) view.scrollTop = view.scrollHeight;
  updateLogPanelState();
}

export function appendLog(item) {
  const key = logEntryKey(item);
  if (logKeySet.has(key)) return;
  logKeySet.add(key);
  logBuffer.push(item);
  trimLogBuffer();
  if (logLevelFilters.has(item.level || 'INFO')) {
    const view = document.getElementById('logView');
    if (!view) return;
    view.appendChild(createLogLineElement(item));
    while (view.childElementCount > 400) view.removeChild(view.firstChild);
    if (logAutoScroll) view.scrollTop = view.scrollHeight;
    updateLogPanelState();
  }
}

export function mergeLogItems(items) {
  if (!items.length) return;
  let addedAny = false;
  items.forEach((item) => {
    if (!item || item.message == null) return;
    const key = logEntryKey(item);
    if (logKeySet.has(key)) return;
    logKeySet.add(key);
    logBuffer.push(item);
    trimLogBuffer();
    if (item.ts > REALTIME.lastLogsPollTs) REALTIME.lastLogsPollTs = item.ts;
    addedAny = true;
  });
  if (!addedAny) return;
  if (isLogsTabVisible()) renderLogView();
  else updateLogPanelState();
}

/** Pull ring buffer from server (works when WS is down or page opened after events). */
export async function bootstrapLogsFromServer(sinceTs = 0) {
  const base = API.base || window.location.origin.replace(/\/$/, '');
  const res = await fetch(
    `${base}/api/logs/recent?since_ts=${encodeURIComponent(sinceTs)}`,
    { cache: 'no-store' },
  );
  if (!res.ok) throw new Error(res.statusText);
  const data = await res.json();
  mergeLogItems(data.items || []);
  if (isLogsTabVisible()) renderLogView();
  else updateLogPanelState();
}
