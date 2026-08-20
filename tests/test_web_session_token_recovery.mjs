import assert from 'node:assert/strict';
import { test } from 'node:test';

function installBrowserGlobals(storage, location = {
  hash: '',
  pathname: '/',
  search: '',
  origin: 'http://127.0.0.1:18765',
}) {
  globalThis.window = {
    location,
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
  globalThis.location = location;
}

test('refreshSession failure clears stored session and in-memory token', async () => {
  const storage = new Map();
  storage.set('danmuai.web.session.v1', JSON.stringify({
    token: 'stale-token',
    base_url: 'http://127.0.0.1:18765',
  }));
  installBrowserGlobals(storage);
  globalThis.fetch = async () => ({
    ok: false,
    status: 401,
    statusText: 'Unauthorized',
    json: async () => ({ detail: 'invalid session' }),
  });

  const {
    API,
    AUTH,
    refreshSession,
    clearSessionCredentials,
  } = await import('../web/static/modules/transport.js');

  API.token = 'stale-token';
  API.base = 'http://127.0.0.1:18765';
  AUTH.state = 'authenticated';

  await assert.rejects(() => refreshSession(), /无法获取控制台会话/);
  assert.equal(API.token, null);
  assert.equal(API.base, '');
  assert.equal(AUTH.state, 'unauthenticated');
  assert.equal(storage.has('danmuai.web.session.v1'), false);

  clearSessionCredentials();
});

test('apiFetch stops retrying with stale bearer after refresh failure', async () => {
  const storage = new Map();
  storage.set('danmuai.web.session.v1', JSON.stringify({
    token: 'stale-token',
    base_url: 'http://127.0.0.1:18765',
  }));
  installBrowserGlobals(storage);
  const calls = [];
  let sessionRefreshAttempts = 0;
  globalThis.fetch = async (url, options = {}) => {
    calls.push({ url, auth: options.headers?.Authorization || null });
    if (String(url).endsWith('/api/session')) {
      sessionRefreshAttempts += 1;
      return {
        ok: false,
        status: 403,
        statusText: 'Forbidden',
        json: async () => ({ detail: 'session rejected' }),
      };
    }
    return {
      ok: false,
      status: 401,
      statusText: 'Unauthorized',
      json: async () => ({ detail: 'unauthorized' }),
    };
  };

  const {
    API,
    AUTH,
    apiFetch,
    clearSessionCredentials,
    setRealtimeHandlers,
  } = await import('../web/static/modules/transport.js');

  API.token = 'stale-token';
  API.base = 'http://127.0.0.1:18765';
  AUTH.state = 'authenticated';

  let authFailureSource = null;
  setRealtimeHandlers({
    onAuthFailure: ({ source }) => {
      authFailureSource = source;
    },
  });

  await assert.rejects(() => apiFetch('/api/status'), /无法获取控制台会话/);
  assert.equal(sessionRefreshAttempts, 1);
  assert.equal(API.token, null);
  assert.equal(AUTH.state, 'unauthenticated');
  assert.equal(storage.has('danmuai.web.session.v1'), false);
  assert.equal(authFailureSource, 'apiFetch');
  const statusCalls = calls.filter((call) => String(call.url).endsWith('/api/status'));
  assert.equal(statusCalls.length, 1, 'apiFetch must not retry the protected request after refresh failure');
  assert.equal(statusCalls[0].auth, 'Bearer stale-token');

  clearSessionCredentials();
});

test('apiFetch retries once after 401 when refresh succeeds', async () => {
  const storage = new Map();
  installBrowserGlobals(storage);
  let statusCalls = 0;
  globalThis.fetch = async (url, options = {}) => {
    if (String(url).endsWith('/api/session')) {
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({ token: 'fresh-token', base_url: 'http://127.0.0.1:18765' }),
      };
    }
    if (String(url).endsWith('/api/status')) {
      statusCalls += 1;
      if (statusCalls === 1) {
        return {
          ok: false,
          status: 401,
          statusText: 'Unauthorized',
          json: async () => ({ detail: 'expired' }),
        };
      }
      assert.equal(options.headers.Authorization, 'Bearer fresh-token');
      return {
        ok: true,
        status: 200,
        statusText: 'OK',
        json: async () => ({ running: false }),
      };
    }
    throw new Error(`unexpected fetch: ${url}`);
  };

  const {
    API,
    apiFetch,
    clearSessionCredentials,
  } = await import('../web/static/modules/transport.js');

  API.token = 'stale-token';
  API.base = 'http://127.0.0.1:18765';

  const status = await apiFetch('/api/status');
  assert.equal(status.running, false);
  assert.equal(API.token, 'fresh-token');
  assert.equal(statusCalls, 2);

  clearSessionCredentials();
});
