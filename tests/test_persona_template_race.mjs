/**
 * W-AUDIT-PERSONA-RACE-001：人格模板加载/编辑/保存身份一致性确定性测试。
 *
 * 通过可控 deferred Promise 构造 A 慢 / B 快的反序时序，驱动
 * `web/static/modules/app-persona-topic-page.js` 的真实导出函数
 * （loadPersonaTemplate / savePersonaTemplate / loadPersonaEditor），
 * 断言旧异步响应不能覆盖新选择，且保存目标始终等于 DOM 内容所属人格。
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
  'personaSelect',
  'personaContract',
  'personaSystemCustom',
  'btnSavePersona',
  'btnRestorePersona',
  'btnDeletePersona',
  'personaSaveStatusBanner',
  'personaTab-manage',
];
const elements = new Map(elementIds.map((id) => [id, new FakeElement(id)]));

const toasts = [];
function captureToast(message, isError = false) { toasts.push({ message, isError }); }

const windowListeners = new Map();
globalThis.document = {
  getElementById: (id) => elements.get(id) || null,
  createElement: () => new FakeElement(),
  querySelectorAll: () => [],
  querySelector: () => null,
  addEventListener() {},
};
globalThis.window = {
  addEventListener(type, fn) {
    if (!windowListeners.has(type)) windowListeners.set(type, []);
    windowListeners.get(type).push(fn);
  },
  // 镜像 web/static/app.js 的 withLoadingState：中途 disabled=true，finally 强制恢复。
  async withLoadingState(btn, _originalText, asyncFn) {
    if (!btn) return asyncFn();
    btn.disabled = true;
    try {
      return await asyncFn();
    } finally {
      btn.disabled = false;
    }
  },
};
globalThis.localStorage = { getItem: () => null, setItem: () => {} };
globalThis.confirm = () => true;
globalThis.prompt = () => null;

const { API } = await import('../web/static/modules/transport.js');
API.base = 'http://danmu.test';
API.token = 'test-token';

const persona = await import('../web/static/modules/app-persona-topic-page.js');
const {
  initPersonaTopicPage,
  loadPersonaTemplate,
  loadPersonaEditor,
  savePersonaTemplate,
  getPersonaEditorState,
} = persona;

// ---------------------------------------------------------------------------
// 工具
// ---------------------------------------------------------------------------

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function makeResponse(data) {
  return { ok: true, status: 200, statusText: 'OK', json: async () => data };
}

function errorResponse(status, detail) {
  return { ok: false, status, statusText: 'Error', json: async () => ({ detail }) };
}

function templateFor(id, extra = {}) {
  return {
    id,
    label: id,
    builtin: false,
    editable: true,
    system_editable: true,
    can_save: true,
    system_custom: `${id} custom`,
    user_pt: 'user-prompt',
    reply_contract: `${id} contract`,
    ...extra,
  };
}

function installFetch(handler) {
  globalThis.fetch = async (url, options = {}) => {
    const path = new URL(url).pathname;
    return handler(path, options, url);
  };
}

const el = (id) => elements.get(id);

/** 用真实函数把编辑器回到“未选择任何人格”的干净状态。 */
async function resetEditor() {
  toasts.length = 0;
  el('personaSelect').value = '';
  el('personaContract').value = '';
  el('personaSystemCustom').value = '';
  el('personaSystemCustom').readOnly = false;
  el('btnSavePersona').disabled = false;
  el('btnRestorePersona').disabled = false;
  await loadPersonaTemplate();
}

initPersonaTopicPage({ showToast: captureToast });

// ---------------------------------------------------------------------------
// 验收 1：A 慢 / B 快，A 后到不能覆盖 B
// ---------------------------------------------------------------------------

