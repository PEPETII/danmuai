/**
 * 模块：status — /api/status 实时快照 → 温馨控制台 overview DOM。
 *
 * 职责：
 *   - applyStatus(st) 把 status 通道 / 轮询结果写到 DOM
 *     - 运行指示（药丸颜色 / 文字 / Realtime 连接状态）
 *     - 4 张本场统计卡（弹幕 / 待播 / 运行时长 / 屏上弹幕）
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

let statusHadError = false;
let lastAppliedStatus = null;
let applyCaptureRegionFromPayload = () => {};
let maybePromptErrorReport = async () => {};
let openErrorReportModal = async () => {};

export function configureStatus({ applyCaptureRegion, onErrorPrompt, onErrorReportManual }) {
  if (applyCaptureRegion) applyCaptureRegionFromPayload = applyCaptureRegion;
  if (onErrorPrompt) maybePromptErrorReport = onErrorPrompt;
  if (onErrorReportManual) openErrorReportModal = onErrorReportManual;
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

/** Single 1s tick for session/lifetime runtime; avoids skip when status WS/poll is irregular. */
const RUNTIME_CLOCK = {
  tickTimer: null,
  session: null,
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
    runtimeEl.textContent = formatRuntime(currentAnchoredSec(RUNTIME_CLOCK.session));
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
    if (!RUNTIME_CLOCK.session?.running) {
      stopRuntimeTick();
      return;
    }
    paintRuntimeDisplays();
  }, 1000);
}

/**
 * Anchor runtime to last server snapshot; while running, advance locally every 1s.
 * Re-anchors only on start/stop or when server drifts ahead by >1s (clock correction).
 */
function syncRuntimeClocks(st) {
  const running = !!st.running;
  const serverSessionSec = Math.max(0, Math.floor(st.runtime_sec || 0));
  const serverLifetimeSec = Math.max(0, Math.floor(st.lifetime_runtime_sec || 0));
  const now = Date.now();
  const wasRunning = !!RUNTIME_CLOCK.session?.running;

  if (running) {
    if (!wasRunning) {
      RUNTIME_CLOCK.session = { baseSec: serverSessionSec, anchorMs: now, running: true };
      RUNTIME_CLOCK.lifetime = { baseSec: serverLifetimeSec, anchorMs: now, running: true };
      startRuntimeTick();
      return;
    }
    const localSession = currentAnchoredSec(RUNTIME_CLOCK.session);
    const localLifetime = currentAnchoredSec(RUNTIME_CLOCK.lifetime);
    if (serverSessionSec > localSession + 1) {
      RUNTIME_CLOCK.session = { baseSec: serverSessionSec, anchorMs: now, running: true };
    }
    if (serverLifetimeSec > localLifetime + 1) {
      RUNTIME_CLOCK.lifetime = { baseSec: serverLifetimeSec, anchorMs: now, running: true };
    }
    if (!RUNTIME_CLOCK.tickTimer) startRuntimeTick();
    return;
  }

  stopRuntimeTick();
  RUNTIME_CLOCK.session = { baseSec: serverSessionSec, anchorMs: now, running: false };
  RUNTIME_CLOCK.lifetime = { baseSec: serverLifetimeSec, anchorMs: now, running: false };
  paintRuntimeDisplays();
}

