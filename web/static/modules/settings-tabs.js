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
  document.querySelectorAll('#page-settings .settings-tab').forEach((tab) => {
    const active = tab.dataset.settingsTab === tabId;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('#page-settings .settings-tab-panel').forEach((panel) => {
    const active = panel.dataset.settingsPanel === tabId;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
  const footer = document.querySelector('#settingsForm .settings-form-footer');
  if (footer) footer.classList.toggle('hidden', tabId === 'stylegen');
  switchDeps.onSettingsTabSwitch?.(tabId);
}

export function initSettingsTabs() {
  document.querySelectorAll('#page-settings .settings-tab').forEach((tab) => {
    tab.addEventListener('click', () => switchSettingsTab(tab.dataset.settingsTab));
  });
  switchSettingsTab(activeSettingsTabId);
}
