import { apiFetch } from './transport.js';

const MAX_IMPORT_FILES = 5;
const MAX_LINES_PER_FILE = 1000;

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

function formatCustomPoolCount(length) {
  const max = danmuPoolMeta?.custom_max;
  return max != null ? `共 ${length} / ${max} 条` : `共 ${length} 条`;
}

function renderCustomDanmuPoolList(items) {
  const list = document.getElementById('poolCustomList');
  const countEl = document.getElementById('poolCustomCount');
  if (countEl) countEl.textContent = formatCustomPoolCount(items.length);
  if (!list) return;
  list.replaceChildren();
  items.forEach((text) => {
    const li = document.createElement('li');
    li.className = 'danmu-pool-custom-item';
    const label = document.createElement('label');
    label.className = 'flex items-start gap-2 text-warmText';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'pool-custom-cb accent-warmPink mt-1';
    const span = document.createElement('span');
    span.textContent = text;
    label.append(cb, span);
    li.append(label);
    list.append(li);
  });
  const selectAll = document.getElementById('poolCustomSelectAll');
  if (selectAll) selectAll.checked = false;
}

function readFileAsText(file, encoding) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ''));
    reader.onerror = () => reject(reader.error || new Error('文件读取失败'));
    reader.readAsText(file, encoding);
  });
}

async function readPoolTxtFile(file) {
  const utf8Text = await readFileAsText(file, 'utf-8');
  if (!utf8Text.includes('\uFFFD')) {
    return { text: utf8Text, encodingFallback: false, hasReplacement: false };
  }
  const gbkText = await readFileAsText(file, 'gbk');
  return {
    text: gbkText,
    encodingFallback: true,
    hasReplacement: gbkText.includes('\uFFFD'),
  };
}

function countFileLines(text) {
  if (!text) return 0;
  return text.split(/\r?\n/).length;
}

function buildImportSkippedHint(skippedItems) {
  if (!skippedItems?.length) return '';
  const reasonLabels = {
    duplicate: '重复',
    empty: '空行',
    limit_reached: '超限',
    unsafe: '不安全',
  };
  const counts = {};
  skippedItems.forEach((item) => {
    const label = reasonLabels[item.reason] || item.reason;
    counts[label] = (counts[label] || 0) + 1;
  });
  const parts = Object.entries(counts).map(([label, n]) => `${label} ${n}`);
  return parts.length ? `（${parts.join('，')}）` : '';
}

async function importCustomDanmuPoolTxtFiles(fileList) {
  const files = [...(fileList || [])];
  const btn = document.getElementById('btnPoolImportTxt');
  const input = document.getElementById('poolImportTxtInput');

  if (!files.length) return;

  if (files.length > MAX_IMPORT_FILES) {
    showToast('最多同时导入 5 个文件', true);
    if (input) input.value = '';
    return;
  }

  if (btn) btn.disabled = true;

  try {
    const readResults = await Promise.all(files.map((file) => readPoolTxtFile(file)));

    for (let i = 0; i < files.length; i += 1) {
      const lineCount = countFileLines(readResults[i].text);
      if (lineCount > MAX_LINES_PER_FILE) {
        showToast(`文件「${files[i].name}」超过 ${MAX_LINES_PER_FILE} 行上限`, true);
        return;
      }
    }

    const combinedText = readResults.map((r) => r.text).join('\n');
    const result = await apiFetch('/api/danmu-pool/custom', {
      method: 'POST',
      body: JSON.stringify({ text: combinedText }),
    });

    renderCustomDanmuPoolList(result.items || []);
    danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');

    const added = result.added || 0;
    const skipped = result.skipped || 0;
    const skipHint = buildImportSkippedHint(result.skipped_items);
    let message = `导入成功，新增 ${added} 条，跳过 ${skipped} 条${skipHint}`;
    if (readResults.some((r) => r.hasReplacement)) {
      message += '；部分字符无法识别';
    }
    showToast(message, skipped > 0 && !added);
  } catch (error) {
    showToast(error.message || '导入失败', true);
  } finally {
    if (btn) btn.disabled = false;
    if (input) input.value = '';
  }
}

