import { apiFetch } from './transport.js';
import { isMaskedApiKey } from './settings-defaults.js';
import { findProvider, getProviderWebsite, isCustomProvider, getDefaultEndpoint } from './settings-providers.js';
import { getModelCatalogModels, getModelNameFromCatalog, pickDefaultCatalogModelId } from './settings-model-catalog.js';

let customModelDeps = {
  showToast: () => {},
  reloadConfigFromServer: async () => ({}),
  syncVisionModelPickerFromForm: () => {},
  updateModelActiveSourceBanner: () => {},
};

let cachedCustomModels = [];
let modelModalBindingsWired = false;

export function getCachedCustomModels() {
  return cachedCustomModels;
}

export function customModelSupportsMic(modelId) {
  const id = (modelId || '').trim();
  if (!id) return false;
  const hit = cachedCustomModels.find((model) => {
    const ids = Array.isArray(model.model_ids) ? model.model_ids.map((x) => String(x || '').trim()) : [];
    const legacy = (model.modelId || '').trim();
    const def = (model.default_model_id || '').trim();
    return ids.includes(id) || legacy === id || def === id;
  });
  return Boolean(hit?.supportsMic);
}

export function configureSettingsCustomModels(deps) {
  customModelDeps = { ...customModelDeps, ...deps };
}

export async function loadCustomModels() {
  if (!modelModalBindingsWired) {
    modelModalBindingsWired = true;
    try { initModelModalBindings(); } catch (_e) { /* DOM not ready yet */ }
  }
  const data = await apiFetch('/api/custom-models');
  cachedCustomModels = data.items || [];
  const list = document.getElementById('customModelsList');
  if (!list) return;
  list.innerHTML = '';
  if (!data.items.length) {
    list.innerHTML = '<p class="text-sm text-gray-400">暂无模型配置档案，点击上方新增~</p>';
    return;
  }
  data.items.forEach((model, index) => {
    const row = document.createElement('div');
    row.className = 'custom-model-row flex flex-wrap items-center gap-3 p-3 bg-cream rounded-xl text-sm';
    const isDefault = (model.default_model_id || model.modelId) === data.default_model_id;

    // 列 1：模型名 + provider chip
    const colName = document.createElement('div');
    colName.className = 'flex items-center gap-2 min-w-0 flex-1';
    const nameSpan = document.createElement('span');
    nameSpan.className = 'font-semibold text-warmText truncate';
    nameSpan.textContent = model.name || '未命名';
    colName.appendChild(nameSpan);
    const providerId = model.provider || '';
    const provider = providerId ? findProvider(providerId) : null;
    if (provider && provider.label) {
      const chip = document.createElement('span');
      chip.className = 'custom-model-provider-chip px-2 py-0.5 rounded-full bg-softPeach text-warmText text-xs font-semibold';
      chip.textContent = provider.label;
      colName.appendChild(chip);
    }
    if (model.supportsMic) {
      const mic = document.createElement('span');
      mic.className = 'text-sky-600 text-xs font-bold';
      mic.textContent = '支持麦克风';
      colName.appendChild(mic);
    }
    if (model.complete === false) {
      const warn = document.createElement('span');
      warn.className = 'text-amber-600 text-xs font-bold';
      warn.textContent = '配置不完整';
      colName.appendChild(warn);
    }

    // 列 2：默认 modelId + 数组长度（+N 表示多 N 项）
    const colModelId = document.createElement('div');
    colModelId.className = 'custom-model-id-col text-gray-500 text-xs whitespace-nowrap';
    const modelIds = Array.isArray(model.model_ids) ? model.model_ids : [];
    const defaultId = model.default_model_id || model.modelId || '';
    const extra = Math.max(0, modelIds.length - 1);
    const idSpan = document.createElement('span');
    idSpan.className = 'font-mono';
    idSpan.textContent = defaultId;
    colModelId.appendChild(idSpan);
    if (extra > 0) {
      const extraSpan = document.createElement('span');
      extraSpan.className = 'text-gray-400';
      extraSpan.textContent = ` (+${extra})`;
      colModelId.appendChild(extraSpan);
    }

    // 列 3：使用下拉（select：当前 default 选中；切换 → POST /api/custom-models/{index}/default）
    const colDefault = document.createElement('div');
    colDefault.className = 'custom-model-default-col';
    const defaultSelect = document.createElement('select');
    defaultSelect.className = 'px-2 py-1 bg-white border border-gray-200 rounded-lg text-xs';
    defaultSelect.setAttribute('aria-label', '使用');
    if (isDefault) {
      const opt = document.createElement('option');
      opt.value = '1';
      opt.selected = true;
      opt.textContent = '✓ 使用';
      defaultSelect.appendChild(opt);
      defaultSelect.disabled = true;
    } else {
      const placeholder = document.createElement('option');
      placeholder.value = '';
      placeholder.textContent = '不使用';
      defaultSelect.appendChild(placeholder);
      const setOpt = document.createElement('option');
      setOpt.value = 'set';
      setOpt.textContent = '设为使用';
      defaultSelect.appendChild(setOpt);
      defaultSelect.addEventListener('change', async () => {
        if (defaultSelect.value === 'set') {
          await setProfileAsDefault(index, model);
        }
        defaultSelect.value = '';
      });
    }
    colDefault.appendChild(defaultSelect);

    // 列 4：操作按钮组（编辑 / 删除 / 设默认）
    const colActions = document.createElement('div');
    colActions.className = 'custom-model-actions flex items-center gap-2';
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'px-3 py-1 border border-gray-200 rounded-lg text-xs';
    editBtn.textContent = '编辑';
    editBtn.onclick = () => openModelModal(index, model);
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'px-3 py-1 border border-red-200 rounded-lg text-xs text-red-600';
    delBtn.textContent = '删除';
    delBtn.onclick = () => openDeleteModelConfirm(model, index);
    colActions.appendChild(editBtn);
    colActions.appendChild(delBtn);
    if (!isDefault) {
      const defBtn = document.createElement('button');
      defBtn.type = 'button';
      defBtn.className = 'px-3 py-1 border border-gray-200 rounded-lg text-xs';
      defBtn.textContent = '设默认';
      defBtn.onclick = async () => { await setProfileAsDefault(index, model); };
      colActions.appendChild(defBtn);
    }

    row.appendChild(colName);
    row.appendChild(colModelId);
    row.appendChild(colDefault);
    row.appendChild(colActions);
    list.appendChild(row);
  });
}

