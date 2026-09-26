import assert from 'node:assert/strict';
import { test } from 'node:test';

class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(...values) {
    values.forEach((value) => this.values.add(value));
  }

  remove(...values) {
    values.forEach((value) => this.values.delete(value));
  }

  contains(value) {
    return this.values.has(value);
  }
}

class FakeElement {
  constructor(tagName = 'div') {
    this.tagName = tagName.toUpperCase();
    this.children = [];
    this.classList = new FakeClassList();
    this.style = {};
    this.dataset = {};
    this.value = '';
    this.checked = false;
    this.disabled = false;
    this.textContent = '';
    this._innerHTML = '';
    this.listeners = new Map();
  }

  set innerHTML(value) {
    this._innerHTML = value;
    this.children = [];
  }

  get innerHTML() {
    return this._innerHTML;
  }

  append(...nodes) {
    this.children.push(...nodes.filter(Boolean));
  }

  appendChild(node) {
    this.children.push(node);
    return node;
  }

  insertBefore(node, reference) {
    const index = this.children.indexOf(reference);
    if (index < 0) this.children.push(node);
    else this.children.splice(index, 0, node);
    return node;
  }

  addEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  dispatch(type, event = {}) {
    const handlers = this.listeners.get(type) || [];
    return handlers.map((handler) => handler({ target: this, ...event }));
  }

  setAttribute(name, value) {
    this[name] = String(value);
  }

  remove() {
    this.removed = true;
  }
}

const elements = new Map();
for (const id of [
  'personaActiveList',
  'personaSaveStatusBanner',
  'personaSaveStatusText',
]) {
  const element = new FakeElement();
  element.id = id;
  elements.set(id, element);
}

globalThis.document = {
  documentElement: { lang: 'zh-CN' },
  body: new FakeElement('body'),
  createElement: (tagName) => new FakeElement(tagName),
  getElementById: (id) => elements.get(id) || null,
  querySelector: () => null,
  querySelectorAll: () => [],
  addEventListener: () => {},
};

globalThis.localStorage = {
  getItem: () => null,
  setItem: () => {},
};
globalThis.sessionStorage = globalThis.localStorage;
globalThis.window = {
  location: { href: 'http://danmu.test/' },
  addEventListener: () => {},
  sessionStorage: globalThis.sessionStorage,
};
globalThis.confirm = () => true;
globalThis.prompt = () => null;

const { API } = await import('../web/static/modules/transport.js');
API.base = 'http://danmu.test';
API.token = 'test-token';

const {
  applyBulkPersonaModel,
  initPersonaTopicPage,
  loadPersonaeCheckboxes,
} = await import('../web/static/modules/app-persona-topic-page.js');

const flush = () => new Promise((resolve) => setImmediate(resolve));
let toastSink = [];
initPersonaTopicPage({
  showToast: (message, isError) => toastSink.push({ message, isError }),
});

function jsonResponse(data, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? 'OK' : 'Error',
    json: async () => data,
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((promiseResolve, promiseReject) => {
    resolve = promiseResolve;
    reject = promiseReject;
  });
  return { promise, resolve, reject };
}

function customModels(modelIds) {
  return jsonResponse({
    items: modelIds.map((profileId) => ({
      id: profileId,
      name: profileId,
      provider: 'test',
      model: `model-${profileId}`,
      default_model_id: `model-${profileId}`,
      profile_id: profileId,
    })),
  });
}

function currentSelect() {
  const list = elements.get('personaActiveList');
  return list.children[0]?.children.find((child) => child.tagName === 'SELECT');
}

function installFetch(handler) {
  globalThis.fetch = async (url, options = {}) => handler(new URL(url), options);
}

