import { apiFetch } from './transport.js';

let toast = () => {};
let handlersBound = false;
let requestInFlight = false;
let modelSettingsCache = null;
let modelSettingsSaveToken = 0;

const CAPABILITY_LABELS = [
  ['dependency_count', '依赖'], ['texture_count', '纹理'], ['parameter_count', '参数'],
  ['motion_files', '原生动作'], ['expression_files', '表情'], ['physics', '物理'],
];

function element(id) { return document.getElementById(id); }
function setText(id, value) { const target = element(id); if (target) target.textContent = value; }

function renderModelSettingsStatus(message) {
  setText('vtuberModelSettingsStatus', message || '');
}

function fillSelectOptions(select, options, selectedValue) {
  if (!select) return;
  select.replaceChildren();
  const none = document.createElement('option');
  none.value = '';
  none.textContent = '无';
  select.appendChild(none);
  (options || []).forEach((item) => {
    const option = document.createElement('option');
    option.value = String(item.id || '');
    option.textContent = String(item.label || item.id || '');
    select.appendChild(option);
  });
  const normalized = String(selectedValue || '');
  if (normalized && [...select.options].some((option) => option.value === normalized)) {
    select.value = normalized;
  } else {
    select.value = '';
  }
}

function renderModelSettings(data) {
  modelSettingsCache = data || null;
  const visionSelect = element('vtuberVisionModelSelect');
  const ttsSelect = element('vtuberTtsModelSelect');
  fillSelectOptions(visionSelect, data?.vision_options, data?.vision_model_id);
  fillSelectOptions(ttsSelect, data?.tts_options, data?.tts_option_id);
  const visionLabel = data?.vision_enabled ? '已选择视觉模型' : '视觉理解已关闭';
  const ttsLabel = data?.tts_enabled ? '已选择 TTS 模型' : '语音合成已关闭';
  renderModelSettingsStatus(`${visionLabel}；${ttsLabel}`);
}

async function loadModelSettings() {
  try {
    renderModelSettings(await apiFetch('/api/virtual-host/models'));
  } catch (error) {
    renderModelSettingsStatus(error?.message || '读取模型设置失败');
    throw error;
  }
}

