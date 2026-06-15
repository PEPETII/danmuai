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
 * 重连：SSE 走 SSE_RECONNECT_BASE_MS=1s → SSE_MAX_RECONNECT_MS=8s 指数退避。
 *
 * 线程：浏览器主线程；不做任何 fetch 缓存之外的工作。
 */

import { API } from './transport.js';

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
  if (!diag) return '等待诊断数据...';
  const configContext = diag.config_context || {};
  const scheduler = diag.scheduler || {};
  const timing = diag.timing || {};
  const runtimeState = diag.runtime_state || {};
  const diagnosis = diag.diagnosis || {};
  const webRuntime = runtimeState.web_runtime || {};
  const stats = runtimeState.stats || {};
  const generation = runtimeState.generation_pipeline || {};
  const suggestions = [];
  if (diagnosis.scheduler_blocked) {
    suggestions.push(`- 检查调度阻塞原因：${scheduler.block_reason || 'unknown'}`);
  }
  if (diagnosis.high_rtt) {
    suggestions.push('- 检查弱网、上游模型响应时间或过慢的视觉请求');
  }
  if (diagnosis.has_pending_timing) {
    suggestions.push('- 检查请求 timing 是否长时间未消费，重点看 reply/error 清理路径');
  }
  if (!suggestions.length) {
    suggestions.push('- 当前快照未发现明显调度或 timing 异常');
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

  const setText = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  setText('diagSchedulerBlocked', diagnosis.scheduler_blocked ? '是' : '否');
  setText('diagBlockReason', scheduler.block_reason || '-');
  setText('diagTriggerGap', formatDiagSeconds(scheduler.seconds_since_last_trigger));
  setText('diagPendingTiming', String(timing.request_started_count ?? 0));
  setText('diagAvgRtt', formatDiagSeconds(timing.avg_rtt));
  setText('diagCooldown', formatDiagMs(timing.smart_cooldown_ms));
  setText('diagHighRtt', diagnosis.high_rtt ? '是' : '否');
  setText('diagRttHistoryLen', String(timing.rtt_history_len ?? 0));
  setText(
    'diagRecentRttSamples',
    JSON.stringify(timing.recent_rtt_samples || []),
  );
  setText(
    'diagRuntimeStats',
    `danmu=${stats.danmu_count ?? 0} · input=${stats.total_input_tokens ?? 0} · output=${stats.total_output_tokens ?? 0} · runtime=${formatDiagSeconds(stats.runtime_sec)}`,
  );
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
    DIAGNOSTICS.sse.onopen = null;
    DIAGNOSTICS.sse.onerror = null;
    DIAGNOSTICS.sse.onmessage = null;
    try {
      DIAGNOSTICS.sse.close();
    } catch (_) {
      /* ignore */
    }
    DIAGNOSTICS.sse = null;
  }
  DIAGNOSTICS.attempt = 0;
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
  if (!API.base) {
    console.warn('[diagnostics] SSE: API.base not ready');
    return;
  }

  clearSseReconnect();
  const url = new URL(`${API.base}/api/diagnostics/events`);
  if (API.token) {
    url.searchParams.set('token', API.token);
  }
  console.debug('[diagnostics] SSE connecting', url.toString());

  try {
    const es = new EventSource(url.toString());
    DIAGNOSTICS.sse = es;

    es.onopen = () => {
      console.debug('[diagnostics] SSE open');
      DIAGNOSTICS.attempt = 0;
    };

    es.addEventListener('hello', (ev) => {
      try {
        const data = JSON.parse(ev.data);
        console.debug('[diagnostics] SSE hello', data);
      } catch (e) {
        console.warn('[diagnostics] SSE hello parse error', e);
      }
    });

    es.addEventListener('diagnostic_snapshot', (ev) => {
      try {
        const diag = JSON.parse(ev.data);
        renderDiagnosticSnapshot(diag);
      } catch (e) {
        console.warn('[diagnostics] SSE snapshot parse error', e);
      }
    });

    es.onerror = () => {
      console.warn('[diagnostics] SSE error');
      disconnectDiagnosticsSSE();
      DIAGNOSTICS.attempt += 1;
      const delay = sseBackoffMs();
      console.debug(`[diagnostics] SSE reconnect in ${delay}ms (attempt ${DIAGNOSTICS.attempt})`);
      DIAGNOSTICS.reconnectTimer = setTimeout(() => {
        DIAGNOSTICS.reconnectTimer = null;
        if (isDiagnosticsPanelVisible()) {
          connectDiagnosticsSSE();
        }
      }, delay);
    };
  } catch (e) {
    console.warn('[diagnostics] SSE creation failed', e);
    disconnectDiagnosticsSSE();
  }
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
  if (btn) btn.textContent = visible ? '隐藏诊断面板' : '显示诊断面板';
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
      showToast('诊断报告已复制');
    } catch (err) {
      console.warn('[diagnostics] copy failed', err);
      showToast('复制诊断报告失败', true);
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