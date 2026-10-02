import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

const classes = new Set(['hidden']);
const banner = {
  textContent: '',
  classList: {
    add: (name) => classes.add(name),
    remove: (name) => classes.delete(name),
  },
};
globalThis.document = {
  documentElement: {},
  getElementById: (id) => id === 'modelActiveSourceBanner' ? banner : null,
};
globalThis.fetch = async (url) => ({
  ok: true,
  json: async () => JSON.parse(await readFile(new URL(`../web${url}`, import.meta.url), 'utf8')),
});
const { loadLocale } = await import('../web/static/modules/i18n.js');
const { updateModelActiveSourceBanner } = await import('../web/static/modules/settings.js');
const config = {
  uses_custom_credentials: true,
  model_display_name: 'Doubao-Seed-2.0-pro',
  active_model_id: 'doubao-seed-2-0-pro-260215',
};

test('active model banner names the current model and directs edits to the visible list', async () => {
  await loadLocale('zh');
  updateModelActiveSourceBanner(config);
  assert.equal(classes.has('hidden'), false);
  assert.ok(banner.textContent.includes(`「${config.model_display_name}」`));
  assert.ok(banner.textContent.includes(`（${config.active_model_id}）`));
  assert.ok(banner.textContent.includes('请编辑上方对应的模型'));
  assert.ok(!banner.textContent.includes('不用于生成弹幕'));
  await loadLocale('en');
  updateModelActiveSourceBanner(config);
  assert.ok(banner.textContent.includes(config.model_display_name));
  assert.ok(banner.textContent.includes(config.active_model_id));
  assert.ok(banner.textContent.includes('edit the corresponding model above'));
  assert.ok(!banner.textContent.includes('not used for generation'));
});

test('missing active credentials clears the banner and missing display name uses the model ID', () => {
  updateModelActiveSourceBanner({ ...config, model_display_name: '' });
  assert.ok(banner.textContent.includes(config.active_model_id));
  updateModelActiveSourceBanner({ uses_custom_credentials: false });
  assert.equal(classes.has('hidden'), true);
  assert.equal(banner.textContent, '');
});
