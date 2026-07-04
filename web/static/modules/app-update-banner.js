import { API, apiFetch } from './transport.js';
import { t } from './i18n.js';
import { activateFocusTrap, deactivateFocusTrap } from './modal-focus-trap.js';

const APP_UPDATE_DISMISS_LOCAL_KEY = 'danmu_app_update_dismissed_latest';

const appVersionState = {
  current: '',
  latest: '',
  releaseUrl: '',
  message: '',
  stale: false,
  cacheState: 'pending',
  cacheAgeSec: null,
  checkStatus: 'pending',
};

const appUpdateDismissState = {
  dismissedLatestVersion: '',
};

let releaseChannels = {};
let sessionSuppressedLatest = '';
let channelDetailState = { copyText: '', openUrl: '' };

let pendingAppUpdatePrompt = null;
let toast = () => {};
let handlersBound = false;
let inAppUpdateBusy = false;

const UPDATE_POLL_INTERVAL_MS = 400;
const UPDATE_POLL_TIMEOUT_MS = 10 * 60 * 1000;

const updateProgressState = {
  visible: false,
  phase: 'idle',
  progress: 0,
  totalBytes: 0,
  downloadedBytes: 0,
  statusText: '',
  errorText: '',
};

function formatBytes(bytes) {
  const value = Number(bytes);
  if (!Number.isFinite(value) || value <= 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const digits = unitIndex === 0 ? 0 : size >= 100 ? 0 : size >= 10 ? 1 : 2;
  return `${size.toFixed(digits)} ${units[unitIndex]}`;
}

function formatProgressMeta({ progress, downloadedBytes, totalBytes }) {
  const pct = Math.max(0, Math.min(100, Number(progress) || 0));
  if (totalBytes > 0) {
    const downloaded = downloadedBytes > 0 ? downloadedBytes : Math.round((totalBytes * pct) / 100);
    return t('dynamic.appUpdateBanner.pct_formatBytes');
  }
  return `${pct}%`;
}

function refreshUpdateProgressUI() {
  const roots = document.querySelectorAll('[data-update-progress-root]');
  roots.forEach((root) => {
    root.classList.toggle('hidden', !updateProgressState.visible);
    const statusEl = root.querySelector('.update-progress-status');
    const trackEl = root.querySelector('.update-progress-track');
    const fillEl = root.querySelector('.update-progress-fill');
    const metaEl = root.querySelector('.update-progress-meta');
    const errorEl = root.querySelector('.update-progress-error');
    const progress = Math.max(0, Math.min(100, Number(updateProgressState.progress) || 0));
    const showBar = ['checking', 'downloading', 'ready', 'applying'].includes(updateProgressState.phase);

    if (statusEl) statusEl.textContent = updateProgressState.statusText || '';
    if (trackEl) {
      trackEl.classList.toggle('hidden', !showBar);
      trackEl.setAttribute('aria-valuenow', String(progress));
    }
    if (fillEl) fillEl.style.width = `${progress}%`;
    if (metaEl) {
      metaEl.textContent = showBar
        ? formatProgressMeta({
            progress,
            downloadedBytes: updateProgressState.downloadedBytes,
            totalBytes: updateProgressState.totalBytes,
          })
        : '';
      metaEl.classList.toggle('hidden', !showBar);
    }
    if (errorEl) {
      const hasError = Boolean(updateProgressState.errorText);
      errorEl.textContent = updateProgressState.errorText || '';
      errorEl.classList.toggle('hidden', !hasError);
    }
  });
}

function setUpdateProgress({
  visible = true,
  phase = 'idle',
  progress = 0,
  totalBytes = 0,
  downloadedBytes = 0,
  statusText = '',
  errorText = '',
} = {}) {
  updateProgressState.visible = visible;
  updateProgressState.phase = phase;
  updateProgressState.progress = progress;
  updateProgressState.totalBytes = totalBytes;
  updateProgressState.downloadedBytes = downloadedBytes;
  updateProgressState.statusText = statusText;
  updateProgressState.errorText = errorText;
  refreshUpdateProgressUI();
}

function hideUpdateProgress() {
  setUpdateProgress({
    visible: false,
    phase: 'idle',
    progress: 0,
    totalBytes: 0,
    downloadedBytes: 0,
    statusText: '',
    errorText: '',
  });
}

function applyVelopackStatusToProgress(status, { fallbackStatusText = '' } = {}) {
  const phase = String(status?.download_phase || 'idle');
  const progress = Number(status?.download_progress) || 0;
  const totalBytes = Number(status?.package_size_bytes) || 0;
  const downloadedBytes = Number(status?.downloaded_bytes) || 0;
  let statusText = fallbackStatusText;
  if (phase === 'checking') statusText = t('dynamic.appUpdateBanner.正在检查更新');
  else if (phase === 'downloading' || status?.downloading) statusText = t('dynamic.appUpdateBanner.正在下载更新');
  else if (phase === 'ready') statusText = t('dynamic.appUpdateBanner.更新已下载_正在重启安装');
  else if (phase === 'applying') statusText = t('dynamic.appUpdateBanner.正在重启安装');
  else if (phase === 'error') statusText = t('dynamic.appUpdateBanner.更新失败');
  else if (status?.message) statusText = String(status.message);

  const latest = normalizeVersionString(status?.latest_version || '');
  if (phase === 'checking' && latest && totalBytes > 0) {
    statusText = t('dynamic.appUpdateBanner.发现新版本_latest_更新包约_f');
  }

  setUpdateProgress({
    visible: true,
    phase,
    progress: phase === 'ready' || phase === 'applying' ? 100 : progress,
    totalBytes,
    downloadedBytes,
    statusText,
    errorText: phase === 'error' ? String(status?.error || status?.message || t('dynamic.appUpdateBanner.更新失败')) : '',
  });
}

function setUpdateControlsDisabled(disabled) {
  const ids = ['btnCheckAppUpdate', 'btnDownloadRestartAppUpdate', 'btnAppUpdateInApp'];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = disabled;
  });
}

