import { apiFetch } from './transport.js';
import { getLanguage, onLanguageChanged, t } from './i18n.js';

const MAX_SELECTED_MEME_TAGS = 3;
const DEFAULT_TAG = '06';

let memeBarrageMeta = null;
let memeTags = [];
let selectedTags = new Set([DEFAULT_TAG]);
let toast = () => {};
let handlersBound = false;
let metaPollTimer = null;
let languageLayoutListenerRegistered = false;

// 标签示例（说明用途，帮助用户判断标签主题；非真实弹幕内容，来自社区烂梗库 sb6657 的语义归纳）
const TAG_EXAMPLES = {
  '00': '这机器打得太下饭了',
  '01': '这选手今天纯纯梦游',
  '02': '老哥说得对，加一',
  '03': 'QUQU这波属实幽默',
  '05': '木柜子又来整活了',
  '06': '弹幕区直接群魔乱舞',
  '07': 'NiKo这枪法还是猛',
  '08': 'ropz安稳如老狗',
  '09': '两边粉丝又吵起来了',
  '10': 'Donk年轻人不讲武德',
  '11': '伟伟这操作看麻了',
  '12': 'Zywoo永远的稳健',
  '13': 'm0NESY这小子有点东西',
  '14': '祥子你坏事做尽',
  '15': 'device宝刀未老',
  '16': 'Twistzz这波太秀了',
  '17': 'DOTA梗还是那么抽象',
  '18': '爱音最好了（大声）',
  '19': '初华你别太爱了',
  '20': 'Falcons这阵容真敢想',
  '21': 's1mple还是那个神',
  '22': '这波操作直接封神',
  '23': '京介你冷静点',
  '24': 'HLTV榜单又闹笑话',
  '25': 'TS这队伍有点东西',
  '26': 'chopper指挥真清晰',
  '27': '🗿🗿🗿',
};

function showToast(message, isError = false) {
  toast(message, isError);
}

function $(id) {
  return document.getElementById(id);
}

function normalizeSelectedTags(tags) {
  const values = Array.from(tags).map((t) => String(t).trim()).filter(Boolean);
  const capped = values.slice(0, MAX_SELECTED_MEME_TAGS);
  return new Set(capped.length ? capped : [DEFAULT_TAG]);
}

function getSelectedCategory() {
  return document.querySelector('input[name="memeCategory"]:checked')?.value || 'random';
}

function getSelectedDisplayMode() {
  return document.querySelector('input[name="memeDisplayMode"]:checked')?.value || 'full';
}

function updateMasterLock() {
  const enabledEl = $('memeBarrageEnabled');
  const area = $('memeSettingsArea');
  if (enabledEl && area) {
    area.classList.toggle('is-locked', !enabledEl.checked);
  }
}

function syncCardSelected() {
  document.querySelectorAll('input[name="memeCategory"]').forEach((r) => {
    r.closest('.meme-opt-card')?.classList.toggle('is-selected', r.checked);
  });
  document.querySelectorAll('input[name="memeDisplayMode"]').forEach((r) => {
    r.closest('.meme-opt-card')?.classList.toggle('is-selected', r.checked);
  });
}

function updateMemeTagCount() {
  const el = $('memeTagCount');
  if (el) el.textContent = String(selectedTags.size);
}

// 标签 chip（带示例），按当前分类决定是否可点、是否达上限禁用
function renderMemeTagGrid(tags) {
  const grid = $('memeTagGrid');
  if (!grid) return;
  grid.replaceChildren();
  const tagged = getSelectedCategory() === 'tagged';
  const atMax = selectedTags.size >= MAX_SELECTED_MEME_TAGS;
  tags.forEach((tag) => {
    const value = tag.value;
    const label = tag.label || value;
    const example = TAG_EXAMPLES[value] || '';
    const sel = selectedTags.has(value);
    const disabled = !tagged || (atMax && !sel);
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'meme-tag-chip' + (sel ? ' active' : '') + (disabled ? ' is-disabled' : '');
    chip.dataset.tagValue = value;
    chip.setAttribute('aria-pressed', String(sel));
    chip.innerHTML =
      `<span class="name">${label}</span>` +
      (example ? `<span class="ex"><span class="tag">示例：</span>${example}</span>` : '');
    if (!disabled) {
      chip.addEventListener('click', () => {
        if (selectedTags.has(value)) {
          if (selectedTags.size > 1) selectedTags.delete(value);
        } else {
          if (selectedTags.size >= MAX_SELECTED_MEME_TAGS) {
            showToast(
              t('dynamic.appMemeBarragePage.最多只能选择_MAX_SELECTED_ME', { maxTags: MAX_SELECTED_MEME_TAGS }) ||
                `最多只能选择 ${MAX_SELECTED_MEME_TAGS} 个标签`,
              true,
            );
            return;
          }
          selectedTags.add(value);
        }
        renderMemeTagGrid(tags);
        updateMemeTagCount();
      });
    }
    grid.append(chip);
  });
  updateMemeTagCount();
}

