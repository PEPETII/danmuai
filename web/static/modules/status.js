/**
 * 模块：status — /api/status 实时快照 → 温馨控制台 overview DOM。
 *
 * 职责：
 *   - applyStatus(st) 把 status 通道 / 轮询结果写到 DOM
 *     - 运行指示（药丸颜色 / 文字 / Realtime 连接状态）
 *     - 4 张本场统计卡（弹幕 / 输入 Token / 运行时长 / 输出 Token）
 *     - 4 张累计统计卡（总弹幕 / 总时长 / 输入 Token / 输出 Token）
 *     - 当前人格、live 状态行、is_error 横幅
 *   - 状态栏 tooltip 按 danmu_render_mode 区分（scrolling 模式 → "在屏条数"；
 *     floating_panel 模式 → 悬浮窗活跃数 / 渲染活跃度，详见 W-FP-005）
 *   - RUNTIME_CLOCK 1s tick 把 session_runtime / lifetime_runtime 平滑到秒，
 *     避免依赖 WS 推送的不规则间隔
 *
 * 跨模块依赖：
 *   - applyCaptureRegionFromPayload / maybePromptErrorReport 由 app.js
 *     configureStatus() 注入；本模块不直接 import 减少耦合
 */

import { getLanguage, t } from './i18n.js';

let statusHadError = false;
let lastProblemEventId = '';
let lastProblemOccurrenceCount = 0;
let lastAppliedStatus = null;
let lastRunning = null;
let lastLiveMessage = null;
let lastSessionRunsKey = '';
let lastCaptureRegionKey = '';
let applyCaptureRegionFromPayload = () => {};
let maybeShowProblem = () => {};
let updateVisibleProblemOccurrence = () => {};

export function configureStatus({ applyCaptureRegion, onProblemShow, onProblemOccurrenceUpdate }) {
  if (applyCaptureRegion) applyCaptureRegionFromPayload = applyCaptureRegion;
  if (onProblemShow) maybeShowProblem = onProblemShow;
  if (onProblemOccurrenceUpdate) updateVisibleProblemOccurrence = onProblemOccurrenceUpdate;
}

export function getStatusHadError() {
  return statusHadError;
}

export function getLastAppliedStatus() {
  return lastAppliedStatus;
}