function setModalUpdateSectionsHidden(hidden) {
  document.getElementById('appUpdateModalAlternateChannels')?.classList.toggle('hidden', hidden);
  document.getElementById('appUpdateModalDismissRow')?.classList.toggle('hidden', hidden);
  document.getElementById('appUpdateChannelDetail')?.classList.toggle('hidden', hidden);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function pollUpdateStatusUntilDone() {
  const startedAt = Date.now();
  while (Date.now() - startedAt < UPDATE_POLL_TIMEOUT_MS) {
    const status = await fetchVelopackUpdateStatus();
    if (!status) {
      throw new Error(t('dynamic.appUpdateBanner.无法获取更新状态'));
    }
    applyVelopackStatusToProgress(status);
    refreshVelopackUpdateButtons(status);

    const phase = String(status.download_phase || 'idle');
    if (phase === 'ready') return status;
    if (phase === 'error') {
      throw new Error(status.error || status.message || t('dynamic.appUpdateBanner.下载失败'));
    }
    if (!status.downloading && phase !== 'downloading' && status.download_ready) {
      return status;
    }
    await sleep(UPDATE_POLL_INTERVAL_MS);
  }
  throw new Error(t('dynamic.appUpdateBanner.下载超时_请稍后重试'));
}

function showToast(message, isError = false) {
  toast(message, isError);
}

function normalizeVersionString(raw) {
  let value = String(raw || '').trim();
  if (value.length > 1 && (value[0] === 'v' || value[0] === 'V') && /\d/.test(value[1])) {
    value = value.slice(1);
  }
  return value;
}

function readAppUpdateDismissFromLocal() {
  try {
    return String(localStorage.getItem(APP_UPDATE_DISMISS_LOCAL_KEY) || '').trim();
  } catch {
    return '';
  }
}

function writeAppUpdateDismissToLocal(version) {
  try {
    localStorage.setItem(APP_UPDATE_DISMISS_LOCAL_KEY, version ? String(version) : '');
  } catch {
    /* ignore */
  }
}

function mergeAppUpdateDismissState(remote, localDismissed) {
  const remoteDismissed =
    typeof remote?.dismissedLatestVersion === 'string'
      ? remote.dismissedLatestVersion.trim()
      : '';
  appUpdateDismissState.dismissedLatestVersion = remoteDismissed || localDismissed || '';
}

async function loadAppUpdateDismissState() {
  const localDismissed = readAppUpdateDismissFromLocal();
  let remote = null;
  try {
    if (API.base) {
      remote = await fetch(`${API.base}/api/app-update-state`, { cache: 'no-store' }).then((r) =>
        r.ok ? r.json() : null,
      );
    }
  } catch {
    remote = null;
  }
  mergeAppUpdateDismissState(remote, localDismissed);
  writeAppUpdateDismissToLocal(appUpdateDismissState.dismissedLatestVersion);
}

async function persistAppUpdateDismiss(latestVersion) {
  const normalized = normalizeVersionString(latestVersion);
  appUpdateDismissState.dismissedLatestVersion = normalized;
  sessionSuppressedLatest = normalized;
  writeAppUpdateDismissToLocal(normalized);
  try {
    await apiFetch('/api/app-update-state', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ dismissedLatestVersion: normalized }),
    });
  } catch {
    /* localStorage remains */
  }
}

