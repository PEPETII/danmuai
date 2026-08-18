import { apiFetch } from './transport.js';

let toast = () => {};
let handlersBound = false;
let requestInFlight = false;
let modelSettingsCache = null;
let modelSettingsSaveToken = 0;
let clickThroughSaveToken = 0;
let displayScaleSaveToken = 0;
let hostSettingsCache = null;
let hostSettingsSaveToken = 0;

const DISPLAY_SCALE_MIN = 25;
const DISPLAY_SCALE_MAX = 300;
const DISPLAY_SCALE_DEFAULT = 100;

const CAPABILITY_LABELS = [
  ['dependency_count', '依赖'], ['texture_count', '纹理'], ['parameter_count', '参数'],
  ['motion_files', '原生动作'], ['expression_files', '表情'], ['physics', '物理'],
];

function element(id) { return document.getElementById(id); }
function setText(id, value) { const target = element(id); if (target) target.textContent = value; }

function renderModelSettingsStatus(message) {
  setText('vtuberModelSettingsStatus', message || '');
}

function renderClickThroughStatus(message) {
  setText('vtuberClickThroughStatus', message || '');
}

function renderDisplayScaleStatus(message) {
  setText('vtuberDisplayScaleStatus', message || '');
}

function renderModeSettingsStatus(message) {
  setText('vtuberModeSettingsStatus', message || '');
}

function clampDisplayScalePercent(value) {
  const parsed = Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed)) return DISPLAY_SCALE_DEFAULT;
  return Math.min(DISPLAY_SCALE_MAX, Math.max(DISPLAY_SCALE_MIN, parsed));
}

function renderDisplayScale(data) {
  const percent = clampDisplayScalePercent(data?.display_scale_percent ?? DISPLAY_SCALE_DEFAULT);
  const range = element('vtuberDisplayScaleRange');
  const input = element('vtuberDisplayScaleInput');
  const resetButton = element('btnVtuberDisplayScaleReset');
  const configured = data?.configured === true && Boolean(data?.model_id);
  if (range) {
    range.value = String(percent);
    range.disabled = !configured;
  }
  if (input) {
    input.value = String(percent);
    input.disabled = !configured;
  }
  if (resetButton) resetButton.disabled = !configured;
  renderDisplayScaleStatus(
    configured
      ? `当前模型显示大小为 ${percent}%。`
      : '导入模型后可调整显示大小。',
  );
}

async function saveDisplayScale(percent, { silent = false } = {}) {
  const normalized = clampDisplayScalePercent(percent);
  const token = ++displayScaleSaveToken;
  renderDisplayScaleStatus('正在保存显示大小…');
  try {
    const data = await apiFetch('/api/live2d/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ display_scale_percent: normalized }),
    });
    if (token !== displayScaleSaveToken) return data;
    renderDisplayScale(data);
    if (!silent) toast(`显示大小已设为 ${normalized}%`);
    return data;
  } catch (error) {
    if (token === displayScaleSaveToken) {
      renderDisplayScaleStatus(error?.message || '保存显示大小失败');
    }
    throw error;
  }
}

function renderClickThrough(data) {
  const toggle = element('vtuberClickThrough');
  if (toggle) toggle.checked = Boolean(data?.click_through);
  renderClickThroughStatus(
    data?.click_through
      ? '鼠标穿透已开启，虚拟主播窗口不再拦截鼠标事件。'
      : '鼠标穿透已关闭，可拖动虚拟主播窗口。',
  );
}

async function saveClickThrough(enabled) {
  const token = ++clickThroughSaveToken;
  renderClickThroughStatus('正在保存鼠标穿透设置…');
  try {
    const data = await apiFetch('/api/live2d/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ click_through: Boolean(enabled) }),
    });
    if (token !== clickThroughSaveToken) return data;
    renderClickThrough(data);
    toast(enabled ? '鼠标穿透已开启' : '鼠标穿透已关闭');
    return data;
  } catch (error) {
    if (token === clickThroughSaveToken) {
      renderClickThroughStatus(error?.message || '保存鼠标穿透设置失败');
    }
    throw error;
  }
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

function snapshotHostModeSettings() {
  return {
    dialogue_enabled: Boolean(hostSettingsCache?.dialogue_enabled),
    danmu_adapter_enabled: Boolean(hostSettingsCache?.danmu_adapter_enabled),
  };
}

function describeHostModeSettings(data) {
  const dialogue = Boolean(data?.dialogue_enabled);
  const adapter = Boolean(data?.danmu_adapter_enabled);
  if (dialogue) return '虚拟主播对话已开启。';
  if (adapter) return 'AI读弹幕适配已开启。';
  return '两种互动模式均已关闭。';
}