export function formatRuntime(sec) {
  const s = Math.max(0, Math.floor(sec || 0));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${String(r).padStart(2, '0')}`;
}

/** Single 1s tick for app-session/lifetime runtime; app session always advances. */
const RUNTIME_CLOCK = {
  tickTimer: null,
  appSession: null,
  lifetime: null,
};

function stopRuntimeTick() {
  if (RUNTIME_CLOCK.tickTimer) {
    clearInterval(RUNTIME_CLOCK.tickTimer);
    RUNTIME_CLOCK.tickTimer = null;
  }
}

function currentAnchoredSec(anchor) {
  if (!anchor) return 0;
  if (!anchor.running) return anchor.baseSec;
  const elapsed = Math.floor((Date.now() - anchor.anchorMs) / 1000);
  return anchor.baseSec + Math.max(0, elapsed);
}

function paintRuntimeDisplays() {
  const runtimeEl = document.getElementById('statRuntime');
  if (runtimeEl) {
    runtimeEl.textContent = formatRuntime(currentAnchoredSec(RUNTIME_CLOCK.appSession));
  }
  const lifetimeEl = document.getElementById('statLifetimeRuntime');
  if (lifetimeEl) {
    lifetimeEl.textContent = formatRuntimeLong(currentAnchoredSec(RUNTIME_CLOCK.lifetime));
  }
}

function startRuntimeTick() {
  stopRuntimeTick();
  paintRuntimeDisplays();
  RUNTIME_CLOCK.tickTimer = setInterval(() => {
    paintRuntimeDisplays();
  }, 1000);
}

/**
 * Anchor runtime to last server snapshot.
 * App-session clock always advances locally every 1s (independent of st.running).
 * Lifetime clock re-anchors only on start/stop or when server drifts ahead by >1s.
 */
function syncRuntimeClocks(st) {
  const running = !!st.running;
  const serverAppSessionSec = Math.max(0, Math.floor(st.app_session_runtime_sec || 0));
  const serverLifetimeSec = Math.max(0, Math.floor(st.lifetime_runtime_sec || 0));
  const now = Date.now();
  const wasRunning = !!RUNTIME_CLOCK.lifetime?.running;

  if (!RUNTIME_CLOCK.appSession) {
    RUNTIME_CLOCK.appSession = { baseSec: serverAppSessionSec, anchorMs: now, running: true };
  } else {
    const localAppSession = currentAnchoredSec(RUNTIME_CLOCK.appSession);
    if (serverAppSessionSec > localAppSession + 1) {
      RUNTIME_CLOCK.appSession = { baseSec: serverAppSessionSec, anchorMs: now, running: true };
    }
  }

  if (running) {
    if (!wasRunning) {
      RUNTIME_CLOCK.lifetime = { baseSec: serverLifetimeSec, anchorMs: now, running: true };
      startRuntimeTick();
      return;
    }
    const localLifetime = currentAnchoredSec(RUNTIME_CLOCK.lifetime);
    if (serverLifetimeSec > localLifetime + 1) {
      RUNTIME_CLOCK.lifetime = { baseSec: serverLifetimeSec, anchorMs: now, running: true };
    }
    if (!RUNTIME_CLOCK.tickTimer) startRuntimeTick();
    return;
  }

  RUNTIME_CLOCK.lifetime = { baseSec: serverLifetimeSec, anchorMs: now, running: false };
  if (!RUNTIME_CLOCK.tickTimer) startRuntimeTick();
  paintRuntimeDisplays();
}

export function formatRuntimeLong(sec) {
  const s = Math.floor(sec || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return t('dynamic.status.h_小时_m_分', { h, m });
  if (m > 0) return `${m}:${String(r).padStart(2, '0')}`;
  return t('dynamic.status.r_秒', { r });
}

function formatSessionTimestamp(unixSec) {
  if (!unixSec) return '—';
  const d = new Date(unixSec * 1000);
  const pad = (x) => String(x).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function formatSessionRunLine(run) {
  const start = formatSessionTimestamp(run.started_at);
  const end = formatSessionTimestamp(run.ended_at);
  const model = run.model || '—';
  const input = run.input_tokens ?? 0;
  const output = run.output_tokens ?? 0;
  const total = run.total_tokens ?? (input + output);
  return t('dynamic.status.start_end_mod', { start, end, model, input, output, total });
}

function sessionRunsKey(runs) {
  const list = Array.isArray(runs) ? runs : [];
  const first = list[0];
  return `${getLanguage()}|${list.length}|${first?.ended_at ?? ''}|${first?.started_at ?? ''}`;
}

function renderSessionRuns(runs) {
  const key = sessionRunsKey(runs);
  if (key === lastSessionRunsKey) return;
  lastSessionRunsKey = key;

  const container = document.getElementById('sessionRunLog');
  const empty = document.getElementById('sessionRunLogEmpty');
  if (!container) return;
  const list = Array.isArray(runs) ? runs : [];
  container.querySelectorAll('.session-run-line').forEach((el) => el.remove());
  if (!list.length) {
    if (empty) empty.classList.remove('hidden');
    return;
  }
  if (empty) empty.classList.add('hidden');
  list.forEach((run) => {
    const line = document.createElement('p');
    line.className = 'session-run-line';
    line.textContent = formatSessionRunLine(run);
    container.appendChild(line);
  });
}

function formatTokenCount(n) {
  const v = Number(n) || 0;
  const locale = getLanguage() === 'en' ? 'en-US' : 'zh-CN';
  return v >= 10000 ? v.toLocaleString(locale) : String(v);
}

/** Force running pill / sub text to refresh after language switch. */
export function resetStatusUiI18nCache() {
  lastRunning = null;
  lastLiveMessage = null;
}

function updateTextIfChanged(el, newText) {
  if (el && el.textContent !== String(newText ?? '')) {
    el.textContent = String(newText ?? '');
  }
}

function captureRegionKey(st) {
  return [
    st.capture_region_mode ?? '',
    st.region_x ?? 0,
    st.region_y ?? 0,
    st.region_w ?? 0,
    st.region_h ?? 0,
    st.region_selection_state || 'idle',
  ].join('|');
}

function applyRunningUi(st, running) {
  const dot = document.getElementById('statusDot');
  const pill = document.getElementById('statusPill');
  const sub = document.getElementById('statusSub');
  const btn = document.getElementById('btnToggle');
  const liveMessage = st.live_message || '';

  if (running) {
    if (dot) {
      dot.className = 'overview-status-dot w-3 h-3 bg-green-400 rounded-full animate-pulse';
    }
    updateTextIfChanged(pill, t('common.generating'));
    updateTextIfChanged(sub, liveMessage || t('dynamic.status.小助手正在为你生成暖心弹幕'));
    updateTextIfChanged(btn, t('common.stopDanmu'));
    btn?.classList.remove('btn-primary', 'ui-button--primary', 'text-white');
    btn?.classList.add('ui-button--secondary');
  } else {
    if (dot) {
      dot.className = 'overview-status-dot w-3 h-3 bg-gray-300 rounded-full';
    }
    updateTextIfChanged(pill, t('common.standby'));
    updateTextIfChanged(sub, t('dynamic.status.小助手正在待命_随时为你生成暖心弹幕'));
    updateTextIfChanged(btn, t('common.startDanmu'));
    btn?.classList.remove('ui-button--secondary', 'bg-white', 'border', 'border-gray-200', 'text-warmText');
    btn?.classList.add('btn-primary', 'ui-button--primary', 'text-white');
  }
}

export function applyStatus(st) {
  const running = !!st.running;
  const liveMessage = st.live_message || '';
  const runningChanged = lastRunning !== running;
  const liveMessageChanged = lastLiveMessage !== liveMessage;

  if (runningChanged || liveMessageChanged) {
    applyRunningUi(st, running);
    lastRunning = running;
    lastLiveMessage = liveMessage;
  }

  lastAppliedStatus = st;

  updateTextIfChanged(document.getElementById('statDanmu'), String(st.app_session_danmu_count ?? 0));
  updateTextIfChanged(
    document.getElementById('statAppInputTokens'),
    formatTokenCount(st.app_session_input_tokens ?? 0),
  );
  syncRuntimeClocks(st);
  updateTextIfChanged(
    document.getElementById('statAppOutputTokens'),
    formatTokenCount(st.app_session_output_tokens ?? 0),
  );

  const lifetimeDanmuEl = document.getElementById('statLifetimeDanmu');
  const lifetimeInputEl = document.getElementById('statLifetimeInputTokens');
  const lifetimeOutputEl = document.getElementById('statLifetimeOutputTokens');
  updateTextIfChanged(lifetimeDanmuEl, String(st.lifetime_danmu_count ?? 0));
  updateTextIfChanged(lifetimeInputEl, formatTokenCount(st.lifetime_input_tokens ?? 0));
  updateTextIfChanged(lifetimeOutputEl, formatTokenCount(st.lifetime_output_tokens ?? 0));

  if (st.capture_region_mode !== undefined || st.region_selection_state !== undefined) {
    const regionKey = captureRegionKey(st);
    if (regionKey !== lastCaptureRegionKey) {
      lastCaptureRegionKey = regionKey;
      applyCaptureRegionFromPayload({
        mode: st.capture_region_mode,
        region: {
          x: st.region_x ?? 0,
          y: st.region_y ?? 0,
          w: st.region_w ?? 0,
          h: st.region_h ?? 0,
        },
        selection_state: st.region_selection_state || 'idle',
      });
    }
  }

  const lifetimeNoteEl = document.getElementById('statLifetimeTokenNote');
  if (lifetimeNoteEl) {
    const lifetimeTotal = Number(st.lifetime_total_tokens) || 0;
    const lifetimeIn = Number(st.lifetime_input_tokens) || 0;
    const lifetimeOut = Number(st.lifetime_output_tokens) || 0;
    const legacyExtra = lifetimeTotal - lifetimeIn - lifetimeOut;
    if (legacyExtra > 0) {
      const noteText =
        t('dynamic.status.另有升级前累计_formatTokenCou', { legacyExtra: formatTokenCount(legacyExtra) });
      updateTextIfChanged(lifetimeNoteEl, noteText);
      lifetimeNoteEl.classList.remove('hidden');
    } else {
      if (lifetimeNoteEl.textContent !== '') lifetimeNoteEl.textContent = '';
      lifetimeNoteEl.classList.add('hidden');
    }
  }

  const personaText =
    (st.persona_names && st.persona_names.length) ? st.persona_names.join(' · ') : '—';
  updateTextIfChanged(document.getElementById('activePersonae'), personaText);
  updateTextIfChanged(document.getElementById('liveStatusLine'), liveMessage);
  renderSessionRuns(st.session_runs);

  if (st.provider_model_mismatch && st.active_model_id) {
    const mismatchNote = document.getElementById('modelActiveSourceBanner');
    if (mismatchNote && mismatchNote.classList.contains('hidden')) {
      mismatchNote.textContent =
        t('dynamic.status.当前_API_地址与模型_st_active', { modelId: st.active_model_id });
      mismatchNote.classList.remove('hidden');
    }
  }

  const compatBanner = document.getElementById('overlayCompatBanner');
  if (compatBanner) {
    const compatText = [
      String(st.overlay_compat_warning || '').trim(),
      String(st.screen_index_fallback_warning || '').trim(),
    ].filter(Boolean).join(' ');
    if (running && compatText) {
      updateTextIfChanged(compatBanner, compatText);
      compatBanner.classList.remove('hidden');
    } else {
      if (compatBanner.textContent !== '') compatBanner.textContent = '';
      compatBanner.classList.add('hidden');
    }
  }

  const banner = document.getElementById('errorBanner');
  const bannerMessage = document.getElementById('errorBannerMessage');
  const problem = st.active_problem || null;
  const bannerText = problem
    ? [problem.title, problem.summary].filter(Boolean).join(' — ')
    : String(st.error_message || '');
  if (bannerText) {
    if (bannerMessage) updateTextIfChanged(bannerMessage, bannerText);
    else if (banner) updateTextIfChanged(banner, bannerText);
    banner?.classList.remove('hidden');
    banner?.classList.add('ui-status-banner--danger');
    banner?.classList.toggle('text-red-700', !!(st.is_error || problem));
  } else {
    banner?.classList.add('hidden');
  }

  if (problem?.event_id) {
    const isNewEvent = problem.event_id !== lastProblemEventId;
    const countChanged =
      problem.event_id === lastProblemEventId &&
      Number(problem.occurrence_count || 1) !== lastProblemOccurrenceCount;
    if (isNewEvent) {
      maybeShowProblem(problem);
    } else if (countChanged) {
      updateVisibleProblemOccurrence(problem);
    }
    lastProblemEventId = problem.event_id;
    lastProblemOccurrenceCount = Number(problem.occurrence_count || 1);
  } else if (!st.error_message) {
    lastProblemEventId = '';
    lastProblemOccurrenceCount = 0;
  }

  const isError = !!(st.is_error || problem);
  statusHadError = isError;
}
