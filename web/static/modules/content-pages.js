/** Announcements, feedback, AI Butler pages. */

import { API, apiFetch } from './transport.js';
import { MASKED_API_KEY, reloadConfigFromServer } from './settings.js';

let bindDeps = { showToast: () => {}, navigate: () => {} };

export function configureContentPageBindings(deps) {
  bindDeps = { ...bindDeps, ...deps };
}

function showToast(msg, isError = false) {
  bindDeps.showToast(msg, isError);
}

function navigate(page) {
  bindDeps.navigate(page);
}

function openRewardModal() {
  const modal = document.getElementById('rewardModal');
  if (!modal) return;
  modal.classList.remove('hidden');
  modal.classList.add('flex');
}

function closeRewardModal() {
  const modal = document.getElementById('rewardModal');
  if (!modal) return;
  modal.classList.add('hidden');
  modal.classList.remove('flex');
}
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

function buildAnnouncementSnippetParts(row) {
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

function buildAnnouncementSnippet(row) {
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

function updateOverviewAnnouncementBanner(rows) {
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
    const onAnnouncementsPage = document.getElementById('page-announcements')?.classList.contains('active');
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
    const list = Array.isArray(rows) ? rows : [];
    renderAnnouncementsList(list);
    markAnnouncementsRead(list);
    updateAnnouncementsNavBadge(false);
  } catch (err) {
    list.innerHTML = `<p class="announcements-error">${escapeHtml(err.message || '加载失败')} <button type="button" class="underline font-semibold" id="btnAnnouncementsRetry">重试</button></p>`;
    document.getElementById('btnAnnouncementsRetry')?.addEventListener('click', () => {
      loadAnnouncementsPage().catch(console.error);
    });
  }
}

function updateFeedbackQuotaHint(quota) {
  const el = document.getElementById('feedbackQuotaHint');
  if (!el) return;
  if (!quota) {
    el.textContent = '暂时无法查询提交额度';
    return;
  }
  const remaining = Number(quota.remaining ?? 0);
  const limit = Number(quota.limit ?? 2);
  const hint = quota.resets_hint || `每 3 小时最多提交 ${limit} 条`;
  if (remaining <= 0) {
    el.textContent = hint;
    el.classList.add('text-red-600');
  } else {
    el.textContent = `本机还可提交 ${remaining} / ${limit} 条（${hint}）`;
    el.classList.remove('text-red-600');
  }
  const submitBtn = document.getElementById('btnFeedbackSubmit');
  if (submitBtn) submitBtn.disabled = remaining <= 0;
}

async function refreshFeedbackQuota() {
  const el = document.getElementById('feedbackQuotaHint');
  if (!el) return;
  if (!window.DanmuSupabase?.isConfigured?.()) {
    el.textContent = '未配置云端反馈服务，无法在线提交（仍可通过下方社群联系）';
    const submitBtn = document.getElementById('btnFeedbackSubmit');
    if (submitBtn) submitBtn.disabled = true;
    return;
  }
  el.textContent = '正在查询提交额度…';
  el.classList.remove('text-red-600');
  try {
    const quota = await window.DanmuSupabase.getFeedbackQuota();
    updateFeedbackQuotaHint(quota);
  } catch (err) {
    el.textContent = err.message || '无法查询提交额度';
  }
}

let feedbackPageInitialized = false;

export function initFeedbackPage() {
  refreshFeedbackQuota().catch(console.error);
  if (feedbackPageInitialized) return;
  feedbackPageInitialized = true;
  document.getElementById('feedbackForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!window.DanmuSupabase?.isConfigured?.()) {
      showToast('未配置云端反馈服务', true);
      return;
    }
    const content = document.getElementById('feedbackContent')?.value ?? '';
    const contact = document.getElementById('feedbackContact')?.value ?? '';
    const btn = document.getElementById('btnFeedbackSubmit');
    if (btn) btn.disabled = true;
    try {
      await window.DanmuSupabase.submitFeedback({ content, contact });
      showToast('反馈已提交，感谢你的帮助~');
      const ta = document.getElementById('feedbackContent');
      const inp = document.getElementById('feedbackContact');
      if (ta) ta.value = '';
      if (inp) inp.value = '';
      await refreshFeedbackQuota();
    } catch (err) {
      showToast(err.message || '提交失败', true);
    } finally {
      await refreshFeedbackQuota();
    }
  });
}

const AI_BUTLER_STATE = {
  messages: [],
  pendingPatch: null,
  pendingReasons: null,
  pendingCurrent: null,
  sending: false,
};

