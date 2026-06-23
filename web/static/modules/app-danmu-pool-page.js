import { apiFetch } from './transport.js';

const MAX_IMPORT_FILES = 5;
const MAX_LINES_PER_FILE = 1000;
const PAGE_SIZE = 100;

let danmuPoolMeta = null;
let currentPage = 1;
let listTotal = 0;
let searchQuery = '';
let searchTimer = null;
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

function formatCustomPoolCount() {
  const total = danmuPoolMeta?.custom_count ?? 0;
  const max = danmuPoolMeta?.custom_max ?? 20000;
  const manual = danmuPoolMeta?.manual_count;
  const base = `自定义库：${total} / ${max}`;
  return manual != null ? `${base}（手动 ${manual} 条）` : base;
}

function updatePoolCustomPager() {
  const pageInfo = document.getElementById('poolCustomPageInfo');
  const prevBtn = document.getElementById('btnPoolCustomPrev');
  const nextBtn = document.getElementById('btnPoolCustomNext');
  const totalPages = Math.max(1, Math.ceil(listTotal / PAGE_SIZE));
  if (pageInfo) {
    pageInfo.textContent = `第 ${currentPage} / ${totalPages} 页（本页最多 ${PAGE_SIZE} 条）`;
  }
  if (prevBtn) prevBtn.disabled = currentPage <= 1;
  if (nextBtn) nextBtn.disabled = currentPage >= totalPages;
}

function renderCustomDanmuPoolList(payload) {
  const items = payload?.items || [];
  listTotal = payload?.total ?? items.length;
  currentPage = payload?.page ?? currentPage;

  const list = document.getElementById('poolCustomList');
  const countEl = document.getElementById('poolCustomCount');
  if (countEl) countEl.textContent = formatCustomPoolCount();
  if (!list) return;
  list.replaceChildren();
  items.forEach((entry) => {
    const text = typeof entry === 'string' ? entry : entry.text;
    const id = typeof entry === 'object' && entry != null ? entry.id : null;
    const li = document.createElement('li');
    li.className = 'danmu-pool-custom-item';
    const label = document.createElement('label');
    label.className = 'flex items-start gap-2 text-warmText';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.className = 'pool-custom-cb accent-warmPink mt-1';
    if (id != null) cb.dataset.id = String(id);
    const span = document.createElement('span');
    span.textContent = text;
    label.append(cb, span);
    li.append(label);
    list.append(li);
  });
  const selectAll = document.getElementById('poolCustomSelectAll');
  if (selectAll) selectAll.checked = false;
  updatePoolCustomPager();
}

async function fetchCustomPage(page = currentPage, search = searchQuery) {
  const params = new URLSearchParams({
    page: String(page),
    page_size: String(PAGE_SIZE),
    source: 'manual',
  });
  if (search.trim()) params.set('search', search.trim());
  return apiFetch(`/api/danmu-pool/custom?${params.toString()}`);
}

async function loadCustomPage(page = currentPage) {
  const payload = await fetchCustomPage(page, searchQuery);
  renderCustomDanmuPoolList(payload);
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

function buildImportSkippedHint(result) {
  const reasonLabels = {
    duplicate: '重复',
    empty: '空行',
    limit_reached: '超限',
    unsafe: '不安全',
  };
  const counts = {};
  const skippedItems = result?.skipped_items || [];
  skippedItems.forEach((item) => {
    const label = reasonLabels[item.reason] || item.reason;
    counts[label] = (counts[label] || 0) + 1;
  });
  if (result?.skipped_duplicate) counts['重复'] = (counts['重复'] || 0) + result.skipped_duplicate;
  if (result?.skipped_empty) counts['空行'] = (counts['空行'] || 0) + result.skipped_empty;
  if (result?.skipped_unsafe) counts['不安全'] = (counts['不安全'] || 0) + result.skipped_unsafe;
  if (result?.skipped_limit) counts['超限'] = (counts['超限'] || 0) + result.skipped_limit;
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
      body: JSON.stringify({ text: combinedText, source: 'import' }),
    });

    danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');
    const countEl = document.getElementById('poolCustomCount');
    if (countEl) countEl.textContent = formatCustomPoolCount();

    const added = result.added || 0;
    const skipped = result.skipped || 0;
    const skipHint = buildImportSkippedHint(result);
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
  danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');
  const customEl = document.getElementById('poolCustomEnabled');
  const minEl = document.getElementById('poolMinOnScreen');
  if (customEl) customEl.checked = Boolean(danmuPoolMeta.custom_enabled);
  if (minEl) minEl.value = String(danmuPoolMeta.min_on_screen ?? 5);
  currentPage = 1;
  searchQuery = '';
  const searchEl = document.getElementById('poolCustomSearch');
  if (searchEl) searchEl.value = '';
  await loadCustomPage(1);
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
  await apiFetch('/api/danmu-pool/custom', {
    method: 'POST',
    body: JSON.stringify({ text, source: 'manual' }),
  });
  danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');
  if (textarea) textarea.value = '';
  currentPage = 1;
  await loadCustomPage(1);
  showToast('已追加手动条目');
}

async function deleteSelectedCustomDanmuPoolItems() {
  const ids = [...document.querySelectorAll('#poolCustomList .pool-custom-cb:checked')]
    .map((cb) => parseInt(cb.dataset.id, 10))
    .filter((id) => Number.isFinite(id) && id > 0);
  if (!ids.length) {
    showToast('请先勾选要删除的句子', true);
    return;
  }
  const result = await apiFetch('/api/danmu-pool/custom', {
    method: 'DELETE',
    body: JSON.stringify({ ids }),
  });
  danmuPoolMeta = await apiFetch('/api/danmu-pool/meta');
  const totalPages = Math.max(1, Math.ceil((danmuPoolMeta.custom_count || 0) / PAGE_SIZE));
  if (currentPage > totalPages) currentPage = totalPages;
  await loadCustomPage(currentPage);
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
  document.getElementById('btnPoolCustomPrev')?.addEventListener('click', () => {
    if (currentPage <= 1) return;
    currentPage -= 1;
    loadCustomPage(currentPage).catch((error) => showToast(error.message, true));
  });
  document.getElementById('btnPoolCustomNext')?.addEventListener('click', () => {
    const totalPages = Math.max(1, Math.ceil(listTotal / PAGE_SIZE));
    if (currentPage >= totalPages) return;
    currentPage += 1;
    loadCustomPage(currentPage).catch((error) => showToast(error.message, true));
  });
  document.getElementById('poolCustomSearch')?.addEventListener('input', (event) => {
    searchQuery = event.target.value || '';
    if (searchTimer) clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      currentPage = 1;
      loadCustomPage(1).catch((error) => showToast(error.message, true));
    }, 300);
  });
}
