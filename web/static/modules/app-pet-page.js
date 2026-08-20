import { apiFetch } from './transport.js';
import { t } from './i18n.js';

let toast = () => {};
let handlersBound = false;
let currentAssetSource = 'builtin';
let currentAssetPath = '';
let currentBarrageSlotAssets = new Map();
let currentPetSettings = null;

function showToast(message, isError = false) {
  toast(message, isError);
}

function setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function setStatusText(text) {
  setText('petStatusText', text);
}

function setAssetText(text) {
  setText('petAssetText', text);
}

function setAssetError(message) {
  const errorEl = document.getElementById('petAssetErrorText');
  if (!errorEl) return;
  if (message) {
    errorEl.textContent = message;
    errorEl.classList.remove('hidden');
  } else {
    errorEl.textContent = '';
    errorEl.classList.add('hidden');
  }
}

function setResetButtonEnabled(enabled) {
  const btn = document.getElementById('btnPetResetAsset');
  if (!btn) return;
  btn.disabled = !enabled;
  btn.classList.toggle('opacity-50', !enabled);
  btn.classList.toggle('cursor-not-allowed', !enabled);
}

function describeAsset(data) {
  const asset = data.asset || {};
  const displayName = asset.display_name || asset.id || t('dynamic.appPetPage.默认桌宠');

  if (asset.ok) {
    setAssetText(displayName);
    setAssetError('');
  } else if (asset.error) {
    setAssetText(currentAssetSource === 'local' ? t('dynamic.appPetPage.自定义桌宠加载失败') : t('dynamic.appPetPage.默认桌宠'));
    setAssetError(asset.error);
  } else {
    setAssetText(t('dynamic.appPetPage.默认桌宠'));
    setAssetError('');
  }

  const sourceText = currentAssetSource === 'local'
    ? currentAssetPath || t('dynamic.appPetPage.本地目录')
    : t('dynamic.appPetPage.使用默认桌宠');
  setText('petAssetSourceText', sourceText);
  setResetButtonEnabled(currentAssetSource === 'local' || Boolean(currentAssetPath));
}

function resolveSlotAssetMap(data) {
  const slotAssets = data?.pet_barrage?.slot_assets;
  if (!Array.isArray(slotAssets)) return new Map();
  return new Map(slotAssets.map((item) => [Number(item.slot_id), item]));
}

function appendTextElement(parent, tagName, className, text) {
  const el = document.createElement(tagName);
  if (className) el.className = className;
  el.textContent = text;
  parent.appendChild(el);
  return el;
}

export function createBarrageSlotCard(slotId, slot, asset) {
  const displayName = asset.display_name || t('dynamic.appPetPage.默认桌宠');
  const resourceLabel = asset.resource_label || t('dynamic.appPetPage.内置默认');
  const assetPath = slot.asset_path || '—';
  const slotNumber = slotId + 1;

  const card = document.createElement('article');
  card.className = 'rounded-2xl border border-softPeach bg-white/80 p-4 space-y-3';

  const headerRow = document.createElement('div');
  headerRow.className = 'flex items-start justify-between gap-3';

  const titleBlock = document.createElement('div');
  appendTextElement(titleBlock, 'h4', 'text-base font-bold text-warmText', `槽位 ${slotNumber}`);
  appendTextElement(titleBlock, 'p', 'text-sm text-gray-500', displayName);
  headerRow.appendChild(titleBlock);

  appendTextElement(
    headerRow,
    'span',
    'rounded-full bg-cream px-3 py-1 text-xs font-semibold text-warmText',
    resourceLabel,
  );

  const previewBox = document.createElement('div');
  previewBox.className = 'rounded-xl border border-softPeach bg-cream/60 p-2 flex items-center justify-center min-h-[140px]';
  const previewImg = document.createElement('img');
  previewImg.src = `/api/pet/barrage-slots/${slotId}/preview`;
  previewImg.alt = `桌宠槽位 ${slotNumber} 预览`;
  previewImg.className = 'max-h-32 w-auto object-contain';
  previewBox.appendChild(previewImg);

  const metaBlock = document.createElement('div');
  metaBlock.className = 'text-xs text-gray-500 space-y-1';
  appendTextElement(metaBlock, 'p', '', `资源来源：${resourceLabel}`);
  appendTextElement(metaBlock, 'p', 'break-all', `资源路径：${assetPath}`);

  const errorEl = document.createElement('p');
  errorEl.className = `slot-error text-sm font-semibold text-red-600${asset.error ? '' : ' hidden'}`;
  errorEl.textContent = asset.error || '';

  const buttonRow = document.createElement('div');
  buttonRow.className = 'flex flex-wrap gap-3';

  const importBtn = document.createElement('button');
  importBtn.type = 'button';
  importBtn.className = 'btn-primary ui-button ui-button--primary ui-button--md';
  importBtn.dataset.slotAction = 'import';
  importBtn.dataset.slotId = String(slotId);
  importBtn.textContent = '切换桌宠';

  const resetBtn = document.createElement('button');
  resetBtn.type = 'button';
  resetBtn.className = 'ui-button ui-button--secondary ui-button--md';
  resetBtn.dataset.slotAction = 'reset';
  resetBtn.dataset.slotId = String(slotId);
  resetBtn.textContent = '恢复默认';

  buttonRow.append(importBtn, resetBtn);
  card.append(headerRow, previewBox, metaBlock, errorEl, buttonRow);
  return card;
}