test('slow A response cannot overwrite fast B selection, DOM or loadedPersonaId', async () => {
  await resetEditor();
  const pendingA = deferred();
  let aSignal = null;
  installFetch((path, options) => {
    if (path === '/api/personae/A/template') {
      aSignal = options.signal;
      return pendingA.promise;
    }
    if (path === '/api/personae/B/template') return makeResponse(templateFor('B'));
    throw new Error(`unexpected ${path}`);
  });

  el('personaSelect').value = 'A';
  const pA = loadPersonaTemplate();
  await flush();
  assert.ok(aSignal, 'request A should carry an AbortSignal');
  assert.equal(getPersonaEditorState().loading, true);
  assert.equal(el('btnSavePersona').disabled, true, 'save disabled while loading');
  assert.equal(el('personaSystemCustom').value, '', 'stale DOM cleared on new load');

  // 切到 B：应 abort A 并以 B 的快速响应建立新身份。
  el('personaSelect').value = 'B';
  const pB = loadPersonaTemplate();
  await pB;
  assert.equal(aSignal.aborted, true, 'previous request aborted on new selection');
  assert.equal(getPersonaEditorState().loadedPersonaId, 'B');
  assert.equal(el('personaSystemCustom').value, 'B custom');
  assert.equal(el('btnSavePersona').disabled, false);

  // A 迟到（模拟底层不支持取消：promise 仍正常 resolve）。
  pendingA.resolve(makeResponse(templateFor('A')));
  await pA;

  assert.equal(getPersonaEditorState().loadedPersonaId, 'B', 'late A must not claim identity');
  assert.equal(el('personaSystemCustom').value, 'B custom', 'late A must not overwrite B DOM');
  assert.equal(el('personaContract').value, 'B contract');
  assert.equal(el('btnSavePersona').disabled, false, 'button state stays with B');
});

// ---------------------------------------------------------------------------
// 验收 2：B 已选但模板 loading 时保存不发 PUT
// ---------------------------------------------------------------------------

test('save is refused and issues no PUT while selected template is still loading', async () => {
  await resetEditor();
  const pendingB = deferred();
  const putCalls = [];
  installFetch((path, options) => {
    const method = options.method || 'GET';
    if (method === 'PUT') { putCalls.push(path); return makeResponse({ ok: true }); }
    if (path === '/api/personae/B/template') return pendingB.promise;
    throw new Error(`unexpected ${method} ${path}`);
  });

  el('personaSelect').value = 'B';
  const pB = loadPersonaTemplate();
  await flush();
  assert.equal(getPersonaEditorState().loading, true);
  assert.equal(el('btnSavePersona').disabled, true);

  await savePersonaTemplate();

  assert.equal(putCalls.length, 0, 'no PUT while loading');
  assert.ok(toasts.some((x) => x.isError && x.message.includes('未就绪')), 'refusal is visible');
  assert.equal(el('personaSystemCustom').value, '', 'no content written for A or B');

  pendingB.resolve(makeResponse(templateFor('B')));
  await pB;
  assert.equal(getPersonaEditorState().loadedPersonaId, 'B');
});

// ---------------------------------------------------------------------------
// 验收 2b：加载失败不保留属于旧人格的可保存 DOM
// ---------------------------------------------------------------------------

test('failed load clears stale persona DOM and keeps save disabled', async () => {
  await resetEditor();
  let bFails = true;
  installFetch((path) => {
    if (path === '/api/personae/A/template') return makeResponse(templateFor('A'));
    if (path === '/api/personae/B/template') {
      return bFails ? errorResponse(400, 'persona.notFound') : makeResponse(templateFor('B'));
    }
    throw new Error(`unexpected ${path}`);
  });

  el('personaSelect').value = 'A';
  await loadPersonaTemplate();
  assert.equal(el('personaSystemCustom').value, 'A custom');
  assert.equal(getPersonaEditorState().loadedPersonaId, 'A');

  // 切到 B，B 加载失败：A 的旧内容必须清空，且不能保存。
  el('personaSelect').value = 'B';
  await loadPersonaTemplate();
  assert.equal(getPersonaEditorState().error, true);
  assert.equal(getPersonaEditorState().loadedPersonaId, '');
  assert.equal(el('personaSystemCustom').value, '', 'stale A content cleared on error');
  assert.equal(el('btnSavePersona').disabled, true, 'save disabled on error');
  assert.ok(toasts.some((x) => x.isError));

  // 错误后可重试：再次加载成功即恢复可保存（不永久禁用）。
  bFails = false;
  await loadPersonaTemplate();
  assert.equal(getPersonaEditorState().loadedPersonaId, 'B');
  assert.equal(el('btnSavePersona').disabled, false, 'retry re-enables save');
});

