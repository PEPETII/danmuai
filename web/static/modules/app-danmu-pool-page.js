import { apiFetch } from './transport.js';
import { t } from './i18n.js';

let danmuPoolMeta = null;
let toast = () => {};
let handlersBound = false;

function showToast(message, isError = false) {
  toast(message, isError);
}

function poolEffectiveEnabledLocal() {
  return Boolean(document.getElementById('poolCustomEnabled')?.checked);
}

function updatePoolMinOnScreenControl() {
  const enabled = danmuPoolMeta?.effective_pool_enabled ?? poolEffectiveEnabledLocal();
  const minEl = document.getElementById('poolMinOnScreen');
  const wrap = document.getElementById('poolMinOnScreenWrap');
  if (minEl) minEl.disabled = !enabled;
  if (wrap) wrap.classList.toggle('is-disabled', !enabled);
  const hint = document.getElementById('poolBothOffHint');
  if (hint) hint.classList.toggle('hidden', Boolean(enabled));
}

function renderTxtPoolStatus(meta = danmuPoolMeta) {
  const fileCountEl = document.getElementById('poolTxtFileCount');
  const lineCountEl = document.getElementById('poolTxtLineCount');
  const dirEl = document.getElementById('poolTxtDir');
  const dirWrap = document.getElementById('poolTxtDirWrap');
  const listEl = document.getElementById('poolTxtFileList');
  if (!meta) return;

  if (fileCountEl) fileCountEl.textContent = String(meta.txt_file_count ?? 0);
  if (lineCountEl) lineCountEl.textContent = String(meta.txt_line_count ?? meta.custom_count ?? 0);
  const skipHint = document.getElementById('poolTxtSkipHint');
  if (skipHint) {
    const skippedUnsafe = meta.txt_skipped_unsafe ?? 0;
    const skippedEmpty = meta.txt_skipped_empty ?? 0;
    const skippedDuplicate = meta.txt_skipped_duplicate ?? 0;
    const skippedTotal = skippedUnsafe + skippedEmpty + skippedDuplicate;
    if (skippedTotal > 0) {
      skipHint.textContent = t('dynamic.appDanmuPoolPage.已跳过_skipped_total_行', {
        skippedTotal,
        skippedUnsafe,
        skippedEmpty,
        skippedDuplicate,
      });
      skipHint.classList.remove('hidden');
    } else {
      skipHint.textContent = '';
      skipHint.classList.add('hidden');
    }
  }
  if (dirEl && dirWrap) {
    const dir = meta.txt_dir || '';
    dirEl.textContent = dir;
    dirWrap.classList.toggle('hidden', !dir);
  }
  if (!listEl) return;

  const files = meta.txt_files || [];
  listEl.innerHTML = '';
  if (!files.length) {
    const empty = document.createElement('li');
    empty.textContent = t('dynamic.appDanmuPoolPage.暂无_TXT_句库文件');
    listEl.appendChild(empty);
    return;
  }
  files.forEach((file) => {
    const item = document.createElement('li');
    const lineCount = file.line_count ?? 0;
    const skippedUnsafe = file.skipped_unsafe ?? 0;
    let label = t('dynamic.appDanmuPoolPage.文件_file_name_共_line_count_条', {
      fileName: file.name || '',
      lineCount,
    });
    if (skippedUnsafe > 0) {
      label += t('dynamic.appDanmuPoolPage.跳过不安全_skipped_unsafe', { skippedUnsafe });
    }
    item.textContent = label;
    listEl.appendChild(item);
  });
}

export async function loadDanmuPoolPage() {
  danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');
  const customEl = document.getElementById('poolCustomEnabled');
  const minEl = document.getElementById('poolMinOnScreen');
  if (customEl) customEl.checked = Boolean(danmuPoolMeta.custom_enabled);
  if (minEl) minEl.value = String(danmuPoolMeta.min_on_screen ?? 5);
  updatePoolMinOnScreenControl();
  renderTxtPoolStatus();
}

async function saveDanmuPoolSettings() {
  const body = {
    custom_enabled: Boolean(document.getElementById('poolCustomEnabled')?.checked),
    min_on_screen: parseInt(document.getElementById('poolMinOnScreen')?.value, 10) || 0,
  };
  await apiFetch('/api/danmu-pool/settings', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');
  updatePoolMinOnScreenControl();
  renderTxtPoolStatus();
  showToast(t('dynamic.appDanmuPoolPage.公式化弹幕库设置已保存'));
}

async function refreshTxtPool() {
  const btn = document.getElementById('btnPoolRefreshTxt');
  if (btn) btn.disabled = true;
  try {
    const result = await apiFetch('/api/danmu-pool/custom/refresh', { method: 'POST' });
    danmuPoolMeta = { ...danmuPoolMeta, ...result };
    renderTxtPoolStatus();
    showToast(
      t('dynamic.appDanmuPoolPage.句库已刷新_共_txt_line_count_条', {
        lineCount: result.txt_line_count ?? 0,
      }),
    );
  } catch (error) {
    showToast(error.message || t('dynamic.appDanmuPoolPage.刷新句库失败'), true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function openTxtFolder() {
  const btn = document.getElementById('btnPoolOpenTxtFolder');
  if (btn) btn.disabled = true;
  try {
    const result = await apiFetch('/api/danmu-pool/custom/open-folder', { method: 'POST' });
    if (result?.txt_dir) {
      danmuPoolMeta = { ...danmuPoolMeta, txt_dir: result.txt_dir };
      renderTxtPoolStatus();
    }
  } catch (error) {
    showToast(error.message || t('dynamic.appDanmuPoolPage.打开文件夹失败'), true);
  } finally {
    if (btn) btn.disabled = false;
  }
}

export function initDanmuPoolPage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;

  document.getElementById('btnSavePoolSettings')?.addEventListener('click', () => {
    saveDanmuPoolSettings().catch((error) => showToast(error.message, true));
  });
  document.getElementById('poolCustomEnabled')?.addEventListener('change', () => {
    if (danmuPoolMeta) {
      danmuPoolMeta.effective_pool_enabled = poolEffectiveEnabledLocal();
    }
    updatePoolMinOnScreenControl();
  });
  document.getElementById('btnPoolRefreshTxt')?.addEventListener('click', () => {
    refreshTxtPool().catch((error) => showToast(error.message, true));
  });
  document.getElementById('btnPoolOpenTxtFolder')?.addEventListener('click', () => {
    openTxtFolder().catch((error) => showToast(error.message, true));
  });
}
