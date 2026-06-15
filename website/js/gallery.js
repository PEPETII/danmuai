/**
 * DanmuAI 官网 — 截图画廊 Tab 切换
 */

function initGallery() {
  var tabs = document.querySelectorAll('.gallery-tab');
  var placeholders = document.querySelectorAll('.laptop-placeholder');

  if (!tabs.length || !placeholders.length) return;

  function switchTab(targetId) {
    tabs.forEach(function (tab) {
      tab.classList.toggle('active', tab.getAttribute('data-target') === targetId);
    });
    placeholders.forEach(function (ph) {
      ph.classList.toggle('active', ph.id === targetId);
    });
  }

  tabs.forEach(function (tab) {
    tab.addEventListener('click', function () {
      switchTab(this.getAttribute('data-target'));
    });
  });

  // Ensure first tab is active
  var firstTab = tabs[0];
  if (firstTab && !document.querySelector('.gallery-tab.active')) {
    switchTab(firstTab.getAttribute('data-target'));
  }
}

document.addEventListener('DOMContentLoaded', initGallery);
