/**
 * 教程页：图文链接（本地硬编码）+ 视频链接（Supabase tutorial_links）。
 */

export const VIDEO_PLACEHOLDER = '正在紧急赶制中...';

export function isNavigableUrl(value) {
  return /^https?:\/\//i.test(String(value || '').trim());
}

function renderTutorialVideo(url) {
  const link = document.getElementById('tutorialVideoLink');
  const placeholder = document.getElementById('tutorialVideoPlaceholder');
  if (!link || !placeholder) return;

  const trimmed = String(url || '').trim() || VIDEO_PLACEHOLDER;
  if (isNavigableUrl(trimmed)) {
    link.href = trimmed;
    link.textContent = trimmed;
    link.classList.remove('hidden');
    placeholder.classList.add('hidden');
    placeholder.textContent = VIDEO_PLACEHOLDER;
    return;
  }

  link.href = '#';
  link.textContent = '';
  link.classList.add('hidden');
  placeholder.textContent = trimmed;
  placeholder.classList.remove('hidden');
}

export async function loadTutorialPage() {
  renderTutorialVideo(VIDEO_PLACEHOLDER);

  if (!window.DanmuSupabase?.isConfigured?.()) return;

  try {
    const row = await window.DanmuSupabase.fetchTutorialVideoLink();
    if (row?.url) {
      renderTutorialVideo(row.url);
    }
  } catch (error) {
    console.warn('[tutorial] supabase fetch failed', error);
  }
}
