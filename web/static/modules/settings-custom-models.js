import { apiFetch } from './transport.js';

let customModelDeps = {
  showToast: () => {},
  reloadConfigFromServer: async () => ({}),
  syncVisionModelPickerFromForm: () => {},
  updateModelActiveSourceBanner: () => {},
};

let cachedCustomModels = [];

export function getCachedCustomModels() {
  return cachedCustomModels;
}

export function customModelSupportsMic(modelId) {
  const id = (modelId || '').trim();
  if (!id) return false;
  const hit = cachedCustomModels.find((model) => (model.modelId || '').trim() === id);
  return Boolean(hit?.supportsMic);
}

export function configureSettingsCustomModels(deps) {
  customModelDeps = { ...customModelDeps, ...deps };
}

export async function loadCustomModels() {
  const data = await apiFetch('/api/custom-models');
  cachedCustomModels = data.items || [];
  const list = document.getElementById('customModelsList');
  if (!list) return;
  list.innerHTML = '';
  if (!data.items.length) {
    list.innerHTML = '<p class="text-sm text-gray-400">暂无自定义模型，点击上方新增~</p>';
    return;
  }
  data.items.forEach((model, index) => {
    const row = document.createElement('div');
    row.className = 'flex flex-wrap items-center gap-2 p-3 bg-cream rounded-xl text-sm';
    const isDefault = model.modelId === data.default_model_id;
    row.innerHTML = `
      <span class="font-semibold text-warmText">${model.name || '未命名'}</span>
      <span class="text-gray-400">${model.modelId}</span>
      ${isDefault ? '<span class="text-green-600 text-xs font-bold">默认</span>' : ''}
      ${model.supportsMic ? '<span class="text-sky-600 text-xs font-bold">支持麦克风</span>' : ''}
      ${model.complete === false ? '<span class="text-amber-600 text-xs font-bold">配置不完整</span>' : ''}
    `;
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.className = 'px-3 py-1 border border-gray-200 rounded-lg text-xs';
    editBtn.textContent = '编辑';
    editBtn.onclick = () => openModelModal(index, model);
    const delBtn = document.createElement('button');
    delBtn.type = 'button';
    delBtn.className = 'px-3 py-1 border border-red-200 rounded-lg text-xs text-red-600';
    delBtn.textContent = '删除';
    delBtn.onclick = async () => {
      if (!confirm(`确定删除模型「${model.name}」吗？`)) return;
      try {
        await apiFetch(`/api/custom-models/${index}`, { method: 'DELETE' });
        customModelDeps.showToast('已删除~');
        loadCustomModels();
      } catch (error) {
        customModelDeps.showToast(error.message, true);
      }
    };
    row.appendChild(editBtn);
    row.appendChild(delBtn);
    if (!isDefault) {
      const defBtn = document.createElement('button');
      defBtn.type = 'button';
      defBtn.className = 'px-3 py-1 border border-gray-200 rounded-lg text-xs';
      defBtn.textContent = '设为默认';
      defBtn.onclick = async () => {
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
      };
      row.appendChild(defBtn);
    }
    list.appendChild(row);
  });
}

export function openModelModal(index, model = {}) {
  document.getElementById('modelEditIndex').value = String(index);
  document.getElementById('modelModalTitle').textContent = index >= 0 ? '编辑模型' : '新增模型';
  document.getElementById('modelName').value = model.name || '';
  document.getElementById('modelId').value = model.modelId || '';
  document.getElementById('modelMode').value = model.mode || 'doubao';
  document.getElementById('modelEndpoint').value = model.endpoint || '';
  document.getElementById('modelApiKey').value = model.apiKey === '********' ? '********' : (model.apiKey || '');
  document.getElementById('modelDescription').value = model.description || '';
  const supportsMicEl = document.getElementById('modelSupportsMic');
  if (supportsMicEl) supportsMicEl.checked = Boolean(model.supportsMic);
  const modal = document.getElementById('modelModal');
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

export function closeModelModal() {
  const modal = document.getElementById('modelModal');
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

export function collectModelForm() {
  return {
    name: document.getElementById('modelName').value,
    modelId: document.getElementById('modelId').value,
    mode: document.getElementById('modelMode').value,
    endpoint: document.getElementById('modelEndpoint').value,
    apiKey: document.getElementById('modelApiKey').value,
    description: document.getElementById('modelDescription').value,
    provider: document.getElementById('modelProvider').value,
    supportsMic: Boolean(document.getElementById('modelSupportsMic')?.checked),
  };
}
