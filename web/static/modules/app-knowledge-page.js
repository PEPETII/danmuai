/**
 * 模块：知识包前端页面（Wave 5 A9）。
 *
 * 三个内联视图经 .hidden 切换：
 *   1) #knowledgeListView         — 知识包列表（默认）
 *   2) #knowledgePackageDetail    — 知识包详情（编辑 / 来源 / 任务 / 条目）
 *   3) #knowledgeRetrievalPreview — 检索预览沙盒
 *
 * 后端契约：见 app/web_api/knowledge_routes.py（14 个端点）。
 * 所有 HTTP 经 apiFetch（自动注入 Bearer + 401 重试）。
 */

import { apiFetch } from './transport.js';
import { t } from './i18n.js';

const JOB_POLL_INTERVAL_MS = 2000;
const ITEMS_PAGE_SIZE = 50;
const ACTIVE_JOB_STATUSES = new Set(['pending', 'running']);

let toast = () => {};
let handlersBound = false;
let jobPollTimer = null;
let currentPackageId = null;
let itemPage = 1;
let itemTotalPages = 1;

function showToast(message, isError = false) {
  toast(message, isError);
}

function statusKey(status) {
  const map = {
    pending: 'statusPending',
    running: 'statusRunning',
    completed: 'statusCompleted',
    completed_with_errors: 'statusCompletedWithErrors',
    failed: 'statusFailed',
    cancelled: 'statusCancelled',
    interrupted: 'statusInterrupted',
  };
  return map[status] || 'statusPending';
}

function kindKey(kind) {
  const map = {
    fact: 'kindFact',
    reaction_pattern: 'kindReaction',
    meme: 'kindMeme',
    style_example: 'kindStyle',
  };
  return map[kind] || 'kindFact';
}

/** 知识包 content_kind 展示文案（API 值保持英文，UI 本地化）。 */
function contentKindLabel(kind) {
  const map = {
    auto: 'optContentAuto',
    fact: 'optContentFact',
    meme: 'optContentMeme',
    livestream: 'optContentLivestream',
    persona: 'optContentPersona',
  };
  const key = map[kind];
  return key ? t(`dynamic.appKnowledgePage.${key}`) : kind || '';
}

function parseScopeTags(text) {
  if (!text) return [];
  return String(text)
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
}

// ---------------------------------------------------------------------------
// 视图切换
// ---------------------------------------------------------------------------

function showListView() {
  document.getElementById('knowledgeListView')?.classList.remove('hidden');
  document.getElementById('knowledgePackageDetail')?.classList.add('hidden');
  document.getElementById('knowledgeRetrievalPreview')?.classList.add('hidden');
}

function showDetailView() {
  document.getElementById('knowledgeListView')?.classList.add('hidden');
  document.getElementById('knowledgePackageDetail')?.classList.remove('hidden');
  document.getElementById('knowledgeRetrievalPreview')?.classList.add('hidden');
}

function showRetrievalView() {
  document.getElementById('knowledgeListView')?.classList.add('hidden');
  document.getElementById('knowledgePackageDetail')?.classList.add('hidden');
  document.getElementById('knowledgeRetrievalPreview')?.classList.remove('hidden');
}

// ---------------------------------------------------------------------------
// 列表视图
// ---------------------------------------------------------------------------