/** W-SETTINGS-RESTRUCT-A-006：将指定 profile 设为系统默认（列 3 下拉 / 列 4 设默认按钮共用）。 */
async function setProfileAsDefault(index, model) {
  const res = await apiFetch(`/api/custom-models/${index}/default`, { method: 'POST' });
  const modelEl = document.getElementById('model');
  if (modelEl && res.default_model_id) {
    modelEl.value = res.default_model_id;
    customModelDeps.syncVisionModelPickerFromForm(res.default_model_id);
  }
  const cfg = await customModelDeps.reloadConfigFromServer();
  customModelDeps.updateModelActiveSourceBanner(cfg);
  customModelDeps.showToast(`已设为默认模型：${res.default_model_id || model.modelId}`);
  loadCustomModels();
}

import { activateFocusTrap, deactivateFocusTrap } from './modal-focus-trap.js';

const TAG_MAX_LEN = 200;

function getTagInputState() {
  const container = document.getElementById('modelIdsTags');
  const input = document.getElementById('modelIdsInput');
  return { container, input };
}

function readTagChips() {
  const { container } = getTagInputState();
  if (!container) return [];
  return Array.from(container.querySelectorAll('.tag-chip[data-value]')).map((chip) => ({
    value: chip.getAttribute('data-value') || '',
    isDefault: chip.hasAttribute('data-default'),
    el: chip,
  }));
}

function getModelIdsFromChips() {
  return readTagChips().map((c) => c.value).filter(Boolean);
}

function getDefaultModelIdFromChips() {
  const chips = readTagChips();
  const def = chips.find((c) => c.isDefault);
  return def?.value || chips[0]?.value || '';
}

