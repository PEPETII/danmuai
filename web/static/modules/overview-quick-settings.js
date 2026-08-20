/**
 * 温馨控制台「快捷入口」：文本 + 按钮/下拉，复用既有页面与 Tab 切换。
 */

/** @type {Record<string, { page: string, settingsTab?: string, petTab?: string, personaTab?: string }>} */
const QUICK_NAV_MAP = {
  mic: { page: 'settings', settingsTab: 'mic' },
  'danmu-read': { page: 'danmu-read' },
  danmu: { page: 'settings', settingsTab: 'danmu' },
  knowledge: { page: 'knowledge' },
  vtuber: { page: 'pet', petTab: 'vtuber' },
  'history-stats': { page: 'history-stats' },
  'live-output': { page: 'live-output' },
  'persona-manage': { page: 'persona', personaTab: 'manage' },
};

let renderModeSyncLock = false;

function syncQuickRenderModeFromMain() {
  const main = document.getElementById('danmu_render_mode');
  const quick = document.getElementById('danmu_render_mode_quick');
  if (!main || !quick) return;
  renderModeSyncLock = true;
  quick.value = main.value;
  quick.disabled = main.disabled;
  quick.classList.toggle('opacity-60', main.disabled);
  quick.classList.toggle('cursor-not-allowed', main.disabled);
  renderModeSyncLock = false;
}

function syncMainRenderModeFromQuick() {
  const main = document.getElementById('danmu_render_mode');
  const quick = document.getElementById('danmu_render_mode_quick');
  if (!main || !quick || main.disabled) return;
  if (main.value === quick.value) return;
  main.value = quick.value;
  main.dispatchEvent(new Event('change', { bubbles: true }));
}

function initRenderModeQuickSync() {
  const main = document.getElementById('danmu_render_mode');
  const quick = document.getElementById('danmu_render_mode_quick');
  if (!main || !quick) return;

  syncQuickRenderModeFromMain();

  main.addEventListener('change', () => {
    if (renderModeSyncLock) return;
    syncQuickRenderModeFromMain();
  });

  quick.addEventListener('change', () => {
    if (renderModeSyncLock) return;
    syncMainRenderModeFromQuick();
    syncQuickRenderModeFromMain();
  });

  document.addEventListener('danmu:config-filled', syncQuickRenderModeFromMain);
}

function activatePetTab(tabId) {
  document.getElementById(`petTabBtn-${tabId}`)?.click();
}

function activatePersonaTab(tabId) {
  document.getElementById(`personaTabBtn-${tabId}`)?.click();
}

function handleQuickNav(key, { navigate, switchSettingsTab }) {
  const target = QUICK_NAV_MAP[key];
  if (!target) return;

  if (target.page === 'settings' && target.settingsTab) {
    navigate('settings');
    switchSettingsTab(target.settingsTab);
    return;
  }

  navigate(target.page);

  if (target.petTab) {
    activatePetTab(target.petTab);
    return;
  }

  if (target.personaTab) {
    activatePersonaTab(target.personaTab);
  }
}

export function initOverviewQuickSettings({ navigate, switchSettingsTab }) {
  const grid = document.getElementById('overviewQuickSettingsGrid');
  if (!grid) return;

  grid.addEventListener('click', (event) => {
    const button = event.target.closest('[data-quick-nav]');
    if (!button || button.disabled) return;
    handleQuickNav(button.dataset.quickNav, { navigate, switchSettingsTab });
  });

  initRenderModeQuickSync();
}
