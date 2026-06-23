/**
 * 模块：feedback-context — 普通反馈与错误自动反馈共用的最小运行上下文采集。
 *
 * 设计原则：
 *   - 不阻塞反馈提交：任何采集失败都返回空/占位值。
 *   - 统一脱敏：api_endpoint 只保留 scheme + host + path，不带 query/fragment/userinfo。
 *   - 统一日志：复用内存 `logBuffer` 与 `/api/logs/recent`，合并去重后限长 8000 字符。
 */

import { apiFetch } from './transport.js';
import { formatLogLine, logBuffer, mergeLogItemsUnique } from './logs.js';

/** 最近日志时间窗口（秒）。 */
const FEEDBACK_LOG_WINDOW_SEC = 90;

/** 日志文本长度上限。 */
const FEEDBACK_LOGS_MAX_LENGTH = 8000;

/**
 * 对 API endpoint 做轻度脱敏。
 *
 * - 保留 protocol + host + pathname。
 * - 移除 userinfo、query、fragment。
 * - 解析失败时返回空字符串，不抛异常。
 *
 * @param {string} rawUrl
 * @returns {string}
 */
export function sanitizeApiEndpoint(rawUrl) {
  if (!rawUrl || typeof rawUrl !== 'string') return '';
  try {
    const url = new URL(rawUrl);
    // URL 构造函数已自动丢弃 userinfo / query / fragment；这里显式只取需要部分。
    return `${url.protocol}//${url.host}${url.pathname}`;
  } catch {
    return '';
  }
}

function truncateLogs(text) {
  if (!text || text.length <= FEEDBACK_LOGS_MAX_LENGTH) return text || '';
  const suffix = '\n...[truncated]';
  return text.slice(0, FEEDBACK_LOGS_MAX_LENGTH - suffix.length) + suffix;
}

/**
 * 采集统一的最小运行上下文。
 *
 * @param {object} options
 * @param {number} [options.logWindowSec=90] 最近日志时间窗口（秒）。
 * @param {boolean} [options.includeRuntimeInfo=true] 是否采集运行信息（模型名、API 地址、服务商、API 模式）。
 * @returns {Promise<object>}
 *
 * 返回对象始终包含以下字段：
 *   - current_model_name: string
 *   - api_endpoint: string
 *   - provider_id: string
 *   - api_mode: string
 *   - recent_logs: string
 *   - app_version: string | null
 *   - reported_at: string (ISO 8601)
 *
 * 可选字段（获取失败时为 null）：
 *   - error_message: string | null
 */
export async function collectFeedbackContext(options = {}) {
  const windowSec = Number(options.logWindowSec) || FEEDBACK_LOG_WINDOW_SEC;
  const includeRuntimeInfo = options.includeRuntimeInfo !== false;
  const nowSec = Date.now() / 1000;
  const sinceTs = Math.max(0, nowSec - windowSec);

  const empty = {
    current_model_name: '-',
    api_endpoint: '',
    provider_id: '-',
    api_mode: '-',
    recent_logs: '',
    app_version: null,
    reported_at: new Date().toISOString(),
    error_message: null,
  };

  // --- 运行信息采集（从 /api/status + /api/config，不依赖 /api/diagnostics）---
  let runtimeInfo = {};
  if (includeRuntimeInfo) {
    try {
      const [statusRes, configRes] = await Promise.all([
        apiFetch('/api/status').catch(() => ({})),
        apiFetch('/api/config').catch(() => ({})),
      ]);
      runtimeInfo = {
        current_model_name: statusRes.model_display_name || statusRes.active_model_id || '-',
        api_endpoint: sanitizeApiEndpoint(configRes.api_endpoint || ''),
        provider_id: statusRes.inferred_provider_id || '-',
        api_mode: configRes.api_mode || '-',
      };
      if (statusRes.error_message != null) {
        runtimeInfo.error_message = String(statusRes.error_message);
      }
    } catch (error) {
      console.warn('[feedback-context] runtime info fetch failed', error);
    }
  }

  const context = { ...empty, ...runtimeInfo, app_version: globalThis.DANMU_APP_VERSION || null };

  // --- 日志采集 ---
  let serverItems = [];
  try {
    const logsRes = await apiFetch(`/api/logs/recent?since_ts=${encodeURIComponent(sinceTs)}`);
    serverItems = Array.isArray(logsRes?.items) ? logsRes.items : [];
  } catch (error) {
    console.warn('[feedback-context] /api/logs/recent failed', error);
  }

  try {
    const merged = mergeLogItemsUnique([...logBuffer, ...serverItems]);
    const lines = merged.map(formatLogLine);
    context.recent_logs = truncateLogs(lines.join('\n'));
  } catch (error) {
    console.warn('[feedback-context] log merge/format failed', error);
    context.recent_logs = '';
  }

  return context;
}