function markFirstChipDefault() {
  const chips = readTagChips();
  if (!chips.length) return;
  const hasDefault = chips.some((c) => c.isDefault);
  if (hasDefault) return;
  applyChipDefault(chips[0].el, true);
}

function applyChipDefault(chipEl, isDefault) {
  if (!chipEl) return;
  if (isDefault) {
    chipEl.setAttribute('data-default', '1');
  } else {
    chipEl.removeAttribute('data-default');
  }
  let mark = chipEl.querySelector('.tag-default-mark');
  if (isDefault && !mark) {
    mark = document.createElement('span');
    mark.className = 'tag-default-mark';
    mark.textContent = '默认';
    chipEl.insertBefore(mark, chipEl.querySelector('.tag-remove'));
  } else if (!isDefault && mark) {
    mark.remove();
  }
}

function renderTagChip(value, isDefault) {
  const chip = document.createElement('span');
  chip.className = 'tag-chip';
  chip.setAttribute('data-value', value);
  if (isDefault) chip.setAttribute('data-default', '1');
  const label = document.createElement('span');
  label.textContent = value;
  chip.appendChild(label);
  if (isDefault) {
    const mark = document.createElement('span');
    mark.className = 'tag-default-mark';
    mark.textContent = '默认';
    chip.appendChild(mark);
  }
  const removeBtn = document.createElement('button');
  removeBtn.type = 'button';
  removeBtn.className = 'tag-remove';
  removeBtn.textContent = '×';
  removeBtn.setAttribute('aria-label', '删除');
  removeBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const wasDefault = chip.hasAttribute('data-default');
    chip.remove();
    if (wasDefault) markFirstChipDefault();
  });
  chip.addEventListener('click', () => {
    const chips = readTagChips();
    chips.forEach((c) => applyChipDefault(c.el, c.el === chip));
  });
  return chip;
}

function addTagChip(value) {
  const { container, input } = getTagInputState();
  if (!container || !input) return false;
  const trimmed = String(value || '').trim();
  if (!trimmed) return false;
  if (trimmed.length > TAG_MAX_LEN) {
    customModelDeps.showToast(`模型 ID 长度超过 ${TAG_MAX_LEN} 字符，未添加`, true);
    return false;
  }
  const existing = getModelIdsFromChips();
  if (existing.some((id) => id === trimmed)) {
    const dup = container.querySelector(`.tag-chip[data-value="${CSS.escape(trimmed)}"]`);
    if (dup) {
      dup.classList.add('error');
      setTimeout(() => dup.classList.remove('error'), 320);
    }
    return false;
  }
  const isFirst = existing.length === 0;
  const chip = renderTagChip(trimmed, isFirst);
  container.insertBefore(chip, input);
  input.value = '';
  return true;
}

function clearTagChips() {
  const { container } = getTagInputState();
  if (!container) return;
  container.querySelectorAll('.tag-chip').forEach((chip) => chip.remove());
}

function fillTagChips(modelIds, defaultModelId) {
  clearTagChips();
  const ids = Array.isArray(modelIds) ? modelIds : [];
  const defId = (defaultModelId || '').trim();
  ids.forEach((id) => {
    const value = String(id || '').trim();
    if (!value) return;
    const isDefault = defId ? value === defId : false;
    const chip = renderTagChip(value, isDefault);
    const { container, input } = getTagInputState();
    if (container && input) container.insertBefore(chip, input);
  });
  markFirstChipDefault();
}

function updateProviderWebsiteDisplay(providerId) {
  const nameEl = document.getElementById('modelProviderName');
  const webRow = document.getElementById('modelProviderWebsite');
  const webLink = document.getElementById('modelProviderWebsiteLink');
  const openBtn = document.getElementById('modelOpenWebsite');
  const provider = findProvider(providerId);
  if (nameEl) {
    if (provider && provider.id) {
      nameEl.textContent = `当前预设：${provider.label}`;
      nameEl.classList.remove('hidden');
    } else {
      nameEl.textContent = '';
      nameEl.classList.add('hidden');
    }
  }
  const website = getProviderWebsite(providerId);
  if (webRow && webLink && openBtn) {
    if (website) {
      webLink.textContent = website;
      webLink.href = website;
      openBtn.dataset.website = website;
      webRow.classList.remove('hidden');
    } else {
      webLink.textContent = '';
      webLink.href = '';
      delete openBtn.dataset.website;
      webRow.classList.add('hidden');
    }
  }
}

