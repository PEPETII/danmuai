/*
 * Supabase 前端集成（PostgREST 直接调，不经后端转发）：
 *
 * 1) 公告（announcements 表）：
 *    - fetchAnnouncements()：拉取 published_at <= now 的列表，按 published_at 降序
 *    - readState 仅本机维护（announcements_read_state，存 config.db）
 * 2) 用户反馈（feedback_messages 表）：
 *    - submitFeedback()：标题 + 详情 + 联系方式；24h 限 2 条（FEEDBACK_RATE_LIMIT）
 * 3) 教程视频链接（tutorial_links 表，kind=video）：
 *    - fetchTutorialVideoLink()：拉取 enabled 视频链接；url 非 http(s) 时客户端显示占位文案
 * 4) 错误报告（error_reports 表，W-ERROR-REPORT-001 引入）：
 *    - submitErrorReport()：fingerprint + summary + logs_excerpt + diagnostics；
 *      24h 同 fingerprint 去重（W-ERROR-REPORT-006 已迁 localStorage）
 *    - rate limit 3 条/3h（ERROR_REPORT_RATE_LIMIT）
 *
 * 配置：window.DANMU_SUPABASE = {url, anonKey}（参见 supabase-config.example.js
 * 复制为 supabase-config.js）。isConfigured() 返回 false 时所有 submit* 直接抛
 * "未配置 Supabase" — 静默失败，避免误把错误反馈给本地而非云端。
 *
 * 版本号：window.DANMU_APP_VERSION 由 app.js 在 GET /api/version 后写入，用于
 * 错误报告 / 反馈的 app_version 字段（运维按版本排障）。
 *
 * IIFE 模式：自包含，挂在 window.DanmuSupabase = {fetchAnnouncements,
 * fetchTutorialVideoLink, submitFeedback, submitErrorReport, isConfigured, getClientId}。
 */
