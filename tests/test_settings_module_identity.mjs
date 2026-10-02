import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { test } from 'node:test';

async function settingsImportedBy(entryPath) {
  const entry = new URL(entryPath, import.meta.url);
  const source = await readFile(entry, 'utf8');
  const imports = [...source.matchAll(/\bfrom\s+(['"])([^'"]*\/settings\.js(?:\?[^'"]*)?)\1/g)];
  assert.equal(imports.length, 1, `${entryPath} must have one settings import`);
  return import(new URL(imports[0][2], entry).href);
}

// Resolve the real entry-point imports, including their query strings. Testing
// settings.js directly would miss two entry points loading different instances.
const appSettings = await settingsImportedBy('../web/static/app.js');
const languageSettings = await settingsImportedBy('../web/static/modules/language.js');

test('app and language use the same settings instance and bootstrap wrappers', () => {
  assert.equal(appSettings, languageSettings);
  assert.equal(appSettings.configureSettingsBindings, languageSettings.configureSettingsBindings);
  assert.equal(appSettings.reloadConfigFromServer, languageSettings.reloadConfigFromServer);
});

test('language refresh reads the microphone device cache populated by app bootstrap', async () => {
  const originalDocument = globalThis.document;
  const originalFetch = globalThis.fetch;
  const { API } = await import('../web/static/modules/transport.js');
  const originalApi = { ...API };
  const { loadLocale } = await import('../web/static/modules/i18n.js');
  const deviceLabel = 'Desk USB Microphone';
  let deviceRequests = 0;
  const classes = new Set(['hidden']);
  const banner = {
    textContent: '',
    dataset: {},
    classList: {
      add: (name) => classes.add(name),
      remove: (name) => classes.delete(name),
    },
  };
  const select = {
    value: '',
    options: [],
    set innerHTML(value) {
      assert.equal(value, '');
      this.options = [];
    },
    appendChild(option) {
      this.options.push(option);
    },
  };
  const elements = new Map([
    ['micActiveSourceBanner', banner],
    ['mic_input_device_id', select],
    ['mic_mode_enabled', { checked: true }],
    ['mic_use_visual_model', { checked: false }],
  ]);
  globalThis.document = {
    documentElement: {},
    getElementById: (id) => elements.get(id) || null,
    createElement(tag) {
      assert.equal(tag, 'option');
      return { value: '', textContent: '' };
    },
  };
  API.base = 'http://settings.test';
  API.token = 'test-session';
  globalThis.fetch = async (url) => {
    if (url === `${API.base}/api/mic/devices`) {
      deviceRequests += 1;
      return {
        ok: true,
        json: async () => ({
          available: true,
          default_input_device_label: deviceLabel,
          devices: [{ id: 7, name: deviceLabel, is_default: true }],
        }),
      };
    }
    assert.match(url, /^\/static\/locales\/(zh|en)\/\w+\.json$/);
    return {
      ok: true,
      json: async () => JSON.parse(await readFile(new URL(`../web${url}`, import.meta.url), 'utf8')),
    };
  };

  try {
    await loadLocale('zh');
    await appSettings.populateMicInputDevices('7');
    assert.equal(deviceRequests, 1);
    assert.equal(select.value, '7');
    assert.equal(select.options[1].value, '7');

    for (const language of ['zh', 'en']) {
      await loadLocale(language);
      languageSettings.updateMicActiveSourceBanner({});
      assert.equal(classes.has('hidden'), false);
      assert.equal(banner.dataset.defaultInputLabel, deviceLabel);
      assert.ok(banner.textContent.includes(deviceLabel));
    }
    assert.equal(deviceRequests, 1, 'localized banner refresh reuses the bootstrap cache');
  } finally {
    globalThis.document = originalDocument;
    globalThis.fetch = originalFetch;
    Object.assign(API, originalApi);
  }
});
