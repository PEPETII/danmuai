/**
 * 模块：transport — fetch 封装 + WebSocket 状态机 + 轮询降级。
 *
 * 三大职责：
 *   1) HTTP：apiFetch() 自动注入 base / token / JSON 头；401/403/5xx 转
 *      formatApiError() 统一文案；apiFormFetch() 用于 multipart（如图片上传）。
 *   2) WebSocket：startRealtimeTransport() 同时拉起两路 WS
 *      - /api/ws/status ：服务端的运行状态推送（运行/待命、统计、is_error）
 *      - /api/ws/logs   ：实时日志流
 *      resumeRealtimeTransport() 为 visibility 恢复单飞入口。
 *      断线走指数退避（baseBackoffMs=1s, maxBackoffMs=16s, attempt 上限 6）。
 *   3) 轮询降级：WS 关闭后经 wsGraceMs（status=2.5s, logs=0.8s）宽限，再
 *      用 setInterval(pollIntervalMs=1500) 走 GET /api/status 和
 *      /api/logs/recent?since_ts=...。错误 toast 走 pollToastCooldownMs=30s
 *      节流（W-AUDIT-FIX-002 引入）。
 *
 * 关键不变量：
 *   - API.base 来自 /api/session；未拉取时 base=''，调用方应 await refreshSession()
 *   - REALTIME.lastLogsPollTs 持久保留，用于日志轮询 since_ts 增量续传
 *   - 状态机由 setRealtimeHandlers({onStatus, onLog, onLogBatch, ...}) 解耦
 */

import { t } from './i18n.js';

export const API = { token: null, base: '' };

/** @typedef {'pending'|'authenticated'|'unauthenticated'} SessionAuthState */
export const AUTH = { state: /** @type {SessionAuthState} */ ('pending') };

const SESSION_STORAGE_KEY = 'danmuai.web.session.v1';
let bootstrapSecret = takeBootstrapSecretFromFragment();
let sessionRefreshPromise = null;
let resumeTransportPromise = null;
let logsBootstrapPromise = null;

function takeBootstrapSecretFromFragment() {
  if (typeof window === 'undefined' || !window.location) return '';
  const hash = window.location.hash || '';
  if (!hash.startsWith('#')) return '';
  const params = new URLSearchParams(hash.slice(1));
  const secret = params.get('bootstrap') || '';
  if (!secret) return '';
  const route = params.get('route');
  const nextHash = route ? `#${route}` : '';
  try {
    window.history.replaceState(
      null,
      document.title,
      `${window.location.pathname}${window.location.search}${nextHash}`,
    );
  } catch (_) {
    // The secret is still sent once if history is unavailable in an embedded shell.
  }
  return secret;
}

function readStoredSession() {
  try {
    const raw = window.sessionStorage.getItem(SESSION_STORAGE_KEY);
    const value = raw ? JSON.parse(raw) : null;
    return value && typeof value.token === 'string' ? value : null;
  } catch (_) {
    return null;
  }
}

function writeStoredSession(session) {
  try {
    window.sessionStorage.setItem(
      SESSION_STORAGE_KEY,
      JSON.stringify({ token: session.token, base_url: session.base_url }),
    );
  } catch (_) {
    // Private browsing or an embedded shell may disable sessionStorage.
  }
}

export function clearSessionCredentials() {
  API.token = null;
  API.base = '';
  AUTH.state = 'unauthenticated';
  try {
    window.sessionStorage.removeItem(SESSION_STORAGE_KEY);
  } catch (_) {
    // sessionStorage may be unavailable in an embedded shell.
  }
}

export function isSessionAuthenticated() {
  return AUTH.state === 'authenticated' && Boolean(API.token);
}

function markSessionAuthenticated() {
  AUTH.state = 'authenticated';
}

function haltRealtimeAfterAuthFailure() {
  stopRealtimeTransport();
  REALTIME.statusAttempt = 6;
  REALTIME.logsAttempt = 6;
  setRealtimeConnUI('failed');
  setLogsConnUI('failed');
}

function reportAuthFailure(error, source) {
  clearSessionCredentials();
  haltRealtimeAfterAuthFailure();
  handlers.onAuthFailure?.({ source, error });
  console.warn(`[transport] session auth recovery failed (${source})`, error);
}

/** @typedef {'connecting'|'connected'|'reconnecting'|'polling'|'failed'} RealtimeConnMode */

export const REALTIME = {
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
  statusConnGeneration: 0,
  logsConnGeneration: 0,
  baseBackoffMs: 1000,
  maxBackoffMs: 16000,
  pollIntervalMs: 1500,
  pollToastCooldownMs: 30000,
  wsGraceMs: 2500,
  logsWsGraceMs: 800,
};