const MODEL_ID_CUSTOM_VALUE = '__custom__';

/** 根据 provider 构建 #modelIdPreset 下拉选项 */
function buildModelIdPresetOptions(providerId) {
  const select = document.getElementById('modelIdPreset');
  if (!select) return;
  select.innerHTML = '';
  const models = getModelCatalogModels(providerId);
  models.forEach((m) => {
    const opt = document.createElement('option');
    opt.value = m.id;
    opt.textContent = `${m.name || m.id}`;
    select.appendChild(opt);
  });
  const customOpt = document.createElement('option');
  customOpt.value = MODEL_ID_CUSTOM_VALUE;
  customOpt.textContent = '自定义配置';
  select.appendChild(customOpt);
  return models;
}

/** 编辑模式下按已有模型回填下拉选中状态 */
function syncModelIdPresetFromForm(modelIds, defaultModelId, providerId) {
  const select = document.getElementById('modelIdPreset');
  if (!select) return;
  const primaryId = (defaultModelId || '').trim() || (modelIds && modelIds[0]) || '';
  const models = getModelCatalogModels(providerId);
  const knownIds = new Set(models.map((m) => m.id));
  if (primaryId && knownIds.has(primaryId)) {
    select.value = primaryId;
  } else {
    select.value = MODEL_ID_CUSTOM_VALUE;
  }
}

/** 设置 chip 输入区的可见性和可用性 */
function setChipInputState(visible, disabled) {
  const wrap = document.getElementById('modelIdsTagsWrap');
  const input = document.getElementById('modelIdsInput');
  if (wrap) {
    if (visible) {
      wrap.classList.remove('hidden');
    } else {
      wrap.classList.add('hidden');
    }
  }
  if (input) {
    input.disabled = disabled;
    if (disabled) {
      input.placeholder = '';
    } else {
      input.placeholder = '例如：doubao-1-5-pro-32k-250115';
    }
  }
}

/** 设置 API 地址字段只读/可编辑状态 */
function setEndpointReadonly(readonly) {
  const el = document.getElementById('modelEndpoint');
  if (!el) return;
  if (readonly) {
    el.setAttribute('readonly', '');
    el.classList.add('bg-gray-100', 'cursor-not-allowed');
  } else {
    el.removeAttribute('readonly');
    el.classList.remove('bg-gray-100', 'cursor-not-allowed');
  }
}

/** 处理模型 ID 下拉变化 */
function onModelIdPresetChange() {
  const select = document.getElementById('modelIdPreset');
  if (!select) return;
  const value = select.value;
  const providerId = document.getElementById('modelProvider')?.value || '';

  if (value === MODEL_ID_CUSTOM_VALUE) {
    // 自定义配置：启用 chip 输入
    setChipInputState(true, false);
  } else {
    // 普通模型：替换 chip 为选中模型，禁用 chip 输入
    clearTagChips();
    addTagChip(value);
    setChipInputState(true, true);

    // 新增模式下同步显示名称
    const editIndex = parseInt(document.getElementById('modelEditIndex')?.value || '-1', 10);
    if (editIndex < 0) {
      const modelName = getModelNameFromCatalog(providerId, value);
      const nameEl = document.getElementById('modelName');
      if (nameEl && modelName) {
        nameEl.value = modelName;
      }
    }
  }
}

