import { apiFetch } from './transport.js';

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
  const displayName = asset.display_name || asset.id || '默认桌宠';
  const sourceLabel = currentAssetSource === 'local' ? '本地目录' : '内置默认';

  if (asset.ok) {
    setAssetText(displayName);
    setAssetError('');
  } else if (asset.error) {
    setAssetText(currentAssetSource === 'local' ? '自定义桌宠加载失败' : '默认桌宠');
    setAssetError(asset.error);
  } else {
    setAssetText('默认桌宠');
    setAssetError('');
  }

  setText('petAssetSourceText', sourceLabel);
  setText('petAssetPathText', currentAssetPath || '—');
  setResetButtonEnabled(currentAssetSource === 'local' || Boolean(currentAssetPath));
}

function resolveSlotAssetMap(data) {
  const slotAssets = data?.pet_barrage?.slot_assets;
  if (!Array.isArray(slotAssets)) return new Map();
  return new Map(slotAssets.map((item) => [Number(item.slot_id), item]));
}

function renderBarrageSlots(data) {
  const container = document.getElementById('petBarrageSlots');
  if (!container) return;
  const slotAssets = resolveSlotAssetMap(data);
  currentBarrageSlotAssets = slotAssets;
  const slots = data?.pet_barrage?.slots || [];
  container.innerHTML = '';
  slots.forEach((slot) => {
    const slotId = Number(slot.slot_id);
    const asset = slotAssets.get(slotId) || {};
    const card = document.createElement('article');
    card.className = 'rounded-2xl border border-softPeach bg-white/80 p-4 space-y-3';
    card.innerHTML = `
      <div class="flex items-start justify-between gap-3">
        <div>
          <h4 class="text-base font-bold text-warmText">槽位 ${slotId + 1}</h4>
          <p class="text-sm text-gray-500">${asset.display_name || '默认桌宠'}</p>
        </div>
        <span class="rounded-full bg-cream px-3 py-1 text-xs font-semibold text-warmText">${asset.resource_label || '内置默认'}</span>
      </div>
      <div class="rounded-xl border border-softPeach bg-cream/60 p-2 flex items-center justify-center min-h-[140px]">
        <img
          src="/api/pet/barrage-slots/${slotId}/preview"
          alt="桌宠槽位 ${slotId + 1} 预览"
          class="max-h-32 w-auto object-contain"
        >
      </div>
      <div class="text-xs text-gray-500 space-y-1">
        <p>资源来源：${asset.resource_label || '内置默认'}</p>
        <p class="break-all">资源路径：${slot.asset_path || '—'}</p>
      </div>
      <p class="slot-error text-sm font-semibold text-red-600 ${asset.error ? '' : 'hidden'}">${asset.error || ''}</p>
      <div class="flex flex-wrap gap-3">
        <button type="button" class="btn-primary px-4 py-2 text-white rounded-xl text-sm font-bold shadow-warm" data-slot-action="import" data-slot-id="${slotId}">切换桌宠</button>
        <button type="button" class="px-4 py-2 bg-white border border-gray-200 rounded-xl text-sm font-semibold text-warmText hover:bg-gray-50" data-slot-action="reset" data-slot-id="${slotId}">恢复默认</button>
      </div>
    `;
    container.appendChild(card);
  });
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
    setStatusText(`已启用 · 待注入指令：${pending.preview}`);
  } else if (!data.enabled) {
    setStatusText('未启用');
  } else if (data.pet_barrage?.enabled) {
    setStatusText('已启用 · 桌宠弹幕形式');
  } else if (data.visible) {
    setStatusText('已启用');
  } else {
    setStatusText('已启用 · 已隐藏（可在桌宠右键菜单显示）');
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
  showToast('桌宠设置已保存');
}

async function submitPetCommand() {
  const input = document.getElementById('petCommandInput');
  const text = input?.value || '';
  if (!text.trim()) {
    showToast('请先输入指令内容', true);
    return;
  }
  await apiFetch('/api/pet/command', {
    method: 'POST',
    body: JSON.stringify({ text }),
  });
  if (input) input.value = '';
  await loadPetPage();
  showToast('已加入下一次弹幕生成');
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
  showToast('已恢复默认桌宠');
}

async function setBarrageSlotToImported(slotId) {
  const imported = await apiFetch(`/api/pet/barrage-slots/${slotId}/import-folder`, { method: 'POST' });
  if (imported.cancelled) {
    fillPetForm(imported);
    return;
  }
  await loadPetPage();
  showToast(`槽位 ${slotId + 1} 已切换桌宠`);
}

async function resetBarrageSlot(slotId) {
  const data = await apiFetch(`/api/pet/barrage-slots/${slotId}/reset`, {
    method: 'POST',
  });
  fillPetForm(data);
  showToast(`槽位 ${slotId + 1} 已恢复默认桌宠`);
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

export function initPetPage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;

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
  bindSlotActions();
}
