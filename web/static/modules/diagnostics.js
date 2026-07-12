/**
 * 模块：diagnostics — 温馨控制台「诊断面板」（默认折叠，独立于 /api/status）。
 *
 * 数据源：/api/diagnostics（GET 或 SSE；与 /api/status 解耦）。
 *
 * 内容：
 *   - 调度：scheduler.blocked / block_reason / trigger_gap
 *   - 请求：timing.pending_count / avg_rtt / high_rtt / rtt_history
 *   - 智能冷却：cooldown_ms
 *   - runtime 摘要 + 诊断报告（buildDiagnosticReportText）
 *   - config_context：当前 active_model_id / provider / persona（W-ERROR-REPORT-004）
 *
 * 重连：fetch SSE 走 SSE_RECONNECT_BASE_MS=1s → SSE_MAX_RECONNECT_MS=8s 指数退避。
 * 认证：Authorization Bearer header（EventSource 无法设 header，故用 fetch streaming）。
 *
 * 线程：浏览器主线程；不做任何 fetch 缓存之外的工作。
 */

import { API, authHeaders, refreshSession } from './transport.js';
import { t } from './i18n.js';

export const DIAGNOSTICS = {
  sse: null,
  reconnectTimer: null,
  attempt: 0,
  last: null,
  observer: null,
  mutationObserver: null,
};

const SSE_RECONNECT_BASE_MS = 1000;
const SSE_MAX_RECONNECT_MS = 8000;

function formatDiagSeconds(value) {
  const num = Number(value) || 0;
  return `${num.toFixed(2)}s`;
}

function formatDiagMs(value) {
  return `${Math.max(0, Math.round(Number(value) || 0))}ms`;
}

export function buildDiagnosticReportText(diag) {
  if (!diag) return t('dynamic.diagnostics.等待诊断数据');
  const configContext = diag.config_context || {};
  const scheduler = diag.scheduler || {};
  const timing = diag.timing || {};
  const runtimeState = diag.runtime_state || {};
  const diagnosis = diag.diagnosis || {};
  const undisplayed = diag.undisplayed || {};
  const webRuntime = runtimeState.web_runtime || {};
  const stats = runtimeState.stats || {};
  const generation = runtimeState.generation_pipeline || {};
  const suggestions = [];
  if (diagnosis.scheduler_blocked) {
    const reason = scheduler.block_reason || 'unknown';
    suggestions.push(t('dynamic.diagnostics.检查调度阻塞原因_scheduler_b', { reason }));
  }
  if (diagnosis.high_rtt) {
    suggestions.push(t('dynamic.diagnostics.检查弱网_上游模型响应时间或过慢的视觉请求'));
  }
  if (diagnosis.has_pending_timing) {
    suggestions.push(t('dynamic.diagnostics.检查请求_timing_是否长时间未消费_重'));
  }
  if (!suggestions.length) {
    suggestions.push(t('dynamic.diagnostics.当前快照未发现明显调度或_timing_异常'));
  }
  return [
    'DanmuAI Diagnostic Report',
    '',
    '[config_context]',
    `active_model_id: ${configContext.active_model_id || '—'}`,
    `provider_id: ${configContext.provider_id || '—'}`,
    `api_endpoint_host: ${configContext.api_endpoint_host || '—'}`,
    `api_mode: ${configContext.api_mode || '—'}`,
    '',
    '[scheduler]',
    `scheduler_blocked: ${!!diagnosis.scheduler_blocked}`,
    `block_reason: ${scheduler.block_reason || ''}`,
    `seconds_since_last_trigger: ${scheduler.seconds_since_last_trigger ?? 0}`,
    '',
    '[timing]',
    `request_started_count: ${timing.request_started_count ?? 0}`,
    `avg_rtt: ${timing.avg_rtt ?? 0}`,
    `smart_cooldown_ms: ${timing.smart_cooldown_ms ?? 0}`,
    `recent_rtt_samples: ${(timing.recent_rtt_samples || []).join(', ') || '[]'}`,
    '',
    '[runtime]',
    `danmu_count: ${stats.danmu_count ?? 0}`,
    `runtime_sec: ${stats.runtime_sec ?? 0}`,
    `cached_layout_mode: ${webRuntime.cached_layout_mode || 'fullscreen'}`,
    `latest_displayed_round: ${generation.latest_displayed_round ?? 0}`,
    '',
    '[undisplayed]',
    `recent_count: ${undisplayed.recent_count ?? 0}`,
    `total_count: ${undisplayed.total_count ?? 0}`,
    `latest_reason: ${undisplayed.latest_reason || '-'}`,
    `top_reason: ${undisplayed.top_reason || '-'} (${undisplayed.top_reason_count ?? 0})`,
    `reason_counts: ${JSON.stringify(undisplayed.reason_counts || {})}`,
    '',
    '[next_steps]',
    ...suggestions,
  ].join('\n');
}

