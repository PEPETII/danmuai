const SAMPLE_COMMENTS = [
  '这波操作可以啊',
  '画面动起来了',
  '主播反应好快',
  '这句弹幕很有现场感',
  '前方高能来了',
  '配置看起来舒服多了',
];

const WATCHED_FIELD_IDS = [
  'danmu_render_mode',
  'danmu_speed',
  'danmu_lines',
  'font_size',
  'opacity',
  'danmu_max_chars',
  'danmu_font_family',
  'danmu_font_bold',
  'floating_panel_width',
  'floating_panel_max_items',
  'floating_panel_speed',
  'floating_panel_opacity',
  'floating_panel_font_size',
  'floating_panel_font_family',
  'floating_panel_font_bold',
];

let initialized = false;
let pendingAnimationFrame = 0;

function clampNumber(value, fallback, min, max) {
  const n = Number.parseFloat(value);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(min, Math.min(max, n));
}

function readNumber(id, fallback, min, max) {
  return clampNumber(document.getElementById(id)?.value, fallback, min, max);
}

function readCheckbox(id) {
  return document.getElementById(id)?.checked === true;
}

function readText(id) {
  return String(document.getElementById(id)?.value || '').trim();
}

function truncateComment(text, maxChars) {
  const chars = Array.from(text);
  if (chars.length <= maxChars) return text;
  return `${chars.slice(0, Math.max(1, maxChars - 1)).join('')}…`;
}

function previewFontSize(realSize, min, max, scale) {
  return clampNumber(realSize * scale, min, min, max);
}

function resolveFontFamily(value) {
  return value || 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif';
}

function previewTexts(maxChars) {
  return SAMPLE_COMMENTS.map((item) => truncateComment(item, maxChars));
}

function clearChildren(el) {
  if (el) el.replaceChildren();
}

function createCommentItem(text, cfg) {
  const item = document.createElement('span');
  item.className = 'danmu-preview-item';
  if (cfg.bold) item.classList.add('is-bold');
  item.textContent = text;
  item.style.fontSize = `${cfg.fontSize}px`;
  item.style.opacity = String(cfg.opacity);
  item.style.fontFamily = resolveFontFamily(cfg.fontFamily);
  return item;
}

function readPreviewConfig() {
  const mode = document.getElementById('danmu_render_mode')?.value === 'floating_panel'
    ? 'floating_panel'
    : 'scrolling';
  const maxChars = Math.round(readNumber('danmu_max_chars', 15, 5, 80));
  return {
    mode,
    maxChars,
    scrolling: {
      speed: readNumber('danmu_speed', 2, 0.5, 10),
      lines: Math.round(readNumber('danmu_lines', 20, 12, 20)),
      opacityPercent: Math.round(readNumber('opacity', 100, 0, 100)),
      fontSize: previewFontSize(readNumber('font_size', 24, 12, 72), 12, 28, 0.58),
      realFontSize: Math.round(readNumber('font_size', 24, 12, 72)),
      fontFamily: readText('danmu_font_family'),
      bold: readCheckbox('danmu_font_bold'),
    },
    floating: {
      width: Math.round(readNumber('floating_panel_width', 360, 200, 800)),
      maxItems: Math.round(readNumber('floating_panel_max_items', 8, 1, 50)),
      speed: readNumber('floating_panel_speed', 1, 0.5, 5),
      opacityPercent: Math.round(readNumber('floating_panel_opacity', 85, 0, 100)),
      fontSize: previewFontSize(readNumber('floating_panel_font_size', 20, 12, 48), 12, 28, 0.72),
      realFontSize: Math.round(readNumber('floating_panel_font_size', 20, 12, 48)),
      fontFamily: readText('floating_panel_font_family'),
      bold: readCheckbox('floating_panel_font_bold'),
    },
  };
}

