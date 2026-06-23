import { API, apiFetch } from './transport.js';

const ANNOUNCEMENTS_READ_IDS_KEY = 'danmu_announcements_read_ids';
const ANNOUNCEMENTS_LAST_SEEN_MS_KEY = 'danmu_announcements_last_seen_ms';
/** @deprecated migrated to ID set + ms; removed after one-time migration */
const ANNOUNCEMENTS_LAST_SEEN_KEY = 'danmu_announcements_last_seen_at';
const ANNOUNCEMENTS_OVERVIEW_BANNER_DISMISSED_ID_KEY =
  'danmu_announcements_overview_banner_dismissed_id';
const ANNOUNCEMENTS_BADGE_POLL_MS = 5 * 60 * 1000;
const ANNOUNCEMENTS_READ_IDS_MAX = 200;
const ANNOUNCEMENT_SNIPPET_MAX_CHARS = 30;

let announcementsBadgePollTimer = null;
let announcementsReadStateLoaded = false;
let announcementsLegacyMigrated = false;
let overviewBannerLatestId = null;

const announcementsReadState = {
  readIds: new Set(),
  lastSeenMs: 0,
  overviewBannerDismissedId: '',
};

function readAnnouncementsReadIdsFromLocal() {
  try {
    const raw = localStorage.getItem(ANNOUNCEMENTS_READ_IDS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((id) => typeof id === 'string' && id) : [];
  } catch {
    return [];
  }
}

function readAnnouncementsLastSeenMsFromLocal() {
  try {
    const raw = localStorage.getItem(ANNOUNCEMENTS_LAST_SEEN_MS_KEY);
    const n = Number(raw);
    return Number.isFinite(n) && n >= 0 ? Math.floor(n) : 0;
  } catch {
    return 0;
  }
}

function readOverviewBannerDismissedIdFromLocal() {
  try {
    return localStorage.getItem(ANNOUNCEMENTS_OVERVIEW_BANNER_DISMISSED_ID_KEY) || '';
  } catch {
    return '';
  }
}

function writeOverviewBannerDismissedIdToLocal(id) {
  try {
    if (id) {
      localStorage.setItem(ANNOUNCEMENTS_OVERVIEW_BANNER_DISMISSED_ID_KEY, id);
    } else {
      localStorage.removeItem(ANNOUNCEMENTS_OVERVIEW_BANNER_DISMISSED_ID_KEY);
    }
  } catch {
    /* ignore quota / private mode */
  }
}

function writeAnnouncementsReadStateToLocal() {
  try {
    const ids = [...announcementsReadState.readIds];
    const trimmed =
      ids.length > ANNOUNCEMENTS_READ_IDS_MAX
        ? ids.slice(-ANNOUNCEMENTS_READ_IDS_MAX)
        : ids;
    localStorage.setItem(ANNOUNCEMENTS_READ_IDS_KEY, JSON.stringify(trimmed));
    localStorage.setItem(
      ANNOUNCEMENTS_LAST_SEEN_MS_KEY,
      String(announcementsReadState.lastSeenMs),
    );
    writeOverviewBannerDismissedIdToLocal(
      announcementsReadState.overviewBannerDismissedId,
    );
  } catch {
    /* ignore quota / private mode */
  }
}

function mergeAnnouncementsReadState(remote, localIds, localMs, localOverviewDismissedId) {
  const mergedIds = new Set();
  if (Array.isArray(remote?.readIds)) {
    for (const id of remote.readIds) {
      if (typeof id === 'string' && id) mergedIds.add(id);
    }
  }
  for (const id of localIds) mergedIds.add(id);
  let lastSeenMs = 0;
  if (remote && Number.isFinite(Number(remote.lastSeenMs))) {
    lastSeenMs = Math.max(0, Math.floor(Number(remote.lastSeenMs)));
  }
  lastSeenMs = Math.max(lastSeenMs, localMs);
  const remoteDismissed =
    typeof remote?.overviewBannerDismissedId === 'string'
      ? remote.overviewBannerDismissedId.trim()
      : '';
  const overviewBannerDismissedId = remoteDismissed || localOverviewDismissedId || '';
  announcementsReadState.readIds = mergedIds;
  announcementsReadState.lastSeenMs = lastSeenMs;
  announcementsReadState.overviewBannerDismissedId = overviewBannerDismissedId;
}

function serializeAnnouncementsReadState() {
  const readIds = [...announcementsReadState.readIds];
  const trimmed =
    readIds.length > ANNOUNCEMENTS_READ_IDS_MAX
      ? readIds.slice(-ANNOUNCEMENTS_READ_IDS_MAX)
      : readIds;
  return {
    readIds: trimmed,
    lastSeenMs: announcementsReadState.lastSeenMs,
    overviewBannerDismissedId: announcementsReadState.overviewBannerDismissedId || '',
  };
}

export async function loadAnnouncementsReadState() {
  const localIds = readAnnouncementsReadIdsFromLocal();
  const localMs = readAnnouncementsLastSeenMsFromLocal();
  const localOverviewDismissedId = readOverviewBannerDismissedIdFromLocal();
  let remote = null;
  try {
    if (API.base) {
      remote = await fetch(`${API.base}/api/announcements-read-state`, {
        cache: 'no-store',
      }).then((r) => (r.ok ? r.json() : null));
    }
  } catch {
    remote = null;
  }
  mergeAnnouncementsReadState(remote, localIds, localMs, localOverviewDismissedId);
  writeAnnouncementsReadStateToLocal();
  announcementsReadStateLoaded = true;
}

async function persistAnnouncementsReadState() {
  writeAnnouncementsReadStateToLocal();
  try {
    await apiFetch('/api/announcements-read-state', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(serializeAnnouncementsReadState()),
    });
  } catch {
    /* localStorage remains; next GET will merge */
  }
}

