/**
 * W-AUDIT-PROBE-PARITY-001：模型弹窗连接测试的阶段判定与竞态/取消行为。
 *
 * 用最小 DOM 打桩 + 可控 fetch 驱动 `web/static/modules/settings-model-modal-probe.js`
 * 的真实导出函数（probeModelConnection / abortModelProbe / renderModelProbeResult），
 * 断言：
 *   1. 只有 complete（business_parse 通过）才渲染完整成功；
 *   2. 部分阶段通过时渲染阶段明细且不显示成功；
 *   3. 旧（迟到）probe 结果不能覆盖新结果；
 *   4. 取消（AbortError）不渲染为 provider 失败；
 *   5. profile_id 漂移时丢弃结果。
 *
 * 不做源码字符串断言。
 */
import assert from 'node:assert/strict';
import { test } from 'node:test';

// ---------------------------------------------------------------------------
// 最小 DOM 打桩
// ---------------------------------------------------------------------------

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...names) { names.forEach((n) => this.values.add(n)); }
  remove(...names) { names.forEach((n) => this.values.delete(n)); }
  contains(name) { return this.values.has(name); }
  toggle(name, force) {
    const next = force === undefined ? !this.values.has(name) : Boolean(force);
    if (next) this.values.add(name); else this.values.delete(name);
    return next;
  }
}

class FakeElement {
  constructor(id = '') {
    this.id = id;
    this.value = '';
    this.textContent = '';
    this.className = '';
    this.disabled = false;
    this.readOnly = false;
    this.hidden = false;
    this.style = {};
    this.dataset = {};
    this.children = [];
    this.classList = new FakeClassList();
    this._listeners = new Map();
    this._attrs = new Map();
  }
  addEventListener(type, fn) {
    if (!this._listeners.has(type)) this._listeners.set(type, []);
    this._listeners.get(type).push(fn);
  }
  dispatch(type, event = {}) {
    for (const fn of this._listeners.get(type) || []) fn(event);
  }
  setAttribute(name, value) { this._attrs.set(name, String(value)); }
  getAttribute(name) { return this._attrs.has(name) ? this._attrs.get(name) : null; }
  removeAttribute(name) { this._attrs.delete(name); }
  append(...nodes) { this.children.push(...nodes); }
  appendChild(node) { this.children.push(node); }
  replaceChildren(...nodes) { this.children = nodes; }
  querySelector() { return null; }
  scrollIntoView() {}
}

const elementIds = [
  'modelProvider',
  'modelProviderTrigger',
  'modelProviderSearch',
  'modelEndpoint',
  'modelApiKey',
  'modelModeValue',
  'modelMaxTokens',
  'modelSupportsMic',
  'modelListTable',
  'modelListTableBody',
  'modelCatalogOptions',
  'modelEditIndex',
  'modelEditProfileId',
  'btnModelProbe',
  'btnModelSave',
  'btnModelProbeTechnicalDetail',
  'modelProbeResult',
  'modelProbeResultTitle',
  'modelProbeResultMessage',
  'modelProbeResultMeta',
  'modelProbeStages',
  'modelProviderError',
  'modelEndpointError',
  'modelApiKeyError',
  'modelMaxTokensError',
  'modelIdListError',
];
const elements = new Map(elementIds.map((id) => [id, new FakeElement(id)]));

const createdElements = [];
globalThis.document = {
  getElementById: (id) => elements.get(id) || null,
  createElement: () => {
    const node = new FakeElement('');
    createdElements.push(node);
    return node;
  },
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener() {},
};
globalThis.window = { addEventListener() {} };
globalThis.localStorage = { getItem: () => null, setItem: () => {} };

const { API } = await import('../web/static/modules/transport.js');
API.base = 'http://danmu.test';
API.token = 'test-token';

const listModule = await import('../web/static/modules/settings-model-modal-list.js');
const probeModule = await import('../web/static/modules/settings-model-modal-probe.js');
const { probeModelConnection, abortModelProbe, buildProbeFingerprint } = probeModule;

const el = (id) => elements.get(id);
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function makeResponse(data) {
  return { ok: true, status: 200, statusText: 'OK', json: async () => data };
}

function installFetch(handler) {
  globalThis.fetch = async (url, options = {}) => handler(String(url), options);
}

function setupForm() {
  listModule.resetModelModalListState();
  listModule.initModelListFromProfile(
    {
      name: 'Probe Profile',
      profile_id: 'cmp_probe_1',
      model_ids: ['probe-model'],
      model_names: { 'probe-model': 'Probe Profile' },
      default_model_id: 'probe-model',
    },
    'custom_openai',
  );
  el('modelProvider').value = 'custom_openai';
  el('modelEndpoint').value = 'https://api.example.com/v1';
  el('modelApiKey').value = '********';
  el('modelMaxTokens').value = '512';
  el('modelEditIndex').value = '0';
  el('modelEditProfileId').value = 'cmp_probe_1';
  el('modelProbeResult').className = '';
  el('modelProbeResult').dataset = {};
  el('modelProbeResultTitle').textContent = '';
  el('modelProbeResultMessage').textContent = '';
  el('modelProbeStages').children = [];
}