const defaultHandlers = {
  onStatus: () => {},
  onLog: () => {},
  onLogBatch: () => {},
  updateLogPanelState: () => {},
  showToast: () => {},
  bootstrapLogs: async () => {},
  onAuthFailure: () => {},
};

let handlers = { ...defaultHandlers };

export function setRealtimeHandlers(patch) {
  handlers = { ...handlers, ...patch };
}

export function authHeaders() {
  const headers = { 'Content-Type': 'application/json' };
  if (API.token) headers.Authorization = `Bearer ${API.token}`;
  return headers;
}

export function formatApiError(detail, fallback = t('common.requestFailed')) {
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
  // dict/object 类型兜底 — 提取 .detail / .error / .message
  if (typeof detail === 'object' && detail !== null) {
    return detail.detail || detail.error || detail.message || JSON.stringify(detail);
  }
  return String(detail);
}

/** Exchange launcher bootstrap or the tab's cached Bearer for a console session. */
export function refreshSession() {
  if (sessionRefreshPromise) return sessionRefreshPromise;
  sessionRefreshPromise = (async () => {
    const sessionUrl = new URL('/api/session', window.location.origin).href;
    const cached = readStoredSession();
    const headers = {};
    if (bootstrapSecret) {
      headers['X-DanmuAI-Bootstrap'] = bootstrapSecret;
    } else {
      const cachedToken = API.token || cached?.token;
      if (cachedToken) headers.Authorization = `Bearer ${cachedToken}`;
    }
    let res;
    try {
      res = await fetch(sessionUrl, { cache: 'no-store', headers });
    } catch (error) {
      clearSessionCredentials();
      throw error;
    }
    if (!res.ok) {
      clearSessionCredentials();
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      const detail = formatApiError(err.detail, res.statusText);
      throw new Error(
        t('dynamic.transport.无法获取控制台会话_HTTP_res_sta', { status: res.status, detail })
        + t('dynamic.transport.请确认终端有_Web_控制台_HTTP_WS_已'),
      );
    }
    const session = await res.json();
    if (!session?.token) {
      clearSessionCredentials();
      throw new Error(t('dynamic.transport.会话接口未返回_token_请重启_python'));
    }
    API.token = session.token;
    API.base = (session.base_url || window.location.origin).replace(/\/$/, '');
    writeStoredSession(session);
    bootstrapSecret = '';
    REALTIME.lastLogsPollTs = 0;
    markSessionAuthenticated();
    return session;
  })();
  sessionRefreshPromise = sessionRefreshPromise.finally(() => {
    sessionRefreshPromise = null;
  });
  return sessionRefreshPromise;
}

export async function apiFetch(path, options = {}, retried = false) {
  if (!API.base) await refreshSession();
  const res = await fetch(`${API.base}${path}`, {
    ...options,
    headers: { ...authHeaders(), ...(options.headers || {}) },
  });
  if ((res.status === 401 || res.status === 403) && !retried) {
    try {
      await refreshSession();
    } catch (error) {
      reportAuthFailure(error, 'apiFetch');
      throw error;
    }
    return apiFetch(path, options, true);
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    const fallback =
      res.status === 404
        ? t('dynamic.transport.接口不存在_请完全退出并重新运行_python')
        : res.statusText;
    throw new Error(formatApiError(err.detail, fallback));
  }
  return res.json();
}

export async function apiFormFetch(path, formData, retried = false) {
  if (!API.base) await refreshSession();
  const res = await fetch(`${API.base}${path}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${API.token}` },
    body: formData,
  });
  if ((res.status === 401 || res.status === 403) && !retried) {
    try {
      await refreshSession();
    } catch (error) {
      reportAuthFailure(error, 'apiFormFetch');
      throw error;
    }
    return apiFormFetch(path, formData, true);
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(formatApiError(err.detail, res.statusText));
  }
  return res.json();
}

function wsUrl(path) {
  const pageOrigin = `${location.protocol}//${location.host}`;
  const base = API.base && new URL(API.base).host === location.host ? API.base : pageOrigin;
  const parsed = new URL(base);
  const proto = parsed.protocol === 'https:' ? 'wss' : 'ws';
  const url = new URL(`${proto}://${parsed.host}${path}`);
  return url.toString();
}

/**
 * Send WebSocket auth as first message (W-SECURITY-002).
 * @returns {Promise<boolean>}
 */
function authenticateWebSocket(ws, timeoutMs = 5000) {
  return new Promise((resolve) => {
    if (!API.token) {
      resolve(false);
      return;
    }

    const timer = setTimeout(() => {
      console.warn('[realtime] WS auth timeout');
      ws.close();
      resolve(false);
    }, timeoutMs);

    const onMessage = (ev) => {
      clearTimeout(timer);
      ws.removeEventListener('message', onMessage);
      try {
        const data = JSON.parse(ev.data);
        resolve(data.type === 'auth' && data.ok === true);
      } catch (_) {
        resolve(false);
      }
    };

    ws.addEventListener('message', onMessage);
    ws.send(JSON.stringify({ type: 'auth', token: API.token }));
  });
}

