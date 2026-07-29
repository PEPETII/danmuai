import { apiFetch } from './transport.js';
import { t } from './i18n.js';
import {
  computePackageCardState,
  humanizeJobError,
} from './app-knowledge-status.js';
import {
  resetPackageContext,
  showKnowledgeToast,
} from './app-knowledge-state.js';
import { openPackageDetail } from './app-knowledge-package-detail.js';
import { openCreatePackageModal, openKnowledgeConfirmModal } from './app-knowledge-modals.js';

function groupJobsByPackageId(jobs, packages) {
  const idToPublic = new Map();
  packages.forEach((pkg) => {
    if (pkg.id != null && pkg.public_id) {
      idToPublic.set(pkg.id, pkg.public_id);
    }
  });
  const byPublic = new Map();
  jobs.forEach((job) => {
    const pub = idToPublic.get(job.package_id);
    if (!pub) return;
    if (!byPublic.has(pub)) byPublic.set(pub, []);
    byPublic.get(pub).push(job);
  });
  return byPublic;
}

let documentClickBound = false;

function bindDocumentCloseMenus() {
  if (documentClickBound) return;
  documentClickBound = true;
  document.addEventListener("click", (e) => {
    document.querySelectorAll(".knowledge-card-more-menu").forEach((menu) => {
      if (!menu.hidden) {
        const btn = menu.parentElement?.querySelector("[aria-haspopup='true']");
        if (!menu.contains(e.target) && e.target !== btn) {
          menu.hidden = true;
          if (btn) btn.setAttribute("aria-expanded", "false");
        }
      }
    });
  });
}

function buildMoreMenu(packageId, menuBtn) {
  const menu = document.createElement('div');
  menu.className = 'knowledge-card-more-menu';
  menu.hidden = true;

  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className =
    'knowledge-card-more-item knowledge-card-more-item--danger ui-button ui-button--ghost ui-button--sm';
  deleteBtn.textContent = t('dynamic.appKnowledgePage.delete');
  deleteBtn.addEventListener('click', () => {
    menu.hidden = true;
    menuBtn.setAttribute('aria-expanded', 'false');
    void deletePackageFromList(packageId);
  });
  menu.append(deleteBtn);

  menuBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = menu.hidden;
    menu.hidden = !open;
    menuBtn.setAttribute('aria-expanded', String(open));
  });

  bindDocumentCloseMenus();

  return menu;
}

