import { API, apiFetch } from './transport.js';

const APP_UPDATE_DISMISS_LOCAL_KEY = 'danmu_app_update_dismissed_latest';

const appVersionState = {
  current: '',
  latest: '',
  releaseUrl: '',
  message: '',
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
    latestEl.textContent = '检查失败';
    latestEl.classList.add('version-latest-failed');
    return;
  }
  if (appVersionState.checkStatus === 'update_available') {
    latestEl.textContent = appVersionState.latest || '-';
    latestEl.classList.add('version-latest-update');
    return;
  }
  if (appVersionState.checkStatus === 'up_to_date') {
    latestEl.textContent = '已是最新';
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
  let text = `当前版本 ${current}，发现新版本 ${latest}。`;
  if (message) text += `\n\n${message}`;
  msgEl.textContent = text;
  hideChannelDetail();
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeAppUpdateModal({ suppressSession = true } = {}) {
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
  const show = Boolean(data?.frozen && (data?.download_ready || data?.update_available));
  dlBtn.classList.toggle('hidden', !show);
  velopackUpdateAvailable = Boolean(data?.update_available);
  if (data?.latest_version && data.latest_version !== appVersionState.current) {
    appVersionState.latest = normalizeVersionString(data.latest_version);
    refreshAppVersionFooter();
  }
}

async function runVelopackInAppUpdateFlow({ fromModal = false } = {}) {
  try {
    const status = await fetchVelopackUpdateStatus();
    if (status && !status.frozen) {
      showToast(status.message || '源码模式不支持应用内更新');
      return false;
    }

    showToast('正在检查更新…');
    const checkData = await runVelopackCheckUpdate();
    refreshVelopackUpdateButtons(checkData);

    if (!checkData.frozen || checkData.error === 'not_frozen') {
      showToast(checkData.message || '源码模式不支持应用内更新');
      return false;
    }
    if (!checkData.ok) {
      showToast(checkData.error || checkData.message || '检查更新失败', true);
      return false;
    }
    if (!checkData.update_available) {
      showToast(
        checkData.message ||
          'Velopack 更新源暂未检测到新版本，请稍后再试或使用其它下载渠道',
      );
      return false;
    }

    showToast(checkData.message || `发现新版本 ${checkData.latest_version}，正在下载…`);
    const downloadData = await runVelopackDownloadUpdate();
    refreshVelopackUpdateButtons(downloadData);
    if (!downloadData.ok) {
      showToast(downloadData.error || downloadData.message || '下载失败', true);
      return false;
    }
    if (!downloadData.download_ready) {
      showToast(downloadData.message || '请先检查更新');
      return false;
    }

    if (fromModal) {
      closeAppUpdateModal({ suppressSession: false });
    }
    showToast('更新已下载，正在重启安装…');
    await runVelopackRestartUpdate();
    return true;
  } catch (error) {
    console.warn('[update] in-app flow failed', error);
    showToast('应用内更新失败', true);
    return false;
  }
}

function openExternalUrl(url, fallbackMessage) {
  try {
    const opened = window.open(url, '_blank', 'noopener,noreferrer');
    if (!opened) {
      navigator.clipboard?.writeText(url);
      showToast(fallbackMessage || '链接已复制到剪贴板，请手动打开');
      return;
    }
    showToast('已在浏览器中打开链接');
  } catch {
    showToast(fallbackMessage || `请手动打开：${url}`);
  }
}

async function copyTextToClipboard(text, successMessage) {
  try {
    await navigator.clipboard.writeText(text);
    showToast(successMessage || '已复制到剪贴板');
  } catch {
    showToast('复制失败，请手动选择文本复制', true);
  }
}

function handleGitHubUpdateClick() {
  const url = releaseChannels.github_releases_url;
  if (!url) {
    showToast('渠道信息不可用', true);
    return;
  }
  openExternalUrl(url, 'GitHub Releases 镜像链接已复制到剪贴板');
}

function handleQuarkUpdateClick() {
  const url = releaseChannels.quark_url;
  const shareText = releaseChannels.quark_share_text;
  if (!url || !shareText) {
    showToast('渠道信息不可用', true);
    return;
  }
  const body = `${shareText}\n\n链接：${url}`;
  showChannelDetail('夸克网盘', body, `${shareText}\n${url}`, url);
}

function handleBaiduUpdateClick() {
  const url = releaseChannels.baidu_url;
  const code = releaseChannels.baidu_extract_code;
  if (!url || !code) {
    showToast('渠道信息不可用', true);
    return;
  }
  const body = `链接：${url}\n提取码：${code}`;
  showChannelDetail('百度网盘', body, `${body}`, url);
}

export async function handleCheckAppUpdateClick() {
  try {
    const data = await runVelopackCheckUpdate();
    refreshVelopackUpdateButtons(data);
    if (!data.frozen) {
      showToast(data.message || '源码模式不支持应用内更新');
      return;
    }
    if (!data.ok) {
      showToast(data.error || data.message || '检查更新失败', true);
      return;
    }
    if (data.update_available) {
      showToast(data.message || `发现新版本 ${data.latest_version}`);
    } else {
      showToast(data.message || '已是最新版本');
    }
  } catch (error) {
    console.warn('[update] check failed', error);
    showToast('检查更新失败', true);
  }
}

export async function handleDownloadRestartAppUpdateClick() {
  try {
    const data = await runVelopackDownloadUpdate();
    if (!data.ok) {
      showToast(data.error || data.message || '下载失败', true);
      return;
    }
    refreshVelopackUpdateButtons(data);
    if (!data.download_ready) {
      showToast(data.message || '请先检查更新');
      return;
    }
  } catch (error) {
    console.warn('[update] download failed', error);
    showToast('下载更新失败', true);
    return;
  }
  try {
    showToast('更新已下载，正在重启安装…');
    await runVelopackRestartUpdate();
  } catch (error) {
    console.warn('[update] restart failed', error);
    showToast('重启安装失败', true);
  }
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
      void copyTextToClipboard(channelDetailState.copyText, '分享信息已复制到剪贴板');
    }
  });
  document.getElementById('btnAppUpdateChannelOpen')?.addEventListener('click', () => {
    if (channelDetailState.openUrl) {
      openExternalUrl(channelDetailState.openUrl, '链接已复制到剪贴板');
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