// ---------------------------------------------------------------------------
// 验收 3：DOM 属于 A 时切到 B，保存被拒且不写入 B
// ---------------------------------------------------------------------------

test('save is refused when DOM belongs to A but selection moved to B', async () => {
  await resetEditor();
  const putCalls = [];
  installFetch((path, options) => {
    const method = options.method || 'GET';
    if (method === 'PUT') { putCalls.push(path); return makeResponse({ ok: true }); }
    if (path === '/api/personae/A/template') return makeResponse(templateFor('A'));
    throw new Error(`unexpected ${method} ${path}`);
  });

  el('personaSelect').value = 'A';
  await loadPersonaTemplate();
  el('personaSystemCustom').value = 'A edited';

  el('personaSelect').value = 'B'; // 直接改选择，不触发加载
  await savePersonaTemplate();

  assert.equal(putCalls.length, 0, 'identity mismatch must not PUT A or B');
  assert.ok(toasts.some((x) => x.isError && x.message.includes('未就绪')));
  assert.equal(el('personaSystemCustom').value, 'A edited', 'A content not written to B');
});

// ---------------------------------------------------------------------------
// 验收 4：保存 A 后立即切 B，A 完成不覆盖 B，服务端只更新 A
// ---------------------------------------------------------------------------

test('completing save for A after switching to B neither overwrites B nor retargets PUT', async () => {
  await resetEditor();
  const pendingPut = deferred();
  const putPaths = [];
  const getPaths = [];
  installFetch((path, options) => {
    const method = options.method || 'GET';
    if (method === 'GET') {
      getPaths.push(path);
      if (path === '/api/personae/A/template') return makeResponse(templateFor('A'));
      if (path === '/api/personae/B/template') return makeResponse(templateFor('B'));
      throw new Error(`unexpected GET ${path}`);
    }
    if (method === 'PUT') { putPaths.push(path); return pendingPut.promise; }
    throw new Error(`unexpected ${method} ${path}`);
  });

  el('personaSelect').value = 'A';
  await loadPersonaTemplate();
  el('personaSystemCustom').value = 'A edited';

  const pSave = savePersonaTemplate();
  await flush();
  assert.deepEqual(putPaths, ['/api/personae/A/template'], 'PUT targets captured persona A');

  // 保存仍在途时切到 B 并加载完成。
  el('personaSelect').value = 'B';
  await loadPersonaTemplate();
  assert.equal(getPersonaEditorState().loadedPersonaId, 'B');
  assert.equal(el('personaSystemCustom').value, 'B custom');

  pendingPut.resolve(makeResponse({ ok: true }));
  await pSave;

  assert.deepEqual(putPaths, ['/api/personae/A/template'], 'only A is updated');
  assert.equal(getPersonaEditorState().loadedPersonaId, 'B', 'A completion must not claim B');
  assert.equal(el('personaSystemCustom').value, 'B custom', 'A completion must not overwrite B DOM');
  assert.equal(
    getPaths.filter((p) => p === '/api/personae/A/template').length,
    1,
    'A save completion must not reload A while B is selected',
  );
  assert.equal(
    toasts.some((x) => x.message.includes('人格已保存')),
    false,
    'no success toast for A once selection moved to B',
  );
});

// ---------------------------------------------------------------------------
// 验收 5：AbortError 静默（不显示错误 toast）
// ---------------------------------------------------------------------------

