import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFile } from 'node:fs/promises';

test('provider picker modal markup keeps search contract', async () => {
  const modalHtml = await readFile(
    new URL('../web/static/partials/modals.html', import.meta.url),
    'utf-8',
  );
  for (const token of [
    'modelProviderPicker',
    'modelProviderTrigger',
    'modelProviderSearch',
    'modelProviderOptions',
    'modelProviderEmpty',
  ]) {
    assert.ok(modalHtml.includes(token), `modals.html should contain ${token}`);
  }
  for (const token of ['modelProviderRegion', 'modelCatalogMultiselect']) {
    assert.ok(!modalHtml.includes(token), `modals.html should not contain ${token}`);
  }
});

test('filterProvidersForModal matches label/id/alias case-insensitively', async () => {
  globalThis.window = { open() {} };
  globalThis.document = {
    getElementById: () => null,
    createElement: () => ({ setAttribute() {}, classList: { add() {}, remove() {}, toggle() {} }, dataset: {}, append() {}, addEventListener() {} }),
    querySelectorAll: () => [],
    querySelector: () => null,
    addEventListener() {},
  };
  globalThis.localStorage = { getItem: () => null, setItem: () => {} };
  globalThis.fetch = async () => ({ ok: true, json: async () => [] });
  const providers = await import('../web/static/modules/settings-providers.js');
  const list = [
    { id: 'google_gemini', label: 'Google Gemini', default_endpoint: 'https://generativelanguage.googleapis.com/v1beta/openai' },
    { id: 'openai', label: 'OpenAI', default_endpoint: 'https://api.openai.com/v1' },
  ];

  for (const keyword of ['Google', 'gemini', '谷歌', 'google_gemini', 'GOOGLE']) {
    const hits = providers.filterProvidersForModal(list, keyword);
    assert.ok(hits.some((item) => item.id === 'google_gemini'), `keyword ${keyword} should match Google Gemini`);
  }

  assert.deepEqual(providers.filterProvidersForModal(list, '  '), list);
  assert.deepEqual(providers.filterProvidersForModal(list, 'no-such-provider-xyz'), []);
});

test('shared provider classification drives hidden and visible modal fields', async () => {
  const providers = await import('../web/static/modules/settings-providers.js');

  const makeField = () => {
    const tokens = new Set();
    return {
      classList: {
        toggle(name, force) {
          if (force) tokens.add(name);
          else tokens.delete(name);
        },
        contains(name) {
          return tokens.has(name);
        },
      },
    };
  };
  const fields = {
    modelModeField: makeField(),
    modelEndpointField: makeField(),
  };
  globalThis.document = {
    getElementById: (id) => fields[id] || null,
    querySelector: () => null,
  };

  const form = await import('../web/static/modules/settings-model-modal-form.js');
  const syncFor = (providerId) => form.syncProviderDependentVisibility(providerId);
  const assertHidden = () => {
    assert.equal(fields.modelModeField.hidden, true);
    assert.equal(fields.modelEndpointField.hidden, true);
    assert.equal(fields.modelModeField.classList.contains('hidden'), true);
    assert.equal(fields.modelEndpointField.classList.contains('hidden'), true);
  };
  const assertVisible = () => {
    assert.equal(fields.modelModeField.hidden, false);
    assert.equal(fields.modelEndpointField.hidden, false);
    assert.equal(fields.modelModeField.classList.contains('hidden'), false);
    assert.equal(fields.modelEndpointField.classList.contains('hidden'), false);
  };

  assert.equal(providers.isCustomProvider('openai'), false);
  assert.equal(providers.isCustomProvider('custom_openai'), true);
  syncFor('openai');
  assertHidden();
  syncFor('custom_openai');
  assertVisible();
  syncFor('doubao');
  assertHidden();
  syncFor('custom_openai');
  assertVisible();
});

test('non-custom provider validation ignores the hidden endpoint field', async () => {
  const list = await import('../web/static/modules/settings-model-modal-list.js');
  const validation = await import('../web/static/modules/settings-model-modal-validation.js');
  const makeInput = (value = '') => ({
    value,
    classList: { toggle() {} },
    setAttribute() {},
  });
  const elements = {
    modelProvider: makeInput('openai'),
    modelEndpoint: makeInput(''),
    modelApiKey: makeInput('test-key'),
    modelMaxTokens: makeInput('512'),
  };
  globalThis.document = {
    getElementById: (id) => elements[id] || null,
    querySelector: () => null,
  };
  list.resetModelModalListState();
  list.initModelListFromProfile(
    { model_ids: ['test-model'], default_model_id: 'test-model' },
    'openai',
  );

  assert.equal(validation.validateModelForm().valid, true);
  elements.modelProvider.value = 'custom_openai';
  assert.equal(validation.validateModelForm().valid, false);
  elements.modelEndpoint.value = 'https://example.com/v1';
  assert.equal(validation.validateModelForm().valid, true);
});
