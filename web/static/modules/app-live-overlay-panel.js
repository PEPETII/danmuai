import { API, apiFetch } from './transport.js';
import { t } from './i18n.js';

const URL_COPIED_KEY = 'danmu_live_overlay_url_copied_v1';
const TEST_SENT_KEY = 'danmu_live_overlay_test_sent_v1';

let liveOverlayStatusTimer = null;
let toast = () => {};
let handlersBound = false;
let latestOverlayStatus = {
  connections: 0,
  last_broadcast_at: null,
  overlay_url: '',
  unavailable: false,
};

function showToast(message, isError = false) {
  toast(message, isError);
}

function readFlag(key) {
  try {
    return localStorage.getItem(key) === '1';
  } catch {
    return false;
  }
}

function writeFlag(key) {
  try {
    localStorage.setItem(key, '1');
  } catch {
    /* ignore private mode / quota */
  }
}

function formatLiveOverlayLastBroadcast(ts) {
  if (ts == null || Number.isNaN(Number(ts))) return '-';
  const date = new Date(Number(ts) * 1000);
  if (Number.isNaN(date.getTime())) return '-';
  return date.toLocaleTimeString();
}

function setSetupStepState(stepId, done) {
  const item = document.querySelector(`[data-live-overlay-step="${stepId}"]`);
  if (!item) return;
  item.classList.toggle('is-done', done);
  item.classList.toggle('is-pending', !done);
}

function renderLiveOverlaySetup() {
  const stateEl = document.getElementById('liveOverlaySetupState');
  const hintEl = document.getElementById('liveOverlaySetupHint');
  const copied = readFlag(URL_COPIED_KEY);
  const testSent = readFlag(TEST_SENT_KEY) || Number(latestOverlayStatus.last_broadcast_at || 0) > 0;
  const connected = Number(latestOverlayStatus.connections || 0) > 0;
  const unavailable = Boolean(latestOverlayStatus.unavailable);

  setSetupStepState('copy', copied || connected);
  setSetupStepState('connect', connected);
  setSetupStepState('test', testSent);

  if (stateEl) {
    stateEl.classList.toggle('is-connected', connected && !unavailable);
    stateEl.classList.toggle('is-waiting', copied && !connected && !unavailable);
    stateEl.classList.toggle('is-error', unavailable);
    if (unavailable) {
      stateEl.textContent = t('dynamic.appLiveOverlayPanel.状态未知');
    } else if (connected) {
      stateEl.textContent = t('common.connected');
    } else if (copied) {
      stateEl.textContent = t('dynamic.appLiveOverlayPanel.等待连接');
    } else {
      stateEl.textContent = t('common.comingSoon');
    }
  }

  if (!hintEl) return;
  if (unavailable) {
    hintEl.textContent = t('dynamic.appLiveOverlayPanel.暂时无法读取直播输出状态_请确认控制台服务仍在运');
  } else if (!copied && !connected) {
    hintEl.textContent = t('dynamic.appLiveOverlayPanel.先复制地址_粘贴到直播软件的浏览器源_网页源');
  } else if (!connected) {
    hintEl.textContent = t('dynamic.appLiveOverlayPanel.地址已复制_保存直播软件的网页源后_连接数会自动');
  } else if (!testSent) {
    hintEl.textContent = t('dynamic.appLiveOverlayPanel.已检测到网页源连接_发送测试弹幕_确认直播画面能');
  } else {
    hintEl.textContent = t('dynamic.appLiveOverlayPanel.直播输出已接通_正式生成弹幕时会同步推送到网页源');
  }
}

function currentLiveOverlayUrl() {
  return document.getElementById('liveOverlayUrl')?.value || '';
}

async function copyLiveOverlayUrl() {
  const urlEl = document.getElementById('liveOverlayUrl');
  const url = currentLiveOverlayUrl();
  if (!url) {
    showToast(t('dynamic.appLiveOverlayPanel.暂无直播地址'));
    return;
  }
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
    } else if (urlEl) {
      urlEl.focus();
      urlEl.select();
      document.execCommand('copy');
    }
    writeFlag(URL_COPIED_KEY);
    renderLiveOverlaySetup();
    showToast(t('dynamic.appLiveOverlayPanel.直播地址已复制'));
  } catch {
    showToast(t('dynamic.appLiveOverlayPanel.复制失败_请手动选择复制'), true);
  }
}

export async function refreshLiveOverlayStatus() {
  const connEl = document.getElementById('liveOverlayConnections');
  const lastEl = document.getElementById('liveOverlayLastBroadcast');
  const urlEl = document.getElementById('liveOverlayUrl');
  if (!connEl || !API.base) return;
  try {
    const status = await fetch(`${API.base}/api/live-overlay/status`, {
      cache: 'no-store',
    }).then((response) => {
      if (!response.ok) throw new Error(String(response.status));
      return response.json();
    });
    latestOverlayStatus = {
      connections: status.connections ?? 0,
      last_broadcast_at: status.last_broadcast_at ?? null,
      overlay_url: status.overlay_url || '',
      unavailable: false,
    };
    connEl.textContent = String(status.connections ?? 0);
    if (lastEl) {
      lastEl.textContent = formatLiveOverlayLastBroadcast(status.last_broadcast_at);
    }
    if (urlEl && status.overlay_url) {
      urlEl.value = status.overlay_url;
    }
    renderLiveOverlaySetup();
  } catch {
    latestOverlayStatus = { ...latestOverlayStatus, unavailable: true };
    connEl.textContent = '-';
    if (lastEl) lastEl.textContent = '-';
    renderLiveOverlaySetup();
  }
}

export function initLiveOverlayPanel(deps = {}) {
  toast = deps.showToast || toast;
  const panel = document.getElementById('liveOverlayPanel');
  if (!panel) return;

  if (!handlersBound) {
    handlersBound = true;
    document.getElementById('btnCopyLiveOverlayUrl')?.addEventListener('click', () => {
      copyLiveOverlayUrl();
    });
    document.getElementById('btnOpenLiveOverlayUrl')?.addEventListener('click', () => {
      const url = currentLiveOverlayUrl();
      if (!url) {
        showToast(t('dynamic.appLiveOverlayPanel.暂无直播地址'));
        return;
      }
      window.open(url, '_blank', 'noopener');
    });
    document.getElementById('btnRefreshLiveOverlayStatus')?.addEventListener('click', async () => {
      await refreshLiveOverlayStatus();
      showToast(t('dynamic.appLiveOverlayPanel.直播输出状态已刷新'));
    });
    document.getElementById('btnLiveOverlayTest')?.addEventListener('click', async () => {
      try {
        await apiFetch('/api/live-overlay/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        });
        writeFlag(TEST_SENT_KEY);
        renderLiveOverlaySetup();
        showToast(t('dynamic.appLiveOverlayPanel.测试弹幕已发送'));
        await refreshLiveOverlayStatus();
      } catch (error) {
        showToast(t('dynamic.appLiveOverlayPanel.发送失败_error_message', {
          error: error?.message || String(error),
        }), true);
      }
    });
  }

  renderLiveOverlaySetup();
  refreshLiveOverlayStatus();
  if (liveOverlayStatusTimer) {
    clearInterval(liveOverlayStatusTimer);
  }
  liveOverlayStatusTimer = setInterval(() => {
    if (document.hidden) return;
    refreshLiveOverlayStatus();
  }, 2000);
}
