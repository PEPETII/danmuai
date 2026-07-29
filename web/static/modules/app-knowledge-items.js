import { apiFetch } from './transport.js';
import { t } from './i18n.js';
import {
  ITEMS_PAGE_SIZE,
  currentPackageId,
  itemPage,
  showKnowledgeToast,
  setItemTotalPages,
} from './app-knowledge-state.js';
import { kindKey } from './app-knowledge-status.js';
import { openKnowledgeConfirmModal } from './app-knowledge-modals.js';

export function scrollToItemsSection() {
  document.getElementById('knowledgeItemList')?.scrollIntoView({
    behavior: 'smooth',
    block: 'start',
  });
}

function summarizeContent(text, maxLen = 120) {
  const raw = String(text || '').trim();
  if (raw.length <= maxLen) return raw;
  return `${raw.slice(0, maxLen)}…`;
}

export function renderItems(items, total, page, pageSize) {
  const listEl = document.getElementById('knowledgeItemList');
  const emptyEl = document.getElementById('knowledgeItemEmpty');
  const pageInfo = document.getElementById('knowledgeItemPageInfo');
  const prevBtn = document.getElementById('btnKnowledgeItemPrev');
  const nextBtn = document.getElementById('btnKnowledgeItemNext');

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  setItemTotalPages(totalPages);

  if (pageInfo) {
    pageInfo.textContent = t('dynamic.appKnowledgePage.page', {
      current: page,
      total: totalPages,
    });
  }
  if (prevBtn) prevBtn.disabled = page <= 1;
  if (nextBtn) nextBtn.disabled = page >= totalPages;

  if (!listEl) return;
  listEl.replaceChildren();

  if (!items || items.length === 0) {
    if (emptyEl) emptyEl.classList.remove('hidden');
    return;
  }
  if (emptyEl) emptyEl.classList.add('hidden');

  items.forEach((item) => {
    const card = document.createElement('div');
    card.className = 'knowledge-item-card p-3 bg-cream border border-softPeach rounded-xl space-y-2 min-w-0';

    const top = document.createElement('div');
    top.className = 'flex flex-wrap items-center gap-2 min-w-0';

    const title = document.createElement('span');
    title.className = 'font-semibold text-warmText flex-1 min-w-0 break-words';
    title.textContent = item.title || '(untitled)';
    top.append(title);

    const kindBadge = document.createElement('span');
    kindBadge.className = 'knowledge-status-badge knowledge-status-badge--muted';
    kindBadge.textContent = t(`dynamic.appKnowledgePage.${kindKey(item.kind)}`);
    top.append(kindBadge);

    const enabledBadge = document.createElement('span');
    enabledBadge.className = `knowledge-status-badge ${
      item.enabled ? 'knowledge-status-badge--success' : 'knowledge-status-badge--muted'
    }`;
    enabledBadge.textContent = item.enabled
      ? t('dynamic.appKnowledgePage.enabled')
      : t('dynamic.appKnowledgePage.disabled');
    top.append(enabledBadge);

    const deleteBtn = document.createElement('button');
    deleteBtn.type = 'button';
    deleteBtn.className =
      'px-3 py-1 bg-white border border-gray-200 rounded-lg text-xs font-semibold text-red-600 hover:bg-red-50 ui-button ui-button--secondary ui-button--sm';
    deleteBtn.textContent = t('dynamic.appKnowledgePage.deleteItem');
    deleteBtn.addEventListener('click', () => {
      void deleteItemById(item.public_id);
    });
    top.append(deleteBtn);

    card.append(top);

    const content = document.createElement('p');
    content.className = 'text-sm text-warmText break-words';
    content.textContent = summarizeContent(item.content);
    card.append(content);

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
    const toggleText = document.createElement('span');
    toggleText.className = 'text-xs text-gray-500 ml-2';
    toggleText.textContent = t('dynamic.appKnowledgePage.itemEnableLabel');
    const toggleWrap = document.createElement('div');
    toggleWrap.className = 'flex items-center gap-2';
    toggleWrap.append(toggleLabel, toggleText);
    card.append(toggleWrap);

    const details = document.createElement('div');
    details.className = 'text-xs text-gray-500 space-y-1 hidden';
    details.id = `knowledge-item-details-${item.public_id}`;

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
      [t('dynamic.appKnowledgePage.fields.examples'), item.examples],
      [t('dynamic.appKnowledgePage.fields.triggers'), item.triggers],
      [t('dynamic.appKnowledgePage.fields.tones'), item.tones],
      [t('dynamic.appKnowledgePage.fields.scopes'), item.scopes],
      [t('dynamic.appKnowledgePage.fields.entities'), item.entities],
      [t('dynamic.appKnowledgePage.fields.evidence'), item.evidence],
    ];
    fields.forEach(([label, value]) => {
      const row = fieldRow(label, value);
      if (row) details.append(row);
    });
    if (item.confidence != null) {
      const row = fieldRow(t('dynamic.appKnowledgePage.fields.confidence'), item.confidence);
      if (row) details.append(row);
    }

    card.append(details);

    if (details.children.length > 0) {
      const expandBtn = document.createElement('button');
      expandBtn.type = 'button';
      expandBtn.className =
        'px-3 py-1 bg-white border border-gray-200 rounded-lg text-xs font-semibold text-warmText hover:bg-gray-50 ui-button ui-button--secondary ui-button--sm';
      expandBtn.textContent = t('dynamic.appKnowledgePage.viewItemDetails');
      expandBtn.setAttribute('aria-expanded', 'false');
      expandBtn.setAttribute('aria-controls', details.id);
      expandBtn.addEventListener('click', () => {
        const expanded = details.classList.toggle('hidden') === false;
        expandBtn.setAttribute('aria-expanded', String(expanded));
      });
      card.append(expandBtn);
    }

    listEl.append(card);
  });
}

export async function loadItems() {
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
    renderItems(
      data.items || [],
      data.total || 0,
      data.page || 1,
      data.page_size || ITEMS_PAGE_SIZE,
    );
  } catch (error) {
    showKnowledgeToast(error.message, true);
    console.warn('[knowledge] loadItems failed', error);
  }
}

async function updateItemEnabled(itemId, enabled) {
  try {
    await apiFetch(`/api/knowledge/items/${encodeURIComponent(itemId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ enabled }),
    });
    showKnowledgeToast(t('dynamic.appKnowledgePage.itemUpdated'));
  } catch (error) {
    showKnowledgeToast(error.message, true);
    await loadItems();
  }
}

async function deleteItemById(itemId) {
  const ok = await openKnowledgeConfirmModal({
    title: t('dynamic.appKnowledgePage.deleteItem'),
    message: t('dynamic.appKnowledgePage.confirmDeleteItem'),
    confirmLabel: t('dynamic.appKnowledgePage.confirm.delete'),
    danger: true,
  });
  if (!ok) return;
  try {
    await apiFetch(`/api/knowledge/items/${encodeURIComponent(itemId)}`, {
      method: 'DELETE',
    });
    showKnowledgeToast(t('dynamic.appKnowledgePage.itemDeleted'));
    await loadItems();
  } catch (error) {
    showKnowledgeToast(error.message, true);
  }
}
