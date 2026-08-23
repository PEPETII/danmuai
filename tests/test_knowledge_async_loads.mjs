import assert from 'node:assert/strict';
import { test } from 'node:test';

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...names) { names.forEach((name) => this.values.add(name)); }
  remove(...names) { names.forEach((name) => this.values.delete(name)); }
  contains(name) { return this.values.has(name); }
  toggle(name, force) {
    const next = force === undefined ? !this.values.has(name) : Boolean(force);
    if (next) this.values.add(name); else this.values.delete(name);
    return next;
  }
}

class FakeElement {
  constructor() {
    this.classList = new FakeClassList();
    this.children = [];
    this.dataset = {};
    this.value = '';
    this.textContent = '';
    this.disabled = false;
    this.checked = false;
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = nodes; }
  addEventListener() {}
  setAttribute() {}
  scrollIntoView() {}
}

const ids = [
  'knowledgeListView', 'knowledgePackageDetail', 'knowledgeRetrievalPreview',
  'knowledgePackageName', 'knowledgePackagePriority', 'knowledgePackageEnabled',
  'knowledgeOverviewName', 'knowledgeOverviewStatusBadge', 'knowledgeOverviewStats',
  'knowledgeOverviewSaveStatus', 'knowledgeJobList', 'knowledgeJobEmpty',
  'knowledgeItemList', 'knowledgeItemEmpty', 'knowledgeItemPageInfo',
  'btnKnowledgeItemPrev', 'btnKnowledgeItemNext', 'knowledgeItemKindFilter',
  'knowledgeItemEnabledFilter', 'knowledgeItemSearch', 'knowledgeBackgroundJobBanner',
  'knowledgeBackgroundJobText',
];
const elements = new Map(ids.map((id) => [id, new FakeElement()]));
elements.get('knowledgePackageDetail').classList.add('hidden');
globalThis.document = {
  getElementById: (id) => elements.get(id),
  createElement: () => new FakeElement(),
  querySelectorAll: () => [],
  addEventListener() {},
};
globalThis.window = {
  setInterval: () => 1,
  clearInterval() {},
};

const { API } = await import('../web/static/modules/transport.js');
const state = await import('../web/static/modules/app-knowledge-state.js');
const detail = await import('../web/static/modules/app-knowledge-package-detail.js');
const items = await import('../web/static/modules/app-knowledge-items.js');

API.base = 'http://danmu.test';
API.token = 'test-token';

function response(data) {
  return { ok: true, status: 200, statusText: 'OK', json: async () => data };
}

test('slow A detail response cannot overwrite fast B detail', async () => {
  state.resetPackageContext();
  const pending = new Map();
  let aSignal = null;
  globalThis.fetch = (url, options = {}) => {
    const path = new URL(url).pathname;
    if (path === '/api/knowledge/packages/A') {
      aSignal = options.signal;
      return new Promise((resolve) => pending.set('A', resolve));
    }
    if (path === '/api/knowledge/packages/B') {
      return Promise.resolve(response({ public_id: 'B', name: 'B package', enabled: true, sources: [], items: { total: 1 } }));
    }
    if (path === '/api/knowledge/jobs') return Promise.resolve(response({ jobs: [] }));
    if (path === '/api/knowledge/items') {
      const packageId = new URL(url).searchParams.get('package_id');
      return Promise.resolve(response({ items: [{ public_id: `${packageId}-item`, title: `${packageId} item`, enabled: true }], total: 1, page: 1, page_size: 50 }));
    }
    throw new Error(`Unexpected request: ${url}`);
  };

  const slowA = detail.openPackageDetail('A');
  await new Promise((resolve) => setTimeout(resolve, 0));
  assert.ok(aSignal);
  const fastB = detail.openPackageDetail('B');
  await fastB;
  pending.get('A')(response({ public_id: 'A', name: 'A package', enabled: false, sources: [], items: { total: 9 } }));
  await slowA;

  assert.equal(aSignal.aborted, true);
  assert.equal(state.currentPackageId, 'B');
  assert.equal(elements.get('knowledgePackageName').value, 'B package');
  assert.equal(elements.get('knowledgeItemList').children[0].children[0].children[0].textContent, 'B item');
});

test('slow A items response cannot overwrite fast B items', async () => {
  state.setCurrentPackageId('A');
  elements.get('knowledgePackageDetail').classList.remove('hidden');
  const pending = new Map();
  let aSignal = null;
  globalThis.fetch = (url, options = {}) => {
    const packageId = new URL(url).searchParams.get('package_id');
    if (packageId === 'A') {
      aSignal = options.signal;
      return new Promise((resolve) => pending.set('A', resolve));
    }
    return Promise.resolve(response({ items: [{ public_id: 'B-item', title: 'B item', enabled: true }], total: 1, page: 1, page_size: 50 }));
  };

  const slowA = items.loadItems();
  state.setCurrentPackageId('B');
  const fastB = items.loadItems();
  await fastB;
  pending.get('A')(response({ items: [{ public_id: 'A-item', title: 'A item', enabled: true }], total: 1, page: 1, page_size: 50 }));
  await slowA;

  assert.equal(aSignal.aborted, true);
  assert.equal(elements.get('knowledgeItemList').children[0].children[0].children[0].textContent, 'B item');
});

test('aborted items request is silent after leaving detail view', async () => {
  state.setCurrentPackageId('A');
  elements.get('knowledgePackageDetail').classList.remove('hidden');
  const toasts = [];
  state.setKnowledgeToast((message, isError) => toasts.push({ message, isError }));
  globalThis.fetch = (_url, options = {}) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  });

  const pending = items.loadItems();
  items.cancelItemsLoad();
  elements.get('knowledgePackageDetail').classList.add('hidden');
  await pending;

  assert.deepEqual(toasts, []);
});
