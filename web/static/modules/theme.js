/**
 * 模块：theme — 温馨 ↔ 黑夜主题切换（localStorage 即时生效 + config.db 同步）。
 *
 * 关键路径：
 *   - localStorage[THEME_STORAGE_KEY] = 'light' | 'dark'（主源；首屏闪屏预防由
 *     index.html 内联 early script 在 <link> 之前读 localStorage 设置
 *     data-theme 属性，避免 FOUC）
 *   - normalizeTheme() 容错：非 'dark' 全部归一为 'light'
 *   - initTheme() 由 app.js init() 第一步调用，避免首屏闪烁
 *   - 主题选择也经 PUT /api/config 写入 config.db（控制台与本机偏好同步）
 *
 * 不变量：data-theme 属性挂在 <html> 元素；CSS 通过 [data-theme="dark"] 选择器
 * 覆盖浅色 token（见 warm-tokens.css）。
 */

import { API, apiFetch, authHeaders } from './transport.js';

export const THEME_STORAGE_KEY = 'danmu_console_theme';

export function normalizeTheme(value) {
  return value === 'dark' ? 'dark' : 'light';
}

export function getStoredTheme() {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return normalizeTheme(value);
  } catch {
    return 'light';
  }
}

function storeThemeLocal(theme) {
  const normalized = normalizeTheme(theme);
  try {
    localStorage.setItem(THEME_STORAGE_KEY, normalized);
  } catch {
    /* ignore quota / private mode */
  }
  return normalized;
}

export function applyTheme(theme) {
  const normalized = normalizeTheme(theme);
  const root = document.documentElement;
  if (normalized === 'dark') {
    root.setAttribute('data-theme', 'dark');
  } else {
    root.removeAttribute('data-theme');
  }

  const btn = document.getElementById('themeToggle');
  if (btn) {
    const isDark = normalized === 'dark';
    btn.setAttribute('aria-pressed', isDark ? 'true' : 'false');
    btn.setAttribute('aria-label', isDark ? '切换浅色模式' : '切换黑夜模式');
    const label = btn.querySelector('.theme-toggle-label');
    if (label) {
      label.textContent = isDark ? '浅色模式' : '黑夜模式';
    }
  }
  return normalized;
}

async function syncThemeFromServer() {
  try {
    const body = await apiFetch('/api/console-theme');
    const serverTheme = normalizeTheme(body?.theme);
    const localTheme = getStoredTheme();
    if (serverTheme !== localTheme) {
      storeThemeLocal(serverTheme);
      applyTheme(serverTheme);
    }
  } catch (e) {
    console.warn('[theme] sync from server failed', e);
  }
}

async function persistThemeToServer(theme) {
  try {
    await fetch(`${API.base}/api/console-theme`, {
      method: 'PUT',
      headers: authHeaders(),
      body: JSON.stringify({ theme }),
    });
  } catch (e) {
    console.warn('[theme] persist to server failed', e);
  }
}

function toggleTheme() {
  const next = getStoredTheme() === 'dark' ? 'light' : 'dark';
  storeThemeLocal(next);
  applyTheme(next);
  persistThemeToServer(next);
}

export function initTheme() {
  applyTheme(getStoredTheme());
  document.getElementById('themeToggle')?.addEventListener('click', toggleTheme);
  syncThemeFromServer();
}