function renderPackageList(packages) {
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
    const card = document.createElement('div');
    card.className = 'card p-6 space-y-3';

    const header = document.createElement('div');
    header.className = 'flex flex-wrap items-center gap-3';

    const name = document.createElement('span');
    name.className = 'text-lg font-bold text-warmText';
    name.textContent = pkg.name || '(unnamed)';
    header.append(name);

    if (pkg.content_kind) {
      const kindBadge = document.createElement('span');
      kindBadge.className =
        'px-2 py-0.5 text-xs font-semibold rounded-full bg-softPeach text-warmText';
      kindBadge.textContent = contentKindLabel(pkg.content_kind);
      header.append(kindBadge);
    }

    const enabledBadge = document.createElement('span');
    enabledBadge.className = `px-2 py-0.5 text-xs font-semibold rounded-full ${
      pkg.enabled ? 'bg-green-100 text-green-700' : 'bg-gray-100 text-gray-500'
    }`;
    enabledBadge.textContent = pkg.enabled
      ? t('dynamic.appKnowledgePage.enabled')
      : t('dynamic.appKnowledgePage.disabled');
    header.append(enabledBadge);

    card.append(header);

    if (pkg.description) {
      const desc = document.createElement('p');
      desc.className = 'text-sm text-gray-500 truncate';
      desc.textContent = pkg.description;
      card.append(desc);
    }

    const stats = document.createElement('p');
    stats.className = 'text-xs text-gray-500';
    const parts = [];
    parts.push(`${t('dynamic.appKnowledgePage.sources')} ${pkg.source_count ?? 0}`);
    parts.push(`${t('dynamic.appKnowledgePage.items')} ${pkg.item_count ?? 0}`);
    parts.push(`${t('dynamic.appKnowledgePage.priority')} ${pkg.priority ?? 0}`);
    stats.textContent = parts.join(' · ');
    card.append(stats);

    if (Array.isArray(pkg.scope_tags) && pkg.scope_tags.length > 0) {
      const tags = document.createElement('div');
      tags.className = 'flex flex-wrap gap-2';
      pkg.scope_tags.forEach((tag) => {
        const chip = document.createElement('span');
        chip.className = 'px-2 py-0.5 text-xs rounded-full bg-cream border border-softPeach text-warmText';
        chip.textContent = tag;
        tags.append(chip);
      });
      card.append(tags);
    }

    const actions = document.createElement('div');
    actions.className = 'flex flex-wrap gap-3 mt-2';

    const enterBtn = document.createElement('button');
    enterBtn.type = 'button';
    enterBtn.className = 'btn-primary px-5 py-2 text-white rounded-xl font-bold shadow-warm text-sm';
    enterBtn.textContent = t('dynamic.appKnowledgePage.preview');
    enterBtn.addEventListener('click', () => {
      openPackageDetail(pkg.public_id).catch((error) =>
        showToast(error.message, true),
      );
    });
    actions.append(enterBtn);

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className =
      'px-5 py-2 bg-red-50 border border-red-200 rounded-xl text-sm font-semibold text-red-600 hover:bg-red-100';
    deleteBtn.textContent = t('dynamic.appKnowledgePage.delete');
    deleteBtn.addEventListener('click', () => {
      void deletePackageFromList(pkg.public_id);
    });
    actions.append(deleteBtn);

    card.append(actions);
    listEl.append(card);
  });
}