function maxAnnouncementCreatedMs(rows) {
  let maxMs = 0;
  for (const row of rows || []) {
    const t = Date.parse(row.created_at || '');
    if (!Number.isNaN(t) && t > maxMs) maxMs = t;
  }
  return maxMs;
}

function migrateLegacyAnnouncementsLastSeen(rows) {
  if (announcementsLegacyMigrated) return;
  announcementsLegacyMigrated = true;
  let legacyIso = '';
  try {
    legacyIso = localStorage.getItem(ANNOUNCEMENTS_LAST_SEEN_KEY) || '';
  } catch {
    legacyIso = '';
  }
  if (!legacyIso) return;
  const seenMs = Date.parse(legacyIso);
  if (!Number.isNaN(seenMs)) {
    for (const row of rows || []) {
      const t = Date.parse(row.created_at || '');
      if (row.id && !Number.isNaN(t) && t <= seenMs) {
        announcementsReadState.readIds.add(row.id);
      }
    }
    announcementsReadState.lastSeenMs = Math.max(announcementsReadState.lastSeenMs, seenMs);
  }
  try {
    localStorage.removeItem(ANNOUNCEMENTS_LAST_SEEN_KEY);
  } catch {
    /* ignore */
  }
}

function hasUnreadAnnouncements(rows) {
  if (!rows?.length) return false;
  return rows.some((row) => row.id && !announcementsReadState.readIds.has(row.id));
}

function markAnnouncementsRead(rows) {
  migrateLegacyAnnouncementsLastSeen(rows);
  for (const row of rows || []) {
    if (row.id) announcementsReadState.readIds.add(row.id);
  }
  const maxMs = maxAnnouncementCreatedMs(rows);
  if (maxMs > 0) {
    announcementsReadState.lastSeenMs = Math.max(announcementsReadState.lastSeenMs, maxMs);
  }
  if (announcementsReadState.readIds.size > ANNOUNCEMENTS_READ_IDS_MAX) {
    const trimmed = [...announcementsReadState.readIds].slice(-ANNOUNCEMENTS_READ_IDS_MAX);
    announcementsReadState.readIds = new Set(trimmed);
  }
  persistAnnouncementsReadState().catch(console.error);
}

export function updateAnnouncementsNavBadge(show) {
  const badge = document.getElementById('announcementsNavBadge');
  if (!badge) return;
  badge.classList.toggle('hidden', !show);
  badge.setAttribute('aria-hidden', show ? 'false' : 'true');
}

function getOverviewBannerDismissedId() {
  return announcementsReadState.overviewBannerDismissedId || '';
}

