import { apiFetch } from './transport.js';

const LABEL_START = '启动虚拟主播';
const LABEL_STOP = '停止虚拟主播';

let toast = () => {};
let requestInFlight = false;
let running = false;
let modelLoaded = false;
let hasModel = false;

const hooks = {
  onAfterStart: null,
  onAfterStop: null,
  onBeforeStop: null,
  onError: null,
};

function element(id) {
  return document.getElementById(id);
}

function modelFromResponse(data) {
  return data?.model ?? data?.result ?? data ?? {};
}

function deriveFlagsFromModelData(data) {
  const model = modelFromResponse(data);
  const configured = model.configured === true;
  const modelPath = String(model.model_path || '');
  const safePathName = modelPath.split('/').pop().split('\\').pop();
  const fileName = model.model_file_name || model.file_name || model.filename
    || (model.model_name ? `${model.model_name}.model3.json` : safePathName);
  const hasModelFlag = configured && Boolean(String(fileName || ''));
  const loaded = model.ok === true || model.status === 'ready';
  const runtimeStatus = model.runtime_status || data?.runtime_status || 'stopped';
  return {
    running: runtimeStatus === 'running',
    modelLoaded: loaded,
    hasModel: hasModelFlag,
  };
}

export function configureVtuberController(deps = {}) {
  if (deps.showToast) toast = deps.showToast;
  if (deps.hooks) {
    Object.assign(hooks, deps.hooks);
  }
}

export function isVtuberRunning() {
  return running;
}

export function isVtuberRequestInFlight() {
  return requestInFlight;
}

export function getVtuberControlFlags() {
  return { running, modelLoaded, hasModel, requestInFlight };
}

export function setVtuberRequestInFlight(active) {
  requestInFlight = Boolean(active);
  updateVtuberState();
}

export function syncVtuberStateFromModelData(data) {
  const flags = deriveFlagsFromModelData(data);
  running = flags.running;
  modelLoaded = flags.modelLoaded;
  hasModel = flags.hasModel;
  updateVtuberState();
  return flags;
}

export function updateVtuberState() {
  const startButton = element('btnVtuberStart');
  const stopButton = element('btnVtuberStop');
  const quickButton = element('btnQuickToggleVtuber');

  if (startButton) startButton.disabled = requestInFlight || !modelLoaded || running;
  if (stopButton) stopButton.disabled = requestInFlight || !running;

  if (quickButton) {
    quickButton.textContent = running ? LABEL_STOP : LABEL_START;
    quickButton.disabled = requestInFlight || (!running && !modelLoaded);
    quickButton.setAttribute('aria-pressed', running ? 'true' : 'false');
  }
}

export async function refreshVtuberRuntimeState() {
  const data = await apiFetch('/api/live2d/model');
  syncVtuberStateFromModelData(data);
  return data;
}

export async function startVtuber() {
  if (requestInFlight || running) return null;
  setVtuberRequestInFlight(true);
  try {
    const response = await apiFetch('/api/live2d/start', { method: 'POST' });
    if (response?.runtime_status !== 'running') {
      throw new Error(response?.error || '桌面窗口启动失败');
    }
    syncVtuberStateFromModelData(response);
    await hooks.onAfterStart?.(response);
    toast('模型已在桌面窗口显示');
    return response;
  } catch (error) {
    hooks.onError?.(error);
    throw error;
  } finally {
    setVtuberRequestInFlight(false);
  }
}

export async function stopVtuber() {
  if (requestInFlight || !running) return null;
  setVtuberRequestInFlight(true);
  try {
    await hooks.onBeforeStop?.();
    const response = await apiFetch('/api/live2d/stop', { method: 'POST' });
    syncVtuberStateFromModelData(response);
    await hooks.onAfterStop?.(response);
    toast('虚拟主播已停止');
    return response;
  } catch (error) {
    hooks.onError?.(error);
    throw error;
  } finally {
    setVtuberRequestInFlight(false);
  }
}

let quickToggleBound = false;

export function initVtuberQuickToggle(deps = {}) {
  if (deps.showToast) toast = deps.showToast;
  if (quickToggleBound) return;
  quickToggleBound = true;
  element('btnQuickToggleVtuber')?.addEventListener('click', () => {
    const action = running ? stopVtuber() : startVtuber();
    action?.catch((error) => toast(error.message, true));
  });
}