async function deletePackageFromList(packageId) {
  if (!window.confirm(t('dynamic.appKnowledgePage.confirmDeletePackage'))) return;
  try {
    await apiFetch(`/api/knowledge/packages/${encodeURIComponent(packageId)}`, {
      method: 'DELETE',
    });
    showToast(t('dynamic.appKnowledgePage.packageDeleted'));
    await loadKnowledgePage();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function createNewPackage() {
  const name = window.prompt(t('dynamic.appKnowledgePage.name'), '');
  if (!name || !name.trim()) return;
  try {
    const result = await apiFetch('/api/knowledge/packages', {
      method: 'POST',
      body: JSON.stringify({ name: name.trim() }),
    });
    showToast(t('dynamic.appKnowledgePage.packageCreated'));
    if (result?.package_id) {
      await openPackageDetail(result.package_id);
    } else {
      await loadKnowledgePage();
    }
  } catch (error) {
    showToast(error.message, true);
  }
}

export async function loadKnowledgePage() {
  showListView();
  stopKnowledgeJobPolling();
  currentPackageId = null;
  try {
    const data = await apiFetch('/api/knowledge/packages');
    renderPackageList(data.packages || []);
  } catch (error) {
    showToast(t('dynamic.appKnowledgePage.loadFailed'), true);
    console.warn('[knowledge] loadPackages failed', error);
  }
}

// ---------------------------------------------------------------------------
// 详情视图
// ---------------------------------------------------------------------------

function fillPackageForm(pkg) {
  const set = (id, value) => {
    const el = document.getElementById(id);
    if (el) el.value = value ?? '';
  };
  set('knowledgePackageName', pkg.name);
  set('knowledgePackageDescription', pkg.description);
  set('knowledgePackageContentKind', pkg.content_kind || 'auto');
  set('knowledgePackageScopeMode', pkg.scope_mode || 'global');
  set('knowledgePackageScopeTags', Array.isArray(pkg.scope_tags) ? pkg.scope_tags.join(', ') : '');
  set('knowledgePackagePriority', pkg.priority ?? 0);
  const enabledEl = document.getElementById('knowledgePackageEnabled');
  if (enabledEl) enabledEl.checked = Boolean(pkg.enabled);
}

function jobStatusBadgeClass(status) {
  if (status === 'completed') return 'bg-green-100 text-green-700';
  if (status === 'running') return 'bg-blue-100 text-blue-700';
  if (status === 'pending') return 'bg-gray-100 text-gray-500';
  if (status === 'failed' || status === 'interrupted') return 'bg-red-100 text-red-700';
  if (status === 'completed_with_errors') return 'bg-yellow-100 text-yellow-700';
  if (status === 'cancelled') return 'bg-gray-100 text-gray-500';
  return 'bg-gray-100 text-gray-500';
}

function renderJobs(jobs) {
  const listEl = document.getElementById('knowledgeJobList');
  const emptyEl = document.getElementById('knowledgeJobEmpty');
  if (!listEl) return;
  listEl.replaceChildren();

  if (!jobs || jobs.length === 0) {
    if (emptyEl) emptyEl.classList.remove('hidden');
    return;
  }
  if (emptyEl) emptyEl.classList.add('hidden');

  jobs.forEach((job) => {
    const row = document.createElement('div');
    row.className = 'p-3 bg-cream border border-softPeach rounded-xl space-y-1';

    const top = document.createElement('div');
    top.className = 'flex flex-wrap items-center gap-2 text-sm';

    const name = document.createElement('span');
    name.className = 'font-semibold text-warmText';
    name.textContent = job.source_id || job.public_id;
    top.append(name);

    const badge = document.createElement('span');
    badge.className = `px-2 py-0.5 text-xs font-semibold rounded-full ${jobStatusBadgeClass(job.status)}`;
    badge.textContent = t(`dynamic.appKnowledgePage.${statusKey(job.status)}`);
    top.append(badge);

    if (job.total_chunks != null && job.processed_chunks != null) {
      const progress = document.createElement('span');
      progress.className = 'text-xs text-gray-500';
      progress.textContent = t('dynamic.appKnowledgePage.progress', {
        processed: job.processed_chunks,
        total: job.total_chunks,
      });
      top.append(progress);
    }

    if (job.generated_items != null) {
      const itemsInfo = document.createElement('span');
      itemsInfo.className = 'text-xs text-gray-500';
      itemsInfo.textContent = t('dynamic.appKnowledgePage.generatedItems', {
        count: job.generated_items,
      });
      top.append(itemsInfo);
    }

    if (ACTIVE_JOB_STATUSES.has(job.status)) {
      const cancelBtn = document.createElement('button');
      cancelBtn.type = 'button';
      cancelBtn.className =
        'px-3 py-1 bg-white border border-gray-200 rounded-lg text-xs font-semibold text-warmText hover:bg-gray-50';
      cancelBtn.textContent = t('dynamic.appKnowledgePage.cancelJob');
      cancelBtn.addEventListener('click', () => {
        void cancelJobById(job.public_id);
      });
      top.append(cancelBtn);
    }

    row.append(top);

    if (job.error_message) {
      const err = document.createElement('p');
      err.className = 'text-xs text-red-600 break-words';
      err.textContent = job.error_message;
      row.append(err);
    }

    listEl.append(row);
  });
}

async function cancelJobById(jobId) {
  try {
    await apiFetch(`/api/knowledge/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: 'POST',
    });
    showToast(t('dynamic.appKnowledgePage.jobCancelled'));
    await refreshJobs();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function refreshJobs() {
  if (!currentPackageId) return;
  try {
    const data = await apiFetch(
      `/api/knowledge/jobs?package_id=${encodeURIComponent(currentPackageId)}`,
    );
    const hadActive = (data.jobs || []).some((j) => ACTIVE_JOB_STATUSES.has(j.status));
    renderJobs(data.jobs || []);
    const anyActive = (data.jobs || []).some((j) => ACTIVE_JOB_STATUSES.has(j.status));
    if (!anyActive) {
      stopKnowledgeJobPolling();
      // 任务从活跃变为终态 → 刷新条目列表
      if (hadActive) {
        await loadItems();
      }
    }
  } catch (error) {
    console.warn('[knowledge] refreshJobs failed', error);
  }
}

function renderItems(items, total, page, pageSize) {
  const listEl = document.getElementById('knowledgeItemList');
  const emptyEl = document.getElementById('knowledgeItemEmpty');
  const pageInfo = document.getElementById('knowledgeItemPageInfo');
  const prevBtn = document.getElementById('btnKnowledgeItemPrev');
  const nextBtn = document.getElementById('btnKnowledgeItemNext');

  itemTotalPages = Math.max(1, Math.ceil(total / pageSize));
  if (pageInfo) {
    pageInfo.textContent = t('dynamic.appKnowledgePage.page', {
      current: page,
      total: itemTotalPages,
    });
  }
  if (prevBtn) prevBtn.disabled = page <= 1;
  if (nextBtn) nextBtn.disabled = page >= itemTotalPages;

  if (!listEl) return;
  listEl.replaceChildren();

  if (!items || items.length === 0) {
    if (emptyEl) emptyEl.classList.remove('hidden');
    return;
  }
  if (emptyEl) emptyEl.classList.add('hidden');

  items.forEach((item) => {
    const card = document.createElement('div');
    card.className = 'p-3 bg-cream border border-softPeach rounded-xl space-y-2';

    const top = document.createElement('div');
    top.className = 'flex flex-wrap items-center gap-2';

    const title = document.createElement('span');
    title.className = 'font-semibold text-warmText flex-1 min-w-0 truncate';
    title.textContent = item.title || '(untitled)';
    top.append(title);

    const kindBadge = document.createElement('span');
    kindBadge.className = 'px-2 py-0.5 text-xs font-semibold rounded-full bg-softPeach text-warmText';
    kindBadge.textContent = t(`dynamic.appKnowledgePage.${kindKey(item.kind)}`);
    top.append(kindBadge);

    const toggleLabel = document.createElement('label');
    toggleLabel.className = 'toggle-switch text-xs';
    const toggleInput = document.createElement('input');
    toggleInput.type = 'checkbox';
    toggleInput.role = 'switch';
    toggleInput.checked = Boolean(item.enabled);
    toggleInput.addEventListener('change', () => {
      void updateItemEnabled(item.public_id, toggleInput.checked);
    });
    toggleLabel.append(toggleInput);
    const toggleSpan = document.createElement('span');
    toggleLabel.append(toggleSpan);
    top.append(toggleLabel);

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className =
      'px-3 py-1 bg-white border border-gray-200 rounded-lg text-xs font-semibold text-red-600 hover:bg-red-50';
    deleteBtn.textContent = t('dynamic.appKnowledgePage.deleteItem');
    deleteBtn.addEventListener('click', () => {
      void deleteItemById(item.public_id);
    });
    top.append(deleteBtn);

    card.append(top);

    const content = document.createElement('p');
    content.className = 'text-sm text-warmText whitespace-pre-wrap break-words';
    content.textContent = item.content || '';
    card.append(content);

    // 展开区
    const details = document.createElement('div');
    details.className = 'text-xs text-gray-500 space-y-1 hidden';

    const fieldRow = (label, value) => {
      if (!value || (Array.isArray(value) && value.length === 0)) return null;
      const row = document.createElement('p');
      const labelSpan = document.createElement('span');
      labelSpan.className = 'font-semibold text-warmText';
      labelSpan.textContent = `${label}: `;
      row.append(labelSpan);
      const valSpan = document.createElement('span');
      valSpan.textContent = Array.isArray(value) ? value.join(', ') : String(value);
      row.append(valSpan);
      return row;
    };

    const fields = [
      ['dynamic.appKnowledgePage.fields.examples', item.examples],
      ['dynamic.appKnowledgePage.fields.triggers', item.triggers],
      ['dynamic.appKnowledgePage.fields.tones', item.tones],
      ['dynamic.appKnowledgePage.fields.scopes', item.scopes],
      ['dynamic.appKnowledgePage.fields.entities', item.entities],
      ['dynamic.appKnowledgePage.fields.evidence', item.evidence],
    ];
    fields.forEach(([key, value]) => {
      const label = t(key);
      const row = fieldRow(label, value);
      if (row) details.append(row);
    });
    if (item.confidence != null) {
      const row = fieldRow(
        t('dynamic.appKnowledgePage.fields.confidence'),
        item.confidence,
      );
      if (row) details.append(row);
    }

    card.append(details);

    if (details.children.length > 0) {
      const expandBtn = document.createElement('button');
      expandBtn.type = 'button';
      expandBtn.className =
        'px-3 py-1 bg-white border border-gray-200 rounded-lg text-xs font-semibold text-warmText hover:bg-gray-50';
      expandBtn.textContent = t('dynamic.appKnowledgePage.preview');
      let expanded = false;
      expandBtn.addEventListener('click', () => {
        expanded = !expanded;
        details.classList.toggle('hidden', !expanded);
      });
      card.append(expandBtn);
    }

    listEl.append(card);
  });
}

async function loadItems() {
  if (!currentPackageId) return;
  const kind = document.getElementById('knowledgeItemKindFilter')?.value || '';
  const enabledRaw = document.getElementById('knowledgeItemEnabledFilter')?.value || '';
  const query = document.getElementById('knowledgeItemSearch')?.value || '';
  const params = new URLSearchParams();
  params.set('package_id', currentPackageId);
  params.set('page', String(itemPage));
  params.set('page_size', String(ITEMS_PAGE_SIZE));
  if (kind) params.set('kind', kind);
  if (enabledRaw === 'true' || enabledRaw === 'false') params.set('enabled', enabledRaw);
  if (query) params.set('query', query);
  try {
    const data = await apiFetch(`/api/knowledge/items?${params.toString()}`);
    renderItems(data.items || [], data.total || 0, data.page || 1, data.page_size || ITEMS_PAGE_SIZE);
  } catch (error) {
    showToast(error.message, true);
    console.warn('[knowledge] loadItems failed', error);
  }
}

async function updateItemEnabled(itemId, enabled) {
  try {
    await apiFetch(`/api/knowledge/items/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    });
    showToast(t('dynamic.appKnowledgePage.itemUpdated'));
  } catch (error) {
    showToast(error.message, true);
    await loadItems();
  }
}

async function deleteItemById(itemId) {
  if (!window.confirm(t('dynamic.appKnowledgePage.confirmDeleteItem'))) return;
  try {
    await apiFetch(`/api/knowledge/items/${encodeURIComponent(itemId)}`, {
      method: 'DELETE',
    });
    showToast(t('dynamic.appKnowledgePage.itemDeleted'));
    await loadItems();
  } catch (error) {
    showToast(error.message, true);
  }
}

async function openPackageDetail(packageId) {
  currentPackageId = packageId;
  itemPage = 1;
  showDetailView();
  try {
    const data = await apiFetch(
      `/api/knowledge/packages/${encodeURIComponent(packageId)}`,
    );
    fillPackageForm(data);
    renderJobs([]);
    await refreshJobs();
    await loadItems();
    // 进入详情后若有活跃任务则启动轮询
    startKnowledgeJobPolling(packageId);
  } catch (error) {
    showToast(error.message, true);
    console.warn('[knowledge] openPackageDetail failed', error);
  }
}

async function savePackageSettings() {
  if (!currentPackageId) return;
  const body = {
    name: document.getElementById('knowledgePackageName')?.value || '',
    description: document.getElementById('knowledgePackageDescription')?.value || '',
    content_kind: document.getElementById('knowledgePackageContentKind')?.value || 'auto',
    scope_mode: document.getElementById('knowledgePackageScopeMode')?.value || 'global',
    scope_tags: parseScopeTags(document.getElementById('knowledgePackageScopeTags')?.value),
    enabled: Boolean(document.getElementById('knowledgePackageEnabled')?.checked),
    priority: parseInt(document.getElementById('knowledgePackagePriority')?.value, 10) || 0,
  };
  try {
    const updated = await apiFetch(
      `/api/knowledge/packages/${encodeURIComponent(currentPackageId)}`,
      { method: 'PATCH', body: JSON.stringify(body) },
    );
    fillPackageForm(updated);
    showToast(t('dynamic.appKnowledgePage.packageUpdated'));
  } catch (error) {
    showToast(error.message, true);
  }
}

async function deleteCurrentPackage() {
  if (!currentPackageId) return;
  if (!window.confirm(t('dynamic.appKnowledgePage.confirmDeletePackage'))) return;
  try {
    await apiFetch(
      `/api/knowledge/packages/${encodeURIComponent(currentPackageId)}`,
      { method: 'DELETE' },
    );
    showToast(t('dynamic.appKnowledgePage.packageDeleted'));
    await loadKnowledgePage();
  } catch (error) {
    showToast(error.message, true);
  }
}

function syncSourceFormVisibility() {
  const type = document.getElementById('knowledgeSourceType')?.value || 'pasted_text';
  const urlWrap = document.getElementById('knowledgeSourceUrlWrap');
  const textWrap = document.getElementById('knowledgePastedTextWrap');
  if (urlWrap) urlWrap.classList.toggle('hidden', type !== 'webpage');
  if (textWrap) textWrap.classList.toggle('hidden', type === 'webpage');
}

async function startImport() {
  if (!currentPackageId) return;
  const sourceType = document.getElementById('knowledgeSourceType')?.value || 'pasted_text';
  const body = {
    source_type: sourceType,
    display_name: document.getElementById('knowledgeDisplayName')?.value || '',
    document_kind: document.getElementById('knowledgeDocumentKind')?.value || 'auto',
  };
  if (sourceType === 'webpage') {
    body.source_url = document.getElementById('knowledgeSourceUrl')?.value || '';
  } else {
    body.pasted_text = document.getElementById('knowledgePastedText')?.value || '';
  }
  try {
    await apiFetch(
      `/api/knowledge/packages/${encodeURIComponent(currentPackageId)}/imports`,
      { method: 'POST', body: JSON.stringify(body) },
    );
    showToast(t('dynamic.appKnowledgePage.importStarted'));
    // 清空粘贴 / URL
    const textEl = document.getElementById('knowledgePastedText');
    const urlEl = document.getElementById('knowledgeSourceUrl');
    const nameEl = document.getElementById('knowledgeDisplayName');
    if (textEl) textEl.value = '';
    if (urlEl) urlEl.value = '';
    if (nameEl) nameEl.value = '';
    await refreshJobs();
    startKnowledgeJobPolling(currentPackageId);
  } catch (error) {
    showToast(error.message, true);
  }
}

// ---------------------------------------------------------------------------
// 检索预览
// ---------------------------------------------------------------------------

function renderRetrievalResult(result) {
  const wrap = document.getElementById('knowledgeRetrievalResult');
  const hitEl = document.getElementById('knowledgeRetrievalHitCount');
  const msEl = document.getElementById('knowledgeRetrievalMs');
  const ftsEl = document.getElementById('knowledgeRetrievalFts');
  const promptEl = document.getElementById('knowledgePromptText');
  const itemsEl = document.getElementById('knowledgeRetrievalItems');

  if (!wrap) return;
  wrap.classList.remove('hidden');

  if (hitEl) {
    hitEl.textContent = t('dynamic.appKnowledgePage.hitCount', {
      count: result?.hit_count ?? 0,
    });
  }
  if (msEl) {
    msEl.textContent = t('dynamic.appKnowledgePage.retrievalMs', {
      ms: result?.retrieval_ms ?? 0,
    });
  }
  if (ftsEl) {
    ftsEl.textContent = t('dynamic.appKnowledgePage.ftsBackend', {
      backend: result?.fts_backend || '—',
    });
  }
  if (promptEl) {
    promptEl.textContent = result?.prompt_text || '';
  }
  if (itemsEl) {
    itemsEl.replaceChildren();
    const items = result?.items || [];
    if (items.length === 0) {
      const empty = document.createElement('p');
      empty.className = 'text-sm text-gray-500';
      empty.textContent = t('dynamic.appKnowledgePage.noResults');
      itemsEl.append(empty);
    } else {
      items.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'p-2 bg-cream border border-softPeach rounded-lg text-sm';
        const title = document.createElement('p');
        title.className = 'font-semibold text-warmText';
        title.textContent = item.title || '(untitled)';
        row.append(title);
        if (item.content) {
          const c = document.createElement('p');
          c.className = 'text-gray-600 whitespace-pre-wrap break-words';
          c.textContent = item.content;
          row.append(c);
        }
        itemsEl.append(row);
      });
    }
  }
}

