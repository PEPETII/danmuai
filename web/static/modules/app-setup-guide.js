/**
 * 首次运行设置引导 (W-PR-INTAKE-023)
 *
 * 在 overview 页面为首次使用者提供设置引导：
 * - API / 模型已配置
 * - Probe / 连通性检查
 * - 识图屏幕已设置
 * - 测试弹幕 / 启动生成进度
 *
 * guide 状态参考：初始 config / status、运行中实时状态、localStorage dismiss / probe / test 痕迹
 */

const LS_DISMISS_KEY = 'danmuai.setupGuide.dismissed';
const LS_PROBE_KEY = 'danmuai.probe.success';
const LS_TEST_KEY = 'danmuai.testDanmu.sent';

let statusUnsubscribe = null;

function isDismissed() {
  return localStorage.getItem(LS_DISMISS_KEY) === '1';
}

function setDismissed(value) {
  if (value) {
    localStorage.setItem(LS_DISMISS_KEY, '1');
  } else {
    localStorage.removeItem(LS_DISMISS_KEY);
  }
}

function checkApiConfigured(cfg) {
  return !!(cfg && cfg.api_endpoint && cfg.api_key && (cfg.model_id || cfg.model));
}

function checkProbeDone() {
  return localStorage.getItem(LS_PROBE_KEY) === '1';
}

function checkScreenSet(cfg) {
  return cfg && cfg.screen_index !== undefined && cfg.screen_index !== null;
}

function checkTestOrRunning(status) {
  if (status && status.is_running) return true;
  return localStorage.getItem(LS_TEST_KEY) === '1';
}

function updateStep(stepId, done) {
  const el = document.querySelector(`.setup-guide-step[data-step="${stepId}"]`);
  if (!el) return;
  const icon = el.querySelector('.setup-guide-step-icon');
  if (done) {
    el.classList.add('setup-guide-step-done');
    if (icon) icon.textContent = '✓';
  } else {
    el.classList.remove('setup-guide-step-done');
    if (icon) icon.textContent = '○';
  }
}

function updateGuide(cfg, status) {
  const guide = document.getElementById('setupGuide');
  if (!guide) return;

  if (isDismissed()) {
    guide.classList.add('hidden');
    return;
  }

  const apiOk = checkApiConfigured(cfg);
  const probeOk = checkProbeDone();
  const screenOk = checkScreenSet(cfg);
  const testOk = checkTestOrRunning(status);

  updateStep('api', apiOk);
  updateStep('probe', probeOk);
  updateStep('screen', screenOk);
  updateStep('test', testOk);

  // Auto-hide when all done
  if (apiOk && probeOk && screenOk && testOk) {
    guide.classList.add('hidden');
    return;
  }

  guide.classList.remove('hidden');
}

export function initSetupGuide({ getConfig, getStatus } = {}) {
  const guide = document.getElementById('setupGuide');
  if (!guide) return;

  const dismissBtn = document.getElementById('btnSetupGuideDismiss');
  if (dismissBtn) {
    dismissBtn.addEventListener('click', () => {
      setDismissed(true);
      guide.classList.add('hidden');
    });
  }

  // Initial render
  const cfg = getConfig ? getConfig() : {};
  const status = getStatus ? getStatus() : {};
  updateGuide(cfg, status);
}

export function refreshSetupGuide(cfg, status) {
  updateGuide(cfg, status);
}

export function markProbeSuccess() {
  localStorage.setItem(LS_PROBE_KEY, '1');
}

export function markTestDanmuSent() {
  localStorage.setItem(LS_TEST_KEY, '1');
}