export function renderPackageList(packages, jobsByPackage = new Map()) {
  const listEl = document.getElementById('knowledgePackageList');
  const emptyEl = document.getElementById('knowledgePackageEmpty');
  if (!listEl) return;
  listEl.replaceChildren();

  if (!packages || packages.length === 0) {
    if (emptyEl) emptyEl.classList.remove('hidden');
    return;
  }
  if (emptyEl) emptyEl.classList.add('hidden');

  packages.forEach((pkg) => {
    const pkgJobs = jobsByPackage.get(pkg.public_id) || [];
    const cardState = computePackageCardState(pkg, pkgJobs);

    const card = document.createElement('div');
    card.className = 'card ui-card knowledge-package-card p-6 space-y-3 min-w-0';

    const header = document.createElement('div');
    header.className = 'flex flex-wrap items-center gap-2 min-w-0';

    const name = document.createElement('span');
    name.className = 'text-lg font-bold text-warmText break-words min-w-0';
    name.textContent = pkg.name || '(unnamed)';
    header.append(name);

    const badge = document.createElement('span');
    badge.className = `knowledge-status-badge ${cardState.badgeKey === 'badgeEnabled' ? 'knowledge-status-badge--success' : cardState.badgeKey === 'badgeNeedsWork' ? 'knowledge-status-badge--warn' : 'knowledge-status-badge--muted'}`;
    badge.textContent = t(`dynamic.appKnowledgePage.cardStatus.${cardState.badgeKey}`);
    header.append(badge);

    card.append(header);

    if (pkg.description) {
      const desc = document.createElement('p');
      desc.className = 'text-sm text-gray-500 break-words';
      desc.textContent = pkg.description;
      card.append(desc);
    }

    const stats = document.createElement('p');
    stats.className = 'text-xs text-gray-500';
    stats.textContent = [
      t('dynamic.appKnowledgePage.sourceCountLabel', { count: pkg.source_count ?? 0 }),
      t('dynamic.appKnowledgePage.itemCountLabel', { count: pkg.item_count ?? 0 }),
    ].join(' · ');
    card.append(stats);

    const statusLine = document.createElement('p');
    statusLine.className = 'text-sm text-warmText';
    statusLine.textContent = t(`dynamic.appKnowledgePage.cardStatus.${cardState.statusKey}`);
    card.append(statusLine);

    const nextStep = document.createElement('p');
    nextStep.className = 'text-xs text-gray-500';
    nextStep.textContent = t('dynamic.appKnowledgePage.cardStatus.nextStep', {
      step: t(`dynamic.appKnowledgePage.cardStatus.${cardState.nextStepKey}`),
    });
    card.append(nextStep);

    const actions = document.createElement('div');
    actions.className = 'flex flex-wrap items-center gap-3 mt-2 knowledge-card-actions';

    const enterBtn = document.createElement('button');
    enterBtn.type = 'button';
    enterBtn.className =
      'btn-primary px-5 py-2 text-white rounded-xl font-bold shadow-warm text-sm ui-button ui-button--primary ui-button--sm';
    enterBtn.textContent = t('dynamic.appKnowledgePage.managePackage');
    enterBtn.addEventListener('click', () => {
      openPackageDetail(pkg.public_id).catch((error) =>
        showKnowledgeToast(error.message, true),
      );
    });
    actions.append(enterBtn);

    const moreBtn = document.createElement('button');
    moreBtn.type = 'button';
    moreBtn.className =
      'px-4 py-2 bg-white border border-gray-200 rounded-xl text-sm font-semibold text-warmText hover:bg-gray-50 ui-button ui-button--secondary ui-button--sm';
    moreBtn.textContent = t('dynamic.appKnowledgePage.more');
    moreBtn.setAttribute('aria-expanded', 'false');
    moreBtn.setAttribute('aria-haspopup', 'true');
    const menu = buildMoreMenu(pkg.public_id, moreBtn);
    actions.append(moreBtn, menu);

    card.append(actions);
    listEl.append(card);
  });
}

async function deletePackageFromList(packageId) {
  const ok = await openKnowledgeConfirmModal({
    title: t('dynamic.appKnowledgePage.delete'),
    message: t('dynamic.appKnowledgePage.confirmDeletePackage'),
    confirmLabel: t('dynamic.appKnowledgePage.confirm.delete'),
    danger: true,
  });
  if (!ok) return;
  try {
    await apiFetch(`/api/knowledge/packages/${encodeURIComponent(packageId)}`, {
      method: 'DELETE',
    });
    showKnowledgeToast(t('dynamic.appKnowledgePage.packageDeleted'));
    await loadKnowledgePage();
  } catch (error) {
    showKnowledgeToast(error.message, true);
  }
}

export async function loadKnowledgePage() {
  const { showListView } = await import('./app-knowledge-page.js');
  const { stopKnowledgeJobPolling } = await import('./app-knowledge-jobs.js');
  showListView();
  stopKnowledgeJobPolling();
  resetPackageContext();

  try {
    const [pkgData, jobsData] = await Promise.all([
      apiFetch('/api/knowledge/packages'),
      apiFetch('/api/knowledge/jobs').catch(() => ({ jobs: [] })),
    ]);
    const packages = pkgData.packages || [];
    const jobsByPackage = groupJobsByPackageId(jobsData.jobs || [], packages);
    renderPackageList(packages, jobsByPackage);
  } catch (error) {
    showKnowledgeToast(t('dynamic.appKnowledgePage.loadFailed'), true);
    console.warn('[knowledge] loadPackages failed', error);
  }
}

export async function createNewPackage() {
  const result = await openCreatePackageModal();
  if (result?.package_id) {
    await openPackageDetail(result.package_id);
  }
}
