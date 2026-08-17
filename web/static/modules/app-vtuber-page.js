import { apiFetch } from './transport.js';

let toast = () => {};
let handlersBound = false;
let requestInFlight = false;

const CAPABILITY_LABELS = [
  ['dependency_count', '依赖'],
  ['texture_count', '纹理'],
  ['parameter_count', '参数'],
  ['motion_groups', '原生动作'],
  ['expression_ids', '表情'],
  ['physics', '物理'],
];

function element(id) {
  return document.getElementById(id);
}

function setText(id, value) {
  const target = element(id);
  if (target) target.textContent = value;
}

function renderRequestError(error) {
  const message = error?.message || '模型状态读取失败';
  const target = element('vtuberModelError');
  if (target) {
    target.textContent = message;
    target.classList.remove('hidden');
  }
  setText('vtuberStatusText', '读取失败');
  setText('vtuberStatusBadge', '错误');
}

function modelFromResponse(data) {
  return data?.model ?? data?.result ?? data ?? {};
}

function normalizeModel(data) {
  const model = modelFromResponse(data);
  const capabilities = model.capabilities || {};
  const modelPath = String(model.model_path || '');
  const fileName = model.file_name || model.model_file_name || model.filename
    || modelPath.split('/').pop().split('\\').pop();
  return {
    ...model,
    capabilities,
    fileName: String(fileName || ''),
    loaded: model.ok === true || ['ready', 'loaded', 'started'].includes(model.status),
  };
}

function capabilityValue(model, key) {
  const value = model.capabilities?.[key];
  if (Array.isArray(value)) return value.length;
  if (key === 'dependency_count' && value == null) return model.capabilities?.dependencies?.length ?? 0;
  if (key === 'parameter_count' && value == null) return model.capabilities?.parameter_ids?.length ?? 0;
  if (key === 'motion_groups' && value == null) return model.capabilities?.motions?.length ?? 0;
  if (key === 'expression_ids' && value == null) return model.capabilities?.expressions?.length ?? 0;
  return value == null ? 0 : value;
}

function renderCapabilities(model) {
  const container = element('vtuberCapabilities');
  if (!container) return;
  container.replaceChildren();
  const missing = model.capabilities?.missing_dependencies || [];
  if (model.loaded) {
    CAPABILITY_LABELS.forEach(([key, label]) => {
      const item = document.createElement('div');
      item.className = 'vtuber-capability';
      const value = document.createElement('strong');
      value.textContent = key === 'physics'
        ? (capabilityValue(model, key) ? '支持' : '无')
        : String(capabilityValue(model, key));
      item.append(value, document.createTextNode(label));
      container.appendChild(item);
    });
  }
  if (missing.length) {
    const warning = document.createElement('p');
    warning.className = 'text-sm text-amber-700';
    warning.textContent = `缺少依赖：${missing.join('、')}`;
    container.appendChild(warning);
  }
}

function renderModel(data) {
  const model = normalizeModel(data);
  const cancelled = data?.cancelled === true;
  const configured = model.configured === true;
  const hasModel = configured && Boolean(model.fileName);
  const hasDisplayName = Boolean(model.fileName);
  const statusText = model.status === 'blocked'
    ? (configured ? '模型不可用' : '导入失败')
    : model.status === 'invalid'
      ? (configured ? '模型无效' : '导入失败')
      : hasModel
        ? '已导入'
        : '未导入';
  setText('vtuberStatusText', cancelled ? '已取消选择' : statusText);
  setText(
    'vtuberStatusBadge',
    cancelled ? '已取消' : model.loaded ? '已就绪' : configured ? '需处理' : '未导入',
  );
  setText('vtuberModelFileName', hasDisplayName ? model.fileName : '未选择模型');
  setText(
    'vtuberModelState',
    cancelled ? '未改变' : model.status || (hasModel ? 'ready' : '未导入'),
  );
  setText(
    'vtuberModelText',
    model.loaded
      ? '当前模型已通过桌面原生选择器登记。'
      : configured
        ? '当前登记的 Live2D 模型不可用，请重新导入。'
        : hasDisplayName
          ? '所选模型未保存，请检查模型依赖后重试。'
          : '尚未导入 Live2D 模型。',
  );
  const clearButton = element('btnVtuberClearModel');
  if (clearButton) clearButton.disabled = requestInFlight || !hasModel;
  renderCapabilities(model);
  const error = data?.error || (model.loaded ? '' : model.reason && !cancelled ? model.reason : '');
  const errorElement = element('vtuberModelError');
  if (errorElement) {
    errorElement.textContent = error;
    errorElement.classList.toggle('hidden', !error);
  }
}

function setRequestState(active) {
  requestInFlight = active;
  const importButton = element('btnVtuberImportModel');
  const clearButton = element('btnVtuberClearModel');
  if (importButton) importButton.disabled = active;
  if (clearButton) clearButton.disabled = active || !element('vtuberModelFileName')?.textContent || element('vtuberModelFileName').textContent === '未选择模型';
}

async function importModel() {
  setRequestState(true);
  try {
    const data = await apiFetch('/api/live2d/import-model', { method: 'POST' });
    renderModel(data);
    if (!data?.cancelled) toast('Live2D 模型已导入');
  } catch (error) {
    renderRequestError(error);
    throw error;
  } finally {
    setRequestState(false);
  }
}

async function clearModel() {
  setRequestState(true);
  try {
    const data = await apiFetch('/api/live2d/clear-model', { method: 'POST' });
    renderModel(data);
    toast('Live2D 模型已移除');
  } catch (error) {
    renderRequestError(error);
    throw error;
  } finally {
    setRequestState(false);
  }
}

export async function loadVtuberPage() {
  try {
    renderModel(await apiFetch('/api/live2d/model'));
  } catch (error) {
    renderRequestError(error);
    throw error;
  }
}

export function initVtuberPage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;
  element('btnVtuberImportModel')?.addEventListener('click', () => {
    importModel().catch((error) => toast(error.message, true));
  });
  element('btnVtuberClearModel')?.addEventListener('click', () => {
    clearModel().catch((error) => toast(error.message, true));
  });
}
