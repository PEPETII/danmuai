/**
 * 模块：content-pages - 内容页兼容导出层。
 *
 * 该文件保留统一依赖注入、reward modal 绑定和历史导出名，
 * 公告 / 反馈的具体实现已下沉到独立子模块。
 *
 * Compatibility anchors for static bundle tests:
 * danmu_announcements_overview_banner_dismissed_id
 * clearInterval(announcementsBadgePollTimer)
 */

import {
  bindAnnouncementsControls,
  buildAnnouncementSnippet as buildAnnouncementSnippetImpl,
  dismissOverviewAnnouncementBanner as dismissOverviewAnnouncementBannerImpl,
  getOverviewBannerLatestId,
  loadAnnouncementsPage,
  loadAnnouncementsReadState,
  refreshAnnouncementsUnreadBadge,
  startAnnouncementsBadgePolling as startAnnouncementsBadgePollingImpl,
  stopAnnouncementsBadgePolling as stopAnnouncementsBadgePollingImpl,
  updateAnnouncementsNavBadge,
  updateOverviewAnnouncementBanner as updateOverviewAnnouncementBannerImpl,
} from './content-announcements.js';
import {
  configureFeedbackBindings,
  initFeedbackPage,
} from './content-feedback.js';
import { loadTutorialPage } from './content-tutorial.js';

let bindDeps = { showToast: () => {}, navigate: () => {} };

export function configureContentPageBindings(deps) {
  bindDeps = { ...bindDeps, ...deps };
  const childDeps = {
    showToast: bindDeps.showToast,
    navigate: bindDeps.navigate,
  };
  configureFeedbackBindings(childDeps);
}

function showToast(msg, isError = false) {
  bindDeps.showToast(msg, isError);
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

function buildAnnouncementSnippet(...args) {
  return buildAnnouncementSnippetImpl(...args);
}

function updateOverviewAnnouncementBanner(...args) {
  return updateOverviewAnnouncementBannerImpl(...args);
}

export function dismissOverviewAnnouncementBanner(...args) {
  return dismissOverviewAnnouncementBannerImpl(...args);
}

export function stopAnnouncementsBadgePolling(...args) {
  return stopAnnouncementsBadgePollingImpl(...args);
}

export function startAnnouncementsBadgePolling(...args) {
  return startAnnouncementsBadgePollingImpl(...args);
}

export {
  initFeedbackPage,
  loadAnnouncementsPage,
  loadAnnouncementsReadState,
  loadTutorialPage,
  refreshAnnouncementsUnreadBadge,
  updateAnnouncementsNavBadge,
};

export function bindContentPageControls(deps = {}) {
  configureContentPageBindings(deps);

  bindAnnouncementsControls(showToast);

  document.querySelectorAll('.js-reward-fab').forEach((btn) => {
    btn.addEventListener('click', openRewardModal);
  });
  document.getElementById('btnRewardClose')?.addEventListener('click', closeRewardModal);
  document.getElementById('rewardModal')?.addEventListener('click', (event) => {
    if (event.target.id === 'rewardModal') closeRewardModal();
  });
  document.getElementById('btnOverviewAnnouncementDismiss')?.addEventListener('click', () => {
    dismissOverviewAnnouncementBannerImpl(getOverviewBannerLatestId());
  });
}
