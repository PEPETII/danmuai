import { apiFetch } from './transport.js';
import { t } from './i18n.js';
import { showKnowledgeToast } from './app-knowledge-state.js';
import { parseCommaList } from './app-knowledge-status.js';

export function renderRetrievalResult(result) {
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
        row.className = 'p-2 bg-cream border border-softPeach rounded-lg text-sm min-w-0';
        const title = document.createElement('p');
        title.className = 'font-semibold text-warmText break-words';
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

export async function startPreview() {
  const sceneBrief = document.getElementById('knowledgeSceneBrief')?.value || '';
  const keywordsRaw = document.getElementById('knowledgeKeywords')?.value || '';
  const maxItems = parseInt(document.getElementById('knowledgeMaxItems')?.value, 10) || 4;
  const maxChars = parseInt(document.getElementById('knowledgeMaxChars')?.value, 10) || 360;
  const body = { max_items: maxItems, max_chars: maxChars };
  if (sceneBrief) body.scene_brief = sceneBrief;
  const keywords = parseCommaList(keywordsRaw);
  if (keywords.length > 0) body.keywords = keywords;
  try {
    const result = await apiFetch('/api/knowledge/retrieval/preview', {
      method: 'POST',
      body: JSON.stringify(body),
    });
    renderRetrievalResult(result);
  } catch (error) {
    showKnowledgeToast(error.message, true);
  }
}