export function formatRuntimeLong(sec) {
  const s = Math.floor(sec || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  if (h > 0) return `${h}小时${m}分`;
  if (m > 0) return `${m}:${String(r).padStart(2, '0')}`;
  return `${r}秒`;
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
  return `${start} - ${end}  ${model}  输入 ${input}  输出 ${output}  总 ${total}`;
}

function renderSessionRuns(runs) {
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
  return v >= 10000 ? v.toLocaleString('zh-CN') : String(v);
}

export function applyStatus(st) {
  lastAppliedStatus = st;
  const running = st.running;
  const dot = document.getElementById('statusDot');
  const pill = document.getElementById('statusPill');
  const sub = document.getElementById('statusSub');
  const btn = document.getElementById('btnToggle');

  if (running) {
    dot.className = 'w-3 h-3 bg-green-400 rounded-full animate-pulse';
    pill.textContent = '生成中';
    sub.textContent = st.live_message || '小助手正在为你生成暖心弹幕~';
    btn.textContent = '停止弹幕';
    btn.classList.remove('btn-primary', 'text-white');
    btn.classList.add('bg-white', 'border', 'border-gray-200', 'text-warmText');
  } else {
    dot.className = 'w-3 h-3 bg-gray-300 rounded-full';
    pill.textContent = '待命';
    sub.textContent = '小助手正在待命，随时为你生成暖心弹幕~';
    btn.textContent = '生成弹幕';
    btn.classList.remove('bg-white', 'border', 'border-gray-200', 'text-warmText');
    btn.classList.add('btn-primary', 'text-white');
  }

  document.getElementById('statDanmu').textContent = String(st.danmu_count ?? 0);
  document.getElementById('statQueue').textContent = String(st.queue_count ?? 0);
  syncRuntimeClocks(st);
  const displayEl = document.getElementById('statDisplay');
  if (displayEl) {
    displayEl.textContent = String(st.display_count ?? 0);
    const mode = st.danmu_render_mode || 'scrolling';
    if (mode === 'floating_panel') {
      displayEl.title = '侧边悬浮窗在屏条数';
    } else {
      displayEl.title = '横向弹幕在屏条数';
    }
  }
  const lifetimeDanmuEl = document.getElementById('statLifetimeDanmu');
  const lifetimeInputEl = document.getElementById('statLifetimeInputTokens');
  const lifetimeOutputEl = document.getElementById('statLifetimeOutputTokens');
  if (lifetimeDanmuEl) lifetimeDanmuEl.textContent = String(st.lifetime_danmu_count ?? 0);
  if (lifetimeInputEl) {
    lifetimeInputEl.textContent = formatTokenCount(st.lifetime_input_tokens ?? 0);
  }
  if (lifetimeOutputEl) {
    lifetimeOutputEl.textContent = formatTokenCount(st.lifetime_output_tokens ?? 0);
  }
  if (st.capture_region_mode !== undefined || st.region_selection_state !== undefined) {
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

  const lifetimeNoteEl = document.getElementById('statLifetimeTokenNote');
  if (lifetimeNoteEl) {
    const lifetimeTotal = Number(st.lifetime_total_tokens) || 0;
    const lifetimeIn = Number(st.lifetime_input_tokens) || 0;
    const lifetimeOut = Number(st.lifetime_output_tokens) || 0;
    const legacyExtra = lifetimeTotal - lifetimeIn - lifetimeOut;
    if (legacyExtra > 0) {
      lifetimeNoteEl.textContent =
        `另有升级前累计 ${formatTokenCount(legacyExtra)} Token（尚未区分输入/输出，已计入历史合计）`;
      lifetimeNoteEl.classList.remove('hidden');
    } else {
      lifetimeNoteEl.textContent = '';
      lifetimeNoteEl.classList.add('hidden');
    }
  }
  document.getElementById('activePersonae').textContent =
    (st.persona_names && st.persona_names.length) ? st.persona_names.join(' · ') : '—';
  document.getElementById('liveStatusLine').textContent = st.live_message || '';
  renderSessionRuns(st.session_runs);
  if (st.provider_model_mismatch && st.active_model_id) {
    const mismatchNote = document.getElementById('modelActiveSourceBanner');
    if (mismatchNote && mismatchNote.classList.contains('hidden')) {
      mismatchNote.textContent =
        `当前 API 地址与模型「${st.active_model_id}」不匹配，请在助手设置中重新选择视觉模型并保存。`;
      mismatchNote.classList.remove('hidden');
    }
  }

  const banner = document.getElementById('errorBanner');
  const bannerMessage = document.getElementById('errorBannerMessage');
  if (st.error_message) {
    if (bannerMessage) bannerMessage.textContent = st.error_message;
    else if (banner) banner.textContent = st.error_message;
    banner?.classList.remove('hidden');
    banner?.classList.toggle('text-red-700', st.is_error);
  } else {
    banner?.classList.add('hidden');
  }

  const isError = !!st.is_error;
  if (isError && !statusHadError) {
    maybePromptErrorReport(st).catch((e) => console.warn('[error-report] prompt failed', e));
  }
  statusHadError = isError;
}
