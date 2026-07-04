import { apiFetch } from './transport.js';
import { t } from './i18n.js';

const MAX_SELECTED_MEME_TAGS = 3;

let memeBarrageMeta = null;
let memeTags = [];
let selectedTags = new Set(['06']);
let toast = () => {};
let handlersBound = false;
let metaPollTimer = null;

function showToast(message, isError = false) {
  toast(message, isError);
}

function normalizeSelectedTags(tags) {
  const values = Array.from(tags).map((t) => String(t).trim()).filter(Boolean);
  const capped = values.slice(0, MAX_SELECTED_MEME_TAGS);
  return new Set(capped.length ? capped : ['06']);
}

function getSelectedCategory() {
  return document.querySelector('input[name="memeCategory"]:checked')?.value || 'random';
}

function getSelectedDisplayMode() {
  return document.querySelector('input[name="memeDisplayMode"]:checked')?.value || 'full';
}

function syncMemeTagButtonStates(grid) {
  const tagged = getSelectedCategory() === 'tagged';
  const atMax = selectedTags.size >= MAX_SELECTED_MEME_TAGS;
  grid.querySelectorAll('.meme-tag-btn').forEach((btn) => {
    const value = btn.dataset.tagValue;
    const active = selectedTags.has(value);
    btn.classList.toggle('active', active);
    const blocked = tagged && atMax && !active;
    btn.disabled = !tagged || blocked;
    btn.classList.toggle('at-limit', blocked);
  });
}

function updateMemeTagGridState() {
  const tagged = getSelectedCategory() === 'tagged';
  const grid = document.getElementById('memeTagGrid');
  if (grid) {
    grid.classList.toggle('is-disabled', !tagged);
    if (tagged) {
      syncMemeTagButtonStates(grid);
    } else {
      grid.querySelectorAll('.meme-tag-btn').forEach((btn) => {
        btn.disabled = true;
        btn.classList.remove('at-limit');
      });
    }
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
    if (selectedTags.has(tag.value)) {
      btn.classList.add('active');
    }
    btn.addEventListener('click', () => {
      if (getSelectedCategory() !== 'tagged') return;
      if (selectedTags.has(tag.value)) {
        if (selectedTags.size <= 1) return;
        selectedTags.delete(tag.value);
      } else {
        if (selectedTags.size >= MAX_SELECTED_MEME_TAGS) {
          showToast(t('dynamic.appMemeBarragePage.最多只能选择_MAX_SELECTED_ME'), true);
          return;
        }
        selectedTags.add(tag.value);
      }
      syncMemeTagButtonStates(grid);
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
  if (Array.isArray(meta.tag) && meta.tag.length > 0) {
    selectedTags = normalizeSelectedTags(new Set(meta.tag.map((t) => String(t))));
  } else if (Array.isArray(meta.tag)) {
    // 数组但为空：保留当前选择，避免误清空
  } else {
    selectedTags = new Set(['06']);
  }
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
    tag: Array.from(normalizeSelectedTags(selectedTags)),
    display_mode: getSelectedDisplayMode(),
    collect_interval_sec: parseInt(document.getElementById('memeCollectInterval')?.value, 10) || 5,
    collect_batch_size: parseInt(document.getElementById('memeCollectBatch')?.value, 10) || 2,
    display_interval_sec: parseInt(document.getElementById('memeDisplayInterval')?.value, 10) || 5,
    display_batch_size: parseInt(document.getElementById('memeDisplayBatch')?.value, 10) || 2,
  };
  const meta = await apiFetch('/api/meme-barrage/settings', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  applyMemeMetaToForm(meta);
  showToast(t('dynamic.appMemeBarragePage.烂梗公式化设置已保存'));
}

async function clearMemeBarrageLibrary() {
  const result = await apiFetch('/api/meme-barrage/clear', { method: 'POST' });
  applyMemeMetaToForm({
    ...memeBarrageMeta,
    library_count: result.library_count ?? 0,
    display_queue_size: result.display_queue_size ?? 0,
  });
  showToast(t('dynamic.appMemeBarragePage.本地库与待展示队列已清除'));
}

export function startMemeBarrageMetaPolling() {
  if (metaPollTimer) return;
  metaPollTimer = window.setInterval(() => {
    refreshMemeMeta().catch((error) => {
      console.warn('refreshMemeMeta failed', error);
    });
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