function suppressAppUpdateForSession(latestVersion) {
  sessionSuppressedLatest = normalizeVersionString(latestVersion);
}

function isAppUpdateSuppressed(latest) {
  const normalized = normalizeVersionString(latest);
  return (
    appUpdateDismissState.dismissedLatestVersion === normalized ||
    sessionSuppressedLatest === normalized
  );
}

function applyReleaseChannels(data) {
  if (!data || typeof data !== 'object') {
    releaseChannels = {};
    return;
  }
  releaseChannels = {
    github_releases_url: data.github_releases_url || '',
    quark_url: data.quark_url || '',
    quark_share_text: data.quark_share_text || '',
    baidu_url: data.baidu_url || '',
    baidu_extract_code: data.baidu_extract_code || '',
    r2_latest_installer_url: data.r2_latest_installer_url || '',
  };
}

async function loadUpdateMetadata() {
  if (!API.base) return null;
  const res = await fetch(`${API.base}/api/update/channels`, { cache: 'no-store' });
  if (!res.ok) return null;
  return res.json();
}

function refreshAppVersionFooter() {
  const currentEl = document.getElementById('appVersionCurrent');
  const latestEl = document.getElementById('appVersionLatest');
  if (!currentEl || !latestEl) return;
  currentEl.textContent = appVersionState.current || '-';
  latestEl.classList.remove('version-latest-ok', 'version-latest-update', 'version-latest-failed');
  if (appVersionState.checkStatus === 'check_failed') {
    latestEl.textContent = t('dynamic.appUpdateBanner.检查失败');
    latestEl.classList.add('version-latest-failed');
    return;
  }
  if (appVersionState.checkStatus === 'update_available') {
    latestEl.textContent = appVersionState.stale
      ? `${appVersionState.latest || '-'}${t('dynamic.appUpdateBanner.缓存')}`
      : appVersionState.latest || '-';
    latestEl.classList.add('version-latest-update');
    return;
  }
  if (appVersionState.checkStatus === 'up_to_date') {
    latestEl.textContent = appVersionState.stale ? t('dynamic.appUpdateBanner.已是最新_缓存') : t('dynamic.appUpdateBanner.已是最新');
    latestEl.classList.add('version-latest-ok');
    return;
  }
  latestEl.textContent = '-';
}

function hideChannelDetail() {
  const panel = document.getElementById('appUpdateChannelDetail');
  if (panel) panel.classList.add('hidden');
  channelDetailState = { copyText: '', openUrl: '' };
}

