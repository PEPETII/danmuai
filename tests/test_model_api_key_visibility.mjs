import assert from 'node:assert/strict';
import { test } from 'node:test';

class FakeElement {
  constructor() {
    this.type = 'password';
    this.value = '';
    this.disabled = false;
    this.dataset = {};
    this.attrs = new Map();
    this.listeners = new Map();
  }

  addEventListener(type, handler) {
    this.listeners.set(type, handler);
  }

  dispatch(type) {
    this.listeners.get(type)?.();
  }

  setAttribute(name, value) {
    this.attrs.set(name, String(value));
  }

  getAttribute(name) {
    return this.attrs.get(name) ?? null;
  }

  select() {
    this.selected = true;
  }
}

const input = new FakeElement();
const button = new FakeElement();
const hint = new FakeElement();
const elements = new Map([
  ['modelApiKey', input],
  ['btnModelApiKeyVisibility', button],
  ['modelApiKeyHint', hint],
]);

globalThis.document = {
  getElementById: (id) => elements.get(id) || null,
  querySelector: () => null,
};
globalThis.localStorage = { getItem: () => null, setItem: () => {} };

const {
  initModelApiKeyVisibility,
  resetModelApiKeyVisibility,
} = await import('../web/static/modules/settings-model-modal-state.js');

initModelApiKeyVisibility();

function setup(value) {
  input.value = value;
  input.type = 'text';
  input.selected = false;
  resetModelApiKeyVisibility();
}

test('new model key toggles between visible and password text', () => {
  setup('sk-new-real-key');

  assert.equal(input.type, 'password');
  assert.equal(button.disabled, false);
  assert.equal(button.getAttribute('aria-disabled'), 'false');
  assert.match(button.getAttribute('title'), /显示|show/i);
  button.dispatch('click');
  assert.equal(input.type, 'text');
  assert.equal(input.value, 'sk-new-real-key');
  assert.equal(button.getAttribute('aria-pressed'), 'true');
  button.dispatch('click');
  assert.equal(input.type, 'password');
  assert.equal(button.getAttribute('aria-pressed'), 'false');
});

test('masked edit key never becomes a pseudo-visible value', () => {
  setup('********');

  assert.equal(input.type, 'password');
  assert.equal(button.disabled, true);
  assert.equal(button.getAttribute('aria-pressed'), 'false');
  button.dispatch('click');
  assert.equal(input.type, 'password');
  assert.equal(input.value, '********');
  assert.equal(button.getAttribute('aria-pressed'), 'false');
});

test('typing a replacement key immediately restores visibility control', () => {
  setup('********');
  input.dispatch('focus');
  assert.equal(input.selected, true);

  input.value = 'sk-replacement-key';
  input.dispatch('input');
  assert.equal(button.disabled, false);
  assert.equal(button.getAttribute('aria-disabled'), 'false');
  button.dispatch('click');
  assert.equal(input.type, 'text');
  assert.equal(input.value, 'sk-replacement-key');
});

test('reset restores password state and masked-key accessibility state', () => {
  setup('sk-real-key');
  button.dispatch('click');
  assert.equal(input.type, 'text');

  input.value = '********';
  resetModelApiKeyVisibility();
  assert.equal(input.type, 'password');
  assert.equal(button.disabled, true);
  assert.equal(button.getAttribute('aria-pressed'), 'false');
  assert.equal(button.getAttribute('aria-disabled'), 'true');
  assert.match(hint.textContent, /saved_api_key_notice|API|密钥/i);
});