/** 处理服务商切换联动 */
function onProviderChangeInModal(providerId, options = {}) {
  const { isEdit = false } = options;
  updateProviderWebsiteDisplay(providerId);

  // 联动 API 地址
  const endpointEl = document.getElementById('modelEndpoint');
  if (isCustomProvider(providerId)) {
    // 自定义服务商：API 地址可编辑
    if (!isEdit) {
      if (endpointEl) endpointEl.value = '';
    }
    setEndpointReadonly(false);
  } else {
    // 非自定义服务商：API 地址自动填入 + 只读
    const defaultEp = getDefaultEndpoint(providerId);
    if (endpointEl) endpointEl.value = defaultEp;
    setEndpointReadonly(true);
  }

  // 联动模型 ID 下拉
  buildModelIdPresetOptions(providerId);
  const models = getModelCatalogModels(providerId);

  if (isCustomProvider(providerId)) {
    // 自定义服务商：默认选中"自定义配置"
    const select = document.getElementById('modelIdPreset');
    if (select) select.value = MODEL_ID_CUSTOM_VALUE;
    setChipInputState(true, false);
  } else if (!isEdit) {
    // 新增模式：选中默认模型
    const defaultId = pickDefaultCatalogModelId(providerId) || (models[0]?.id) || '';
    const select = document.getElementById('modelIdPreset');
    if (select && defaultId) select.value = defaultId;

    // 替换 chip 为默认模型
    clearTagChips();
    if (defaultId) addTagChip(defaultId);
    setChipInputState(true, true);

    // 同步显示名称
    const modelName = getModelNameFromCatalog(providerId, defaultId);
    const nameEl = document.getElementById('modelName');
    if (nameEl && modelName) {
      nameEl.value = modelName;
    }
  }

  // 联动 API 模式
  const provider = findProvider(providerId);
  const modeEl = document.getElementById('modelMode');
  if (provider && modeEl) {
    modeEl.value = provider.mode === 'openai-compatible' ? 'openai' : provider.mode;
  }
}

