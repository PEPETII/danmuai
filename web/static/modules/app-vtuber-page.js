import { apiFetch } from './transport.js';

let toast = () => {};
let handlersBound = false;
let requestInFlight = false;

const CAPABILITY_LABELS = [
  ['dependency_count', '依赖'], ['texture_count', '纹理'], ['parameter_count', '参数'],
  ['motion_files', '原生动作'], ['expression_files', '表情'], ['physics', '物理'],
];

const PARAMETER_ACTIONS = [
  '点头', '摇头', '歪头', '左右看', '自动眨眼',
  '开心', '惊讶', '疑惑', '思考', '说话口型',
];

const CONTROL_ENDPOINTS = {
  parameter: '/api/live2d/control/parameter',
  action: '/api/live2d/control/action',
  motion: '/api/live2d/control/motion',
  expression: '/api/live2d/control/expression',
};

function element(id) { return document.getElementById(id); }
function setText(id, value) { const target = element(id); if (target) target.textContent = value; }
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

function renderControlHint(container, message) {
  if (!container) return;
  container.replaceChildren();
  const hint = document.createElement('p'); hint.className = 'settings-section-hint'; hint.textContent = message;
  container.appendChild(hint);
}

async function sendControl(kind, payload) {
  const endpoint = CONTROL_ENDPOINTS[kind];
  if (!endpoint) throw new Error(`未知的 Live2D 控制类型：${kind}`);
  const response = await apiFetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  setText('vtuberRuntimeStatus', response?.message || '控制请求已发送到桌面窗口。');
  return response;
}

function addDesktopControl(container, label, kind, payload, running) {
  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'ui-button ui-button--secondary ui-button--sm vtuber-desktop-control';
  button.textContent = label;
  button.disabled = !running;
  button.title = running ? '发送到桌面窗口运行时' : '启动虚拟主播后可用';
  button.dataset.controlKind = kind;
  button.addEventListener('click', async () => {
    button.disabled = true;
    try { await sendControl(kind, payload); }
    catch (error) { renderRequestError(error); toast(error.message, true); }
    finally { button.disabled = !running; }
  });
  container.appendChild(button);
}

function renderParameterControls(model, running) {
  const container = element('vtuberParameters');
  if (!container) return;
  const specs = Array.isArray(model.capabilities?.parameter_specs)
    ? model.capabilities.parameter_specs.filter((item) => item && item.parameter_id)
    : [];
  const ids = specs.length ? specs : (Array.isArray(model.capabilities?.parameter_ids)
    ? model.capabilities.parameter_ids.map((parameter_id) => ({ parameter_id })) : []);
  container.replaceChildren();
  if (!ids.length) {
    renderControlHint(container, '模型未提供可枚举的参数。');
    return;
  }
  const note = document.createElement('p');
  note.className = 'settings-section-hint vtuber-control-note';
  note.textContent = '参数由桌面窗口运行时控制，页面仅显示已发现的参数。';
  container.appendChild(note);
  ids.forEach((spec) => {
    const id = String(spec.parameter_id);
    const row = document.createElement('div'); row.className = 'vtuber-parameter-row';
    const name = document.createElement('code'); name.title = id; name.textContent = id;
    const range = document.createElement('input'); range.type = 'range'; range.className = 'vtuber-parameter-value';
    const minimum = Number.isFinite(Number(spec.minimum)) ? Number(spec.minimum) : -1;
    const maximum = Number.isFinite(Number(spec.maximum)) ? Number(spec.maximum) : 1;
    const initial = Number.isFinite(Number(spec.current)) ? Number(spec.current)
      : (Number.isFinite(Number(spec.default)) ? Number(spec.default) : 0);
    range.min = String(minimum); range.max = String(maximum);
    range.step = String(Math.max((maximum - minimum) / 200, 0.001));
    range.value = String(Math.min(maximum, Math.max(minimum, initial))); range.disabled = !running;
    range.title = running ? '通过桌面窗口控制参数' : '启动虚拟主播后可用';
    const value = document.createElement('output'); value.className = 'vtuber-control-value'; value.textContent = Number(range.value).toFixed(2);
    range.addEventListener('input', () => { value.textContent = Number(range.value).toFixed(2); });
    range.addEventListener('change', async () => {
      const previous = range.dataset.previous || '0';
      range.disabled = true;
      try {
        await sendControl('parameter', { parameter_id: id, value: Number(range.value) });
        range.dataset.previous = range.value;
      } catch (error) {
        range.value = previous; value.textContent = Number(previous).toFixed(2);
        renderRequestError(error); toast(error.message, true);
      } finally { range.disabled = !running; }
    });
    row.append(name, range, value); container.appendChild(row);
  });
}