const AI_BUTLER_FIELD_LABELS = {
  temperature: '创意程度 (temperature)',
  max_tokens: '输出 token 上限',
  danmu_speed: '弹幕速度',
  danmu_lines: '弹幕行数',
  danmu_max_chars: '单条字数上限',
  dedup_threshold: '去重阈值',
  layout_mode: '显示区域',
  opacity: '透明度',
  font_size: '字号',
  eviction_mode: '退场模式',
  empty_accel: '空轨道加速',
  image_max_width: '截图最大宽度',
  image_quality: 'JPEG 质量',
  memory_mode: '记忆模式',
  memory_window: '记忆窗口',
  normal_recognition_interval_sec: '识图间隔（秒）',
  normal_reply_count: '每批弹幕条数',
};

function aiButlerFieldLabel(key) {
  return AI_BUTLER_FIELD_LABELS[key] || key;
}

function appendAiButlerMessage(role, text) {
  const box = document.getElementById('aiButlerMessages');
  if (!box) return;
  const row = document.createElement('div');
  row.className =
    role === 'user' ? 'ai-butler-msg ai-butler-msg-user' : 'ai-butler-msg ai-butler-msg-assistant';
  const bubble = document.createElement('div');
  bubble.className = 'ai-butler-msg-bubble';
  bubble.textContent = text;
  row.appendChild(bubble);
  box.appendChild(row);
  box.scrollTop = box.scrollHeight;
}

function showAiButlerThinking() {
  removeAiButlerThinking();
  const box = document.getElementById('aiButlerMessages');
  if (!box) return;
  const row = document.createElement('div');
  row.id = 'aiButlerThinkingRow';
  row.className = 'ai-butler-msg ai-butler-msg-assistant ai-butler-msg-thinking';
  row.setAttribute('aria-busy', 'true');
  const bubble = document.createElement('div');
  bubble.className = 'ai-butler-msg-bubble ai-butler-thinking-bubble';
  bubble.textContent = '正在思考中…';
  row.appendChild(bubble);
  box.appendChild(row);
  box.scrollTop = box.scrollHeight;
}

function removeAiButlerThinking() {
  document.getElementById('aiButlerThinkingRow')?.remove();
}

function setAiButlerInputBusy(busy) {
  const input = document.getElementById('aiButlerInput');
  const sendBtn = document.getElementById('btnAiButlerSend');
  if (input) input.disabled = busy;
  if (sendBtn) {
    sendBtn.disabled = busy;
    sendBtn.textContent = busy ? '思考中…' : '发送';
  }
}

function clearAiButlerSuggestionPanel() {
  AI_BUTLER_STATE.pendingPatch = null;
  AI_BUTLER_STATE.pendingReasons = null;
  AI_BUTLER_STATE.pendingCurrent = null;
  const panel = document.getElementById('aiButlerSuggestionPanel');
  const body = document.getElementById('aiButlerPatchBody');
  const hint = document.getElementById('aiButlerDiscardedHint');
  if (body) body.replaceChildren();
  if (hint) {
    hint.textContent = '';
    hint.classList.add('hidden');
  }
  panel?.classList.add('hidden');
}

function renderAiButlerSuggestion(data) {
  const patch = data.patch || {};
  const keys = Object.keys(patch);
  if (!keys.length) {
    clearAiButlerSuggestionPanel();
    return;
  }
  AI_BUTLER_STATE.pendingPatch = { ...patch };
  AI_BUTLER_STATE.pendingReasons = { ...(data.reasons || {}) };
  AI_BUTLER_STATE.pendingCurrent = { ...(data.current_values || {}) };

  const body = document.getElementById('aiButlerPatchBody');
  if (!body) return;
  body.replaceChildren();
  keys.forEach((key) => {
    const tr = document.createElement('tr');
    const cells = [
      aiButlerFieldLabel(key),
      String(AI_BUTLER_STATE.pendingCurrent[key] ?? '—'),
      String(patch[key] ?? ''),
      String((data.reasons && data.reasons[key]) || '—'),
    ];
    cells.forEach((text) => {
      const td = document.createElement('td');
      td.className = 'py-2 pr-3 align-top';
      td.textContent = text;
      tr.appendChild(td);
    });
    body.appendChild(tr);
  });

  const discarded = data.discarded_fields || [];
  const hint = document.getElementById('aiButlerDiscardedHint');
  if (hint && discarded.length) {
    hint.textContent = `已忽略不允许修改的字段：${discarded.join('、')}`;
    hint.classList.remove('hidden');
  } else if (hint) {
    hint.classList.add('hidden');
  }

  document.getElementById('aiButlerSuggestionPanel')?.classList.remove('hidden');
}