test('aborted template load is silent and leaves no error toast', async () => {
  await resetEditor();
  installFetch((path, options) => {
    if (path === '/api/personae/A/template') {
      return new Promise((_resolve, reject) => {
        options.signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')));
      });
    }
    if (path === '/api/personae/B/template') return makeResponse(templateFor('B'));
    throw new Error(`unexpected ${path}`);
  });

  el('personaSelect').value = 'A';
  const pA = loadPersonaTemplate();
  await flush();
  el('personaSelect').value = 'B';
  const pB = loadPersonaTemplate();
  await pB;
  await pA;

  assert.equal(toasts.length, 0, 'abort must not surface an error toast');
  assert.equal(getPersonaEditorState().loadedPersonaId, 'B');
});

// ---------------------------------------------------------------------------
// 验收 6：真实保存错误可见且不清除未保存内容
// ---------------------------------------------------------------------------

test('real save failure stays visible and preserves unsaved editor content', async () => {
  await resetEditor();
  installFetch((path, options) => {
    const method = options.method || 'GET';
    if (method === 'PUT') return errorResponse(500, 'server boom');
    if (path === '/api/personae/A/template') return makeResponse(templateFor('A'));
    throw new Error(`unexpected ${method} ${path}`);
  });

  el('personaSelect').value = 'A';
  await loadPersonaTemplate();
  el('personaSystemCustom').value = 'unsaved but correct';

  await savePersonaTemplate();

  assert.ok(toasts.some((x) => x.isError && x.message.includes('server boom')), 'error visible');
  assert.equal(el('personaSystemCustom').value, 'unsaved but correct', 'unsaved content preserved');
  assert.equal(el('btnSavePersona').disabled, false, 'still retryable');
});

// ---------------------------------------------------------------------------
// 验收 7：合法加载/编辑/保存不回归（含保存后回读与成功提示）
// ---------------------------------------------------------------------------

test('valid load / edit / save still works and reloads from server after success', async () => {
  await resetEditor();
  let putDone = false;
  installFetch((path, options) => {
    const method = options.method || 'GET';
    if (method === 'PUT') { putDone = true; return makeResponse({ ok: true }); }
    if (path === '/api/personae/A/template') {
      return makeResponse(templateFor('A', { system_custom: putDone ? 'A edited' : 'A custom' }));
    }
    throw new Error(`unexpected ${method} ${path}`);
  });

  el('personaSelect').value = 'A';
  await loadPersonaTemplate();
  assert.equal(el('personaSystemCustom').value, 'A custom');
  assert.equal(el('btnSavePersona').disabled, false);

  el('personaSystemCustom').value = 'A edited';
  await savePersonaTemplate();

  assert.equal(putDone, true);
  assert.equal(el('personaSystemCustom').value, 'A edited', 'reloaded server value');
  assert.ok(toasts.some((x) => x.message.includes('人格已保存')));
  assert.equal(getPersonaEditorState().loadedPersonaId, 'A');
});

// ---------------------------------------------------------------------------
// 验收 8：响应 tpl.id 与选择不一致时忽略
// ---------------------------------------------------------------------------

test('template response whose id mismatches the selection is ignored', async () => {
  await resetEditor();
  installFetch((path) => {
    if (path === '/api/personae/B/template') return makeResponse(templateFor('OTHER'));
    throw new Error(`unexpected ${path}`);
  });

  el('personaSelect').value = 'B';
  await loadPersonaTemplate();

  assert.equal(getPersonaEditorState().loadedPersonaId, '');
  assert.equal(getPersonaEditorState().error, true);
  assert.equal(el('personaSystemCustom').value, '');
  assert.equal(el('btnSavePersona').disabled, true);
});

// ---------------------------------------------------------------------------
// 验收 9：自定义人格删除后首项回退仍可用
// ---------------------------------------------------------------------------