function renderHostSettings(data) {
  hostSettingsCache = data || null;
  const dialogueToggle = element('vtuberDialogueEnabled');
  const adapterToggle = element('vtuberDanmuAdapterEnabled');
  if (dialogueToggle) dialogueToggle.checked = Boolean(data?.dialogue_enabled);
  if (adapterToggle) adapterToggle.checked = Boolean(data?.danmu_adapter_enabled);
  renderModeSettingsStatus(describeHostModeSettings(data));
}

function syncRuntimeStatusToHostSettings(runtimeStatus) {
  if (!hostSettingsCache) return;
  hostSettingsCache = { ...hostSettingsCache, runtime_status: runtimeStatus };
}

async function loadHostSettings() {
  try {
    renderHostSettings(await apiFetch('/api/virtual-host/settings'));
  } catch (error) {
    renderModeSettingsStatus(error?.message || '读取互动模式失败');
    throw error;
  }
}

async function saveHostSettings(patch) {
  const previous = snapshotHostModeSettings();
  const optimistic = { ...previous };
  if (patch.dialogue_enabled === true) {
    optimistic.dialogue_enabled = true;
    optimistic.danmu_adapter_enabled = false;
  } else if (patch.dialogue_enabled === false) {
    optimistic.dialogue_enabled = false;
  }
  if (patch.danmu_adapter_enabled === true) {
    optimistic.danmu_adapter_enabled = true;
    optimistic.dialogue_enabled = false;
  } else if (patch.danmu_adapter_enabled === false) {
    optimistic.danmu_adapter_enabled = false;
  }
  renderHostSettings({ ...(hostSettingsCache || {}), ...optimistic });
  const token = ++hostSettingsSaveToken;
  renderModeSettingsStatus('正在保存互动模式…');
  try {
    const data = await apiFetch('/api/virtual-host/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (token !== hostSettingsSaveToken) return data;
    renderHostSettings(data);
    toast('互动模式已保存');
    return data;
  } catch (error) {
    if (token === hostSettingsSaveToken) {
      renderHostSettings({ ...(hostSettingsCache || {}), ...previous });
      renderModeSettingsStatus(error?.message || '保存互动模式失败');
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
  renderClickThrough(model);
  renderDisplayScale(model);
  syncRuntimeStatusToHostSettings(runtimeStatus);
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
    await Promise.all([
      loadModelSettings(),
      loadHostSettings(),
      apiFetch('/api/live2d/model').then((data) => renderModel(data)),
    ]);
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
  element('vtuberClickThrough')?.addEventListener('change', (event) => {
    saveClickThrough(Boolean(event.target?.checked))
      .catch((error) => toast(error.message, true));
  });
  element('vtuberDialogueEnabled')?.addEventListener('change', (event) => {
    const enabled = Boolean(event.target?.checked);
    saveHostSettings({ dialogue_enabled: enabled })
      .catch((error) => toast(error.message, true));
  });
  element('vtuberDanmuAdapterEnabled')?.addEventListener('change', (event) => {
    const enabled = Boolean(event.target?.checked);
    saveHostSettings({ danmu_adapter_enabled: enabled })
      .catch((error) => toast(error.message, true));
  });
  const displayScaleRange = element('vtuberDisplayScaleRange');
  const displayScaleInput = element('vtuberDisplayScaleInput');
  const syncDisplayScaleControls = (percent, { persist = false } = {}) => {
    const normalized = clampDisplayScalePercent(percent);
    if (displayScaleRange) displayScaleRange.value = String(normalized);
    if (displayScaleInput) displayScaleInput.value = String(normalized);
    if (persist) {
      saveDisplayScale(normalized).catch((error) => toast(error.message, true));
    }
  };
  displayScaleRange?.addEventListener('input', (event) => {
    syncDisplayScaleControls(event.target?.value);
  });
  displayScaleRange?.addEventListener('change', (event) => {
    syncDisplayScaleControls(event.target?.value, { persist: true });
  });
  displayScaleInput?.addEventListener('change', (event) => {
    syncDisplayScaleControls(event.target?.value, { persist: true });
  });
  element('btnVtuberDisplayScaleReset')?.addEventListener('click', () => {
    syncDisplayScaleControls(DISPLAY_SCALE_DEFAULT, { persist: true });
  });
  element('btnVtuberImportModel')?.addEventListener('click', () => importModel().catch((error) => toast(error.message, true)));
  element('btnVtuberImportModelAdvanced')?.addEventListener('click', () => importModel('/api/live2d/import-model-file').catch((error) => toast(error.message, true)));
  element('btnVtuberClearModel')?.addEventListener('click', () => clearModel().catch((error) => toast(error.message, true)));
  element('btnVtuberStart')?.addEventListener('click', () => startModel().catch((error) => toast(error.message, true)));
  element('btnVtuberStop')?.addEventListener('click', () => stopModel().catch((error) => toast(error.message, true)));
}
