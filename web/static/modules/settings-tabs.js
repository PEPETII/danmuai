let activeSettingsTabId = 'api';
let switchDeps = {
  onSettingsTabSwitch: null,
};

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
  switchSettingsTab(activeSettingsTabId);
}