test('loadPersonaEditor falls back to the first persona after the selected one disappears', async () => {
  await resetEditor();
  let list = ['A'];
  installFetch((path, options) => {
    const method = options.method || 'GET';
    if (path === '/api/personae' && method === 'GET') {
      return makeResponse({
        items: list.map((id) => ({ id, label: id, builtin: false, active: false, model_id: '' })),
      });
    }
    if (path === '/api/personae/A/template') return makeResponse(templateFor('A'));
    if (path === '/api/personae/B/template') return makeResponse(templateFor('B'));
    throw new Error(`unexpected ${method} ${path}`);
  });

  await loadPersonaEditor();
  assert.equal(el('personaSelect').value, 'A');
  assert.equal(getPersonaEditorState().loadedPersonaId, 'A');

  list = ['B']; // A 被删除
  await loadPersonaEditor();
  assert.equal(el('personaSelect').value, 'B', 'falls back to first available');
  assert.equal(getPersonaEditorState().loadedPersonaId, 'B');
  assert.equal(el('personaSystemCustom').value, 'B custom');
  assert.equal(el('btnSavePersona').disabled, false);
});

// ---------------------------------------------------------------------------
// 验收 10：页面事件绑定（change 触发加载 / 加载中点击保存被拒）
// ---------------------------------------------------------------------------

test('page wiring: change loads template and save click is refused while loading', async () => {
  await resetEditor();
  const pendingB = deferred();
  const putCalls = [];
  installFetch((path, options) => {
    const method = options.method || 'GET';
    if (path === '/api/personae/B/template') return pendingB.promise;
    if (method === 'PUT') { putCalls.push(path); return makeResponse({ ok: true }); }
    throw new Error(`unexpected ${method} ${path}`);
  });

  initPersonaTopicPage({ showToast: captureToast });
  el('personaSelect').value = 'B';
  el('personaSelect').dispatch('change', {});
  await flush();
  assert.equal(getPersonaEditorState().loading, true);

  el('btnSavePersona').dispatch('click', {});
  await flush();
  assert.equal(putCalls.length, 0, 'click while loading must not PUT');
  assert.ok(toasts.some((x) => x.isError));

  pendingB.resolve(makeResponse(templateFor('B')));
  await flush();
  assert.equal(getPersonaEditorState().loadedPersonaId, 'B');
});

// ---------------------------------------------------------------------------
// 验收 11：恢复默认使用加载身份，且在切换选择后不污染新编辑器
// ---------------------------------------------------------------------------

test('restore uses the loaded persona identity and updates the editor', async () => {
  await resetEditor();
  const restorePaths = [];
  installFetch((path, options) => {
    const method = options.method || 'GET';
    if (method === 'POST' && path.endsWith('/restore')) {
      restorePaths.push(path);
      return makeResponse({ system_custom: 'A default' });
    }
    if (path === '/api/personae/A/template') {
      return makeResponse(templateFor('A', { builtin: true, editable: false }));
    }
    throw new Error(`unexpected ${method} ${path}`);
  });

  el('personaSelect').value = 'A';
  await loadPersonaTemplate();
  assert.equal(el('btnRestorePersona').disabled, false);

  el('btnRestorePersona').dispatch('click', { currentTarget: el('btnRestorePersona') });
  await flush();

  assert.deepEqual(restorePaths, ['/api/personae/A/restore']);
  assert.equal(el('personaSystemCustom').value, 'A default');
});

test('restore result does not overwrite a newly selected persona', async () => {
  await resetEditor();
  const pendingRestore = deferred();
  installFetch((path, options) => {
    const method = options.method || 'GET';
    if (method === 'POST' && path.endsWith('/restore')) return pendingRestore.promise;
    if (path === '/api/personae/A/template') return makeResponse(templateFor('A', { builtin: true, editable: false }));
    if (path === '/api/personae/B/template') return makeResponse(templateFor('B'));
    throw new Error(`unexpected ${method} ${path}`);
  });

  el('personaSelect').value = 'A';
  await loadPersonaTemplate();

  el('btnRestorePersona').dispatch('click', { currentTarget: el('btnRestorePersona') });
  await flush();

  el('personaSelect').value = 'B';
  await loadPersonaTemplate();
  assert.equal(el('personaSystemCustom').value, 'B custom');

  pendingRestore.resolve(makeResponse({ system_custom: 'A default' }));
  await flush();

  assert.equal(el('personaSystemCustom').value, 'B custom', 'late restore must not overwrite B');
});
