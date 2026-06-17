import { apiFetch } from './transport.js';
import { MASKED_API_KEY } from './settings-defaults.js';

const DISMISSED_KEY = 'danmu_setup_guide_dismissed_v1';
const PROBE_OK_KEY = 'danmu_setup_guide_probe_ok_v1';
const TEST_DANMU_OK_KEY = 'danmu_setup_guide_test_danmu_ok_v1';

const STEP_DEFS = [
  { id: 'api', label: '接口与 Key' },
  { id: 'model', label: '视觉模型' },
  { id: 'probe', label: '连接测试' },
  { id: 'capture', label: '识图屏幕' },
  { id: 'test', label: '测试弹幕' },
];

let setupGuideDeps = {
  navigate: () => {},
  switchSettingsTab: () => {},
  showToast: () => {},
};

let latestConfig = {};
let latestStatus = {};
let guideInitialized = false;
let probeBusy = false;
let testBusy = false;

function readStorageJson(key) {
  try {
    return JSON.parse(localStorage.getItem(key) || 'null');
  } catch {
    return null;
  }
}

function writeStorageJson(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* ignore private mode / quota */
  }
}

function isDismissed() {
  try {
    return localStorage.getItem(DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

function setDismissed() {
  try {
    localStorage.setItem(DISMISSED_KEY, '1');
  } catch {
    /* ignore private mode / quota */
  }
}

function activeModelId() {
  const modelField = document.getElementById('model');
  if (modelField) {
    const modelValue = String(modelField.value || '').trim();
    const customValue = String(document.getElementById('modelCustom')?.value || '').trim();
    return modelValue || customValue;
  }
  return String(
    latestConfig.active_model_id
      || latestConfig.default_model_id
      || latestConfig.model
      || document.getElementById('model')?.value
      || '',
  ).trim();
}

function endpointValue() {
  const field = document.getElementById('api_endpoint');
  if (field) return String(field.value || '').trim();
  return String(
    latestConfig.api_endpoint
      || '',
  ).trim();
}

function apiModeValue() {
  const field = document.getElementById('api_mode');
  if (field) return String(field.value || '').trim();
  return String(
    latestConfig.api_mode
      || '',
  ).trim();
}

function hasApiKey() {
  const input = document.getElementById('api_key');
  if (!input) return latestConfig.has_api_key === true;
  const field = String(input.value || '').trim();
  if (!field) return false;
  if (field === MASKED_API_KEY) return latestConfig.has_api_key === true;
  return true;
}

function configSignature() {
  return [
    endpointValue(),
    apiModeValue(),
    activeModelId(),
    hasApiKey() ? 'key' : 'no-key',
  ].join('|');
}

function hasGeneratedBefore() {
  const st = latestStatus || {};
  const sessionRuns = Array.isArray(st.session_runs) ? st.session_runs : [];
  return (
    Number(st.lifetime_danmu_count || 0) > 0
    || Number(st.danmu_count || 0) > 0
    || sessionRuns.length > 0
  );
}

function probeComplete() {
  if (hasGeneratedBefore()) return true;
  const record = readStorageJson(PROBE_OK_KEY);
  return record?.ok === true && record.signature === configSignature();
}

function testDanmuComplete() {
  if (hasGeneratedBefore()) return true;
  const record = readStorageJson(TEST_DANMU_OK_KEY);
  return record?.ok === true;
}

function collectStepState() {
  const apiReady = Boolean(endpointValue() && hasApiKey());
  const modelReady = Boolean(activeModelId() && latestConfig.provider_model_mismatch !== true);
  const screenField = document.getElementById('screen_index');
  return {
    api: apiReady,
    model: modelReady,
    probe: apiReady && modelReady && probeComplete(),
    capture: Boolean(screenField && screenField.value !== ''),
    test: testDanmuComplete(),
  };
}

function completedCount(state) {
  return STEP_DEFS.filter((step) => state[step.id]).length;
}

function shouldShowGuide(state) {
  if (isDismissed()) return false;
  if (completedCount(state) === STEP_DEFS.length) return false;
  if (hasGeneratedBefore() && state.api && state.model) return false;
  return true;
}

function setButtonBusy(button, busy, busyText, idleText) {
  if (!button) return;
  button.disabled = busy;
  button.classList.toggle('is-busy', busy);
  button.textContent = busy ? busyText : idleText;
}

function navigateToSettingsTab(tabId, focusId = '') {
  setupGuideDeps.navigate('settings');
  setupGuideDeps.switchSettingsTab(tabId);
  if (focusId) {
    window.setTimeout(() => document.getElementById(focusId)?.focus(), 50);
  }
}

function renderSteps(state) {
  const list = document.getElementById('setupGuideSteps');
  if (!list) return;
  list.replaceChildren();
  STEP_DEFS.forEach((step) => {
    const done = Boolean(state[step.id]);
    const item = document.createElement('li');
    item.className = `setup-guide-step ${done ? 'is-done' : 'is-pending'}`;
    const dot = document.createElement('span');
    dot.className = 'setup-guide-step-dot';
    dot.textContent = done ? '✓' : '';
    const label = document.createElement('span');
    label.className = 'setup-guide-step-label';
    label.textContent = step.label;
    item.append(dot, label);
    list.appendChild(item);
  });
}

function renderGuide() {
  const panel = document.getElementById('firstRunSetupGuide');
  if (!panel) return;
  const state = collectStepState();
  panel.classList.toggle('hidden', !shouldShowGuide(state));

  const done = completedCount(state);
  const progressText = document.getElementById('setupGuideProgressText');
  const progressBar = document.getElementById('setupGuideProgressBar');
  if (progressText) progressText.textContent = `${done} / ${STEP_DEFS.length}`;
  if (progressBar) progressBar.style.width = `${(done / STEP_DEFS.length) * 100}%`;
  renderSteps(state);

  const apiBtn = document.getElementById('btnSetupGuideApi');
  const probeBtn = document.getElementById('btnSetupGuideProbe');
  const captureBtn = document.getElementById('btnSetupGuideCapture');
  const testBtn = document.getElementById('btnSetupGuideTestDanmu');
  if (apiBtn) apiBtn.textContent = state.api && state.model ? '调整接口' : '配置接口';
  if (probeBtn) probeBtn.disabled = probeBusy || !state.api || !state.model;
  if (testBtn) testBtn.disabled = testBusy;
  if (captureBtn) captureBtn.textContent = state.capture ? '调整识图' : '选择识图';
}

function bindConfigFieldUpdates() {
  [
    'api_endpoint',
    'api_key',
    'api_mode',
    'model',
    'modelCustom',
    'screen_index',
  ].forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', renderGuide);
    el.addEventListener('change', renderGuide);
  });
  document.getElementById('visionModelPicker')?.addEventListener('click', () => {
    window.setTimeout(renderGuide, 0);
  });
}

function collectProbePayload() {
  const keyField = String(document.getElementById('api_key')?.value || '').trim();
  return {
    api_endpoint: endpointValue(),
    api_key: keyField === MASKED_API_KEY ? MASKED_API_KEY : keyField,
    model: activeModelId(),
    api_mode: apiModeValue(),
  };
}

async function runProbe() {
  const button = document.getElementById('btnSetupGuideProbe');
  const state = collectStepState();
  if (!state.api || !state.model) {
    navigateToSettingsTab('api', !state.api ? 'api_key' : 'modelCustom');
    setupGuideDeps.showToast('请先补齐 API Key 与视觉模型', true);
    return;
  }
  try {
    probeBusy = true;
    setButtonBusy(button, true, '测试中...', '测试连接');
    const result = await apiFetch('/api/probe', {
      method: 'POST',
      body: JSON.stringify(collectProbePayload()),
    });
    if (result.ok) {
      writeStorageJson(PROBE_OK_KEY, {
        ok: true,
        signature: configSignature(),
        at: Date.now(),
      });
    }
    setupGuideDeps.showToast(result.message || (result.ok ? '连接成功' : '连接失败'), !result.ok);
  } catch (error) {
    setupGuideDeps.showToast(error.message || '连接测试失败', true);
  } finally {
    probeBusy = false;
    setButtonBusy(button, false, '测试中...', '测试连接');
    renderGuide();
  }
}

async function sendTestDanmu() {
  const button = document.getElementById('btnSetupGuideTestDanmu');
  try {
    testBusy = true;
    setButtonBusy(button, true, '发送中...', '发送测试弹幕');
    await apiFetch('/api/test/danmu', {
      method: 'POST',
      body: JSON.stringify({
        items: ['DanmuAI 测试弹幕已就位'],
        persona: '首次配置',
      }),
    });
    writeStorageJson(TEST_DANMU_OK_KEY, { ok: true, at: Date.now() });
    setupGuideDeps.showToast('测试弹幕已发送');
  } catch (error) {
    setupGuideDeps.showToast(error.message || '发送测试弹幕失败', true);
  } finally {
    testBusy = false;
    setButtonBusy(button, false, '发送中...', '发送测试弹幕');
    renderGuide();
  }
}

export function updateSetupGuideConfig(config) {
  latestConfig = config || latestConfig || {};
  renderGuide();
}

export function updateSetupGuideStatus(status) {
  latestStatus = status || latestStatus || {};
  renderGuide();
}

export function initSetupGuide(config = {}, status = {}) {
  latestConfig = config || {};
  latestStatus = status || {};
  if (guideInitialized) {
    renderGuide();
    return;
  }
  guideInitialized = true;

  document.getElementById('btnSetupGuideDismiss')?.addEventListener('click', () => {
    setDismissed();
    renderGuide();
  });
  document.getElementById('btnSetupGuideApi')?.addEventListener('click', () => {
    navigateToSettingsTab('api', hasApiKey() ? 'modelCustom' : 'api_key');
  });
  document.getElementById('btnSetupGuideProbe')?.addEventListener('click', () => {
    runProbe();
  });
  document.getElementById('btnSetupGuideCapture')?.addEventListener('click', () => {
    navigateToSettingsTab('capture', 'btnCaptureRegionSelect');
  });
  document.getElementById('btnSetupGuideTestDanmu')?.addEventListener('click', () => {
    sendTestDanmu();
  });
  bindConfigFieldUpdates();
  renderGuide();
}

export function configureSetupGuide(deps = {}) {
  setupGuideDeps = { ...setupGuideDeps, ...deps };
}
