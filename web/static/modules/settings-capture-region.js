import { apiFetch } from './transport.js';
import { t } from './i18n.js';

let captureRegionDeps = {
  showToast: () => {},
};

let captureRegionPollTimer = null;

export function configureSettingsCaptureRegion(deps) {
  captureRegionDeps = { ...captureRegionDeps, ...deps };
}

export function applyCaptureRegionFromPayload(data) {
  const modeEl = document.getElementById('captureRegionModeLabel');
  const coordsEl = document.getElementById('captureRegionCoords');
  const resetBtn = document.getElementById('btnCaptureRegionReset');
  const selectBtn = document.getElementById('btnCaptureRegionSelect');
  if (!modeEl || !data) return;

  const mode = data.mode || 'full';
  const region = data.region || {};
  const state = data.selection_state || 'idle';
  const selecting = state === 'selecting';

  if (selectBtn) {
    selectBtn.disabled = selecting;
    selectBtn.textContent = selecting ? t('dynamic.settingsCaptureRegion.正在框选') : t('dynamic.settingsCaptureRegion.鼠标框选识图范围');
  }

  if (selecting) {
    modeEl.textContent = t('dynamic.settingsCaptureRegion.正在框选_请在识图显示器上拖动鼠标_Esc_取消');
    coordsEl?.classList.add('hidden');
    return;
  }

  if (mode === 'custom' && region.w > 0 && region.h > 0) {
    modeEl.textContent = t('dynamic.settingsCaptureRegion.自定义区域识图');
    if (coordsEl) {
      coordsEl.textContent = t('dynamic.settingsCaptureRegion.区域_x_region_x_y_re', {
        x: region.x,
        y: region.y,
        w: region.w,
        h: region.h,
      });
      coordsEl.classList.remove('hidden');
    }
    resetBtn?.classList.remove('hidden');
    return;
  }

  modeEl.textContent = t('dynamic.settingsCaptureRegion.全屏识图');
  coordsEl?.classList.add('hidden');
  resetBtn?.classList.add('hidden');
}

async function fetchCaptureRegionStatus() {
  return apiFetch('/api/capture-region');
}

function stopCaptureRegionPoll() {
  if (captureRegionPollTimer) {
    clearTimeout(captureRegionPollTimer);
    captureRegionPollTimer = null;
  }
}

async function pollCaptureRegionUntilDone() {
  stopCaptureRegionPoll();
  const maxMs = 120000;
  const intervalMs = 500;
  const start = Date.now();

  return new Promise((resolve) => {
    const tick = async () => {
      try {
        const data = await fetchCaptureRegionStatus();
        applyCaptureRegionFromPayload(data);
        const state = data.selection_state || 'idle';
        if (state !== 'selecting') {
          stopCaptureRegionPoll();
          resolve(data);
          return;
        }
        if (Date.now() - start >= maxMs) {
          stopCaptureRegionPoll();
          applyCaptureRegionFromPayload({ selection_state: 'timeout' });
          captureRegionDeps.showToast(t('dynamic.settingsCaptureRegion.框选等待超时_请重试'), true);
          resolve(data);
          return;
        }
        captureRegionPollTimer = setTimeout(tick, intervalMs);
      } catch (error) {
        stopCaptureRegionPoll();
        captureRegionDeps.showToast(error.message || t('dynamic.settingsCaptureRegion.获取识图区域状态失败'), true);
        resolve(null);
      }
    };
    tick();
  });
}

export function initCaptureRegionControls() {
  document.getElementById('btnCaptureRegionSelect')?.addEventListener('click', async () => {
    try {
      const res = await apiFetch('/api/capture-region/select', { method: 'POST' });
      applyCaptureRegionFromPayload({
        mode: 'full',
        region: { x: 0, y: 0, w: 0, h: 0 },
        selection_state: res.selection_state || 'selecting',
      });
      captureRegionDeps.showToast(t('dynamic.settingsCaptureRegion.请在识图显示器上拖动鼠标框选区域'));
      const done = await pollCaptureRegionUntilDone();
      if (!done) return;
      if (done.selection_state === 'saved') {
        captureRegionDeps.showToast(t('dynamic.settingsCaptureRegion.识图区域已保存'));
      } else if (done.selection_state === 'cancelled') {
        captureRegionDeps.showToast(t('dynamic.settingsCaptureRegion.已取消框选'));
      } else if (done.selection_state === 'invalid') {
        captureRegionDeps.showToast(t('dynamic.settingsCaptureRegion.区域无效或过小_请重新框选'), true);
      }
    } catch (error) {
      captureRegionDeps.showToast(error.message || t('dynamic.settingsCaptureRegion.无法启动框选'), true);
    }
  });

  document.getElementById('btnCaptureRegionReset')?.addEventListener('click', async () => {
    try {
      await apiFetch('/api/capture-region/reset', { method: 'POST' });
      const data = await fetchCaptureRegionStatus();
      applyCaptureRegionFromPayload(data);
      captureRegionDeps.showToast(t('dynamic.settingsCaptureRegion.已恢复全屏识图'));
    } catch (error) {
      captureRegionDeps.showToast(error.message || t('dynamic.settingsCaptureRegion.恢复全屏失败'), true);
    }
  });

  fetchCaptureRegionStatus()
    .then(applyCaptureRegionFromPayload)
    .catch(() => {});
}