// 分类切换：同步卡片选中态、显隐标签块/本地库提示，并重渲标签网格
function updateMemeCategoryView() {
  syncCardSelected();
  const cat = getSelectedCategory();
  $('memeTagBlock')?.classList.toggle('hidden', cat !== 'tagged');
  $('memeLocalHint')?.classList.toggle('hidden', cat !== 'local');
  renderMemeTagGrid(memeTags);
}

function renderMemeCounts(meta) {
  const count = meta?.library_count ?? 0;
  const queue = meta?.display_queue_size ?? 0;
  const libEl = $('memeLibraryCount');
  const queueEl = $('memeQueueCount');
  const inlineEl = $('memeLocalCountInline');
  if (libEl) libEl.textContent = String(count);
  if (queueEl) queueEl.textContent = String(queue);
  if (inlineEl) inlineEl.textContent = `【${count}】`;
}

// 实时预估上屏频率：展示间隔 / 展示批量 = 平均每条间隔秒数
function updateMemeFreq() {
  const di = parseInt($('memeDisplayInterval')?.value, 10) || 5;
  const db = parseInt($('memeDisplayBatch')?.value, 10) || 2;
  const per = di / db;
  const numEl = $('memeFreqNum');
  if (numEl) numEl.textContent = per < 1 ? per.toFixed(1) : String(Math.round(per));
  let qual = '';
  if (per < 2) qual = '很热闹 —— 弹幕刷得飞快，适合人气高的直播间。';
  else if (per <= 6) qual = '适中 —— 直播间不会太吵也不会冷场。';
  else qual = '偏安静 —— 偶尔来一句，适合不想太打扰的场合。';
  const qualEl = $('memeFreqQual');
  if (qualEl) qualEl.textContent = qual;
  const bars = $('memeFreqBars');
  if (bars) {
    bars.replaceChildren();
    for (let i = 0; i < 12; i++) {
      const bar = document.createElement('i');
      const h = 30 - Math.min(28, per * 4) + (i % 3) * 6;
      bar.style.height = Math.max(8, h) + 'px';
      bar.style.opacity = per < 2 ? '0.9' : per <= 6 ? '0.55' : '0.3';
      bars.append(bar);
    }
  }
}

function setRangeVal(id, value) {
  const el = $(id);
  if (el) el.value = String(value);
  const v = $(id + 'Val');
  if (v) v.textContent = String(value);
}

function applyMemeMetaToForm(meta, { formFields = true } = {}) {
  memeBarrageMeta = meta;
  if (!formFields) {
    renderMemeCounts(meta);
    return;
  }
  const enabledEl = $('memeBarrageEnabled');
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
    selectedTags = new Set([DEFAULT_TAG]);
  }

  setRangeVal('memeCollectInterval', meta.collect_interval_sec ?? 5);
  setRangeVal('memeCollectBatch', meta.collect_batch_size ?? 2);
  setRangeVal('memeDisplayInterval', meta.display_interval_sec ?? 5);
  setRangeVal('memeDisplayBatch', meta.display_batch_size ?? 2);

  renderMemeCounts(meta);
  updateMasterLock();
  updateMemeCategoryView();
  updateMemeFreq();
}

export function switchDanmuPoolTab(tabId) {
  if (getLanguage() === 'en' && tabId === 'meme') {
    tabId = 'custom';
  }
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

export function applyDanmuPoolLanguageLayout() {
  const isEn = getLanguage() === 'en';
  const memeTab = document.querySelector('[data-danmu-pool-tab="meme"]');
  const memePanel = document.querySelector('[data-danmu-pool-panel="meme"]');
  const tabBar = document.querySelector('.danmu-pool-tabs');
  const tabsBarWrap = document.querySelector('.danmu-pool-page .settings-tabs-bar');

  if (memeTab) {
    memeTab.hidden = isEn;
    memeTab.setAttribute('aria-hidden', isEn ? 'true' : 'false');
    memeTab.tabIndex = isEn ? -1 : 0;
  }
  if (memePanel) {
    if (isEn) {
      memePanel.hidden = true;
      memePanel.classList.remove('active');
      memePanel.setAttribute('aria-hidden', 'true');
    } else {
      memePanel.setAttribute('aria-hidden', 'false');
    }
  }
  if (tabBar) tabBar.classList.toggle('hidden', isEn);
  if (tabsBarWrap) tabsBarWrap.classList.toggle('hidden', isEn);

  if (isEn) {
    switchDanmuPoolTab('custom');
  }
}

function ensureDanmuPoolLanguageLayoutListener() {
  if (languageLayoutListenerRegistered) return;
  languageLayoutListenerRegistered = true;
  onLanguageChanged(applyDanmuPoolLanguageLayout);
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
    enabled: Boolean($('memeBarrageEnabled')?.checked),
    category: getSelectedCategory(),
    tag: Array.from(normalizeSelectedTags(selectedTags)),
    display_mode: getSelectedDisplayMode(),
    collect_interval_sec: parseInt($('memeCollectInterval')?.value, 10) || 5,
    collect_batch_size: parseInt($('memeCollectBatch')?.value, 10) || 2,
    display_interval_sec: parseInt($('memeDisplayInterval')?.value, 10) || 5,
    display_batch_size: parseInt($('memeDisplayBatch')?.value, 10) || 2,
  };
  const meta = await apiFetch('/api/meme-barrage/settings', {
    method: 'PUT',
    body: JSON.stringify(body),
  });
  applyMemeMetaToForm(meta);
  showToast(t('dynamic.appMemeBarragePage.烂梗公式化设置已保存'));
}

