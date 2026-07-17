/**
 * 直播设置页的 Tab 切换 + DOM 搬移。
 *
 * 模式与 guide-tabs.js 一致：
 * - `data-live-settings-move` 的元素搬到 `#liveSettingsTab-{value}` 容器
 * - `data-live-settings-panel$="-source"` 的源 section 隐藏
 * - `data-live-settings-tab` 的 Tab 按钮绑定切换
 */

let activeLiveSettingsTabId = 'live-output';

export function getActiveLiveSettingsTabId() {
  return activeLiveSettingsTabId;
}

export function configureLiveSettingsTabs(deps) {
  // reserved for future toast / deps wiring
  void deps;
}

export function switchLiveSettingsTab(tabId) {
  activeLiveSettingsTabId = tabId;
  document.querySelectorAll('[data-live-settings-tab]').forEach((tab) => {
    const active = tab.dataset.liveSettingsTab === tabId;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-live-settings-panel]').forEach((panel) => {
    const isTarget = panel.dataset.liveSettingsPanel === tabId;
    panel.classList.toggle('active', isTarget);
    panel.hidden = !isTarget;
  });
}

export function initLiveSettingsTabs() {
  // 1. DOM 搬移
  document.querySelectorAll('[data-live-settings-move]').forEach((src) => {
    const target = document.getElementById(`liveSettingsTab-${src.dataset.liveSettingsMove}`);
    if (target) target.appendChild(src);
  });
  // 2. 隐藏源 section
  document.querySelectorAll('[data-live-settings-panel$="-source"]').forEach((el) => {
    el.classList.remove('active');
    el.hidden = true;
  });
  // 3. 绑定 Tab 按钮
  document.querySelectorAll('[data-live-settings-tab]').forEach((tab) => {
    tab.addEventListener('click', () => switchLiveSettingsTab(tab.dataset.liveSettingsTab));
  });
  // 4. 初始化默认 Tab
  switchLiveSettingsTab(activeLiveSettingsTabId);
}
