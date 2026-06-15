/**
 * DanmuAI 官网 — 主题切换
 * 参考 web/static/modules/theme.js 简化版
 */

const STORAGE_KEY = 'danmuai_site_theme';

function getStoredTheme() {
  try {
    return localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function applyTheme(theme) {
  if (theme === 'dark') {
    document.documentElement.setAttribute('data-theme', 'dark');
  } else {
    document.documentElement.removeAttribute('data-theme');
  }
}

function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') === 'dark'
    ? 'dark'
    : 'light';
  const next = current === 'dark' ? 'light' : 'dark';
  applyTheme(next);
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch { /* ignore */ }
  updateToggleAria(next);
}

function updateToggleAria(theme) {
  document.querySelectorAll('.theme-toggle').forEach(function (btn) {
    btn.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
    btn.setAttribute('aria-label', theme === 'dark' ? '切换到浅色模式' : '切换到深色模式');
  });
}

function initTheme() {
  var stored = getStoredTheme();
  if (stored) {
    applyTheme(stored);
  }
  updateToggleAria(stored || 'light');

  document.querySelectorAll('.theme-toggle').forEach(function (btn) {
    btn.addEventListener('click', toggleTheme);
  });
}

document.addEventListener('DOMContentLoaded', initTheme);
