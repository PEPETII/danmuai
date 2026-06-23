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
 *
 * 关闭持久化：内存变量 guideDismissed（同步）+ localStorage（跨刷新）
 */

const LS_DISMISS_KEY = 'danmuai.setupGuide.dismissed';
const LS_PROBE_KEY = 'danmuai.probe.success';
const LS_TEST_KEY = 'danmuai.testDanmu.sent';

let statusUnsubscribe = null;
let guideInitialized = false;

/** 内存关闭标志 — 点击关闭后立即设为 true，所有渲染路径优先检查此变量 */
let guideDismissed = false;

function readDismissedFromStorage() {
  try {
    return localStorage.getItem(LS_DISMISS_KEY) === '1';
  } catch {
    return false;
  }
}

/** 同步写入内存 + 异步持久化到 localStorage */
function persistDismissed() {
  try {
    localStorage.setItem(LS_DISMISS_KEY, '1');
  } catch {
    /* 静默失败：localStorage 不可用时无法持久化 */
  }
}

function isDismissed() {
  return guideDismissed || readDismissedFromStorage();
}

function checkApiConfigured(cfg) {
  return !!(cfg && cfg.api_endpoint && cfg.api_key && (cfg.model_id || cfg.model));
}

function checkProbeDone() {
  try {
    return localStorage.getItem(LS_PROBE_KEY) === '1';
  } catch {
    return false;
  }
}

function checkScreenSet(cfg) {
  return cfg && cfg.screen_index !== undefined && cfg.screen_index !== null;
}

function checkTestOrRunning(status) {
  if (status && status.is_running) return true;
  try {
    return localStorage.getItem(LS_TEST_KEY) === '1';
  } catch {
    return false;
  }
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

/**
 * 唯一的渲染入口：统一检查 isDismissed() → 决定显示/隐藏。
 * 不再有任何代码路径能绕过此检查直接 remove('hidden')。
 */
function updateGuide(cfg, status) {
  const guide = document.getElementById('setupGuide');
  if (!guide) return;

  // 已关闭 → 强制隐藏，不再执行任何显示逻辑
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
  if (guideInitialized) return;
  guideInitialized = true;

  // 启动时从 localStorage 恢复关闭状态到内存变量
  guideDismissed = readDismissedFromStorage();

  const guide = document.getElementById('setupGuide');
  if (!guide) return;

  const dismissBtn = document.getElementById('btnSetupGuideDismiss');
  if (dismissBtn) {
    dismissBtn.addEventListener('click', () => {
      // 1. 先同步设置内存标志（立即生效，后续所有 isDismissed() 调用都返回 true）
      guideDismissed = true;
      // 2. 再隐藏 DOM
      guide.classList.add('hidden');
      // 3. 最后异步持久化（即使失败也不影响已生效的关闭状态）
      persistDismissed();
    });
  }

  // Initial render
  const cfg = getConfig ? getConfig() : {};
  const status = getStatus ? getStatus() : {};
  updateGuide(cfg, status);
}

export function refreshSetupGuide(cfg, status) {
  // 外层短路：已关闭则跳过整个更新流程
  if (isDismissed()) return;
  updateGuide(cfg, status);
}

export function markProbeSuccess() {
  try {
    localStorage.setItem(LS_PROBE_KEY, '1');
  } catch { /* ignore */ }
}

export function markTestDanmuSent() {
  try {
    localStorage.setItem(LS_TEST_KEY, '1');
  } catch { /* ignore */ }
}