test('row bindings serialize per persona and stale completion cannot win', async () => {
  const personaId = 'row-serial';
  let serverProfileId = 'profile-a';
  const putRequests = [];
  toastSink = [];
  const first = deferred();
  const second = deferred();

  installFetch(async (url, options) => {
    if (url.pathname === '/api/personae' && options.method !== 'PUT') {
      return jsonResponse({
        items: [{
          id: personaId,
          label: personaId,
          active: false,
          builtin: true,
          profile_id: serverProfileId,
          model_id: `model-${serverProfileId}`,
          binding_status: 'ok',
        }],
        active: [],
      });
    }
    if (url.pathname === '/api/custom-models') return customModels(['profile-a', 'profile-b', 'profile-c']);
    if (url.pathname === `/api/personae/${personaId}/model`) {
      const body = JSON.parse(options.body);
      putRequests.push({ body, deferred: putRequests.length === 0 ? first : second });
      return putRequests.at(-1).deferred.promise;
    }
    throw new Error(`unexpected request: ${url}`);
  });

  await loadPersonaeCheckboxes('personaActiveList');
  const select = currentSelect();

  select.value = 'profile-b';
  select.dispatch('change');
  await flush();
  select.value = 'profile-c';
  select.dispatch('change');
  await flush();

  assert.equal(putRequests.length, 1);
  assert.equal(putRequests[0].body.profile_id, 'profile-b');
  assert.equal(putRequests[0].body.model_id, 'model-profile-b');

  serverProfileId = 'profile-b';
  first.resolve(jsonResponse({ ok: true }));
  await flush();
  await flush();
  assert.equal(putRequests.length, 2);
  assert.equal(putRequests[1].body.profile_id, 'profile-c');
  assert.equal(toastSink.some(({ message }) => String(message).includes('模型已绑定')), false);

  second.resolve(jsonResponse({ ok: false }, 400));
  await flush();
  await flush();
  assert.equal(select.value, 'profile-b');
  assert.equal(toastSink.at(-1).isError, true);
});

test('unknown commit failure reconciles from GET instead of local rollback', async () => {
  const personaId = 'row-timeout';
  let listCalls = 0;
  let serverProfileId = 'profile-a';
  toastSink = [];

  installFetch(async (url, options) => {
    if (url.pathname === '/api/personae' && options.method !== 'PUT') {
      listCalls += 1;
      if (listCalls > 1) serverProfileId = 'profile-b';
      return jsonResponse({
        items: [{
          id: personaId,
          label: personaId,
          active: false,
          builtin: true,
          profile_id: serverProfileId,
          model_id: `model-${serverProfileId}`,
          binding_status: 'ok',
        }],
        active: [],
      });
    }
    if (url.pathname === '/api/custom-models') return customModels(['profile-a', 'profile-b']);
    if (url.pathname === `/api/personae/${personaId}/model`) return jsonResponse({ error: 'gateway timeout' }, 504);
    throw new Error(`unexpected request: ${url}`);
  });

  await loadPersonaeCheckboxes('personaActiveList');
  const select = currentSelect();
  select.value = 'profile-b';
  select.dispatch('change');
  await flush();
  await flush();

  assert.equal(listCalls, 2);
  assert.equal(select.value, 'profile-b');
  assert.equal(toastSink.at(-1).isError, true);
});

test('stale row failure cannot roll back or toast over a newer row choice', async () => {
  const personaId = 'row-stale-error';
  let serverProfileId = 'profile-a';
  const putRequests = [];
  const first = deferred();
  const second = deferred();
  toastSink = [];

  installFetch(async (url, options) => {
    if (url.pathname === '/api/personae' && options.method !== 'PUT') {
      return jsonResponse({
        items: [{
          id: personaId,
          label: personaId,
          active: false,
          builtin: true,
          profile_id: serverProfileId,
          model_id: `model-${serverProfileId}`,
          binding_status: 'ok',
        }],
        active: [],
      });
    }
    if (url.pathname === '/api/custom-models') return customModels(['profile-a', 'profile-b', 'profile-c']);
    if (url.pathname === `/api/personae/${personaId}/model`) {
      const body = JSON.parse(options.body);
      const pending = putRequests.length === 0 ? first : second;
      putRequests.push({ body, pending });
      return pending.promise;
    }
    throw new Error(`unexpected request: ${url}`);
  });

  await loadPersonaeCheckboxes('personaActiveList');
  const select = currentSelect();
  select.value = 'profile-b';
  select.dispatch('change');
  await flush();
  select.value = 'profile-c';
  select.dispatch('change');
  await flush();

  first.resolve(jsonResponse({ error: 'rejected' }, 400));
  await flush();
  await flush();
  assert.equal(putRequests.length, 2);
  assert.equal(toastSink.length, 0);
  assert.equal(select.value, 'profile-c');

  serverProfileId = 'profile-c';
  second.resolve(jsonResponse({ ok: true }));
  await flush();
  assert.equal(select.value, 'profile-c');
});

