import assert from 'node:assert/strict';
import { test } from 'node:test';

class Input {
  constructor({ id = '', name = '', type = 'text', value = '', dataset = {} } = {}) {
    Object.assign(this, { id, name, type, value, dataset });
    this.listeners = new Map();
    this.classList = { contains: () => false };
  }

  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }

  closest() { return null; }
  dispatch(type) { this.listeners.get(type)?.({ target: this, type }); }
}

globalThis.HTMLInputElement = Input;
globalThis.window = { addEventListener() {} };
const names = ['outline', 'shadow', 'border', 'username'].map((kind) => `floating_panel_${kind}_color`);
const texts = names.map((name) => new Input({ name, value: '#aabbcc80', dataset: { sgColorField: name } }));
const pickers = names.map((name) => new Input({ type: 'color', value: '#000000', dataset: { sgColorFor: name } }));
const preset = new Input({ name: 'floating_panel_style_preset', value: 'blivechat_line' });
const elements = new Map();
for (const kind of ['Card', 'Text']) {
  const pickerId = `sg${kind}ColorPicker`;
  const hexId = `sg${kind}ColorHex`;
  elements.set(pickerId, new Input({ id: pickerId, type: 'color', value: '#112233' }));
  elements.set(hexId, new Input({ id: hexId, value: '#11223380' }));
}
const addPreview = new Input();
elements.set('sgBtnAddPreview', addPreview);
const form = {
  addEventListener() {},
  querySelector(selector) {
    const name = selector.match(/^\[name="(.+)"\]$/)?.[1];
    if (name) return [...texts, preset].find((input) => input.name === name) || null;
    const colorName = selector.match(/^\[data-sg-color-for="(.+)"\]$/)?.[1];
    return pickers.find((input) => input.dataset.sgColorFor === colorName) || null;
  },
  querySelectorAll(selector) {
    if (selector === '[data-sg-color-for]') return pickers;
    if (selector === '[data-sg-color-field]') return texts;
    return [];
  },
};
elements.set('styleGeneratorForm', form);
globalThis.document = {
  getElementById: (id) => elements.get(id) || null,
  querySelector: (selector) => form.querySelector(selector),
  querySelectorAll: () => [],
};
const requests = [];
globalThis.fetch = async (url) => {
  const path = new URL(url).pathname;
  requests.push(path);
  const payloads = {
    '/api/config': Object.fromEntries(names.map((name) => [name, '#12345678'])),
    '/api/floating-panel/style-presets': { presets: {} },
    '/api/personae': { items: [] },
    '/api/fonts': { families: [], imported: [] },
    '/api/floating-panel/custom-css': { files: [] },
    '/api/floating-panel/custom-css/templates': { templates: [] },
  };
  assert.ok(path in payloads, `unexpected API request: ${path}`);
  return { ok: true, json: async () => payloads[path] };
};
const { API } = await import('../web/static/modules/transport.js');
API.base = 'http://test.local';
API.token = 'test-only';
const { initStyleGeneratorPage, loadStyleGeneratorPage } = await import('../web/static/modules/app-style-generator-page.js');

test('style page initializes and finishes loading with synchronized colors', async () => {
  const errors = [];
  initStyleGeneratorPage({ showToast: (message, isError) => { if (isError) errors.push(message); } });
  assert.deepEqual(pickers.map((input) => input.value), names.map(() => '#AABBCC'));
  assert.ok(addPreview.listeners.has('click'), 'initialization must reach preview controls');
  await loadStyleGeneratorPage();
  assert.deepEqual(errors, []);
  assert.ok(requests.includes('/api/floating-panel/custom-css/templates'), 'loading must reach CSS resources');
  assert.deepEqual(pickers.map((input) => input.value), names.map(() => '#123456'));
  assert.deepEqual(texts.map((input) => input.value), names.map(() => '#12345678'));
});

test('both palette inputs synchronize RGB and retain alpha on picker changes', () => {
  for (const kind of ['Card', 'Text']) {
    const picker = elements.get(`sg${kind}ColorPicker`);
    const hex = elements.get(`sg${kind}ColorHex`);
    hex.value = '#abcdef7f';
    hex.dispatch('input');
    assert.equal(picker.value, '#ABCDEF');
    assert.equal(hex.value, '#ABCDEF7F');
    picker.value = '#987654';
    picker.dispatch('input');
    assert.equal(hex.value, '#9876547F');
    hex.value = '#ABC';
    hex.dispatch('input');
    assert.equal(picker.value, '#987654', 'incomplete hex must not overwrite the picker');
    hex.value = '#010203';
    hex.dispatch('change');
    assert.equal(picker.value, '#010203');
  }
});