async function startPreview() {
  const sceneBrief = document.getElementById('knowledgeSceneBrief')?.value || '';
  const keywordsRaw = document.getElementById('knowledgeKeywords')?.value || '';
  const maxItems = parseInt(document.getElementById('knowledgeMaxItems')?.value, 10) || 4;
  const maxChars = parseInt(document.getElementById('knowledgeMaxChars')?.value, 10) || 360;
  const body = { max_items: maxItems, max_chars: maxChars };
  if (sceneBrief) body.scene_brief = sceneBrief;
  const keywords = parseScopeTags(keywordsRaw);
  if (keywords.length > 0) body.keywords = keywords;
  try {
    const result = await apiFetch('/api/knowledge/retrieval/preview', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    renderRetrievalResult(result);
  } catch (error) {
    showToast(error.message, true);
  }
}

// ---------------------------------------------------------------------------
// 轮询
// ---------------------------------------------------------------------------

export function startKnowledgeJobPolling(packagePublicId) {
  if (jobPollTimer) {
    // 若切换到不同 package，先停掉旧轮询
    if (currentPackageId !== packagePublicId) {
      stopKnowledgeJobPolling();
    } else {
      return;
    }
  }
  currentPackageId = packagePublicId;
  jobPollTimer = window.setInterval(() => {
    refreshJobs().catch((error) => {
      console.warn('[knowledge] job poll failed', error);
    });
  }, JOB_POLL_INTERVAL_MS);
}

export function stopKnowledgeJobPolling() {
  if (!jobPollTimer) return;
  window.clearInterval(jobPollTimer);
  jobPollTimer = null;
}

// ---------------------------------------------------------------------------
// 初始化
// ---------------------------------------------------------------------------

export function initKnowledgePage(deps = {}) {
  toast = deps.showToast || toast;
  if (handlersBound) return;
  handlersBound = true;

  document.getElementById('btnKnowledgeNewPackage')?.addEventListener('click', () => {
    void createNewPackage();
  });
  document.getElementById('btnKnowledgeRefresh')?.addEventListener('click', () => {
    void loadKnowledgePage();
  });
  document.getElementById('btnKnowledgeRetrievalPreview')?.addEventListener('click', () => {
    showRetrievalView();
  });

  document.getElementById('btnKnowledgeBackToList')?.addEventListener('click', () => {
    void loadKnowledgePage();
  });
  document.getElementById('btnKnowledgePreviewBack')?.addEventListener('click', () => {
    void loadKnowledgePage();
  });

  document.getElementById('btnKnowledgeSavePackage')?.addEventListener('click', () => {
    void savePackageSettings();
  });
  document.getElementById('btnKnowledgeDeletePackage')?.addEventListener('click', () => {
    void deleteCurrentPackage();
  });

  document.getElementById('knowledgeSourceType')?.addEventListener('change', () => {
    syncSourceFormVisibility();
  });
  document.getElementById('btnKnowledgeStartImport')?.addEventListener('click', () => {
    void startImport();
  });

  document.getElementById('btnKnowledgeSearchItems')?.addEventListener('click', () => {
    itemPage = 1;
    void loadItems();
  });
  document.getElementById('btnKnowledgeItemPrev')?.addEventListener('click', () => {
    if (itemPage > 1) {
      itemPage -= 1;
      void loadItems();
    }
  });
  document.getElementById('btnKnowledgeItemNext')?.addEventListener('click', () => {
    if (itemPage < itemTotalPages) {
      itemPage += 1;
      void loadItems();
    }
  });

  document.getElementById('btnKnowledgeStartPreview')?.addEventListener('click', () => {
    void startPreview();
  });

  syncSourceFormVisibility();
}
