import { apiFetch } from './transport.js';

let toast = () => {};
let handlersBound = false;

function showToast(message, isError = false) {
  toast(message, isError);
}

function setStatusText(text) {
  const el = document.getElementById('petStatusText');
  if (el) el.textContent = text;
}

function setAssetText(text) {
  const el = document.getElementById('petAssetText');
  if (el) el.textContent = text;
}

function fillPetForm(data) {
  const enabled = document.getElementById('petEnabled');
  const scale = document.getElementById('petScale');
  const opacity = document.getElementById('petOpacity');
  const alwaysOnTop = document.getElementById('petAlwaysOnTop');
  const clickThrough = document.getElementById('petClickThrough');
  const commandBox = document.getElementById('petCommandBoxEnabled');
  const ttl = document.getElementById('petCommandTtl');
  const applyCount = document.getElementById('petCommandApplyCount');

  if (enabled) enabled.checked = Boolean(data.enabled);
  if (scale) scale.value = String(data.scale ?? 1);
  if (opacity) opacity.value = String(data.opacity ?? 1);
  if (alwaysOnTop) alwaysOnTop.checked = Boolean(data.always_on_top);
  if (clickThrough) clickThrough.checked = Boolean(data.click_through);
  if (commandBox) commandBox.checked = Boolean(data.command_box_enabled);
  if (ttl) ttl.value = String(data.command_ttl_sec ?? 30);
  if (applyCount) applyCount.value = String(data.command_apply_count ?? 1);

  const pending = data.pending_command;
  if (data.has_pending_command && pending?.preview) {
    setStatusText(`已启用 · 待注入指令：${pending.preview}`);
  } else if (!data.enabled) {
    setStatusText('未启用');
  } else if (data.visible) {
    setStatusText('已启用');
  } else {
    setStatusText('已启用 · 已隐藏（可在桌宠右键菜单显示）');
  }

  const asset = data.asset || {};
  if (asset.ok) {
    setAssetText(`${asset.display_name || asset.id || '默认宠物'}`);
  } else if (asset.error) {
    setAssetText(`加载失败：${asset.error}`);
  } else {
    setAssetText('默认宠物');
  }
}

function collectPetPayload() {
  return {
    enabled: Boolean(document.getElementById('petEnabled')?.checked),
    scale: parseFloat(document.getElementById('petScale')?.value) || 1,
    opacity: parseFloat(document.getElementById('petOpacity')?.value) || 1,
    always_on_top: Boolean(document.getElementById('petAlwaysOnTop')?.checked),
    click_through: Boolean(document.getElementById('petClickThrough')?.checked),
    command_box_enabled: Boolean(document.getElementById('petCommandBoxEnabled')?.checked),
    command_ttl_sec: parseInt(document.getElementById('petCommandTtl')?.value, 10) || 30,
    command_apply_count: parseInt(document.getElementById('petCommandApplyCount')?.value, 10) || 1,
    asset_source: 'builtin',
    asset_path: '',
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
    showToast('导入文件夹功能正在开发中，当前将继续使用内置默认素材。');
  });
}