function showChannelDetail(title, body, copyText, openUrl) {
  const panel = document.getElementById('appUpdateChannelDetail');
  const titleEl = document.getElementById('appUpdateChannelDetailTitle');
  const bodyEl = document.getElementById('appUpdateChannelDetailBody');
  if (!panel || !titleEl || !bodyEl) return;
  titleEl.textContent = title;
  bodyEl.textContent = body;
  channelDetailState = { copyText, openUrl };
  panel.classList.remove('hidden');
}

function showAppUpdateModal(latest, message) {
  const modal = document.getElementById('appUpdateModal');
  const msgEl = document.getElementById('appUpdateModalMessage');
  if (!modal || !msgEl) return;
  const current = appVersionState.current || '-';
  let text = t('dynamic.appUpdateBanner.当前版本_current_发现新版本');
  if (message) text += `\n\n${message}`;
  msgEl.textContent = text;
  hideChannelDetail();
  modal.classList.remove('hidden');
  modal.classList.add('flex');
  activateFocusTrap(modal, () => closeAppUpdateModal({ suppressSession: true }));
}

function closeAppUpdateModal({ suppressSession = true } = {}) {
  deactivateFocusTrap();
  const modal = document.getElementById('appUpdateModal');
  if (!modal) return;
  if (suppressSession && appVersionState.latest) {
    suppressAppUpdateForSession(appVersionState.latest);
  }
  hideChannelDetail();
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}

function maybeShowAppUpdateModal() {
  if (!pendingAppUpdatePrompt) return;
  const { latest, message } = pendingAppUpdatePrompt;
  if (isAppUpdateSuppressed(latest)) {
    pendingAppUpdatePrompt = null;
    return;
  }
  showAppUpdateModal(latest, message);
  pendingAppUpdatePrompt = null;
}

export async function initAppVersionAndUpdateCheck() {
  try {
    if (!API.base) {
      appVersionState.checkStatus = 'check_failed';
      refreshAppVersionFooter();
      return;
    }
    const versionRes = await fetch(`${API.base}/api/version`, { cache: 'no-store' });
    if (!versionRes.ok) throw new Error('version api failed');
    const versionData = await versionRes.json();
    const current = String(versionData.current_version || '').trim();
    appVersionState.current = current;
    window.DANMU_APP_VERSION = current;
    refreshAppVersionFooter();

    const metadata = await loadUpdateMetadata();
    if (!metadata?.latest_version) {
      appVersionState.checkStatus = 'check_failed';
      refreshAppVersionFooter();
      await loadAppUpdateDismissState();
      return;
    }

    applyReleaseChannels(metadata);
    const latest = normalizeVersionString(metadata.latest_version);
    appVersionState.latest = latest;
    appVersionState.releaseUrl = String(metadata.release_url || metadata.r2_latest_installer_url || '').trim();
    appVersionState.message = String(metadata.message || '').trim();
    appVersionState.stale = Boolean(metadata.stale);
    appVersionState.cacheState = String(metadata.cache_state || '');
    appVersionState.cacheAgeSec =
      typeof metadata.cache_age_sec === 'number' ? metadata.cache_age_sec : null;

    if (metadata.update_available) {
      appVersionState.checkStatus = 'update_available';
      pendingAppUpdatePrompt = { latest, message: appVersionState.message };
    } else {
      appVersionState.checkStatus = 'up_to_date';
      pendingAppUpdatePrompt = null;
    }
    refreshAppVersionFooter();

    await loadAppUpdateDismissState();
    maybeShowAppUpdateModal();
  } catch (error) {
    console.warn('[version] init check failed', error);
    appVersionState.checkStatus = 'check_failed';
    refreshAppVersionFooter();
  }
}

let velopackUpdateAvailable = false;

async function fetchVelopackUpdateStatus() {
  try {
    return await apiFetch('/api/update/status', { cache: 'no-store' });
  } catch {
    return null;
  }
}

async function runVelopackCheckUpdate() {
  return apiFetch('/api/update/check', { method: 'POST' });
}

async function runVelopackDownloadUpdate() {
  return apiFetch('/api/update/download', { method: 'POST' });
}

