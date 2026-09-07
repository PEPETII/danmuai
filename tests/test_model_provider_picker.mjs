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
