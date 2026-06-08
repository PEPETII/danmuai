const SETTINGS_UI_MODE_KEY = 'danmu_settings_ui_mode';

let activeSettingsTabId = 'api';
let switchDeps = {
  onSettingsTabSwitch: null,
};

function getSettingsUiMode() {
  try {
    const v = localStorage.getItem(SETTINGS_UI_MODE_KEY);
    return v === 'full' ? 'full' : 'simplified';
  } catch {
    return 'simplified';
  }
}

function applySettingsUiMode() {
  const mode = getSettingsUiMode();
  const form = document.getElementById('settingsForm');
  if (form) {
    form.classList.toggle('settings-ui-simplified', mode === 'simplified');
    form.classList.toggle('settings-ui-full', mode === 'full');
  }
  document.querySelectorAll('.settings-ui-mode-btn').forEach((btn) => {
    const active = btn.dataset.settingsUiMode === mode;
    btn.classList.toggle('active', active);
    btn.setAttribute('aria-pressed', active ? 'true' : 'false');
  });
}

function setSettingsUiMode(mode) {
  const normalized = mode === 'full' ? 'full' : 'simplified';
  try {
    localStorage.setItem(SETTINGS_UI_MODE_KEY, normalized);
  } catch {
    /* ignore quota / private mode */
  }
  applySettingsUiMode();
}

export function initSettingsUiMode() {
  applySettingsUiMode();
  document.querySelectorAll('.settings-ui-mode-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      setSettingsUiMode(btn.dataset.settingsUiMode);
    });
  });
}

export function configureSettingsTabs(deps) {
  switchDeps = { ...switchDeps, ...deps };
}

export function getActiveSettingsTabId() {
  return activeSettingsTabId;
}

export function switchSettingsTab(tabId) {
  activeSettingsTabId = tabId;
  document.querySelectorAll('.settings-tab').forEach((tab) => {
    const active = tab.dataset.settingsTab === tabId;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('.settings-tab-panel').forEach((panel) => {
    const active = panel.dataset.settingsPanel === tabId;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
  switchDeps.onSettingsTabSwitch?.(tabId);
}

export function initSettingsTabs() {
  document.querySelectorAll('#settingsForm .settings-tab').forEach((tab) => {
    tab.addEventListener('click', () => switchSettingsTab(tab.dataset.settingsTab));
  });
}