function collectForm() {
  return {
    name: 'Probe Profile',
    profile_id: el('modelEditProfileId').value,
    model_ids: ['probe-model'],
    model_names: { 'probe-model': 'Probe Profile' },
    default_model_id: 'probe-model',
    max_tokens: 512,
    mode: 'openai-compatible',
    endpoint: el('modelEndpoint').value,
    apiKey: el('modelApiKey').value,
    provider: 'custom_openai',
    supportsMic: false,
    thinking_effort: 'off',
    temperature: 0.8,
  };
}

function stagesPayload({ complete }) {
  const statuses = complete
    ? ['passed', 'passed', 'passed', 'passed', 'passed']
    : ['passed', 'passed', 'passed', 'failed', 'skipped'];
  return ['local', 'auth_model', 'text', 'vision_stream', 'business_parse'].map(
    (stage, index) => ({ stage, status: statuses[index], ok: statuses[index] === 'passed' }),
  );
}

setupForm();
probeModule.initModelModalProbe(collectForm);

test('buildProbeFingerprint binds profile_id and profile parameters', () => {
  const fingerprint = buildProbeFingerprint(collectForm());
  assert.ok(fingerprint.includes('"profile_id":"cmp_probe_1"'));
  assert.ok(fingerprint.includes('"thinking_effort":"off"'));
  assert.ok(fingerprint.includes('"temperature":0.8'));
});

test('full chain success requires complete (business_parse passed)', async () => {
  setupForm();
  installFetch(() => makeResponse({ ok: true, complete: true, profile_id: 'cmp_probe_1', stages: stagesPayload({ complete: true }) }));
  await probeModelConnection(collectForm);
  assert.equal(el('modelProbeResult').dataset.state, 'success');
  assert.equal(el('modelProbeResultTitle').textContent, '连接测试成功');
  assert.equal(el('modelProbeStages').children.length, 5);
  assert.ok(el('modelProbeStages').children.every((li) => li.dataset.status === 'passed'));
});

test('partial pass renders stage details and never claims success', async () => {
  setupForm();
  installFetch(() => makeResponse({
    ok: false,
    complete: false,
    error_category: 'invalid_content_part',
    status_code: 400,
    message: 'failed: invalid_content_part',
    profile_id: 'cmp_probe_1',
    stages: stagesPayload({ complete: false }),
  }));
  await probeModelConnection(collectForm);
  assert.equal(el('modelProbeResult').dataset.state, 'error');
  assert.equal(el('modelProbeResultTitle').textContent, '连接测试未完全通过');
  assert.ok(el('modelProbeResultMessage').textContent.includes('文本连接可用'));
  const byStage = Object.fromEntries(
    el('modelProbeStages').children.map((li) => [li.dataset.stage, li.dataset.status]),
  );
  assert.equal(byStage.vision_stream, 'failed');
  assert.equal(byStage.business_parse, 'skipped');
  assert.equal(byStage.text, 'passed');
});

test('a late stale probe result cannot overwrite the newer result', async () => {
  setupForm();
  const slow = deferred();
  let calls = 0;
  installFetch(() => {
    calls += 1;
    if (calls === 1) return slow.promise;
    return Promise.resolve(makeResponse({
      ok: true,
      complete: true,
      profile_id: 'cmp_probe_1',
      stages: stagesPayload({ complete: true }),
    }));
  });

  const first = probeModelConnection(collectForm);
  await flush();
  const second = probeModelConnection(collectForm);
  await second;
  assert.equal(el('modelProbeResult').dataset.state, 'success');

  // 迟到的旧响应：即使底层不支持取消、promise 正常 resolve，也不得覆盖新结果。
  slow.resolve(makeResponse({
    ok: false,
    complete: false,
    error_category: 'auth_invalid',
    status_code: 401,
    message: 'old failure',
    profile_id: 'cmp_probe_1',
    stages: stagesPayload({ complete: false }),
  }));
  await first;
  assert.equal(el('modelProbeResult').dataset.state, 'success', 'stale result must not overwrite');
  assert.equal(el('modelProbeResultTitle').textContent, '连接测试成功');
});

test('abort is silent and does not render a provider failure', async () => {
  setupForm();
  installFetch((_url, options) => new Promise((_resolve, reject) => {
    options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
  }));
  const pending = probeModelConnection(collectForm);
  await flush();
  assert.equal(el('modelProbeResult').dataset.state, 'loading');

  abortModelProbe();
  await pending;
  assert.equal(el('modelProbeResult').dataset.state, 'loading', 'cancel must not render an error');
  assert.notEqual(el('modelProbeResultTitle').textContent, '连接测试失败');
});

test('result bound to a different profile_id is discarded', async () => {
  setupForm();
  installFetch(() => makeResponse({
    ok: true,
    complete: true,
    profile_id: 'cmp_other_profile',
    stages: stagesPayload({ complete: true }),
  }));
  await probeModelConnection(collectForm);
  assert.notEqual(el('modelProbeResult').dataset.state, 'success');
});
