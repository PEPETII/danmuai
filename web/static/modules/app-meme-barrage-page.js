import { apiFetch } from './transport.js';

let memeBarrageMeta = null;
let memeTags = [];
let selectedTag = '06';
let toast = () => {};
let handlersBound = false;
let metaPollTimer = null;

function showToast(message, isError = false) {
  toast(message, isError);
}

function getSelectedCategory() {
  return document.querySelector('input[name="memeCategory"]:checked')?.value || 'random';
}

function getSelectedDisplayMode() {
  return document.querySelector('input[name="memeDisplayMode"]:checked')?.value || 'full';
}

function updateMemeTagGridState() {
  const tagged = getSelectedCategory() === 'tagged';
  const grid = document.getElementById('memeTagGrid');
  if (grid) {
    grid.classList.toggle('is-disabled', !tagged);
    grid.querySelectorAll('.meme-tag-btn').forEach((btn) => {
      btn.disabled = !tagged;
    });
  }
  document.querySelectorAll('.meme-category-group input').forEach((input) => {
    input.disabled = false;
  });
}

function renderMemeTagGrid(tags) {
  const grid = document.getElementById('memeTagGrid');
  if (!grid) return;
  grid.replaceChildren();
  tags.forEach((tag) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'meme-tag-btn';
    btn.dataset.tagValue = tag.value;
    btn.textContent = tag.label || tag.value;
    if (tag.value === selectedTag) {
      btn.classList.add('active');
    }
    btn.addEventListener('click', () => {
      if (getSelectedCategory() !== 'tagged') return;
      selectedTag = tag.value;
      grid.querySelectorAll('.meme-tag-btn').forEach((el) => {
        el.classList.toggle('active', el.dataset.tagValue === selectedTag);
      });
    });
    grid.append(btn);
  });
  updateMemeTagGridState();
}

function renderMemeCounts(meta) {
  const count = meta?.library_count ?? 0;
  const queue = meta?.display_queue_size ?? 0;
  const libEl = document.getElementById('memeLibraryCount');
  const queueEl = document.getElementById('memeQueueCount');
  const inlineEl = document.getElementById('memeLocalCountInline');
  if (libEl) libEl.textContent = String(count);
  if (queueEl) queueEl.textContent = String(queue);
  if (inlineEl) inlineEl.textContent = `【${count}】`;
}

function applyMemeMetaToForm(meta, { formFields = true } = {}) {
  memeBarrageMeta = meta;
  if (!formFields) {
    renderMemeCounts(meta);
    return;
  }
  const enabledEl = document.getElementById('memeBarrageEnabled');
  if (enabledEl) enabledEl.checked = Boolean(meta.enabled);
  document.querySelectorAll('input[name="memeCategory"]').forEach((input) => {
    input.checked = input.value === meta.category;
  });
  document.querySelectorAll('input[name="memeDisplayMode"]').forEach((input) => {
    input.checked = input.value === meta.display_mode;
  });
  selectedTag = meta.tag || selectedTag;
  const collectInterval = document.getElementById('memeCollectInterval');
  const collectBatch = document.getElementById('memeCollectBatch');
  const displayInterval = document.getElementById('memeDisplayInterval');
  const displayBatch = document.getElementById('memeDisplayBatch');
  if (collectInterval) collectInterval.value = String(meta.collect_interval_sec ?? 5);
  if (collectBatch) collectBatch.value = String(meta.collect_batch_size ?? 40);
  if (displayInterval) displayInterval.value = String(meta.display_interval_sec ?? 5);
  if (displayBatch) displayBatch.value = String(meta.display_batch_size ?? 20);
  renderMemeTagGrid(memeTags);
  renderMemeCounts(meta);
  updateMemeTagGridState();
}

export function switchDanmuPoolTab(tabId) {
  document.querySelectorAll('[data-danmu-pool-tab]').forEach((tab) => {
    const active = tab.dataset.danmuPoolTab === tabId;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  document.querySelectorAll('[data-danmu-pool-panel]').forEach((panel) => {
    const active = panel.dataset.danmuPoolPanel === tabId;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
}

export async function loadMemeBarragePage() {
  const [meta, tagResp] = await Promise.all([
    apiFetch('/api/meme-barrage/meta'),
    apiFetch('/api/meme-barrage/tags'),
  ]);
  memeTags = tagResp.tags || [];
  applyMemeMetaToForm(meta);
}

async function refreshMemeMeta() {
  const meta = await apiFetch('/api/meme-barrage/meta');
  applyMemeMetaToForm(meta, { formFields: false });
  return meta;
}

async function saveMemeBarrageSettings() {
  const body = {
    enabled: Boolean(document.getElementById('memeBarrageEnabled')?.checked),
    category: getSelectedCategory(),
    tag: selectedTag,
    display_mode: getSelectedDisplayMode(),
    collect_interval_sec: parseInt(document.getElementById('memeCollectInterval')?.value, 10) || 5,
    collect_batch_size: parseInt(document.getElementById('memeCollectBatch')?.value, 10) || 40,
    display_interval_sec: parseInt(document.getElementById('memeDisplayInterval')?.value, 10) || 5,
    display_batch_size: parseInt(document.getElementById('memeDisplayBatch')?.value, 10) || 20,
  };
  const meta = await apiFetch('/api/meme-barrage/settings', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  applyMemeMetaToForm(meta);
  showToast('烂梗公式化设置已保存');
}

async function clearMemeBarrageLibrary() {
  const result = await apiFetch('/api/meme-barrage/clear', { method: 'POST' });
  applyMemeMetaToForm({
    ...memeBarrageMeta,
    library_count: result.library_count ?? 0,
    display_queue_size: result.display_queue_size ?? 0,
  });
  showToast('本地库与待展示队列已清除');
}

export function startMemeBarrageMetaPolling() {
  if (metaPollTimer) return;
  metaPollTimer = window.setInterval(() => {
    if (!document.getElementById('page-danmu-pool')?.classList.contains('active')) return;
    refreshMemeMeta().catch(() => {});
  }, 3000);
}

export function stopMemeBarrageMetaPolling() {
  if (!metaPollTimer) return;
  window.clearInterval(metaPollTimer);
  metaPollTimer = null;
}

export function initMemeBarragePage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;

  document.querySelectorAll('[data-danmu-pool-tab]').forEach((tab) => {
    tab.addEventListener('click', (event) => {
      event.stopPropagation();
      switchDanmuPoolTab(tab.dataset.danmuPoolTab);
    });
  });

  document.querySelectorAll('input[name="memeCategory"]').forEach((input) => {
    input.addEventListener('change', () => updateMemeTagGridState());
  });

  document.getElementById('btnSaveMemeBarrageSettings')?.addEventListener('click', () => {
    saveMemeBarrageSettings().catch((error) => showToast(error.message, true));
  });

  document.getElementById('btnMemeBarrageClear')?.addEventListener('click', () => {
    clearMemeBarrageLibrary().catch((error) => showToast(error.message, true));
  });
}