function renderBarrageSlots(data) {
  const container = document.getElementById('petBarrageSlots');
  if (!container) return;
  const slotAssets = resolveSlotAssetMap(data);
  currentBarrageSlotAssets = slotAssets;
  const slots = data?.pet_barrage?.slots || [];
  container.replaceChildren();
  slots.forEach((slot) => {
    const slotId = Number(slot.slot_id);
    const asset = slotAssets.get(slotId) || {};
    container.appendChild(createBarrageSlotCard(slotId, slot, asset));
  });
}

function updateBarrageModeHint() {
  const petEnabled = Boolean(document.getElementById('petEnabled')?.checked);
  const barrageEnabled = Boolean(document.getElementById('petBarrageModeEnabled')?.checked);
  if (!petEnabled) return;
  if (barrageEnabled) {
    setStatusText(t('dynamic.appPetPage.已启用_桌宠弹幕形式_保存后生效'));
  } else {
    setStatusText(t('dynamic.appPetPage.已启用_将显示普通单桌宠_保存后生效'));
  }
}

function updateBarrageUi(data) {
  const enabled = Boolean(data?.pet_barrage?.enabled);
  const toggle = document.getElementById('petBarrageModeEnabled');
  if (toggle) toggle.checked = enabled;
  document.documentElement.dataset.petBarrageModeEnabled = enabled ? '1' : '0';
  const section = document.getElementById('petBarrageSlotsSection');
  if (section) section.classList.toggle('hidden', !enabled);
  if (enabled) renderBarrageSlots(data);
}

function fillPetForm(data) {
  currentPetSettings = data;
  const enabled = document.getElementById('petEnabled');
  const scale = document.getElementById('petScale');
  const opacity = document.getElementById('petOpacity');
  const alwaysOnTop = document.getElementById('petAlwaysOnTop');
  const clickThrough = document.getElementById('petClickThrough');
  const commandBox = document.getElementById('petCommandBoxEnabled');
  const ttl = document.getElementById('petCommandTtl');
  const applyCount = document.getElementById('petCommandApplyCount');

  if (enabled) enabled.checked = Boolean(data.enabled);
  if (scale) scale.value = String(data.scale ?? 0.5);
  if (opacity) opacity.value = String(data.opacity ?? 1);
  if (alwaysOnTop) alwaysOnTop.checked = Boolean(data.always_on_top);
  if (clickThrough) clickThrough.checked = Boolean(data.click_through);
  if (commandBox) commandBox.checked = Boolean(data.command_box_enabled);
  if (ttl) ttl.value = String(data.command_ttl_sec ?? 30);
  if (applyCount) applyCount.value = String(data.command_apply_count ?? 1);

  currentAssetSource = data.asset_source === 'local' ? 'local' : 'builtin';
  currentAssetPath = String(data.asset_path || '');

  const pending = data.pending_command;
  if (data.has_pending_command && pending?.preview) {
    setStatusText(t('dynamic.appPetPage.已启用_待注入指令_pending_pr', { preview: pending.preview }));
  } else if (!data.enabled) {
    setStatusText(t('dynamic.appPetPage.未启用'));
  } else if (data.pet_barrage?.enabled) {
    setStatusText(t('dynamic.appPetPage.已启用_桌宠弹幕形式'));
  } else if (data.visible) {
    setStatusText(t('dynamic.appPetPage.已启用'));
  } else {
    setStatusText(t('dynamic.appPetPage.已启用_已隐藏_可在桌宠右键菜单显示'));
  }

  describeAsset(data);
  updateBarrageUi(data);
}

function collectPetPayload() {
  return {
    enabled: Boolean(document.getElementById('petEnabled')?.checked),
    scale: parseFloat(document.getElementById('petScale')?.value) || 0.5,
    opacity: parseFloat(document.getElementById('petOpacity')?.value) || 1,
    always_on_top: Boolean(document.getElementById('petAlwaysOnTop')?.checked),
    click_through: Boolean(document.getElementById('petClickThrough')?.checked),
    command_box_enabled: Boolean(document.getElementById('petCommandBoxEnabled')?.checked),
    command_ttl_sec: parseInt(document.getElementById('petCommandTtl')?.value, 10) || 30,
    command_apply_count: parseInt(document.getElementById('petCommandApplyCount')?.value, 10) || 1,
    asset_source: currentAssetSource,
    asset_path: currentAssetPath,
    pet_barrage_mode_enabled: Boolean(document.getElementById('petBarrageModeEnabled')?.checked),
  };
}