async function runVelopackRestartUpdate() {
  return apiFetch('/api/update/restart', { method: 'POST' });
}

function refreshVelopackUpdateButtons(data) {
  const dlBtn = document.getElementById('btnDownloadRestartAppUpdate');
  if (!dlBtn) return;
  const show = Boolean(
    data?.frozen && (data?.download_ready || data?.update_available) && !inAppUpdateBusy,
  );
  dlBtn.classList.toggle('hidden', !show);
  velopackUpdateAvailable = Boolean(data?.update_available);
  if (data?.latest_version && data.latest_version !== appVersionState.current) {
    appVersionState.latest = normalizeVersionString(data.latest_version);
    refreshAppVersionFooter();
  }
}

async function runInAppUpdateWithProgress({ fromModal = false, skipCheck = false } = {}) {
  if (inAppUpdateBusy) return false;
  inAppUpdateBusy = true;
  setUpdateControlsDisabled(true);
  setModalUpdateSectionsHidden(true);

  try {
    const initialStatus = await fetchVelopackUpdateStatus();
    if (initialStatus && !initialStatus.frozen) {
      showToast(initialStatus.message || t('dynamic.appUpdateBanner.源码模式不支持应用内更新'));
      return false;
    }

    let checkData = initialStatus;
    if (!skipCheck) {
      setUpdateProgress({
        visible: true,
        phase: 'checking',
        progress: 0,
        statusText: t('dynamic.appUpdateBanner.正在检查更新'),
      });
      checkData = await runVelopackCheckUpdate();
      refreshVelopackUpdateButtons(checkData);

      if (!checkData.frozen || checkData.error === 'not_frozen') {
        showToast(checkData.message || t('dynamic.appUpdateBanner.源码模式不支持应用内更新'));
        return false;
      }
      if (!checkData.ok) {
        applyVelopackStatusToProgress({
          ...checkData,
          download_phase: 'error',
        });
        showToast(checkData.error || checkData.message || t('dynamic.appUpdateBanner.检查更新失败'), true);
        return false;
      }
      if (!checkData.update_available) {
        hideUpdateProgress();
        showToast(checkData.message || t('dynamic.appUpdateBanner.已是最新版本'));
        return false;
      }

      applyVelopackStatusToProgress({
        ...checkData,
        download_phase: 'checking',
      });
    } else if (!checkData?.update_available && !checkData?.download_ready) {
      checkData = await runVelopackCheckUpdate();
      refreshVelopackUpdateButtons(checkData);
      if (!checkData.update_available) {
        hideUpdateProgress();
        showToast(checkData.message || t('dynamic.appUpdateBanner.请先检查更新'));
        return false;
      }
    }

    setUpdateProgress({
      visible: true,
      phase: 'downloading',
      progress: 0,
      totalBytes: Number(checkData?.package_size_bytes) || 0,
      statusText:
        checkData?.latest_version
          ? t('dynamic.appUpdateBanner.发现新版本_checkData_latest')
          : t('dynamic.appUpdateBanner.正在下载更新'),
    });

    const downloadStart = await runVelopackDownloadUpdate();
    refreshVelopackUpdateButtons(downloadStart);
    if (!downloadStart.ok) {
      applyVelopackStatusToProgress({
        ...downloadStart,
        download_phase: 'error',
      });
      showToast(downloadStart.error || downloadStart.message || t('dynamic.appUpdateBanner.下载失败'), true);
      return false;
    }

    if (downloadStart.download_ready || downloadStart.download_phase === 'ready') {
      applyVelopackStatusToProgress({
        ...downloadStart,
        download_phase: 'ready',
        download_progress: 100,
      });
    } else {
      await pollUpdateStatusUntilDone();
    }

    if (fromModal) {
      closeAppUpdateModal({ suppressSession: false });
    }

    setUpdateProgress({
      visible: true,
      phase: 'applying',
      progress: 100,
      totalBytes: Number(checkData?.package_size_bytes) || 0,
      downloadedBytes: Number(checkData?.package_size_bytes) || 0,
      statusText: t('dynamic.appUpdateBanner.更新已下载_正在重启安装'),
    });
    showToast(t('dynamic.appUpdateBanner.更新已下载_正在重启安装'));
    await runVelopackRestartUpdate();
    return true;
  } catch (error) {
    console.warn('[update] in-app flow failed', error);
    setUpdateProgress({
      visible: true,
      phase: 'error',
      progress: updateProgressState.progress,
      totalBytes: updateProgressState.totalBytes,
      downloadedBytes: updateProgressState.downloadedBytes,
      statusText: t('dynamic.appUpdateBanner.更新失败'),
      errorText: error?.message || t('dynamic.appUpdateBanner.应用内更新失败'),
    });
    showToast(error?.message || t('dynamic.appUpdateBanner.应用内更新失败'), true);
    return false;
  } finally {
    inAppUpdateBusy = false;
    setUpdateControlsDisabled(false);
    setModalUpdateSectionsHidden(false);
    if (updateProgressState.phase !== 'applying') {
      const shouldHide = updateProgressState.phase !== 'error';
      if (shouldHide) hideUpdateProgress();
    }
  }
}