function renderDiagnosticSnapshot(diag) {
  DIAGNOSTICS.last = diag || null;
  const scheduler = diag?.scheduler || {};
  const timing = diag?.timing || {};
  const diagnosis = diag?.diagnosis || {};
  const stats = diag?.runtime_state?.stats || {};
  const undisplayed = diag?.undisplayed || {};

  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  setText('diagSchedulerBlocked', diagnosis.scheduler_blocked ? t('common.yes') : t('common.no'));
  setText('diagBlockReason', scheduler.block_reason || '-');
  setText('diagTriggerGap', formatDiagSeconds(scheduler.seconds_since_last_trigger));
  setText('diagPendingTiming', String(timing.request_started_count ?? 0));
  setText('diagAvgRtt', formatDiagSeconds(timing.avg_rtt));
  setText('diagCooldown', formatDiagMs(timing.smart_cooldown_ms));
  setText('diagHighRtt', diagnosis.high_rtt ? t('common.yes') : t('common.no'));
  setText('diagRttHistoryLen', String(timing.rtt_history_len ?? 0));
  setText(
    'diagRecentRttSamples',
    JSON.stringify(timing.recent_rtt_samples || []),
  );
  setText(
    'diagRuntimeStats',
    `danmu=${stats.danmu_count ?? 0} · input=${stats.total_input_tokens ?? 0} · output=${stats.total_output_tokens ?? 0} · runtime=${formatDiagSeconds(stats.runtime_sec)}`,
  );
  // 未上屏弹幕诊断
  setText('diagUndisplayedRecent', String(undisplayed.recent_count ?? 0));
  setText('diagUndisplayedTotal', String(undisplayed.total_count ?? 0));
  setText('diagUndisplayedLatest', undisplayed.latest_reason || '-');
  const topReason = undisplayed.top_reason
    ? `${undisplayed.top_reason} (${undisplayed.top_reason_count ?? 0})`
    : '-';
  setText('diagUndisplayedTop', topReason);
  const recentEvents = undisplayed.recent_events || [];
  const recentList = recentEvents
    .slice(-10)
    .map((ev) => `${ev.reason}`)
    .join(', ');
  setText('diagUndisplayedRecentList', recentList || '-');
  setText('diagnosticReportPreview', buildDiagnosticReportText(diag));
}

function isDiagnosticsPanelVisible() {
  const panel = document.getElementById('diagnosticsPanel');
  if (!panel || panel.classList.contains('hidden')) return false;
  return document.getElementById('page-overview')?.classList.contains('active') ?? false;
}

function sseBackoffMs() {
  const exp = Math.min(DIAGNOSTICS.attempt, 4);
  return Math.min(SSE_RECONNECT_BASE_MS * 2 ** exp, SSE_MAX_RECONNECT_MS);
}

function clearSseReconnect() {
  if (DIAGNOSTICS.reconnectTimer) {
    clearTimeout(DIAGNOSTICS.reconnectTimer);
    DIAGNOSTICS.reconnectTimer = null;
  }
}

function disconnectDiagnosticsSSE() {
  clearSseReconnect();
  if (DIAGNOSTICS.sse) {
    try {
      DIAGNOSTICS.sse.abortController?.abort();
    } catch (_) {
      /* ignore */
    }
    DIAGNOSTICS.sse = null;
  }
  DIAGNOSTICS.attempt = 0;
}

function scheduleSseReconnect() {
  clearSseReconnect();
  if (DIAGNOSTICS.sse) {
    try {
      DIAGNOSTICS.sse.abortController?.abort();
    } catch (_) {
      /* ignore */
    }
    DIAGNOSTICS.sse = null;
  }
  DIAGNOSTICS.attempt += 1;
  const delay = sseBackoffMs();
  console.debug(`[diagnostics] SSE reconnect in ${delay}ms (attempt ${DIAGNOSTICS.attempt})`);
  DIAGNOSTICS.reconnectTimer = setTimeout(() => {
    DIAGNOSTICS.reconnectTimer = null;
    if (isDiagnosticsPanelVisible()) {
      connectDiagnosticsSSE();
    }
  }, delay);
}

function dispatchSseEvent(eventName, dataText) {
  if (!dataText) return;
  try {
    if (eventName === 'hello') {
      const data = JSON.parse(dataText);
      console.debug('[diagnostics] SSE hello', data);
      return;
    }
    if (eventName === 'diagnostic_snapshot') {
      const diag = JSON.parse(dataText);
      renderDiagnosticSnapshot(diag);
    }
  } catch (e) {
    console.warn('[diagnostics] SSE event parse error', e);
  }
}

