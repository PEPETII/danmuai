import { collectFeedbackContext } from './feedback-context.js';

let showToast = () => {};
let feedbackPageInitialized = false;

export function configureFeedbackBindings(deps = {}) {
  showToast = deps.showToast || showToast;
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

export function initFeedbackPage() {
  refreshFeedbackQuota().catch(console.error);
  if (feedbackPageInitialized) return;
  feedbackPageInitialized = true;
  document.getElementById('feedbackForm')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!window.DanmuSupabase?.isConfigured?.()) {
      showToast('未配置云端反馈服务', true);
      return;
    }
    const content = document.getElementById('feedbackContent')?.value ?? '';
    const contact = document.getElementById('feedbackContact')?.value ?? '';
    const btn = document.getElementById('btnFeedbackSubmit');
    if (btn) btn.disabled = true;
    try {
      const context = await collectFeedbackContext();
      await window.DanmuSupabase.submitFeedback({
        content,
        contact,
        contextJson: context,
        logsExcerpt: context.recent_logs,
      });
      showToast('反馈已提交，感谢你的帮助~');
      const textarea = document.getElementById('feedbackContent');
      const input = document.getElementById('feedbackContact');
      if (textarea) textarea.value = '';
      if (input) input.value = '';
      await refreshFeedbackQuota();
    } catch (err) {
      showToast(err.message || '提交失败', true);
    } finally {
      await refreshFeedbackQuota();
    }
  });
}