async function runVelopackInAppUpdateFlow({ fromModal = false } = {}) {
  return runInAppUpdateWithProgress({ fromModal, skipCheck: false });
}

function openExternalUrl(url, fallbackMessage) {
  try {
    const opened = window.open(url, '_blank', 'noopener,noreferrer');
    if (!opened) {
      navigator.clipboard?.writeText(url);
      showToast(fallbackMessage || t('dynamic.appUpdateBanner.链接已复制到剪贴板_请手动打开'));
      return;
    }
    showToast(t('dynamic.appUpdateBanner.已在浏览器中打开链接'));
  } catch {
    showToast(fallbackMessage || t('dynamic.appUpdateBanner.请手动打开_url'));
  }
}

async function copyTextToClipboard(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(successMessage || t('common.copied'));
  } catch {
    showToast(t('dynamic.appUpdateBanner.复制失败_请手动选择文本复制'), true);
  }
}

function handleGitHubUpdateClick() {
  const url = releaseChannels.github_releases_url;
  if (!url) {
    showToast(t('dynamic.appUpdateBanner.渠道信息不可用'), true);
    return;
  }
  openExternalUrl(url, t('dynamic.appUpdateBanner.GitHub_Releases_镜像链接已复制到'));
}

function handleQuarkUpdateClick() {
  const url = releaseChannels.quark_url;
  const shareText = releaseChannels.quark_share_text;
  if (!url || !shareText) {
    showToast(t('dynamic.appUpdateBanner.渠道信息不可用'), true);
    return;
  }
  const body = t('dynamic.appUpdateBanner.shareText_n_n链接_url');
  showChannelDetail(t('dynamic.appUpdateBanner.夸克网盘'), body, `${shareText}\n${url}`, url);
}

function handleBaiduUpdateClick() {
  const url = releaseChannels.baidu_url;
  const code = releaseChannels.baidu_extract_code;
  if (!url || !code) {
    showToast(t('dynamic.appUpdateBanner.渠道信息不可用'), true);
    return;
  }
  const body = t('dynamic.appUpdateBanner.链接_url_n提取码_code');
  showChannelDetail(t('dynamic.appUpdateBanner.百度网盘'), body, `${body}`, url);
}