async function readDiagnosticsSseStream(abortController) {
  const response = await fetch(`${API.base}/api/diagnostics/events`, {
    headers: { ...authHeaders(), Accept: 'text/event-stream' },
    cache: 'no-store',
    signal: abortController.signal,
  });

  if (abortController.signal.aborted) return;

  if (response.status === 401 || response.status === 403) {
    console.warn('[diagnostics] SSE auth rejected');
    scheduleSseReconnect();
    return;
  }
  if (!response.ok) {
    console.warn('[diagnostics] SSE HTTP error', response.status);
    scheduleSseReconnect();
    return;
  }

  console.debug('[diagnostics] SSE open');
  DIAGNOSTICS.attempt = 0;

  const reader = response.body?.getReader();
  if (!reader) {
    console.warn('[diagnostics] SSE: no response body');
    scheduleSseReconnect();
    return;
  }

  const decoder = new TextDecoder();
  let buffer = '';
  let currentEvent = '';
  let currentData = '';

  const flushEvent = () => {
    if (currentData) {
      dispatchSseEvent(currentEvent, currentData);
    }
    currentEvent = '';
    currentData = '';
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done || abortController.signal.aborted) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop() || '';

    for (const rawLine of lines) {
      const line = rawLine.replace(/\r$/, '');
      if (line === '') {
        flushEvent();
        continue;
      }
      if (line.startsWith(':')) continue;
      if (line.startsWith('event:')) {
        currentEvent = line.slice(6).trim();
        continue;
      }
      if (line.startsWith('data:')) {
        const chunk = line.slice(5).trimStart();
        currentData = currentData ? `${currentData}\n${chunk}` : chunk;
      }
    }
  }

  if (!abortController.signal.aborted) {
    scheduleSseReconnect();
  }
}

export function disconnectDiagnosticsPanel() {
  disconnectDiagnosticsSSE();
}

export function destroyDiagnosticsPanel() {
  disconnectDiagnosticsSSE();
  if (DIAGNOSTICS.observer) {
    DIAGNOSTICS.observer.disconnect();
    DIAGNOSTICS.observer = null;
  }
  if (DIAGNOSTICS.mutationObserver) {
    DIAGNOSTICS.mutationObserver.disconnect();
    DIAGNOSTICS.mutationObserver = null;
  }
}

function connectDiagnosticsSSE() {
  if (DIAGNOSTICS.sse) return;

  clearSseReconnect();
  console.debug('[diagnostics] SSE connecting');

  const abortController = new AbortController();
  DIAGNOSTICS.sse = { abortController };

  void (async () => {
    try {
      if (!API.base || !API.token) {
        await refreshSession();
      }
      if (!API.base || !API.token) {
        console.warn('[diagnostics] SSE: session not ready');
        scheduleSseReconnect();
        return;
      }
      await readDiagnosticsSseStream(abortController);
    } catch (e) {
      if (e?.name === 'AbortError' || abortController.signal.aborted) return;
      console.warn('[diagnostics] SSE stream error', e);
      scheduleSseReconnect();
    } finally {
      if (DIAGNOSTICS.sse?.abortController === abortController) {
        DIAGNOSTICS.sse = null;
      }
    }
  })();
}

function handlePanelVisibilityChange(entries) {
  const entry = entries[0];
  const panel = document.getElementById('diagnosticsPanel');
  if (!panel) return;

  // 面板可见（不含 hidden 类）、在概览页且在视口内时连接 SSE
  const isVisible = isDiagnosticsPanelVisible() && entry.isIntersecting;
  if (isVisible) {
    connectDiagnosticsSSE();
  } else {
    disconnectDiagnosticsSSE();
  }
}

function setDiagnosticsPanelVisible(visible) {
  const panel = document.getElementById('diagnosticsPanel');
  const btn = document.getElementById('btnToggleDiagnosticsPanel');
  if (!panel) return;
  panel.classList.toggle('hidden', !visible);
  panel.setAttribute('aria-hidden', visible ? 'false' : 'true');
  if (btn) btn.textContent = visible ? t('dynamic.diagnostics.隐藏诊断面板') : t('dynamic.diagnostics.显示诊断面板');
  handlePanelVisibilityChange([
    { target: panel, isIntersecting: isDiagnosticsPanelVisible() },
  ]);
}

export function initDiagnosticsPanel({ showToast }) {
  document.getElementById('btnToggleDiagnosticsPanel')?.addEventListener('click', () => {
    const panel = document.getElementById('diagnosticsPanel');
    if (!panel) return;
    setDiagnosticsPanelVisible(panel.classList.contains('hidden'));
  });

  document.getElementById('btnCopyDiagnosticsReport')?.addEventListener('click', async () => {
    const text = buildDiagnosticReportText(DIAGNOSTICS.last);
    try {
      await navigator.clipboard.writeText(text);
      showToast(t('dynamic.diagnostics.诊断报告已复制'));
    } catch (err) {
      console.warn('[diagnostics] copy failed', err);
      showToast(t('dynamic.diagnostics.复制诊断报告失败'), true);
    }
  });

  // 使用 IntersectionObserver 监测面板可见性
  const panel = document.getElementById('diagnosticsPanel');
  if (panel && !DIAGNOSTICS.observer) {
    DIAGNOSTICS.observer = new IntersectionObserver(handlePanelVisibilityChange, {
      threshold: 0.1,
    });
    DIAGNOSTICS.observer.observe(panel);

    // 同时监听 hidden 类变化（MutationObserver）
    DIAGNOSTICS.mutationObserver = new MutationObserver(() => {
      handlePanelVisibilityChange([
        { target: panel, isIntersecting: isDiagnosticsPanelVisible() },
      ]);
    });
    DIAGNOSTICS.mutationObserver.observe(panel, {
      attributes: true,
      attributeFilter: ['class'],
    });
  }
}