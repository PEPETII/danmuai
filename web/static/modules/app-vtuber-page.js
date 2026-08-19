import { apiFetch } from './transport.js';

let toast = () => {};
let handlersBound = false;
let requestInFlight = false;
let modelSettingsCache = null;
let modelSettingsSaveToken = 0;
let live2dModelCache = null;
let live2dModelSaveToken = 0;
let clickThroughSaveToken = 0;
let displayScaleSaveToken = 0;
let hostSettingsCache = null;
let hostSettingsSaveToken = 0;
let voiceStatusCache = null;
let voiceSessionArmed = false;
let voiceRequestInFlight = false;

const DISPLAY_SCALE_MIN = 25;
const DISPLAY_SCALE_MAX = 300;
const DISPLAY_SCALE_DEFAULT = 100;

const CAPABILITY_SUMMARY_LABELS = [
  ['motion_files', '动作'],
  ['expression_files', '表情'],
  ['physics', '物理'],
  ['texture_count', '纹理'],
];

function element(id) { return document.getElementById(id); }
function setText(id, value) { const target = element(id); if (target) target.textContent = value; }

function formatPipelineToken(value) {
  const text = String(value || '').trim();
  return text || '—';
}

function setStatusPill(state, label) {
  const pill = element('vtuberStatusBadge');
  const labelNode = element('vtuberStatusText');
  if (labelNode) labelNode.textContent = label;
  if (!pill) return;
  pill.dataset.state = state;
  pill.className = `vtuber-status-pill vtuber-status-pill--${state}`;
}

function renderAdvancedDiagnostics(model = null, voiceStatus = voiceStatusCache) {
  const normalized = model ? normalizeModel(model) : null;
  const modelPath = String(normalized?.model_path || model?.model_path || '').trim();
  setText('vtuberAdvancedModelPath', modelPath || '—');

  const runtimeStatus = String(
    normalized?.runtime_status || model?.runtime_status || hostSettingsCache?.runtime_status || 'stopped',
  );
  const running = runtimeStatus === 'running';
  const desktopVisible = Boolean(normalized?.desktop_visible ?? model?.desktop_visible);
  const runtimeLines = [
    running ? '虚拟主播运行中' : '虚拟主播未启动',
    desktopVisible ? '桌面窗口已显示' : '桌面窗口未显示',
    element('vtuberDesktopStatusHint')?.textContent || '',
  ].filter(Boolean);
  setText('vtuberAdvancedRuntimeState', runtimeLines.join('；'));

  const visionEnabled = Boolean(modelSettingsCache?.vision_enabled);
  const ttsEnabled = Boolean(modelSettingsCache?.tts_enabled);
  const pipelineParts = [
    `ASR ${formatPipelineToken(voiceStatus?.asr_status)}`,
    `LLM ${formatPipelineToken(voiceStatus?.llm_status)}`,
    `TTS ${formatPipelineToken(voiceStatus?.tts_status)}`,
    `语音 ${voiceStatus?.armed ? '已武装' : '未武装'}`,
    `视觉 ${visionEnabled ? '已启用' : '未启用'}`,
    `TTS 配置 ${ttsEnabled ? '已启用' : '未启用'}`,
  ];
  setText('vtuberAdvancedPipelineStatus', pipelineParts.join(' · '));

  const live2dLines = [
    normalized?.fileName || '未选择模型',
    normalized?.status || (normalized?.loaded ? 'ready' : '未导入'),
    normalized?.loaded ? '模型资源已就绪' : '模型资源未就绪',
  ].filter(Boolean);
  setText('vtuberAdvancedLive2dStatus', live2dLines.join(' · '));

  const diagnostics = [
    model?.error || normalized?.reason || '',
    voiceStatus?.failure_reason || '',
    voiceStatus?.blocking_error || '',
    voiceStatus?.mic_error || '',
  ].map((item) => String(item || '').trim()).filter(Boolean);
  setText('vtuberAdvancedDiagnostics', diagnostics.length ? diagnostics.join('；') : '—');
}

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

function renderKnowledgeSettingsStatus(message) {
  setText('vtuberKnowledgeSettingsStatus', message || '');
}