/** @param {RealtimeConnMode} mode */
function setRealtimeConnUI(mode) {
  const labels = {
    connecting: t('common.connecting'),
    connected: t('common.connected'),
    reconnecting: t('common.reconnecting'),
    polling: t('common.polling'),
    failed: t('common.connectionFailed'),
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
    connecting: t('common.connecting'),
    connected: t('common.realtime'),
    reconnecting: t('common.reconnecting'),
    polling: t('common.httpSync'),
    failed: t('common.connectionFailed'),
  };
  const el = document.querySelector(
    '#guideTab-logs [data-realtime-conn], #page-logs [data-realtime-conn]',
  );
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

/**
 * 判断 WS 关闭是否因连接数已满导致。
 */
function isMaxConsumersClose(code, reason) {
  if (code !== 1008) return false;
  const r = (reason || '').toLowerCase();
  return r.includes(t('dynamic.transport.连接数已满')) || r.includes('max consumers');
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
  handlers.updateLogPanelState();
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

function isTransportHealthy() {
  return REALTIME.statusOpen && REALTIME.logsOpen
    && REALTIME.statusWs?.readyState === WebSocket.OPEN
    && REALTIME.logsWs?.readyState === WebSocket.OPEN;
}

function scheduleLogsBootstrap(sinceTs = REALTIME.lastLogsPollTs) {
  if (logsBootstrapPromise) return logsBootstrapPromise;
  logsBootstrapPromise = handlers.bootstrapLogs(sinceTs)
    .catch((e) => console.warn('[realtime] logs bootstrap failed', e))
    .finally(() => { logsBootstrapPromise = null; });
  return logsBootstrapPromise;
}

function ensureRealtimeConnections() {
  setRealtimeConnUI('connecting');
  setLogsConnUI('connecting');
  REALTIME.logsWsDownAt = Date.now();
  scheduleLogsPollingGraceCheck();
  connectStatusWebSocket();
  connectLogsWebSocket();
}

async function pollStatusOnce(retried = false) {
  const res = await fetch(`${API.base}/api/status`, { headers: authHeaders() });
  if ((res.status === 401 || res.status === 403) && !retried) {
    try {
      await refreshSession();
    } catch (error) {
      reportAuthFailure(error, 'statusPoll');
      throw error;
    }
    return pollStatusOnce(true);
  }
  if (!res.ok) throw new Error(res.statusText);
  handlers.onStatus(await res.json());
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
          handlers.showToast(t('dynamic.transport.状态轮询失败_界面可能不是最新'), true);
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

async function pollLogsOnce(retried = false) {
  const res = await fetch(
    `${API.base}/api/logs/recent?since_ts=${encodeURIComponent(REALTIME.lastLogsPollTs)}`,
    { cache: 'no-store', headers: authHeaders() },
  );
  if ((res.status === 401 || res.status === 403) && !retried) {
    try {
      await refreshSession();
    } catch (error) {
      reportAuthFailure(error, 'logsPoll');
      throw error;
    }
    return pollLogsOnce(true);
  }
  if (!res.ok) throw new Error(res.statusText);
  const data = await res.json();
  handlers.onLogBatch(data.items || []);
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

function connectStatusWebSocket() {
  clearStatusReconnect();
  detachWebSocket(REALTIME.statusWs);
  const url = wsUrl('/ws/status');
  console.debug('[realtime] status WS connecting', url);
  updateRealtimeConnUI();
  const ws = new WebSocket(url);
  const connId = ++REALTIME.statusConnGeneration;
  REALTIME.statusWs = ws;

  ws.onopen = async () => {
    if (REALTIME.statusWs !== ws || connId !== REALTIME.statusConnGeneration) return;
    console.debug('[realtime] status WS open');
    const authOk = await authenticateWebSocket(ws);
    if (REALTIME.statusWs !== ws || connId !== REALTIME.statusConnGeneration) return;
    if (!authOk) {
      console.warn('[realtime] status WS auth failed');
      ws.close();
      return;
    }
    REALTIME.statusAttempt = 0;
    REALTIME.statusOpen = true;
    REALTIME.statusWsDownAt = 0;
    stopStatusPolling();
    updateRealtimeConnUI();
  };

  ws.onmessage = (ev) => {
    if (REALTIME.statusWs !== ws) return;
    try {
      const data = JSON.parse(ev.data);
      // 跳过认证响应消息
      if (data.type === 'auth') return;
      handlers.onStatus(data);
    } catch (e) {
      console.error('[realtime] status message parse error', e);
    }
  };

  ws.onerror = () => {
    if (REALTIME.statusWs !== ws) return;
    console.warn('[realtime] status WS error');
    if (REALTIME.statusAttempt >= 3) {
      console.warn(
        t('dynamic.transport.realtime_无法连接后端_WebSoc')
        + t('dynamic.transport.终端有_Web_控制台_HTTP_WS_已监听')
        + t('dynamic.transport.可刷新页面或重启_DanmuAI'),
      );
    }
  };

  ws.onclose = (ev) => {
    if (REALTIME.statusWs !== ws) return;
    console.debug('[realtime] status WS close', ev.code, ev.reason || '');
    REALTIME.statusOpen = false;
    if (!REALTIME.statusWsDownAt) REALTIME.statusWsDownAt = Date.now();
    if (isMaxConsumersClose(ev.code, ev.reason)) {
      console.warn('[realtime] status WS closed: max consumers reached, stopping reconnect');
      handlers.showToast(t('dynamic.transport.WebSocket_连接数已达上限_请关闭其他控'), true);
      updateRealtimeConnUI();
      return;
    }
    if (ev.code === 1008) {
      refreshSession()
        .then(() => scheduleStatusReconnect())
        .catch((e) => reportAuthFailure(e, 'ws-status'));
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
  const connId = ++REALTIME.logsConnGeneration;
  REALTIME.logsWs = ws;

  ws.onopen = async () => {
    if (REALTIME.logsWs !== ws || connId !== REALTIME.logsConnGeneration) return;
    console.debug('[realtime] logs WS open');
    const authOk = await authenticateWebSocket(ws);
    if (REALTIME.logsWs !== ws || connId !== REALTIME.logsConnGeneration) return;
    if (!authOk) {
      console.warn('[realtime] logs WS auth failed');
      ws.close();
      return;
    }
    REALTIME.logsAttempt = 0;
    REALTIME.logsOpen = true;
    REALTIME.logsWsDownAt = 0;
    stopLogsPolling();
    scheduleLogsBootstrap(REALTIME.lastLogsPollTs);
    updateRealtimeConnUI();
  };

  ws.onmessage = (ev) => {
    if (REALTIME.logsWs !== ws) return;
    try {
      const data = JSON.parse(ev.data);
      // 跳过认证响应消息
      if (data.type === 'auth') return;
      handlers.onLog(data);
    } catch (e) {
      console.error('[realtime] log message parse error', e);
    }
  };

  ws.onerror = () => {
    if (REALTIME.logsWs !== ws) return;
    console.warn('[realtime] logs WS error');
    if (REALTIME.logsAttempt >= 3) {
      console.warn(
        t('dynamic.transport.realtime_日志_WebSocket'),
      );
    }
    if (!REALTIME.logsWsDownAt) REALTIME.logsWsDownAt = Date.now();
    scheduleLogsPollingGraceCheck();
  };

  ws.onclose = (ev) => {
    if (REALTIME.logsWs !== ws) return;
    console.debug('[realtime] logs WS close', ev.code, ev.reason || '');
    REALTIME.logsOpen = false;
    if (!REALTIME.logsWsDownAt) REALTIME.logsWsDownAt = Date.now();
    if (isMaxConsumersClose(ev.code, ev.reason)) {
      console.warn('[realtime] logs WS closed: max consumers reached, stopping reconnect');
      handlers.showToast(t('dynamic.transport.WebSocket_连接数已达上限_请关闭其他控'), true);
      updateRealtimeConnUI();
      return;
    }
    if (ev.code === 1008) {
      refreshSession()
        .then(() => scheduleLogsReconnect())
        .catch((e) => reportAuthFailure(e, 'ws-logs'));
      return;
    }
    scheduleLogsReconnect();
    updateRealtimeConnUI();
  };
}

export function startRealtimeTransport() {
  ensureRealtimeConnections();
}

export function resumeRealtimeTransport() {
  if (resumeTransportPromise) return resumeTransportPromise;
  resumeTransportPromise = (async () => {
    await refreshSession();
    REALTIME.statusAttempt = 0;
    REALTIME.logsAttempt = 0;
    clearStatusReconnect();
    clearLogsReconnect();
    if (isTransportHealthy()) return;
    ensureRealtimeConnections();
  })().finally(() => {
    resumeTransportPromise = null;
  });
  return resumeTransportPromise;
}

export function stopRealtimeTransport() {
  clearStatusReconnect();
  clearLogsReconnect();
  stopStatusPolling();
  stopLogsPolling();
  detachWebSocket(REALTIME.statusWs);
  REALTIME.statusWs = null;
  REALTIME.statusOpen = false;
  detachWebSocket(REALTIME.logsWs);
  REALTIME.logsWs = null;
  REALTIME.logsOpen = false;
  updateRealtimeConnUI();
}
