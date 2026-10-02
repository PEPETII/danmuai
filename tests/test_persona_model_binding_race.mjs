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
    this.listeners = new Map();
    this.textContent = '';
    this.value = '';
    this.checked = false;
    this._innerHTML = '';
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

  addEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  setAttribute(name, value) {
    this[name] = String(value);
  }
}

const personaActiveList = new FakeElement();
const elements = new Map([['personaActiveList', personaActiveList]]);
globalThis.document = {
  documentElement: { lang: 'zh-CN' },
  createElement: (tagName) => new FakeElement(tagName),
  getElementById: (id) => elements.get(id) || null,
  querySelector: () => null,
  querySelectorAll: () => [],
};
globalThis.window = {
  location: { href: 'http://danmu.test/' },
  sessionStorage: { getItem: () => null, setItem: () => {} },
};

const { API } = await import('../web/static/modules/transport.js');
API.base = 'http://danmu.test';
API.token = 'test-token';

const { loadPersonaeCheckboxes } = await import('../web/static/modules/app-persona-topic-page.js');

function jsonResponse(data) {
  return {
    ok: true,
    status: 200,
    statusText: 'OK',
    json: async () => data,
  };
}

test('persona rows contain activation controls but no model binding controls', async () => {
  const requests = [];
  globalThis.fetch = async (url, options = {}) => {
    requests.push({ url: new URL(url), options });
    return jsonResponse({
      items: [
        {
          id: 'builtin-persona',
          label: 'Built-in persona',
          active: true,
          builtin: true,
          profile_id: 'ignored-profile',
          model_id: 'ignored-model',
          binding_status: 'legacy-only',
        },
        {
          id: 'custom-persona',
          label: 'Custom persona',
          active: false,
          builtin: false,
          profile_id: 'ignored-profile-2',
          model_id: 'ignored-model-2',
        },
      ],
    });
  };

  await loadPersonaeCheckboxes('personaActiveList');

  assert.equal(requests.length, 1);
  assert.equal(requests[0].url.pathname, '/api/personae');
  assert.equal(personaActiveList.children.length, 2);
  assert.equal(personaActiveList.children[0].children.some((child) => child.tagName === 'SELECT'), false);
  assert.equal(personaActiveList.children[1].children.some((child) => child.tagName === 'SELECT'), false);
  assert.equal(personaActiveList.children[0].children[0].children[0].tagName, 'INPUT');
  assert.equal(personaActiveList.children[1].children[0].children[0].tagName, 'INPUT');
  assert.equal(personaActiveList.children[1].children.at(-1).tagName, 'BUTTON');
});
