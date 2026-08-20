import assert from 'node:assert/strict';
import { test } from 'node:test';

function installBrowserGlobals(storage = new Map()) {
  globalThis.window = {
    location: {
      hash: '',
      pathname: '/',
      search: '',
      origin: 'http://127.0.0.1:18765',
      protocol: 'http:',
      host: '127.0.0.1:18765',
    },
    history: { replaceState() {} },
    sessionStorage: {
      getItem(key) {
        return storage.get(key) ?? null;
      },
      setItem(key, value) {
        storage.set(key, value);
      },
      removeItem(key) {
        storage.delete(key);
      },
    },
  };
  globalThis.document = {
    title: 'DanmuAI',
    querySelectorAll: () => [],
    querySelector: () => null,
  };
  globalThis.localStorage = { getItem: () => null, setItem: () => {} };
  globalThis.location = globalThis.window.location;
}

class MockWebSocket {
  static OPEN = 1;

  static CONNECTING = 0;

  constructor(url) {
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    MockWebSocket.created.push(this);
    queueMicrotask(() => this._simulateOpen());
  }

  static created = [];

  _simulateOpen() {
    if (this.readyState !== MockWebSocket.CONNECTING) return;
    this.readyState = MockWebSocket.OPEN;
    this.onopen?.();
    queueMicrotask(() => {
      this.onmessage?.({ data: JSON.stringify({ type: 'auth', ok: true }) });
    });
  }

  close() {
    this.readyState = 3;
    this.onclose?.({ code: 1000, reason: '' });
  }

  send() {}

  addEventListener(event, handler) {
    if (event === 'message') this.onmessage = handler;
  }

  removeEventListener() {}
}

async function loadTransport() {
  return import('../web/static/modules/transport.js');
}

test('resumeRealtimeTransport coalesces concurrent visibility resumes', async () => {
  installBrowserGlobals();
  MockWebSocket.created = [];
  globalThis.WebSocket = MockWebSocket;
  let sessionCalls = 0;
  globalThis.fetch = async (url) => {
    if (String(url).endsWith('/api/session')) {
      sessionCalls += 1;
      await new Promise((resolve) => setTimeout(resolve, 10));
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({ token: 'token', base_url: 'http://127.0.0.1:18765' }),
      };
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const {
    API,
    AUTH,
    REALTIME,
    clearSessionCredentials,
    resumeRealtimeTransport,
    setRealtimeHandlers,
    stopRealtimeTransport,
  } = await loadTransport();

  stopRealtimeTransport();
  API.token = 'token';
  API.base = 'http://127.0.0.1:18765';
  AUTH.state = 'authenticated';
  REALTIME.statusOpen = false;
  REALTIME.logsOpen = false;

  let bootstrapCalls = 0;
  setRealtimeHandlers({
    bootstrapLogs: async () => {
      bootstrapCalls += 1;
    },
  });

  await Promise.all([
    resumeRealtimeTransport(),
    resumeRealtimeTransport(),
    resumeRealtimeTransport(),
  ]);

  assert.equal(sessionCalls, 1, 'concurrent resumes must share one session refresh');
  assert.equal(MockWebSocket.created.length, 2, 'one status and one logs socket per reconnect');
  assert.equal(bootstrapCalls, 1, 'logs bootstrap runs once after logs WS opens');

  stopRealtimeTransport();
  clearSessionCredentials();
});

test('resumeRealtimeTransport reuses healthy open sockets', async () => {
  installBrowserGlobals();
  MockWebSocket.created = [];
  globalThis.WebSocket = MockWebSocket;
  globalThis.fetch = async (url) => {
    if (String(url).endsWith('/api/session')) {
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({ token: 'token', base_url: 'http://127.0.0.1:18765' }),
      };
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const {
    API,
    AUTH,
    REALTIME,
    clearSessionCredentials,
    resumeRealtimeTransport,
    setRealtimeHandlers,
    stopRealtimeTransport,
  } = await loadTransport();

  stopRealtimeTransport();
  API.token = 'token';
  API.base = 'http://127.0.0.1:18765';
  AUTH.state = 'authenticated';

  const statusWs = { readyState: MockWebSocket.OPEN };
  const logsWs = { readyState: MockWebSocket.OPEN };
  REALTIME.statusWs = statusWs;
  REALTIME.logsWs = logsWs;
  REALTIME.statusOpen = true;
  REALTIME.logsOpen = true;

  let bootstrapCalls = 0;
  setRealtimeHandlers({
    bootstrapLogs: async () => {
      bootstrapCalls += 1;
    },
  });

  await resumeRealtimeTransport();

  assert.equal(MockWebSocket.created.length, 0, 'healthy sockets should not be recreated');
  assert.equal(bootstrapCalls, 0, 'healthy sockets should not trigger HTTP bootstrap');

  stopRealtimeTransport();
  clearSessionCredentials();
});

test('stale logs WS open callback does not bootstrap after reconnect', async () => {
  installBrowserGlobals();
  MockWebSocket.created = [];
  globalThis.WebSocket = MockWebSocket;
  globalThis.fetch = async (url) => {
    if (String(url).endsWith('/api/session')) {
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({ token: 'token', base_url: 'http://127.0.0.1:18765' }),
      };
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const {
    API,
    AUTH,
    REALTIME,
    clearSessionCredentials,
    resumeRealtimeTransport,
    setRealtimeHandlers,
    stopRealtimeTransport,
  } = await loadTransport();

  API.token = 'token';
  API.base = 'http://127.0.0.1:18765';
  AUTH.state = 'authenticated';
  stopRealtimeTransport();
  REALTIME.statusOpen = false;
  REALTIME.logsOpen = false;
  REALTIME.statusWs = null;
  REALTIME.logsWs = null;

  let bootstrapCalls = 0;
  setRealtimeHandlers({
    bootstrapLogs: async () => {
      bootstrapCalls += 1;
    },
  });

  const firstResume = resumeRealtimeTransport();
  while (MockWebSocket.created.length < 2) {
    await Promise.resolve();
  }
  const staleLogsWs = MockWebSocket.created.find((ws) => ws.url.includes('/ws/logs'));
  assert.ok(staleLogsWs);

  stopRealtimeTransport();
  REALTIME.statusOpen = false;
  REALTIME.logsOpen = false;
  await firstResume;

  bootstrapCalls = 0;
  await resumeRealtimeTransport();

  staleLogsWs._simulateOpen();
  await Promise.resolve();
  await Promise.resolve();

  assert.equal(bootstrapCalls, 1, 'only the active logs socket may bootstrap');

  stopRealtimeTransport();
  clearSessionCredentials();
});
