/**
 * Module: diagnostic-report-text - plain text report from /api/diagnostics snapshot.
 * Used by error reporting; panel UI/SSE removed (W-DIAGNOSTICS-PANEL-REMOVE-001).
 */

import { t } from './i18n.js';

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