export function openModelModal(index, model = {}) {
  const isEdit = index >= 0;
  document.getElementById('modelEditIndex').value = String(index);
  document.getElementById('modelModalTitle').textContent = isEdit ? '编辑模型' : '新增模型';

  const providerId = isEdit ? (model.provider || '') : 'doubao';
  const providerEl = document.getElementById('modelProvider');
  if (providerEl) providerEl.value = providerId;

  // 构建 provider 联动
  buildModelIdPresetOptions(providerId);

  if (isEdit) {
    // 编辑模式：回填已有数据
    updateProviderWebsiteDisplay(providerId);

    // API 地址回填
    const endpointEl = document.getElementById('modelEndpoint');
    if (endpointEl) endpointEl.value = model.endpoint || '';
    if (isCustomProvider(providerId)) {
      setEndpointReadonly(false);
    } else {
      setEndpointReadonly(true);
    }

    // 模型 ID 下拉回填
    const modelIds = Array.isArray(model.model_ids) && model.model_ids.length
      ? model.model_ids
      : (model.modelId ? [model.modelId] : []);
    const defaultModelId = model.default_model_id || model.modelId || '';
    syncModelIdPresetFromForm(modelIds, defaultModelId, providerId);

    // chip 回填
    fillTagChips(modelIds, defaultModelId);

    // 根据下拉选中状态决定 chip 输入区
    const presetEl = document.getElementById('modelIdPreset');
    const isCustomModel = !presetEl || presetEl.value === MODEL_ID_CUSTOM_VALUE;
    if (isCustomModel) {
      setChipInputState(true, false);
    } else {
      setChipInputState(true, true);
    }

    // 显示名称：优先保留原名称
    document.getElementById('modelName').value = model.name || '';

    // API 模式回填
    document.getElementById('modelMode').value = model.mode || (document.getElementById('api_mode')?.value || 'doubao');
  } else {
    // 新增模式：默认 doubao + 联动
    onProviderChangeInModal(providerId, { isEdit: false });
  }

  document.getElementById('modelApiKey').value = isMaskedApiKey(model.apiKey)
    ? model.apiKey
    : (model.apiKey || '');
  const maxTokensEl = document.getElementById('modelMaxTokens');
  if (maxTokensEl) {
    const raw = model.max_tokens;
    let val = 512;
    if (typeof raw === 'number' && raw >= 512) val = raw;
    else if (raw) {
      const parsed = parseInt(raw, 10);
      if (!Number.isNaN(parsed) && parsed >= 512) val = parsed;
    }
    maxTokensEl.value = String(val);
  }
  document.getElementById('modelDescription').value = model.description || '';
  const supportsMicEl = document.getElementById('modelSupportsMic');
  if (supportsMicEl) supportsMicEl.checked = Boolean(model.supportsMic);
  const toggleKey = document.getElementById('toggleModelKey');
  if (toggleKey) toggleKey.checked = false;
  const apiKeyEl = document.getElementById('modelApiKey');
  if (apiKeyEl) apiKeyEl.type = 'password';
  const modal = document.getElementById('modelModal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  activateFocusTrap(modal, closeModelModal);
}

export function closeModelModal() {
  deactivateFocusTrap();
  const modal = document.getElementById('modelModal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

/**
 * 格式化删除模型档案的确认文案。
 * - name 为空时降级为「这条模型档案」
 * - N = profile.model_ids.length（缺失或为空时降级为 1）
 */
export function formatDeleteModelMessage(profile) {
  const name = (profile?.name || '').trim();
  const ids = Array.isArray(profile?.model_ids) ? profile.model_ids : [];
  const n = ids.length || 1;
  const display = name || '这条模型档案';
  return `确定删除模型「${display}」吗？该档案包含 ${n} 个模型 ID，将一并删除。若该档案是当前默认，将自动切换到下一条。`;
}

/** 一次性监听清理句柄（避免内存泄漏） */
let _deleteModelConfirmCleanup = null;

/**
 * 打开删除模型档案二次确认 Modal。
 * 复用 restoreDefaultsModal 风格：classList 切换 + activateFocusTrap / deactivateFocusTrap。
 * 一次性监听在关闭时清空，避免内存泄漏。
 */
export function openDeleteModelConfirm(profile, index) {
  const modal = document.getElementById('deleteModelConfirmModal');
  if (!modal) return;
  const messageEl = document.getElementById('deleteModelConfirmMessage');
  if (messageEl) messageEl.textContent = formatDeleteModelMessage(profile);

  // 先清理上一轮残留监听（防御性）
  if (typeof _deleteModelConfirmCleanup === 'function') {
    _deleteModelConfirmCleanup();
    _deleteModelConfirmCleanup = null;
  }

  modal.classList.remove('hidden');
  modal.classList.add('flex');
  activateFocusTrap(modal, closeDeleteModelConfirm);

  const okBtn = document.getElementById('btnDeleteModelConfirmOk');
  const cancelBtn = document.getElementById('btnDeleteModelConfirmCancel');

  const close = () => closeDeleteModelConfirm();

  const onConfirm = async () => {
    try {
      await apiFetch(`/api/custom-models/${index}`, { method: 'DELETE' });
      closeDeleteModelConfirm();
      customModelDeps.showToast('已删除~');
      loadCustomModels();
    } catch (error) {
      closeDeleteModelConfirm();
      customModelDeps.showToast(error.message, true);
    }
  };

  const onBackdropClick = (e) => {
    if (e.target === modal) close();
  };

  okBtn?.addEventListener('click', onConfirm, { once: true });
  cancelBtn?.addEventListener('click', close, { once: true });
  modal.addEventListener('click', onBackdropClick);

  _deleteModelConfirmCleanup = () => {
    okBtn?.removeEventListener('click', onConfirm);
    cancelBtn?.removeEventListener('click', close);
    modal.removeEventListener('click', onBackdropClick);
    _deleteModelConfirmCleanup = null;
  };
}

/** 关闭删除模型档案二次确认 Modal，并清空一次性监听 */
export function closeDeleteModelConfirm() {
  const modal = document.getElementById('deleteModelConfirmModal');
  if (modal) {
    modal.classList.add('hidden');
    modal.classList.remove('flex');
  }
  if (typeof _deleteModelConfirmCleanup === 'function') {
    _deleteModelConfirmCleanup();
    _deleteModelConfirmCleanup = null;
  }
  deactivateFocusTrap();
}

export function collectModelForm() {
  const modelIds = getModelIdsFromChips();
  const defaultModelId = getDefaultModelIdFromChips();
  const maxTokensRaw = parseInt(document.getElementById('modelMaxTokens')?.value || '512', 10);
  const maxTokens = Number.isNaN(maxTokensRaw) || maxTokensRaw < 512 ? 512 : maxTokensRaw;
  return {
    name: document.getElementById('modelName').value,
    modelId: defaultModelId,
    model_ids: modelIds,
    default_model_id: defaultModelId,
    max_tokens: maxTokens,
    mode: document.getElementById('modelMode').value,
    endpoint: document.getElementById('modelEndpoint').value,
    apiKey: document.getElementById('modelApiKey').value,
    description: document.getElementById('modelDescription').value,
    provider: document.getElementById('modelProvider').value,
    supportsMic: Boolean(document.getElementById('modelSupportsMic')?.checked),
  };
}

export async function saveModel() {
  const index = parseInt(document.getElementById('modelEditIndex').value, 10);
  const body = collectModelForm();
  if (!body.model_ids.length) {
    throw new Error('请至少添加一个模型 ID');
  }
  if (index >= 0) {
    await apiFetch(`/api/custom-models/${index}`, { method: 'PUT', body: JSON.stringify(body) });
  } else {
    await apiFetch('/api/custom-models', { method: 'POST', body: JSON.stringify(body) });
  }
  closeModelModal();
  customModelDeps.showToast('模型已保存~');
  loadCustomModels();
}

export async function probe() {
  const index = parseInt(document.getElementById('modelEditIndex')?.value || '-1', 10);
  const form = collectModelForm();
  if (!form.model_ids.length) {
    throw new Error('请至少添加一个模型 ID');
  }
  const res = await apiFetch('/api/custom-models/probe', {
    method: 'POST',
    body: JSON.stringify({ ...form, index, model_id: form.default_model_id }),
  });
  customModelDeps.showToast(res.message, !res.ok);
  return res;
}

export function initModelModalBindings() {
  const providerEl = document.getElementById('modelProvider');
  if (providerEl) {
    providerEl.addEventListener('change', (e) => {
      const isEdit = parseInt(document.getElementById('modelEditIndex')?.value || '-1', 10) >= 0;
      onProviderChangeInModal(e.target.value, { isEdit });
    });
  }
  const presetEl = document.getElementById('modelIdPreset');
  if (presetEl) {
    presetEl.addEventListener('change', () => {
      onModelIdPresetChange();
    });
  }
  // W-SETTINGS-RESTRUCT-A-006：「+ 添加模型」按钮 → openModelModal(-1)（新增模型；index < 0）
  const addBtn = document.getElementById('btnAddCustomModel');
  if (addBtn) {
    addBtn.addEventListener('click', () => openModelModal(-1));
  }
  const openBtn = document.getElementById('modelOpenWebsite');
  if (openBtn) {
    openBtn.addEventListener('click', () => {
      const website = openBtn.dataset.website || getProviderWebsite(document.getElementById('modelProvider')?.value);
      if (website) window.open(website, '_blank');
    });
  }
  const toggleKey = document.getElementById('toggleModelKey');
  if (toggleKey) {
    toggleKey.addEventListener('change', () => {
      const inp = document.getElementById('modelApiKey');
      if (inp) inp.type = toggleKey.checked ? 'text' : 'password';
    });
  }
  const { input } = getTagInputState();
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (input.disabled) return;
      if (e.key === 'Enter' || e.key === ',') {
        e.preventDefault();
        addTagChip(input.value);
      } else if (e.key === 'Backspace' && !input.value) {
        const chips = readTagChips();
        if (chips.length) {
          const last = chips[chips.length - 1];
          const wasDefault = last.isDefault;
          last.el.remove();
          if (wasDefault) markFirstChipDefault();
        }
      }
    });
    input.addEventListener('blur', () => {
      if (input.disabled) return;
      if (input.value) addTagChip(input.value);
    });
  }
}

export { addTagChip, getModelIdsFromChips, getDefaultModelIdFromChips, markFirstChipDefault, clearTagChips, fillTagChips, readTagChips, TAG_MAX_LEN };

