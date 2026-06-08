/**
 * 模块：transport — fetch 封装 + WebSocket 状态机 + 轮询降级。
 *
 * 三大职责：
 *   1) HTTP：apiFetch() 自动注入 base / token / JSON 头；401/403/5xx 转
 *      formatApiError() 统一文案；apiFormFetch() 用于 multipart（如图片上传）。
 *   2) WebSocket：startRealtimeTransport() 同时拉起两路 WS
 *      - /api/ws/status ：服务端的运行状态推送（运行/待命、统计、is_error）
 *      - /api/ws/logs   ：实时日志流
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

export const API = { token: null, base: '' };

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

export function formatApiError(detail, fallback = '请求失败') {
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

/** Re-fetch session token (required after each `python main.py` restart). */
export async function refreshSession() {
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

export async function apiFetch(path, options = {}, retried = false) {
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

export async function apiFormFetch(path, formData) {
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

function wsUrl(path) {
  const pageOrigin = `${location.protocol}//${location.host}`;
  const base = API.base && new URL(API.base).host === location.host ? API.base : pageOrigin;
  const parsed = new URL(base);
  const proto = parsed.protocol === 'https:' ? 'wss' : 'ws';
  const url = new URL(`${proto}://${parsed.host}${path}`);
  return url.toString();
}

/**
 * 发送 WebSocket 认证消息（首次消息认证机制）。
 * W-SECURITY-002: Token 不再通过 query 参数传递，改为连接后首条消息。
 * @param {WebSocket} ws - WebSocket 实例
 * @param {number} timeoutMs - 认证超时（毫秒）
 * @returns {Promise<boolean>} 认证是否成功
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

async function pollStatusOnce() {
  const res = await fetch(`${API.base}/api/status`);
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
          handlers.showToast('状态轮询失败，界面可能不是最新', true);
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
  REALTIME.statusWs = ws;

  ws.onopen = async () => {
    console.debug('[realtime] status WS open');
    const authOk = await authenticateWebSocket(ws);
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

  ws.onopen = async () => {
    console.debug('[realtime] logs WS open');
    const authOk = await authenticateWebSocket(ws);
    if (!authOk) {
      console.warn('[realtime] logs WS auth failed');
      ws.close();
      return;
    }
    REALTIME.logsAttempt = 0;
    REALTIME.logsOpen = true;
    REALTIME.logsWsDownAt = 0;
    stopLogsPolling();
    handlers.bootstrapLogs(REALTIME.lastLogsPollTs).catch((e) => {
      console.warn('[realtime] logs bootstrap after WS open failed', e);
    });
    updateRealtimeConnUI();
  };

  ws.onmessage = (ev) => {
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

export function startRealtimeTransport() {
  setRealtimeConnUI('connecting');
  setLogsConnUI('connecting');
  REALTIME.logsWsDownAt = Date.now();
  scheduleLogsPollingGraceCheck();
  handlers.bootstrapLogs(0).catch((e) => {
    console.warn('[realtime] initial logs bootstrap failed', e);
  });
  connectStatusWebSocket();
  connectLogsWebSocket();
}