test('bulk uses the same per-persona queue as a row write', async () => {
  const personaId = 'bulk-shared-queue';
  let serverProfileId = 'profile-a';
  const putRequests = [];
  const rowWrite = deferred();
  const bulkWrite = deferred();

  installFetch(async (url, options = {}) => {
    if (url.pathname === '/api/personae' && options.method !== 'PUT') {
      return jsonResponse({
        items: [{
          id: personaId,
          label: personaId,
          active: false,
          builtin: true,
          profile_id: serverProfileId,
          model_id: `model-${serverProfileId}`,
          binding_status: 'ok',
        }],
        active: [],
      });
    }
    if (url.pathname === '/api/custom-models') return customModels(['profile-a', 'profile-b', 'profile-c']);
    if (url.pathname === `/api/personae/${personaId}/model`) {
      const body = JSON.parse(options.body);
      const pending = putRequests.length === 0 ? rowWrite : bulkWrite;
      putRequests.push({ body, pending });
      return pending.promise;
    }
    throw new Error(`unexpected request: ${url}`);
  });

  await loadPersonaeCheckboxes('personaActiveList');
  const select = currentSelect();
  select.value = 'profile-b';
  select.dispatch('change');
  await flush();

  const bulkPromise = applyBulkPersonaModel('profile-c', 'model-profile-c');
  await flush();
  assert.equal(putRequests.length, 1);

  serverProfileId = 'profile-b';
  rowWrite.resolve(jsonResponse({ ok: true }));
  await flush();
  await flush();
  assert.equal(putRequests.length, 2);
  assert.equal(putRequests[1].body.profile_id, 'profile-c');

  serverProfileId = 'profile-c';
  bulkWrite.resolve(jsonResponse({ ok: true }));
  const result = await bulkPromise;
  assert.equal(result.failed.length, 0);
  assert.deepEqual(putRequests.map(({ body }) => body.profile_id), ['profile-b', 'profile-c']);
});

test('bulk preserves per-item observable failure semantics', async () => {
  const firstPersonaId = 'bulk-partial-a';
  const secondPersonaId = 'bulk-partial-b';
  const serverProfiles = {
    [firstPersonaId]: 'profile-a',
    [secondPersonaId]: 'profile-b',
  };
  const requests = [];

  installFetch(async (url, options = {}) => {
    if (url.pathname === '/api/personae' && options.method !== 'PUT') {
      return jsonResponse({
        items: Object.entries(serverProfiles).map(([id, profileId]) => ({
          id,
          label: id,
          active: false,
          builtin: true,
          profile_id: profileId,
          model_id: `model-${profileId}`,
          binding_status: 'ok',
        })),
        active: [],
      });
    }
    if (url.pathname === '/api/custom-models') return customModels(['profile-a', 'profile-b', 'profile-z']);
    const match = url.pathname.match(/^\/api\/personae\/([^/]+)\/model$/);
    if (match) {
      const personaId = match[1];
      const body = JSON.parse(options.body);
      requests.push({ personaId, body });
      if (personaId === secondPersonaId) return jsonResponse({ error: 'rejected' }, 400);
      serverProfiles[personaId] = body.profile_id;
      return jsonResponse({ ok: true });
    }
    throw new Error(`unexpected request: ${url}`);
  });

  const result = await applyBulkPersonaModel('profile-z', 'model-profile-z');
  assert.equal(result.total, 2);
  assert.equal(result.failed.length, 1);
  assert.equal(result.failed[0].error.status, 400);
  assert.equal(serverProfiles[firstPersonaId], 'profile-z');
  assert.equal(serverProfiles[secondPersonaId], 'profile-b');
  assert.deepEqual(requests.map(({ personaId }) => personaId).sort(), [firstPersonaId, secondPersonaId].sort());
});