export async function loadPetPage() {
  const data = await apiFetch('/api/pet/settings');
  fillPetForm(data);
}

async function savePetSettings() {
  const payload = collectPetPayload();
  const data = await apiFetch('/api/pet/settings', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
  fillPetForm(data);
  showToast(t('dynamic.appPetPage.桌宠设置已保存'));
}

async function submitPetCommand() {
  const input = document.getElementById('petCommandInput');
  const text = input?.value || '';
  if (!text.trim()) {
    showToast(t('dynamic.appPetPage.请先输入指令内容'), true);
    return;
  }
  await apiFetch('/api/pet/command', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
  if (input) input.value = '';
  await loadPetPage();
  showToast(t('dynamic.appPetPage.已加入下一次弹幕生成'));
}

async function importPetFolder() {
  const data = await apiFetch('/api/pet/import-folder', { method: 'POST' });
  if (!data.cancelled) {
    const asset = data.asset || {};
    showToast(`已切换到桌宠：${asset.display_name || asset.id || '自定义桌宠'}`);
  }
  fillPetForm(data);
}

async function resetPetAsset() {
  const data = await apiFetch('/api/pet/reset-asset', { method: 'POST' });
  fillPetForm(data);
  showToast(t('dynamic.appPetPage.已恢复默认桌宠'));
}

async function setBarrageSlotToImported(slotId) {
  const imported = await apiFetch(`/api/pet/barrage-slots/${slotId}/import-folder`, { method: 'POST' });
  if (imported.cancelled) {
    fillPetForm(imported);
    return;
  }
  await loadPetPage();
  showToast(t('dynamic.appPetPage.槽位_slotId_1_已切换桌宠', { slotNumber: slotId + 1 }));
}

async function resetBarrageSlot(slotId) {
  const data = await apiFetch(`/api/pet/barrage-slots/${slotId}/reset`, {
    method: 'POST',
  });
  fillPetForm(data);
  showToast(t('dynamic.appPetPage.槽位_slotId_1_已恢复默认桌宠', { slotNumber: slotId + 1 }));
}

function bindSlotActions() {
  const container = document.getElementById('petBarrageSlots');
  if (!container) return;
  container.addEventListener('click', (event) => {
    const button = event.target.closest('[data-slot-action]');
    if (!button) return;
    const slotId = parseInt(button.dataset.slotId || '-1', 10);
    const action = button.dataset.slotAction;
    if (slotId < 0) return;
    if (action === 'import') {
      setBarrageSlotToImported(slotId).catch((error) => showToast(error.message, true));
      return;
    }
    if (action === 'reset') {
      resetBarrageSlot(slotId).catch((error) => showToast(error.message, true));
    }
  });
}

function initPetTabs() {
  document.querySelectorAll('.pet-tabs .settings-tab').forEach((tab) => {
    tab.addEventListener('click', () => {
      const tabId = tab.dataset.petTab;
      document.querySelectorAll('.pet-tabs .settings-tab').forEach((t) => {
        const active = t.dataset.petTab === tabId;
        t.classList.toggle('active', active);
        t.setAttribute('aria-selected', active ? 'true' : 'false');
      });
      document.querySelectorAll('[data-pet-panel]').forEach((panel) => {
        const active = panel.dataset.petPanel === tabId;
        panel.classList.toggle('active', active);
        panel.hidden = !active;
      });
      if (tabId === 'vtuber-persona') {
        import('./app-vtuber-persona-page.js').then((mod) => {
          mod.initVtuberPersonaPage({ showToast: toast });
          mod.onVtuberPersonaTabActivated();
        }).catch(() => {});
      }
      if (tabId === 'vtuber-download') {
        import('./app-vtuber-download-page.js').then((mod) => {
          mod.initVtuberDownloadPage();
          mod.onVtuberDownloadTabActivated();
        }).catch(() => {});
      }
    });
  });
}

export function initPetPage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;
  initPetTabs();

  document.getElementById('btnPetSave')?.addEventListener('click', () => {
    savePetSettings().catch((error) => showToast(error.message, true));
  });
  document.getElementById('btnPetCommandSubmit')?.addEventListener('click', () => {
    submitPetCommand().catch((error) => showToast(error.message, true));
  });
  document.getElementById('btnPetImportFolder')?.addEventListener('click', () => {
    importPetFolder().catch((error) => showToast(error.message, true));
  });
  document.getElementById('btnPetResetAsset')?.addEventListener('click', () => {
    resetPetAsset().catch((error) => showToast(error.message, true));
  });
  document.getElementById('petBarrageModeEnabled')?.addEventListener('change', updateBarrageModeHint);
  bindSlotActions();
}
