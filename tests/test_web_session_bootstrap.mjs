import assert from 'node:assert/strict';
import { test } from 'node:test';

test('transport exchanges fragment bootstrap once and removes the secret from location', async () => {
  const storage = new Map();
  const calls = [];
  const location = {
    hash: '#bootstrap=fragment-secret&route=settings',
    pathname: '/',
    search: '',
    origin: 'http://127.0.0.1:18765',
  };
  globalThis.window = {
    location,
    history: {
      replaceState(_state, _title, nextUrl) {
        const parsed = new URL(nextUrl, location.origin);
        location.hash = parsed.hash;
        location.pathname = parsed.pathname;
        location.search = parsed.search;
      },
    },
    sessionStorage: {
      getItem(key) {
        return storage.get(key) ?? null;
      },
      setItem(key, value) {
        storage.set(key, value);
      },
    },
  };
  globalThis.document = { title: 'DanmuAI' };
  globalThis.localStorage = { getItem: () => null, setItem: () => {} };
  globalThis.fetch = async (url, options) => {
    calls.push({ url, options });
    return {
      ok: true,
      status: 200,
      statusText: 'OK',
      json: async () => ({ token: 'session-token', base_url: location.origin }),
    };
  };

  const { API, refreshSession } = await import('../web/static/modules/transport.js');
  await refreshSession();

  assert.equal(location.hash, '#settings');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.headers['X-DanmuAI-Bootstrap'], 'fragment-secret');
  assert.equal(API.token, 'session-token');
  assert.equal(JSON.parse(storage.get('danmuai.web.session.v1')).token, 'session-token');
});