async function updateAiButlerApiHint() {
  const hint = document.getElementById('aiButlerApiHint');
  if (!hint) return;
  try {
    const cfg = await apiFetch('/api/config');
    const hasKey = cfg.api_key === MASKED_API_KEY || Boolean((cfg.api_key || '').trim());
    const hasModel = Boolean((cfg.model || '').trim());
    const hasEndpoint = Boolean((cfg.api_endpoint || '').trim());
    if (hasKey && hasModel && hasEndpoint) {
      hint.classList.add('hidden');
    } else {
      hint.classList.remove('hidden');
    }
  } catch {
    hint.classList.remove('hidden');
  }
}

async function sendAiButlerMessage() {
  if (AI_BUTLER_STATE.sending) return;
  const input = document.getElementById('aiButlerInput');
  const text = (input?.value || '').trim();
  if (!text) {
    showToast('请输入消息', true);
    return;
  }

  AI_BUTLER_STATE.sending = true;
  setAiButlerInputBusy(true);
  clearAiButlerSuggestionPanel();
  appendAiButlerMessage('user', text);
  AI_BUTLER_STATE.messages.push({ role: 'user', content: text });
  if (input) input.value = '';
  showAiButlerThinking();

  try {
    const history = AI_BUTLER_STATE.messages.slice(0, -1).slice(-20);
    const data = await apiFetch('/api/ai-butler/chat', {
      method: 'POST',
      body: JSON.stringify({ message: text, history }),
    });
    removeAiButlerThinking();
    const reply = data.reply || '（无回复）';
    appendAiButlerMessage('assistant', reply);
    AI_BUTLER_STATE.messages.push({ role: 'assistant', content: reply });
    renderAiButlerSuggestion(data);
    await updateAiButlerApiHint();
  } catch (err) {
    removeAiButlerThinking();
    appendAiButlerMessage('assistant', err.message || '请求失败');
    showToast(err.message || 'AI 管家请求失败', true);
  } finally {
    AI_BUTLER_STATE.sending = false;
    setAiButlerInputBusy(false);
  }
}

async function applyAiButlerPatch() {
  const patch = AI_BUTLER_STATE.pendingPatch;
  if (!patch || !Object.keys(patch).length) {
    showToast('没有可应用的配置建议', true);
    return;
  }
  const applyBtn = document.getElementById('btnAiButlerApply');
  if (applyBtn) applyBtn.disabled = true;
  try {
    await apiFetch('/api/config', {
      method: 'POST',
      body: JSON.stringify({ data: patch }),
    });
    await reloadConfigFromServer();
    clearAiButlerSuggestionPanel();
    showToast('配置已应用并同步到助手设置~');
  } catch (err) {
    showToast(err.message || '保存配置失败', true);
  } finally {
    if (applyBtn) applyBtn.disabled = false;
  }
}

export function initAiButlerPage() {
  updateAiButlerApiHint().catch(console.error);
}

function bindAiButlerControls() {
  document.getElementById('btnAiButlerSend')?.addEventListener('click', () => {
    sendAiButlerMessage().catch(console.error);
  });
  document.getElementById('aiButlerInput')?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendAiButlerMessage().catch(console.error);
    }
  });
  document.getElementById('btnAiButlerApply')?.addEventListener('click', () => {
    applyAiButlerPatch().catch(console.error);
  });
  document.getElementById('btnAiButlerCancel')?.addEventListener('click', () => {
    clearAiButlerSuggestionPanel();
    showToast('已取消配置建议');
  });
  document.getElementById('btnAiButlerGoSettings')?.addEventListener('click', () => {
    navigate('settings');
  });
}

export function bindContentPageControls(deps = {}) {
  configureContentPageBindings(deps);

  bindAiButlerControls();

  document.getElementById('btnAnnouncementsRefresh')?.addEventListener('click', () => {
    loadAnnouncementsPage().catch((e) => showToast(e.message, true));
  });
  document.getElementById('btnOverviewAnnouncementDismiss')?.addEventListener('click', () => {
    dismissOverviewAnnouncementBanner(overviewBannerLatestId);
  });
  document.querySelectorAll('.js-reward-fab').forEach((btn) => {
    btn.addEventListener('click', openRewardModal);
  });
  document.getElementById('btnRewardClose')?.addEventListener('click', closeRewardModal);
  document.getElementById('rewardModal')?.addEventListener('click', (e) => {
    if (e.target.id === 'rewardModal') closeRewardModal();
  });
}
