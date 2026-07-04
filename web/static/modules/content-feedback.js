import { collectFeedbackContext } from './feedback-context.js';
import { t } from './i18n.js';

let showToast = () => {};
let feedbackPageInitialized = false;

export function configureFeedbackBindings(deps = {}) {
  showToast = deps.showToast || showToast;
}

function updateFeedbackQuotaHint(quota) {
  const el = document.getElementById('feedbackQuotaHint');
  if (!el) return;
  if (!quota) {
    el.textContent = t('dynamic.appErrorReporting.暂时无法查询提交额度');
    return;
  }
  const remaining = Number(quota.remaining ?? 0);
  const limit = Number(quota.limit ?? 2);
  const hint = quota.resets_hint || t('dynamic.appErrorReporting.每_3_小时最多提交_limit_条');
  if (remaining <= 0) {
    el.textContent = hint;
    el.classList.add('text-red-600');
  } else {
    el.textContent = t('dynamic.contentFeedback.本机还可提交_remaining_2');
    el.classList.remove('text-red-600');
  }
  const submitBtn = document.getElementById('btnFeedbackSubmit');
  if (submitBtn) submitBtn.disabled = remaining <= 0;
}

async function refreshFeedbackQuota() {
  const el = document.getElementById('feedbackQuotaHint');
  if (!el) return;
  if (!window.DanmuSupabase?.isConfigured?.()) {
    el.textContent = t('dynamic.contentFeedback.未配置云端反馈服务_无法在线提交_仍可通过下方社');
    const submitBtn = document.getElementById('btnFeedbackSubmit');
    if (submitBtn) submitBtn.disabled = true;
    return;
  }
  el.textContent = t('dynamic.appErrorReporting.正在查询提交额度');
  el.classList.remove('text-red-600');
  try {
    const quota = await window.DanmuSupabase.getFeedbackQuota();
    updateFeedbackQuotaHint(quota);
  } catch (err) {
    el.textContent = err.message || t('dynamic.appErrorReporting.无法查询提交额度');
  }
}

export function initFeedbackPage() {
  refreshFeedbackQuota().catch(console.error);
  if (feedbackPageInitialized) return;
  feedbackPageInitialized = true;
  document.getElementById('feedbackForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!window.DanmuSupabase?.isConfigured?.()) {
      showToast(t('dynamic.appErrorReporting.未配置云端反馈服务'), true);
      return;
    }
    const content = document.getElementById('feedbackContent')?.value ?? '';
    const contact = document.getElementById('feedbackContact')?.value ?? '';
    const btn = document.getElementById('btnFeedbackSubmit');
    if (btn) btn.disabled = true;
    try {
      const includeRuntimeInfo = document.getElementById('feedbackIncludeRuntimeInfo')?.checked !== false;
      const context = await collectFeedbackContext({ includeRuntimeInfo });
      await window.DanmuSupabase.submitFeedback({
        content,
        contact,
        contextJson: context,
        logsExcerpt: context.recent_logs,
      });
      showToast(t('dynamic.contentFeedback.反馈已提交_感谢你的帮助'));
      const textarea = document.getElementById('feedbackContent');
      const input = document.getElementById('feedbackContact');
      if (textarea) textarea.value = '';
      if (input) input.value = '';
      await refreshFeedbackQuota();
    } catch (err) {
      showToast(err.message || t('dynamic.contentFeedback.提交失败'), true);
    } finally {
      await refreshFeedbackQuota();
    }
  });
}