export async function loadDanmuPoolPage() {
  const [meta, custom] = await Promise.all([
    apiFetch('/api/danmu-pool/meta'),
    apiFetch('/api/danmu-pool/custom'),
  ]);
  danmuPoolMeta = meta;
  const customEl = document.getElementById('poolCustomEnabled');
  const minEl = document.getElementById('poolMinOnScreen');
  if (customEl) customEl.checked = Boolean(meta.custom_enabled);
  if (minEl) minEl.value = String(meta.min_on_screen ?? 5);
  renderCustomDanmuPoolList(custom.items || []);
  updatePoolMinOnScreenControl();
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
  showToast('公式化弹幕库设置已保存');
}

async function addCustomDanmuPoolItems() {
  const textarea = document.getElementById('poolCustomTextarea');
  const text = textarea?.value || '';
  if (!text.trim()) {
    showToast('请先输入要追加的弹幕句子', true);
    return;
  }
  const result = await apiFetch('/api/danmu-pool/custom', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
  renderCustomDanmuPoolList(result.items || []);
  danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');
  if (textarea) textarea.value = '';
  const skipped = result.skipped || 0;
  if (skipped > 0) {
    showToast(`已追加 ${result.added} 条，跳过 ${skipped} 条`, skipped > 0 && !result.added);
  } else {
    showToast(`已追加 ${result.added} 条`);
  }
}

async function deleteSelectedCustomDanmuPoolItems() {
  const texts = [...document.querySelectorAll('#poolCustomList .pool-custom-cb:checked')]
    .map((cb) => cb.closest('label')?.querySelector('span')?.textContent)
    .filter(Boolean);
  if (!texts.length) {
    showToast('请先勾选要删除的句子', true);
    return;
  }
  const result = await apiFetch('/api/danmu-pool/custom', {
    method: 'DELETE',
    body: JSON.stringify({ texts }),
  });
  renderCustomDanmuPoolList(result.items || []);
  danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');
  showToast(`已删除 ${result.removed} 条`);
}

export function initDanmuPoolPage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;

  document.getElementById('btnSavePoolSettings')?.addEventListener('click', () => {
    saveDanmuPoolSettings().catch((error) => showToast(error.message, true));
  });
  document.getElementById('btnPoolCustomAppend')?.addEventListener('click', () => {
    addCustomDanmuPoolItems().catch((error) => showToast(error.message, true));
  });
  document.getElementById('btnPoolCustomClearInput')?.addEventListener('click', () => {
    const textarea = document.getElementById('poolCustomTextarea');
    if (textarea) textarea.value = '';
  });
  document.getElementById('btnPoolCustomDelete')?.addEventListener('click', () => {
    deleteSelectedCustomDanmuPoolItems().catch((error) => showToast(error.message, true));
  });
  document.getElementById('poolCustomSelectAll')?.addEventListener('change', (event) => {
    const checked = event.target.checked;
    document.querySelectorAll('#poolCustomList .pool-custom-cb').forEach((cb) => {
      cb.checked = checked;
    });
  });
  document.getElementById('poolCustomEnabled')?.addEventListener('change', () => {
    if (danmuPoolMeta) {
      danmuPoolMeta.effective_pool_enabled = poolEffectiveEnabledLocal();
    }
    updatePoolMinOnScreenControl();
  });
  document.getElementById('btnPoolImportTxt')?.addEventListener('click', () => {
    document.getElementById('poolImportTxtInput')?.click();
  });
  document.getElementById('poolImportTxtInput')?.addEventListener('change', (event) => {
    importCustomDanmuPoolTxtFiles(event.target.files).catch((error) =>
      showToast(error.message || '导入失败', true),
    );
  });
}