async function saveModelSettings(patch) {
  const token = ++modelSettingsSaveToken;
  renderModelSettingsStatus('正在保存模型设置…');
  try {
    const data = await apiFetch('/api/virtual-host/models', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (token !== modelSettingsSaveToken) return data;
    renderModelSettings(data);
    toast('虚拟主播模型设置已保存');
    return data;
  } catch (error) {
    if (token === modelSettingsSaveToken) {
      renderModelSettingsStatus(error?.message || '保存模型设置失败');
    }
    throw error;
  }
}

function modelFromResponse(data) { return data?.model ?? data?.result ?? data ?? {}; }

function normalizeModel(data) {
  const model = modelFromResponse(data);
  const capabilities = model.capabilities || {};
  const modelPath = String(model.model_path || '');
  const safePathName = modelPath.split('/').pop().split('\\').pop();
  const fileName = model.model_file_name || model.file_name || model.filename
    || (model.model_name ? `${model.model_name}.model3.json` : safePathName);
  return {
    ...model,
    capabilities,
    fileName: String(fileName || ''),
    loaded: model.ok === true || model.status === 'ready',
  };
}

function countCapability(model, key) {
  const value = model.capabilities?.[key];
  if (Array.isArray(value)) return value.length;
  if (key === 'parameter_count' && value == null) return model.capabilities?.parameter_ids?.length || 0;
  return value == null ? 0 : value;
}

function renderCapabilities(model) {
  const container = element('vtuberCapabilities');
  if (!container) return;
  container.replaceChildren();
  CAPABILITY_LABELS.forEach(([key, label]) => {
    const item = document.createElement('div'); item.className = 'vtuber-capability';
    const value = document.createElement('strong');
    const count = countCapability(model, key);
    value.textContent = key === 'physics' ? (count ? '支持' : '无') : String(count);
    item.append(value, document.createTextNode(label)); container.appendChild(item);
  });
  const missing = model.capabilities?.missing_dependencies || [];
  if (missing.length) {
    const warning = document.createElement('p'); warning.className = 'text-sm text-amber-700';
    warning.textContent = `缺少依赖：${missing.join('、')}`; container.appendChild(warning);
  }
}

function renderRequestError(error) {
  const message = error?.message || 'Live2D 操作失败';
  const target = element('vtuberModelError');
  if (target) { target.textContent = message; target.classList.remove('hidden'); }
  setText('vtuberStatusText', '操作失败'); setText('vtuberStatusBadge', '错误');
  setText('vtuberRuntimeStatus', message); setText('vtuberDesktopStatusText', '错误');
  setText('vtuberDesktopStatusHint', '桌面窗口控制失败，请查看上方错误信息。');
}

function renderModel(data) {
  const model = normalizeModel(data);
  const configured = model.configured === true;
  const hasModel = configured && Boolean(model.fileName);
  const runtimeStatus = model.runtime_status || 'stopped';
  const running = runtimeStatus === 'running';
  const statusText = model.status === 'blocked' ? '模型不可用' : model.status === 'invalid' ? '模型无效'
    : hasModel ? (running ? '运行中' : '已导入') : '未导入';
  setText('vtuberStatusText', data?.cancelled ? '已取消选择' : statusText);
  setText('vtuberStatusBadge', running ? '运行中' : model.loaded ? '已就绪' : '未导入');
  setText('vtuberModelFileName', model.fileName || '未选择模型');
  setText('vtuberModelState', model.status || (hasModel ? 'ready' : '未导入'));
  setText('vtuberModelText', model.loaded ? '当前模型已通过本机资源代理准备就绪。' : configured ? '当前登记的 Live2D 模型不可用，请重新导入。' : '尚未导入 Live2D 模型。');
  setText('vtuberRuntimeStatus', running ? '模型已在桌面窗口显示。' : model.loaded ? '模型已就绪，可以启动虚拟主播。' : '请先导入可用模型。');
  setText('vtuberDesktopStatusText', running ? '运行中' : '未启动');
  setText('vtuberDesktopStatusHint', running ? '模型已在桌面窗口显示。' : '启动后模型将在桌面窗口显示，当前页面不会渲染 Live2D。');
  renderCapabilities(model);
  const error = data?.error || (model.loaded ? '' : model.reason || '');
  const errorElement = element('vtuberModelError');
  if (errorElement) { errorElement.textContent = error; errorElement.classList.toggle('hidden', !error); }
  const importButton = element('btnVtuberImportModel'); const clearButton = element('btnVtuberClearModel');
  const advancedButton = element('btnVtuberImportModelAdvanced');
  const startButton = element('btnVtuberStart'); const stopButton = element('btnVtuberStop');
  if (importButton) importButton.disabled = requestInFlight;
  if (advancedButton) advancedButton.disabled = requestInFlight;
  if (clearButton) clearButton.disabled = requestInFlight || !hasModel;
  if (startButton) startButton.disabled = requestInFlight || !model.loaded || running;
  if (stopButton) stopButton.disabled = requestInFlight || !running;
}

function setRequestState(active) {
  requestInFlight = active;
  const current = element('vtuberModelFileName')?.textContent || '';
  const hasModel = current && current !== '未选择模型';
  const importButton = element('btnVtuberImportModel'); if (importButton) importButton.disabled = active;
  const advancedButton = element('btnVtuberImportModelAdvanced'); if (advancedButton) advancedButton.disabled = active;
  const clearButton = element('btnVtuberClearModel'); if (clearButton) clearButton.disabled = active || !hasModel;
  const running = element('vtuberStatusBadge')?.textContent === '运行中';
  const startButton = element('btnVtuberStart'); if (startButton) startButton.disabled = active || !hasModel || running;
  const stopButton = element('btnVtuberStop'); if (stopButton) stopButton.disabled = active || !running;
}

async function startModel() {
  setRequestState(true);
  try {
    const response = await apiFetch('/api/live2d/start', { method: 'POST' });
    if (response?.runtime_status !== 'running') throw new Error(response?.error || '桌面窗口启动失败');
    renderModel(response);
    setText('vtuberRuntimeStatus', '模型已在桌面窗口显示。');
    setText('vtuberDesktopStatusText', '运行中');
    setText('vtuberDesktopStatusHint', '模型已在桌面窗口显示。');
    toast('模型已在桌面窗口显示');
  } catch (error) { renderRequestError(error); throw error; } finally { setRequestState(false); }
}

async function stopModel() {
  setRequestState(true);
  try {
    const response = await apiFetch('/api/live2d/stop', { method: 'POST' });
    renderModel(response); toast('虚拟主播已停止');
  } catch (error) { renderRequestError(error); throw error; } finally { setRequestState(false); }
}

async function importModel(endpoint = '/api/live2d/import-model') {
  setRequestState(true);
  try {
    const data = await apiFetch(endpoint, { method: 'POST' });
    renderModel(data);
    if (!data?.cancelled) toast('Live2D 模型已导入，可以启动虚拟主播');
  } catch (error) { renderRequestError(error); throw error; } finally { setRequestState(false); }
}

async function clearModel() {
  setRequestState(true);
  try {
    if (element('vtuberStatusBadge')?.textContent === '运行中') {
      await apiFetch('/api/live2d/stop', { method: 'POST' });
    }
    renderModel(await apiFetch('/api/live2d/clear-model', { method: 'POST' })); toast('Live2D 模型已移除');
  } catch (error) { renderRequestError(error); throw error; } finally { setRequestState(false); }
}

export async function loadVtuberPage() {
  try {
    await loadModelSettings();
    renderModel(await apiFetch('/api/live2d/model'));
  } catch (error) { renderRequestError(error); throw error; }
}

export function initVtuberPage(deps = {}) {
  toast = deps.showToast || toast; if (handlersBound) return; handlersBound = true;
  element('vtuberVisionModelSelect')?.addEventListener('change', () => {
    saveModelSettings({ vision_model_id: element('vtuberVisionModelSelect')?.value || '' })
      .catch((error) => toast(error.message, true));
  });
  element('vtuberTtsModelSelect')?.addEventListener('change', () => {
    saveModelSettings({ tts_option_id: element('vtuberTtsModelSelect')?.value || '' })
      .catch((error) => toast(error.message, true));
  });
  element('btnVtuberImportModel')?.addEventListener('click', () => importModel().catch((error) => toast(error.message, true)));
  element('btnVtuberImportModelAdvanced')?.addEventListener('click', () => importModel('/api/live2d/import-model-file').catch((error) => toast(error.message, true)));
  element('btnVtuberClearModel')?.addEventListener('click', () => clearModel().catch((error) => toast(error.message, true)));
  element('btnVtuberStart')?.addEventListener('click', () => startModel().catch((error) => toast(error.message, true)));
  element('btnVtuberStop')?.addEventListener('click', () => stopModel().catch((error) => toast(error.message, true)));
}