function isDialogueVoiceEligible(settings = hostSettingsCache) {
  return Boolean(settings?.dialogue_enabled)
    && !Boolean(settings?.danmu_adapter_enabled)
    && settings?.runtime_status === 'running';
}

function syncVoiceSessionArmed(data) {
  if (data && typeof data.armed === 'boolean') {
    voiceSessionArmed = data.armed;
  }
}

async function postVoiceAction(endpoint) {
  if (voiceRequestInFlight) return null;
  voiceRequestInFlight = true;
  try {
    const data = await apiFetch(endpoint, { method: 'POST' });
    syncVoiceSessionArmed(data);
    return data;
  } finally {
    voiceRequestInFlight = false;
  }
}

async function startVoiceSession({ silent = false } = {}) {
  if (!isDialogueVoiceEligible() || voiceSessionArmed || voiceRequestInFlight) return null;
  const data = await postVoiceAction('/api/virtual-host/voice/start');
  if (data && !silent) toast('已开始语音聆听');
  return data;
}

async function stopVoiceSession({ silent = false } = {}) {
  if (!voiceSessionArmed && !voiceRequestInFlight) return null;
  const data = await postVoiceAction('/api/virtual-host/voice/stop');
  if (data && !silent) toast('已停止语音聆听');
  return data;
}

async function cancelVoiceSession({ silent = false } = {}) {
  if (!voiceSessionArmed && !voiceRequestInFlight) return null;
  const data = await postVoiceAction('/api/virtual-host/voice/cancel');
  if (data && !silent) toast('已取消语音轮次');
  return data;
}

async function syncVoiceDialogueForRuntime({ silent = true } = {}) {
  if (isDialogueVoiceEligible()) {
    return startVoiceSession({ silent });
  }
  voiceSessionArmed = false;
  return cancelVoiceSession({ silent });
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

function renderLive2dModelSelect(data) {
  live2dModelCache = data || null;
  const select = element('vtuberLive2dModelSelect');
  if (!select) return;
  select.replaceChildren();
  const none = document.createElement('option');
  none.value = '';
  none.textContent = '无';
  select.appendChild(none);
  const models = Array.isArray(data?.models) ? data.models : [];
  models.forEach((model) => {
    const option = document.createElement('option');
    option.value = String(model.id || '');
    option.textContent = String(model.label || model.model_name || model.id || '');
    option.disabled = model.ready === false;
    select.appendChild(option);
  });
  const selected = String(data?.model_id || '');
  select.value = selected && [...select.options].some((option) => option.value === selected)
    ? selected : '';
  select.disabled = requestInFlight;
  if (!models.length) {
    setText('vtuberLive2dModelSelectStatus', '尚未导入 Live2D 模型。');
    return;
  }
  const selectedOption = [...select.options].find((option) => option.value === select.value);
  setText(
    'vtuberLive2dModelSelectStatus',
    selectedOption?.value ? `当前使用：${selectedOption.textContent}` : '请选择当前虚拟主播使用的模型。',
  );
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
  renderAdvancedDiagnostics();
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
    knowledge_enabled: Boolean(hostSettingsCache?.knowledge_enabled),
  };
}

function describeKnowledgeSettings(data) {
  return Boolean(data?.knowledge_enabled)
    ? '已开启：语音对话与弹幕适配生成时将检索弹幕知识库。'
    : '已关闭：虚拟主播回复不再注入知识库检索结果。';
}

function describeHostModeSettings(data) {
  const dialogue = Boolean(data?.dialogue_enabled);
  const adapter = Boolean(data?.danmu_adapter_enabled);
  if (dialogue) {
    return data?.runtime_status === 'running'
      ? '虚拟主播对话已开启，正在自动聆听语音。'
      : '虚拟主播对话已开启，启动后将自动聆听语音。';
  }
  if (adapter) return 'AI读弹幕适配已开启。';
  return '两种互动模式均已关闭。';
}