export async function handleCheckAppUpdateClick() {
  if (inAppUpdateBusy) return;
  inAppUpdateBusy = true;
  setUpdateControlsDisabled(true);
  try {
    setUpdateProgress({
      visible: true,
      phase: 'checking',
      progress: 0,
      statusText: t('dynamic.appUpdateBanner.正在检查更新'),
    });
    const data = await runVelopackCheckUpdate();
    refreshVelopackUpdateButtons(data);
    if (!data.frozen) {
      hideUpdateProgress();
      showToast(data.message || t('dynamic.appUpdateBanner.源码模式不支持应用内更新'));
      return;
    }
    if (!data.ok) {
      applyVelopackStatusToProgress({ ...data, download_phase: 'error' });
      showToast(data.error || data.message || t('dynamic.appUpdateBanner.检查更新失败'), true);
      return;
    }
    if (data.update_available) {
      const totalBytes = Number(data.package_size_bytes) || 0;
      const sizeHint = totalBytes > 0 ? t('dynamic.appUpdateBanner.更新包约_formatBytes_tota') : '';
      setUpdateProgress({
        visible: true,
        phase: 'idle',
        progress: 0,
        totalBytes,
        statusText: t('dynamic.appUpdateBanner.newVersionStatus', {
          latest: data.latest_version || '',
          sizeHint,
        }),
      });
      showToast(data.message || t('dynamic.appUpdateBanner.发现新版本_data_latest_vers_2'));
      window.setTimeout(() => {
        if (updateProgressState.phase === 'idle' && updateProgressState.visible) {
          hideUpdateProgress();
        }
      }, 5000);
    } else {
      hideUpdateProgress();
      showToast(data.message || t('dynamic.appUpdateBanner.已是最新版本'));
    }
  } catch (error) {
    console.warn('[update] check failed', error);
    setUpdateProgress({
      visible: true,
      phase: 'error',
      statusText: t('dynamic.appUpdateBanner.检查更新失败'),
      errorText: error?.message || t('dynamic.appUpdateBanner.检查更新失败'),
    });
    showToast(t('dynamic.appUpdateBanner.检查更新失败'), true);
  } finally {
    inAppUpdateBusy = false;
    setUpdateControlsDisabled(false);
  }
}

export async function handleDownloadRestartAppUpdateClick() {
  await runInAppUpdateWithProgress({ skipCheck: velopackUpdateAvailable });
}

export function initVelopackUpdateButtons() {
  document.getElementById('btnCheckAppUpdate')?.addEventListener('click', () => {
    void handleCheckAppUpdateClick();
  });
  document.getElementById('btnDownloadRestartAppUpdate')?.addEventListener('click', () => {
    void handleDownloadRestartAppUpdateClick();
  });
  void fetchVelopackUpdateStatus().then((data) => {
    if (data) refreshVelopackUpdateButtons(data);
  });
}

export function initAppUpdateModal(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;
  initVelopackUpdateButtons();

  document.getElementById('btnAppUpdateInApp')?.addEventListener('click', () => {
    void runVelopackInAppUpdateFlow({ fromModal: true });
  });
  document.getElementById('btnAppUpdateGitHub')?.addEventListener('click', () => {
    handleGitHubUpdateClick();
  });
  document.getElementById('btnAppUpdateQuark')?.addEventListener('click', () => {
    handleQuarkUpdateClick();
  });
  document.getElementById('btnAppUpdateBaidu')?.addEventListener('click', () => {
    handleBaiduUpdateClick();
  });
  document.getElementById('btnAppUpdateChannelCopy')?.addEventListener('click', () => {
    if (channelDetailState.copyText) {
      void copyTextToClipboard(channelDetailState.copyText, t('dynamic.appUpdateBanner.分享信息已复制到剪贴板'));
    }
  });
  document.getElementById('btnAppUpdateChannelOpen')?.addEventListener('click', () => {
    if (channelDetailState.openUrl) {
      openExternalUrl(channelDetailState.openUrl, t('dynamic.appUpdateBanner.链接已复制到剪贴板'));
    }
  });
  document.getElementById('btnAppUpdateDismiss')?.addEventListener('click', async () => {
    const latest = appVersionState.latest;
    closeAppUpdateModal({ suppressSession: false });
    if (latest) {
      await persistAppUpdateDismiss(latest);
    }
  });
  document.getElementById('appUpdateModal')?.addEventListener('click', (event) => {
    if (event.target.id === 'appUpdateModal') {
      closeAppUpdateModal({ suppressSession: true });
    }
  });
}