async function resetMemeBarrageSettings() {
  const enabledEl = $('memeBarrageEnabled');
  if (enabledEl) enabledEl.checked = true;
  const setRadio = (name, val) => {
    const r = document.querySelector(`input[name="${name}"][value="${val}"]`);
    if (r) r.checked = true;
  };
  setRadio('memeCategory', 'random');
  setRadio('memeDisplayMode', 'full');
  selectedTags = new Set([DEFAULT_TAG]);
  setRangeVal('memeCollectInterval', 5);
  setRangeVal('memeCollectBatch', 2);
  setRangeVal('memeDisplayInterval', 5);
  setRangeVal('memeDisplayBatch', 2);
  updateMasterLock();
  updateMemeCategoryView();
  updateMemeFreq();
  try {
    await saveMemeBarrageSettings();
    showToast('已恢复默认设置');
  } catch (error) {
    showToast(error.message, true);
  }
}

async function clearMemeBarrageLibrary() {
  if (!window.confirm('确定清除本地库与待展示队列？已上屏的弹幕不会消失。')) return;
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
  ensureDanmuPoolLanguageLayoutListener();
  applyDanmuPoolLanguageLayout();
  if (handlersBound) return;
  handlersBound = true;

  document.querySelectorAll('[data-danmu-pool-tab]').forEach((tab) => {
    tab.addEventListener('click', (event) => {
      event.stopPropagation();
      if (getLanguage() === 'en' && tab.dataset.danmuPoolTab === 'meme') {
        return;
      }
      switchDanmuPoolTab(tab.dataset.danmuPoolTab);
    });
  });

  document.querySelectorAll('input[name="memeCategory"]').forEach((input) => {
    input.addEventListener('change', () => updateMemeCategoryView());
  });

  document.querySelectorAll('input[name="memeDisplayMode"]').forEach((input) => {
    input.addEventListener('change', () => syncCardSelected());
  });

  const enabledEl = $('memeBarrageEnabled');
  if (enabledEl) enabledEl.addEventListener('change', () => updateMasterLock());

  [['memeCollectInterval', 'memeCollectBatch'], ['memeDisplayInterval', 'memeDisplayBatch']].forEach(
    ([iId]) => {
      const el = $(iId);
      if (el) {
        el.addEventListener('input', () => {
          const v = $(iId + 'Val');
          if (v) v.textContent = el.value;
          updateMemeFreq();
        });
      }
    },
  );

  document.querySelectorAll('.meme-preset').forEach((btn) => {
    btn.addEventListener('click', () => {
      const p = btn.dataset.preset;
      const map = {
        'collect-slow': ['memeCollectInterval', 30, 'memeCollectBatch', 10],
        'collect-norm': ['memeCollectInterval', 5, 'memeCollectBatch', 2],
        'collect-fast': ['memeCollectInterval', 2, 'memeCollectBatch', 40],
        'show-slow': ['memeDisplayInterval', 15, 'memeDisplayBatch', 1],
        'show-norm': ['memeDisplayInterval', 5, 'memeDisplayBatch', 2],
        'show-fast': ['memeDisplayInterval', 2, 'memeDisplayBatch', 6],
      }[p];
      if (!map) return;
      setRangeVal(map[0], map[1]);
      setRangeVal(map[2], map[3]);
      updateMemeFreq();
    });
  });

  $('btnSaveMemeBarrageSettings')?.addEventListener('click', () => {
    saveMemeBarrageSettings().catch((error) => showToast(error.message, true));
  });

  $('btnResetMemeBarrageSettings')?.addEventListener('click', () => {
    resetMemeBarrageSettings().catch((error) => showToast(error.message, true));
  });

  $('btnMemeBarrageClear')?.addEventListener('click', () => {
    clearMemeBarrageLibrary().catch((error) => showToast(error.message, true));
  });
}
