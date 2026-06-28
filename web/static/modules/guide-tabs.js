/**
 * 教程与弹幕日志页的 Tab 切换。
 *
 * - 与 `modules/settings-tabs.js` 同样的模式：`hidden` + `.active` + `aria-selected`，
 *   默认 Tab 缓存在模块级变量 `activeGuideTabId` 中（不持久化，与设置 Tab 一致）。
 * - 把 `#page-tutorial` / `#page-logs` 两个源 `<section>` 内部的 `<header>` + `<div class="card">`
 *   （`[data-guide-move]`）搬到 `#page-guide` 下对应的 `#guideTab-tutorial` / `#guideTab-logs` 容器，
 *   再把源 `<section>` 隐藏并移除 `.active`。这样既复用了既有 DOM id（`#logView`、
 *   `#tutorialVideoLink` 等），又把它们"折叠"进了 `#page-guide` 的两个 Tab Panel。
 */

let activeGuideTabId = 'tutorial';
let switchDeps = {
  onGuideTabSwitch: null,
};

export function getActiveGuideTabId() {
  return activeGuideTabId;
}

export function configureGuideTabs(deps) {
  switchDeps = { ...switchDeps, ...deps };
}

export function switchGuideTab(tabId) {
  activeGuideTabId = tabId;
  document.querySelectorAll('[data-guide-tab]').forEach((tab) => {
    const active = tab.dataset.guideTab === tabId;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-guide-panel]').forEach((panel) => {
    const isTarget = panel.dataset.guidePanel === tabId;
    panel.classList.toggle('active', isTarget);
    panel.hidden = !isTarget;
  });
  switchDeps.onGuideTabSwitch?.(tabId);
}

export function initGuideTabs() {
  // 1. 移动 DOM：把源 section 的 header + card 节点搬到 #page-guide 的对应 panel 容器里。
  document.querySelectorAll('[data-guide-move]').forEach((src) => {
    const target = document.getElementById(`guideTab-${src.dataset.guideMove}`);
    if (target) target.appendChild(src);
  });
  // 2. 隐藏源 section（#page-tutorial / #page-logs）：它们仍存在以保留内部 id，
  //    但 `.active` 必须移除，否则 navigate('guide') 与源面板之间会出现竞争。
  document.querySelectorAll('[data-guide-panel$="-source"]').forEach((el) => {
    el.classList.remove('active');
    el.hidden = true;
  });
  // 3. 绑定 Tab 按钮。
  document.querySelectorAll('[data-guide-tab]').forEach((tab) => {
    tab.addEventListener('click', () => switchGuideTab(tab.dataset.guideTab));
  });
  // 4. 初始化默认 Tab。
  switchGuideTab(activeGuideTabId);
}