function setOverviewBannerDismissedId(id) {
  announcementsReadState.overviewBannerDismissedId = id ? String(id) : '';
  writeOverviewBannerDismissedIdToLocal(announcementsReadState.overviewBannerDismissedId);
  persistAnnouncementsReadState().catch(console.error);
}

export function buildAnnouncementSnippetParts(row) {
  const title = String(row?.title ?? '').trim();
  const body = String(row?.body ?? '').trim();
  let combined;
  let titleCharCount;

  if (title && body) {
    combined = `${title}：${body}`;
    titleCharCount = Array.from(title).length + 1;
  } else if (title) {
    combined = title;
    titleCharCount = Array.from(title).length;
  } else if (body) {
    combined = body;
    titleCharCount = 0;
  } else {
    return null;
  }

  const chars = Array.from(combined);
  const overLimit = chars.length > ANNOUNCEMENT_SNIPPET_MAX_CHARS;
  const truncatedChars = overLimit ? chars.slice(0, ANNOUNCEMENT_SNIPPET_MAX_CHARS) : chars;
  const suffix = overLimit ? '…' : '';

  if (!title || !body) {
    if (title) {
      return { hasTitle: true, titlePart: truncatedChars.join('') + suffix, restPart: '' };
    }
    return { hasTitle: false, titlePart: '', restPart: truncatedChars.join('') + suffix };
  }

  const titleOnlyLen = Array.from(title).length;
  if (truncatedChars.length <= titleOnlyLen) {
    return { hasTitle: true, titlePart: truncatedChars.join('') + suffix, restPart: '' };
  }

  return {
    hasTitle: true,
    titlePart: title,
    restPart: truncatedChars.slice(titleCharCount).join('') + suffix,
  };
}

export function buildAnnouncementSnippet(row) {
  const parts = buildAnnouncementSnippetParts(row);
  if (!parts) return '';
  return (parts.hasTitle ? parts.titlePart : '') + parts.restPart;
}

function renderOverviewAnnouncementBannerText(textEl, parts) {
  if (!parts || (!parts.titlePart && !parts.restPart)) {
    textEl.textContent = '';
    return;
  }
  if (parts.hasTitle && parts.titlePart) {
    textEl.innerHTML =
      `<strong class="overview-announcement-banner-title">${escapeHtml(parts.titlePart)}</strong>` +
      escapeHtml(parts.restPart);
  } else {
    textEl.textContent = parts.restPart;
  }
}

function hideOverviewAnnouncementBanner() {
  const banner = document.getElementById('overviewAnnouncementBanner');
  if (!banner) return;
  banner.classList.add('hidden');
  overviewBannerLatestId = null;
}

export function updateOverviewAnnouncementBanner(rows) {
  const banner = document.getElementById('overviewAnnouncementBanner');
  const textEl = document.getElementById('overviewAnnouncementBannerText');
  if (!banner || !textEl) return;

  if (!window.DanmuSupabase?.isConfigured?.() || !rows?.length) {
    hideOverviewAnnouncementBanner();
    return;
  }

  const latest = rows[0];
  if (!latest?.id) {
    hideOverviewAnnouncementBanner();
    return;
  }

  const parts = buildAnnouncementSnippetParts(latest);
  if (!parts || (!parts.titlePart && !parts.restPart)) {
    hideOverviewAnnouncementBanner();
    return;
  }

  if (latest.id === getOverviewBannerDismissedId()) {
    hideOverviewAnnouncementBanner();
    return;
  }

  overviewBannerLatestId = latest.id;
  const level = ['info', 'warning', 'critical'].includes(latest.level) ? latest.level : 'info';
  banner.classList.remove('hidden', 'announcement-level-warning', 'announcement-level-critical');
  if (level === 'warning' || level === 'critical') {
    banner.classList.add(`announcement-level-${level}`);
  }
  renderOverviewAnnouncementBannerText(textEl, parts);
}

export function dismissOverviewAnnouncementBanner(id) {
  if (id) setOverviewBannerDismissedId(id);
  hideOverviewAnnouncementBanner();
}

export function getOverviewBannerLatestId() {
  return overviewBannerLatestId;
}