function renderParameterActions(running) {
  const container = element('vtuberActions');
  if (!container) return;
  container.replaceChildren();
  const note = document.createElement('p');
  note.className = 'settings-section-hint vtuber-control-note';
  note.textContent = '基础动作由桌面窗口运行时执行。';
  container.appendChild(note);
  PARAMETER_ACTIONS.forEach((label) => addDesktopControl(container, label, 'action', { action: label }, running));
}

function renderNativeControls(model, running) {
  const capabilities = model.capabilities || {};
  const motions = element('vtuberMotions'); const expressions = element('vtuberExpressions');
  const motionFiles = Array.isArray(capabilities.motion_files) ? capabilities.motion_files : [];
  const expressionFiles = Array.isArray(capabilities.expression_files) ? capabilities.expression_files : [];
  const motionEntries = Array.isArray(capabilities.motion_entries) ? capabilities.motion_entries
    : motionFiles.map((file) => ({ file }));
  const expressionEntries = Array.isArray(capabilities.expression_entries) ? capabilities.expression_entries
    : expressionFiles.map((file) => ({ file }));
  if (motions) {
    motions.replaceChildren();
    if (!motionEntries.length) renderControlHint(motions, '暂无动作文件。');
    else {
      const note = document.createElement('p'); note.className = 'settings-section-hint vtuber-control-note';
      note.textContent = '原生动作由桌面窗口运行时执行。'; motions.appendChild(note);
      motionEntries.forEach((entry) => {
        const file = String(entry?.file || ''); if (!file) return;
        const group = String(entry?.group || ''); const name = group ? `${group} · ${file}` : file;
        addDesktopControl(motions, name, 'motion', { file }, running);
      });
    }
  }
  if (expressions) {
    expressions.replaceChildren();
    if (!expressionEntries.length) renderControlHint(expressions, '暂无表情文件。');
    else {
      const note = document.createElement('p'); note.className = 'settings-section-hint vtuber-control-note';
      note.textContent = '表情由桌面窗口运行时执行。'; expressions.appendChild(note);
      expressionEntries.forEach((entry) => {
        const file = String(entry?.file || ''); if (!file) return;
        const id = String(entry?.id || ''); const name = id ? `${id} · ${file}` : file;
        addDesktopControl(expressions, name, 'expression', { file }, running);
      });
    }
  }
}

function renderControlPanels(model, running) {
  renderParameterControls(model, running);
  renderParameterActions(running);
  renderNativeControls(model, running);
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
  setText('vtuberDesktopStatusHint', running ? '模型已在桌面窗口显示，当前页面仅提供控制面板。' : '启动后模型将在桌面窗口显示，当前页面不会渲染 Live2D。');
  renderCapabilities(model); renderControlPanels(model, running);
  const error = data?.error || (model.loaded ? '' : model.reason || '');
  const errorElement = element('vtuberModelError');
  if (errorElement) { errorElement.textContent = error; errorElement.classList.toggle('hidden', !error); }
  const importButton = element('btnVtuberImportModel'); const clearButton = element('btnVtuberClearModel');
  const startButton = element('btnVtuberStart'); const stopButton = element('btnVtuberStop');
  if (importButton) importButton.disabled = requestInFlight;
  if (clearButton) clearButton.disabled = requestInFlight || !hasModel;
  if (startButton) startButton.disabled = requestInFlight || !model.loaded || running;
  if (stopButton) stopButton.disabled = requestInFlight || !running;
}

function setRequestState(active) {
  requestInFlight = active;
  const current = element('vtuberModelFileName')?.textContent || '';
  const hasModel = current && current !== '未选择模型';
  const importButton = element('btnVtuberImportModel'); if (importButton) importButton.disabled = active;
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
    setText('vtuberDesktopStatusHint', '模型已在桌面窗口显示，当前页面仅提供控制面板。');
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

async function importModel() {
  setRequestState(true);
  try {
    const data = await apiFetch('/api/live2d/import-model', { method: 'POST' });
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
  try { renderModel(await apiFetch('/api/live2d/model')); } catch (error) { renderRequestError(error); throw error; }
}

export function initVtuberPage(deps = {}) {
  toast = deps.showToast || toast; if (handlersBound) return; handlersBound = true;
  element('btnVtuberImportModel')?.addEventListener('click', () => importModel().catch((error) => toast(error.message, true)));
  element('btnVtuberClearModel')?.addEventListener('click', () => clearModel().catch((error) => toast(error.message, true)));
  element('btnVtuberStart')?.addEventListener('click', () => startModel().catch((error) => toast(error.message, true)));
  element('btnVtuberStop')?.addEventListener('click', () => stopModel().catch((error) => toast(error.message, true)));
}