function renderScrollingPreview(container, cfg, texts) {
  clearChildren(container);
  if (!container) return;

  const laneCount = Math.max(4, Math.min(7, Math.round(cfg.lines / 3)));
  const duration = clampNumber(12 / cfg.speed, 6, 2.8, 18);
  const itemCount = Math.max(5, Math.min(9, laneCount + 2));
  for (let i = 0; i < itemCount; i += 1) {
    const item = createCommentItem(texts[i % texts.length], {
      bold: cfg.bold,
      fontFamily: cfg.fontFamily,
      fontSize: cfg.fontSize,
      opacity: cfg.opacityPercent / 100,
    });
    const lane = i % laneCount;
    item.style.top = `${((lane + 0.5) / laneCount) * 100}%`;
    item.style.animationDuration = `${duration}s`;
    item.style.animationDelay = `${-(i * duration) / itemCount}s`;
    container.appendChild(item);
  }
}

function renderFloatingPreview(container, cfg, texts) {
  clearChildren(container);
  if (!container) return;

  const panel = document.createElement('div');
  panel.className = 'danmu-preview-floating-panel';
  panel.style.width = `${Math.max(170, Math.min(320, Math.round(cfg.width * 0.42)))}px`;
  panel.style.maxWidth = '76%';
  container.appendChild(panel);

  const duration = clampNumber(9 / cfg.speed, 7, 3.2, 16);
  const itemCount = Math.max(1, Math.min(6, cfg.maxItems));
  for (let i = 0; i < itemCount; i += 1) {
    const item = createCommentItem(texts[i % texts.length], {
      bold: cfg.bold,
      fontFamily: cfg.fontFamily,
      fontSize: cfg.fontSize,
      opacity: cfg.opacityPercent / 100,
    });
    item.classList.add('danmu-preview-floating-item');
    item.style.animationDuration = `${duration}s`;
    item.style.animationDelay = `${-(i * duration) / itemCount}s`;
    panel.appendChild(item);
  }
}

function updatePreviewMeta(cfg) {
  const badge = document.getElementById('danmuStylePreviewMode');
  const meta = document.getElementById('danmuStylePreviewMeta');
  if (cfg.mode === 'floating_panel') {
    if (badge) badge.textContent = '从下到上';
    if (meta) {
      meta.textContent = `速度 ${cfg.floating.speed.toFixed(1)} · 最多 ${cfg.floating.maxItems} 条 · 字号 ${cfg.floating.realFontSize}px · 透明度 ${cfg.floating.opacityPercent}%`;
    }
    return;
  }
  if (badge) badge.textContent = '横向弹幕';
  if (meta) {
    meta.textContent = `速度 ${cfg.scrolling.speed.toFixed(1)} · 轨道 ${cfg.scrolling.lines} 行 · 字号 ${cfg.scrolling.realFontSize}px · 透明度 ${cfg.scrolling.opacityPercent}%`;
  }
}

export function updateDanmuStylePreview() {
  const stage = document.getElementById('danmuStylePreviewStage');
  const scrolling = document.getElementById('danmuStylePreviewScrolling');
  const floating = document.getElementById('danmuStylePreviewFloating');
  if (!stage || !scrolling || !floating) return;

  const cfg = readPreviewConfig();
  const texts = previewTexts(cfg.maxChars);
  stage.dataset.mode = cfg.mode;
  scrolling.classList.toggle('hidden', cfg.mode !== 'scrolling');
  floating.classList.toggle('hidden', cfg.mode !== 'floating_panel');

  if (cfg.mode === 'floating_panel') {
    clearChildren(scrolling);
    renderFloatingPreview(floating, cfg.floating, texts);
  } else {
    clearChildren(floating);
    renderScrollingPreview(scrolling, cfg.scrolling, texts);
  }
  updatePreviewMeta(cfg);
}

export function requestDanmuStylePreviewUpdate() {
  if (pendingAnimationFrame) return;
  const schedule = window.requestAnimationFrame || ((callback) => window.setTimeout(callback, 16));
  pendingAnimationFrame = schedule(() => {
    pendingAnimationFrame = 0;
    updateDanmuStylePreview();
  });
}

export function initDanmuStylePreview() {
  if (initialized) {
    updateDanmuStylePreview();
    return;
  }
  initialized = true;
  WATCHED_FIELD_IDS.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.addEventListener('input', requestDanmuStylePreviewUpdate);
    el.addEventListener('change', requestDanmuStylePreviewUpdate);
  });
  updateDanmuStylePreview();
}