(function initDanmuSupabase(global) {
  const STORAGE_CLIENT_ID = 'danmu_feedback_client_id';
  const FEEDBACK_RATE_LIMIT_MSG = '每 3 小时最多提交 2 条反馈，请稍后再试';
  const ERROR_REPORT_RATE_LIMIT_MSG =
    '每 3 小时最多自动提交 3 条错误报告，请稍后再试或使用侧栏「问题反馈」';
  // 由 app.js 在 GET /api/version 后写入；反馈提交前可懒加载
  function resolveAppVersion() {
    const v = global.DANMU_APP_VERSION;
    return typeof v === 'string' && v.trim() ? v.trim() : '';
  }

  function config() {
    const cfg = global.DANMU_SUPABASE;
    if (!cfg || !cfg.url || !cfg.anonKey) return null;
    const url = String(cfg.url).replace(/\/$/, '');
    const anonKey = String(cfg.anonKey).trim();
    if (!url || !anonKey || url.includes('YOUR_PROJECT')) return null;
    return { url, anonKey };
  }

  function isConfigured() {
    return config() !== null;
  }

  function authHeaders(extra) {
    const cfg = config();
    if (!cfg) throw new Error('未配置 Supabase，请复制 supabase-config.example.js 为 supabase-config.js');
    return {
      apikey: cfg.anonKey,
      Authorization: `Bearer ${cfg.anonKey}`,
      'Content-Type': 'application/json',
      ...extra,
    };
  }

  function getOrCreateClientId() {
    try {
      let id = global.localStorage.getItem(STORAGE_CLIENT_ID);
      if (id && /^[0-9a-f-]{36}$/i.test(id)) return id;
      id = global.crypto?.randomUUID?.() || null;
      if (!id) {
        id = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
          const r = (Math.random() * 16) | 0;
          const v = c === 'x' ? r : (r & 0x3) | 0x8;
          return v.toString(16);
        });
      }
      global.localStorage.setItem(STORAGE_CLIENT_ID, id);
      return id;
    } catch {
      return '00000000-0000-4000-8000-000000000000';
    }
  }

  function parseErrorMessage(res, bodyText) {
    const text = bodyText || '';
    if (
      res.status === 403 ||
      res.status === 401 ||
      /row-level security/i.test(text) ||
      /policy/i.test(text)
    ) {
      if (/error_reports/i.test(text) || res.url?.includes('/error_reports')) {
        return ERROR_REPORT_RATE_LIMIT_MSG;
      }
      if (/feedback/i.test(text) || res.url?.includes('/feedback')) {
        return FEEDBACK_RATE_LIMIT_MSG;
      }
    }
    try {
      const parsed = JSON.parse(text);
      const msg = parsed.message || parsed.error || parsed.hint || parsed.details;
      if (msg) return String(msg);
    } catch {
      /* ignore */
    }
    return text || `请求失败（HTTP ${res.status}）`;
  }

  async function supabaseFetch(path, options = {}) {
    const cfg = config();
    if (!cfg) throw new Error('未配置 Supabase');
    const res = await global.fetch(`${cfg.url}${path}`, {
      ...options,
      headers: authHeaders(options.headers),
    });
    if (!res.ok) {
      const text = await res.text();
      const err = new Error(parseErrorMessage(res, text));
      err.status = res.status;
      throw err;
    }
    if (res.status === 204) return null;
    const text = await res.text();
    if (!text) return null;
    return JSON.parse(text);
  }

  async function fetchAppUpdate() {
    if (!isConfigured()) return null;
    const query =
      '/rest/v1/app_updates?select=latest_version,release_url,enabled,message,updated_at' +
      '&enabled=eq.true&order=updated_at.desc&limit=1';
    const rows = await supabaseFetch(query, { method: 'GET' });
    if (!Array.isArray(rows) || rows.length === 0) return null;
    const row = rows[0];
    return {
      latest_version: String(row.latest_version || '').trim(),
      release_url: String(row.release_url || '').trim(),
      message: row.message == null ? '' : String(row.message).trim(),
      updated_at: row.updated_at,
    };
  }

  async function fetchTutorialVideoLink() {
    if (!isConfigured()) return null;
    const query =
      '/rest/v1/tutorial_links?select=url,enabled,updated_at' +
      '&kind=eq.video&enabled=eq.true&order=updated_at.desc&limit=1';
    const rows = await supabaseFetch(query, { method: 'GET' });
    if (!Array.isArray(rows) || rows.length === 0) return null;
    const row = rows[0];
    return {
      url: String(row.url || '').trim(),
      updated_at: row.updated_at,
    };
  }

  async function listAnnouncements() {
    const query =
      '/rest/v1/announcements?select=id,title,body,level,pinned,created_at,starts_at,ends_at' +
      '&order=pinned.desc,created_at.desc';
    return supabaseFetch(query, { method: 'GET' });
  }

  async function getFeedbackQuota() {
    const clientId = getOrCreateClientId();
    return supabaseFetch('/rest/v1/rpc/feedback_quota', {
      method: 'POST',
      headers: { Prefer: 'return=representation' },
      body: JSON.stringify({ p_client_id: clientId }),
    });
  }

  async function submitFeedback({ content, contact }) {
    const trimmed = String(content || '').trim();
    if (!trimmed) throw new Error('请填写反馈内容');
    if (trimmed.length > 2000) throw new Error('反馈内容不能超过 2000 字');
    const contactVal = String(contact || '').trim();
    if (contactVal.length > 200) throw new Error('联系方式不能超过 200 字');

    const clientId = getOrCreateClientId();
    try {
      await supabaseFetch('/rest/v1/feedback', {
        method: 'POST',
        headers: { Prefer: 'return=minimal' },
        body: JSON.stringify({
          content: trimmed,
          contact: contactVal || null,
          client_id: clientId,
          app_version: resolveAppVersion() || null,
          platform: 'windows',
          locale: global.navigator?.language || 'zh-CN',
        }),
      });
    } catch (err) {
      if (err.status === 403 || err.status === 401) {
        throw new Error(FEEDBACK_RATE_LIMIT_MSG);
      }
      throw err;
    }
  }

  async function getErrorReportQuota() {
    const clientId = getOrCreateClientId();
    return supabaseFetch('/rest/v1/rpc/error_reports_quota', {
      method: 'POST',
      headers: { Prefer: 'return=representation' },
      body: JSON.stringify({ p_client_id: clientId }),
    });
  }

  async function submitErrorReport({
    summary,
    logsExcerpt,
    diagnosticsJson,
    errorFingerprint,
    userNote,
    contact,
  }) {
    const summaryVal = String(summary || '').trim();
    if (!summaryVal) throw new Error('错误摘要不能为空');
    if (summaryVal.length > 500) throw new Error('错误摘要不能超过 500 字');

    let logsVal = logsExcerpt == null ? null : String(logsExcerpt);
    if (logsVal && logsVal.length > 8000) {
      logsVal = `${logsVal.slice(0, 7990)}\n…[truncated]`;
    }

    const fingerprintVal = String(errorFingerprint || '').trim() || null;
    let userNoteVal = userNote == null ? null : String(userNote).trim();
    if (userNoteVal && userNoteVal.length > 1000) {
      userNoteVal = `${userNoteVal.slice(0, 990)}…[truncated]`;
    }
    let contactVal = contact == null ? null : String(contact).trim();
    if (contactVal && contactVal.length > 200) {
      contactVal = contactVal.slice(0, 200);
    }
    const clientId = getOrCreateClientId();
    const body = {
      summary: summaryVal,
      logs_excerpt: logsVal || null,
      diagnostics_json: diagnosticsJson ?? null,
      error_fingerprint: fingerprintVal,
      user_note: userNoteVal || null,
      contact: contactVal || null,
      client_id: clientId,
      app_version: resolveAppVersion() || null,
      platform: 'windows',
      locale: global.navigator?.language || 'zh-CN',
    };

    try {
      await supabaseFetch('/rest/v1/error_reports', {
        method: 'POST',
        headers: { Prefer: 'return=minimal' },
        body: JSON.stringify(body),
      });
    } catch (err) {
      if (err.status === 403 || err.status === 401) {
        throw new Error(ERROR_REPORT_RATE_LIMIT_MSG);
      }
      throw err;
    }
  }

  global.DanmuSupabase = {
    resolveAppVersion,
    FEEDBACK_RATE_LIMIT_MSG,
    ERROR_REPORT_RATE_LIMIT_MSG,
    isConfigured,
    getOrCreateClientId,
    fetchAppUpdate,
    fetchTutorialVideoLink,
    listAnnouncements,
    getFeedbackQuota,
    submitFeedback,
    getErrorReportQuota,
    submitErrorReport,
  };
})(typeof window !== 'undefined' ? window : globalThis);