function renderHostSettings(data) {
  hostSettingsCache = data || null;
  const dialogueToggle = element('vtuberDialogueEnabled');
  const adapterToggle = element('vtuberDanmuAdapterEnabled');
  const knowledgeToggle = element('vtuberKnowledgeEnabled');
  if (dialogueToggle) dialogueToggle.checked = Boolean(data?.dialogue_enabled);
  if (adapterToggle) adapterToggle.checked = Boolean(data?.danmu_adapter_enabled);
  if (knowledgeToggle) knowledgeToggle.checked = Boolean(data?.knowledge_enabled);
  renderModeSettingsStatus(describeHostModeSettings(data));
  renderKnowledgeSettingsStatus(describeKnowledgeSettings(data));
  renderAdvancedDiagnostics();
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

async function saveHostSettings(patch, { successToast = '互动模式已保存' } = {}) {
  const previous = snapshotHostModeSettings();
  const leavingDialogue = previous.dialogue_enabled && (
    patch.dialogue_enabled === false || patch.danmu_adapter_enabled === true
  );
  const enablingDialogue = !previous.dialogue_enabled && patch.dialogue_enabled === true;
  if (leavingDialogue) {
    try {
      await cancelVoiceSession({ silent: true });
    } catch {
      // Mode save still proceeds; backend refresh_mode_settings is authoritative.
    }
    voiceSessionArmed = false;
  }
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
  if (patch.knowledge_enabled === true) {
    optimistic.knowledge_enabled = true;
  } else if (patch.knowledge_enabled === false) {
    optimistic.knowledge_enabled = false;
  }
  renderHostSettings({ ...(hostSettingsCache || {}), ...optimistic });
  const token = ++hostSettingsSaveToken;
  const savingKnowledgeOnly = Object.keys(patch).length === 1 && 'knowledge_enabled' in patch;
  if (savingKnowledgeOnly) {
    renderKnowledgeSettingsStatus('正在保存知识库检索设置…');
  } else {
    renderModeSettingsStatus('正在保存互动模式…');
  }
  try {
    const data = await apiFetch('/api/virtual-host/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (token !== hostSettingsSaveToken) return data;
    renderHostSettings(data);
    if (enablingDialogue || leavingDialogue) {
      await syncVoiceDialogueForRuntime({ silent: true }).catch(() => {});
    }
    toast(successToast);
    return data;
  } catch (error) {
    if (token === hostSettingsSaveToken) {
      renderHostSettings({ ...(hostSettingsCache || {}), ...previous });
      if (savingKnowledgeOnly) {
        renderKnowledgeSettingsStatus(error?.message || '保存知识库检索设置失败');
      } else {
        renderModeSettingsStatus(error?.message || '保存互动模式失败');
      }
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

function formatCapabilityValue(model, key) {
  const count = countCapability(model, key);
  if (key === 'physics') return count ? '✓' : '✗';
  return String(count);
}

function renderCapabilities(model) {
  const container = element('vtuberCapabilities');
  if (!container) return;
  container.replaceChildren();
  const configured = model?.configured === true;
  if (!configured) {
    const empty = document.createElement('span');
    empty.className = 'vtuber-capability-summary__label';
    empty.textContent = '导入模型后可查看能力摘要。';
    container.appendChild(empty);
    return;
  }
  CAPABILITY_SUMMARY_LABELS.forEach(([key, label]) => {
    const item = document.createElement('span');
    item.className = 'vtuber-capability-summary__item';
    const labelNode = document.createElement('span');
    labelNode.className = 'vtuber-capability-summary__label';
    labelNode.textContent = label;
    const valueNode = document.createElement('span');
    valueNode.className = 'vtuber-capability-summary__value';
    valueNode.textContent = formatCapabilityValue(model, key);
    item.append(labelNode, document.createTextNode(' '), valueNode);
    container.appendChild(item);
  });
  const missing = model.capabilities?.missing_dependencies || [];
  if (missing.length) {
    const warning = document.createElement('span');
    warning.className = 'vtuber-capability-summary__warning';
    warning.textContent = `缺少依赖：${missing.join('、')}`;
    container.appendChild(warning);
  }
}

function deriveStatusPresentation(model, data, { error = false } = {}) {
  const configured = model.configured === true;
  const hasModel = configured && Boolean(model.fileName);
  const runtimeStatus = model.runtime_status || 'stopped';
  const running = runtimeStatus === 'running';
  if (error) {
    return { state: 'error', label: '错误' };
  }
  if (data?.cancelled) {
    return { state: 'warning', label: '已取消选择' };
  }
  if (running) {
    return { state: 'running', label: '运行中' };
  }
  if (model.status === 'blocked' || model.status === 'invalid') {
    return { state: 'warning', label: model.status === 'blocked' ? '模型不可用' : '模型无效' };
  }
  if (model.loaded) {
    return { state: 'ready', label: '已就绪' };
  }
  if (hasModel) {
    return { state: 'warning', label: '已导入' };
  }
  return { state: 'pending', label: '未导入' };
}

function renderRequestError(error) {
  const message = error?.message || 'Live2D 操作失败';
  const target = element('vtuberModelError');
  if (target) { target.textContent = message; target.classList.remove('hidden'); }
  setStatusPill('error', '错误');
  setText('vtuberRuntimeStatus', message);
  setText('vtuberDesktopStatusText', '错误');
  setText('vtuberDesktopStatusHint', '桌面窗口控制失败，请查看高级信息中的错误详情。');
  renderAdvancedDiagnostics();
}

function renderModel(data) {
  const model = normalizeModel(data);
  const configured = model.configured === true;
  const hasModel = configured && Boolean(model.fileName);
  const runtimeStatus = model.runtime_status || 'stopped';
  const running = runtimeStatus === 'running';
  const statusPresentation = deriveStatusPresentation(model, data);
  setStatusPill(statusPresentation.state, statusPresentation.label);
  setText('vtuberModelFileName', model.fileName || '未选择模型');
  setText('vtuberModelState', model.status || (hasModel ? 'ready' : '未导入'));
  setText('vtuberModelText', model.loaded ? '当前模型已通过本机资源代理准备就绪。' : configured ? '当前登记的 Live2D 模型不可用，请重新导入。' : '尚未导入 Live2D 模型。');
  setText('vtuberRuntimeStatus', running ? '模型已在桌面窗口显示。' : model.loaded ? '模型已就绪，可以启动虚拟主播。' : '请先导入可用模型。');
  setText('vtuberDesktopStatusText', running ? '运行中' : '未启动');
  setText('vtuberDesktopStatusHint', running ? '模型已在桌面窗口显示。' : '启动后模型将在桌面窗口显示，当前页面不会渲染 Live2D。');
  renderLive2dModelSelect(data);
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
  renderAdvancedDiagnostics(data);
}

function isVtuberRunning() {
  const pill = element('vtuberStatusBadge');
  return pill?.dataset?.state === 'running';
}

function setRequestState(active) {
  requestInFlight = active;
  const current = element('vtuberModelFileName')?.textContent || '';
  const hasModel = current && current !== '未选择模型';
  const importButton = element('btnVtuberImportModel'); if (importButton) importButton.disabled = active;
  const advancedButton = element('btnVtuberImportModelAdvanced'); if (advancedButton) advancedButton.disabled = active;
  const clearButton = element('btnVtuberClearModel'); if (clearButton) clearButton.disabled = active || !hasModel;
  const modelSelect = element('vtuberLive2dModelSelect'); if (modelSelect) modelSelect.disabled = active;
  const running = isVtuberRunning();
  const startButton = element('btnVtuberStart'); if (startButton) startButton.disabled = active || !hasModel || running;
  const stopButton = element('btnVtuberStop'); if (stopButton) stopButton.disabled = active || !running;
}

async function selectLive2dModel(modelId) {
  const token = ++live2dModelSaveToken;
  setRequestState(true);
  setText('vtuberLive2dModelSelectStatus', '正在切换 Live2D 模型…');
  try {
    const data = await apiFetch('/api/live2d/model', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ model_id: String(modelId || '') }),
    });
    if (token !== live2dModelSaveToken) return data;
    renderModel(data);
    toast(data?.model_id ? 'Live2D 模型已切换' : '当前 Live2D 模型已清除');
    return data;
  } catch (error) {
    if (token === live2dModelSaveToken) {
      renderRequestError(error);
      if (live2dModelCache) renderLive2dModelSelect(live2dModelCache);
    }
    throw error;
  } finally {
    setRequestState(false);
  }
}

async function startModel() {
  setRequestState(true);
  try {
    const response = await apiFetch('/api/live2d/start', { method: 'POST' });
    if (response?.runtime_status !== 'running') throw new Error(response?.error || '桌面窗口启动失败');
    renderModel(response);
    syncRuntimeStatusToHostSettings('running');
    setText('vtuberRuntimeStatus', '模型已在桌面窗口显示。');
    setText('vtuberDesktopStatusText', '运行中');
    setText('vtuberDesktopStatusHint', '模型已在桌面窗口显示。');
    await syncVoiceDialogueForRuntime({ silent: true }).catch(() => {});
    renderHostSettings(hostSettingsCache);
    toast('模型已在桌面窗口显示');
  } catch (error) { renderRequestError(error); throw error; } finally { setRequestState(false); }
}

async function stopModel() {
  setRequestState(true);
  try {
    voiceSessionArmed = false;
    await cancelVoiceSession({ silent: true }).catch(() => {});
    const response = await apiFetch('/api/live2d/stop', { method: 'POST' });
    renderModel(response);
    syncRuntimeStatusToHostSettings('stopped');
    renderHostSettings(hostSettingsCache);
    toast('虚拟主播已停止');
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

async function openModelsFolder() {
  const button = element('btnVtuberImportModelAdvanced');
  if (button) button.disabled = true;
  try {
    await apiFetch('/api/live2d/open-models-folder', { method: 'POST' });
  } catch (error) {
    toast(error?.message || '打开模型文件夹失败', true);
    throw error;
  } finally {
    if (button) button.disabled = requestInFlight;
  }
}

async function clearModel() {
  setRequestState(true);
  try {
    if (isVtuberRunning()) {
      await apiFetch('/api/live2d/stop', { method: 'POST' });
    }
    renderModel(await apiFetch('/api/live2d/clear-model', { method: 'POST' })); toast('Live2D 模型已移除');
  } catch (error) { renderRequestError(error); throw error; } finally { setRequestState(false); }
}

function applyVoiceStatus(data) {
  voiceStatusCache = data || null;
  syncVoiceSessionArmed(data);
  renderAdvancedDiagnostics();
}

export async function loadVtuberPage() {
  try {
    await Promise.all([
      loadModelSettings(),
      loadHostSettings(),
      apiFetch('/api/live2d/model').then((data) => renderModel(data)),
    ]);
    try {
      applyVoiceStatus(await apiFetch('/api/virtual-host/voice/status'));
    } catch {
      voiceStatusCache = null;
      voiceSessionArmed = false;
      renderAdvancedDiagnostics();
    }
  } catch (error) { renderRequestError(error); throw error; }
}

export function initVtuberPage(deps = {}) {
  toast = deps.showToast || toast; if (handlersBound) return; handlersBound = true;
  element('vtuberLive2dModelSelect')?.addEventListener('change', (event) => {
    selectLive2dModel(event.target?.value || '').catch((error) => toast(error.message, true));
  });
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
  element('vtuberKnowledgeEnabled')?.addEventListener('change', (event) => {
    const enabled = Boolean(event.target?.checked);
    saveHostSettings(
      { knowledge_enabled: enabled },
      { successToast: '知识库检索设置已保存' },
    ).catch((error) => toast(error.message, true));
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
  element('btnVtuberImportModelAdvanced')?.addEventListener('click', () => openModelsFolder().catch(() => {}));
  element('btnVtuberClearModel')?.addEventListener('click', () => clearModel().catch((error) => toast(error.message, true)));
  element('btnVtuberStart')?.addEventListener('click', () => startModel().catch((error) => toast(error.message, true)));
  element('btnVtuberStop')?.addEventListener('click', () => stopModel().catch((error) => toast(error.message, true)));
}
