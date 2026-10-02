import { createAutoSave } from './auto-save.js';

export function createStyleGeneratorPersistence({
  styleSaveKeys,
  boolKeys,
  adjustDisplayAreaKey,
  derivedStyleSaveKeys,
  readBool,
  readStr,
  applyDerivedLegacyStyleFields,
  apiFetch,
  t,
  showToast,
  setDirty,
}) {
  function collectStylePayload() {
    const data = {};
    styleSaveKeys.forEach((key) => {
      if (key === adjustDisplayAreaKey || derivedStyleSaveKeys.has(key)) return;
      if (boolKeys.has(key)) {
        const checked = readBool(key);
        data[key] = key === adjustDisplayAreaKey
          ? (checked ? '0' : '1')
          : (checked ? '1' : '0');
        return;
      }
      data[key] = readStr(key, '');
    });
    applyDerivedLegacyStyleFields(data);
    return data;
  }

  const autoSave = createAutoSave({
    capture: collectStylePayload,
    save: async (payload, { isLatest }) => {
      await apiFetch('/api/config', {
        method: 'PUT',
        body: JSON.stringify(payload),
      });
      if (isLatest()) setDirty(false);
    },
    onState: (state, error) => {
      const status = document.getElementById('sgSaveStatus');
      if (state === 'saving') {
        if (status) status.textContent = t('dynamic.autoSaveStatus.saving');
      } else if (state === 'saved') {
        if (status) status.textContent = t('dynamic.autoSaveStatus.saved');
      } else if (state === 'error') {
        setDirty(true);
        if (status) status.textContent = t('dynamic.autoSaveStatus.error');
        showToast(error?.message || t('dynamic.autoSaveStatus.error'), true);
      }
    },
  });

  return {
    collectStylePayload,
    flush: () => autoSave.flush(),
    schedule: (options = {}) => autoSave.schedule(options),
  };
}