export async function refreshAnnouncementsUnreadBadge() {
  if (!announcementsReadStateLoaded) {
    await loadAnnouncementsReadState();
  }
  if (!window.DanmuSupabase?.isConfigured?.()) {
    updateAnnouncementsNavBadge(false);
    hideOverviewAnnouncementBanner();
    return;
  }
  try {
    const rows = await window.DanmuSupabase.listAnnouncements();
    const list = Array.isArray(rows) ? rows : [];
    migrateLegacyAnnouncementsLastSeen(list);
    updateOverviewAnnouncementBanner(list);
    const onAnnouncementsPage = document
      .getElementById('page-announcements')
      ?.classList.contains('active');
    if (onAnnouncementsPage) {
      markAnnouncementsRead(list);
      updateAnnouncementsNavBadge(false);
      return;
    }
    updateAnnouncementsNavBadge(hasUnreadAnnouncements(list));
  } catch {
    hideOverviewAnnouncementBanner();
    /* keep current badge state */
  }
}

export function stopAnnouncementsBadgePolling() {
  if (announcementsBadgePollTimer) {
    clearInterval(announcementsBadgePollTimer);
    announcementsBadgePollTimer = null;
  }
}

export function startAnnouncementsBadgePolling() {
  if (announcementsBadgePollTimer) return;
  announcementsBadgePollTimer = setInterval(() => {
    refreshAnnouncementsUnreadBadge().catch(console.error);
  }, ANNOUNCEMENTS_BADGE_POLL_MS);
}

function formatAnnouncementDate(iso) {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return String(iso);
  }
}

function escapeHtml(text) {
  return String(text ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function renderAnnouncementsList(items) {
  const list = document.getElementById('announcementsList');
  if (!list) return;
  if (!window.DanmuSupabase?.isConfigured?.()) {
    list.innerHTML =
      '<p class="announcements-error">未配置云端公告服务。请将 supabase-config.example.js 复制为 supabase-config.js 并填入项目地址与密钥。</p>';
    return;
  }
  if (!items?.length) {
    list.innerHTML = '<p class="announcements-empty">暂无公告</p>';
    return;
  }
  list.innerHTML = items
    .map((row) => {
      const level = ['info', 'warning', 'critical'].includes(row.level) ? row.level : 'info';
      const pinned = row.pinned
        ? '<span class="announcement-pinned-badge">置顶</span>'
        : '';
      const meta = formatAnnouncementDate(row.created_at);
      return `<article class="announcement-card announcement-level-${level}">
        <header class="announcement-card-header">
          <h3 class="announcement-card-title">${escapeHtml(row.title)}</h3>
          ${pinned}
          <time class="announcement-card-meta" datetime="${escapeHtml(row.created_at || '')}">${escapeHtml(meta)}</time>
        </header>
        <div class="announcement-card-body">${escapeHtml(row.body)}</div>
      </article>`;
    })
    .join('');
}

export async function loadAnnouncementsPage() {
  const list = document.getElementById('announcementsList');
  if (!list) return;
  if (!window.DanmuSupabase?.isConfigured?.()) {
    renderAnnouncementsList([]);
    return;
  }
  list.innerHTML = '<p class="text-gray-500 text-sm">正在加载公告…</p>';
  try {
    const rows = await window.DanmuSupabase.listAnnouncements();
    const items = Array.isArray(rows) ? rows : [];
    renderAnnouncementsList(items);
    markAnnouncementsRead(items);
    updateAnnouncementsNavBadge(false);
  } catch (err) {
    list.innerHTML = `<p class="announcements-error">${escapeHtml(err.message || '加载失败')} <button type="button" class="underline font-semibold" id="btnAnnouncementsRetry">重试</button></p>`;
    document.getElementById('btnAnnouncementsRetry')?.addEventListener('click', () => {
      loadAnnouncementsPage().catch(console.error);
    });
  }
}

export function bindAnnouncementsControls(showToast) {
  document.getElementById('btnAnnouncementsRefresh')?.addEventListener('click', () => {
    loadAnnouncementsPage().catch((e) => showToast(e.message, true));
  });
  document.getElementById('btnOverviewAnnouncementDismiss')?.addEventListener('click', () => {
    dismissOverviewAnnouncementBanner(overviewBannerLatestId);
  });
}
