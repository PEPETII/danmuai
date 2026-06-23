/**
 * 弹幕样式预览 (W-PR-INTAKE-022)
 *
 * 纯前端预览：读取 settingsTab-danmu 表单值，实时渲染弹幕效果。
 * 不调用后端、不写入持久化、不接入真实 overlay。
 */

const PREVIEW_TEXTS = [
  '这波操作666',
  '哈哈哈哈哈太搞了',
  '主播好强！',
  '前方高能预警',
  'awsl',
];

let previewTimer = null;
let previewIndex = 0;

function getField(id) {
  return document.getElementById(id);
}

function getNumber(id, fallback) {
  const el = getField(id);
  if (!el || el.value === '') return fallback;
  const num = Number(el.value);
  return Number.isNaN(num) ? fallback : num;
}

function getSelect(id, fallback) {
  const el = getField(id);
  return el ? el.value || fallback : fallback;
}

function getChecked(id) {
  const el = getField(id);
  return el ? el.checked : false;
}

function getRenderMode() {
  return getSelect('danmu_render_mode', 'scrolling');
}

function buildScrollingStyle() {
  const speed = getNumber('danmu_speed', 3);
  const fontSize = getNumber('danmu_font_size', 24);
  const opacity = Math.max(0, Math.min(1, getNumber('danmu_opacity', 100) / 100));
  const maxChars = getNumber('danmu_max_chars', 15);
  const fontFamily = getSelect('danmu_font_family', '');
  const bold = getChecked('danmu_font_bold');

  return {
    speed,
    fontSize,
    opacity,
    maxChars,
    fontFamily,
    bold,
  };
}

function buildFloatingStyle() {
  const width = getNumber('floating_panel_width', 400);
  const maxItems = getNumber('floating_panel_max_items', 10);
  const speed = getNumber('floating_panel_speed', 2);
  const opacity = Math.max(0, Math.min(1, getNumber('floating_panel_opacity', 90) / 100));
  const fontSize = getNumber('floating_panel_font_size', 20);
  const fontFamily = getSelect('floating_panel_font_family', '');
  const bold = getChecked('floating_panel_font_bold');

  return {
    width,
    maxItems,
    speed,
    opacity,
    fontSize,
    fontFamily,
    bold,
  };
}

function truncate(text, maxChars) {
  if (!maxChars || maxChars <= 0) return text;
  if (text.length <= maxChars) return text;
  return text.slice(0, maxChars) + '...';
}

function renderScrollingPreview() {
  const track = document.getElementById('danmuPreviewTrack');
  if (!track) return;

  const style = buildScrollingStyle();
  track.innerHTML = '';

  const text = truncate(PREVIEW_TEXTS[previewIndex % PREVIEW_TEXTS.length], style.maxChars);
  previewIndex++;

  const item = document.createElement('span');
  item.textContent = text;
  item.style.fontSize = `${style.fontSize}px`;
  item.style.opacity = String(style.opacity);
  item.style.fontWeight = style.bold ? 'bold' : 'normal';
  if (style.fontFamily) {
    item.style.fontFamily = style.fontFamily;
  }
  item.style.whiteSpace = 'nowrap';
  item.style.position = 'absolute';
  item.style.right = '-100%';
  item.style.transition = `right ${10 / style.speed}s linear`;
  item.style.color = '#fff';
  item.style.textShadow = '0 0 4px rgba(0,0,0,0.8)';

  track.appendChild(item);
  requestAnimationFrame(() => {
    item.style.right = '100%';
  });
}

function renderFloatingPreview() {
  const panel = document.getElementById('danmuPreviewFloatingPanel');
  if (!panel) return;

  const style = buildFloatingStyle();

  panel.style.width = `${Math.min(style.width, 400)}px`;
  panel.style.opacity = String(style.opacity);

  const fontSize = `${style.fontSize}px`;
  const fontWeight = style.bold ? 'bold' : 'normal';
  const fontFamily = style.fontFamily || 'inherit';

  const text = truncate(PREVIEW_TEXTS[previewIndex % PREVIEW_TEXTS.length], 0);
  previewIndex++;

  const item = document.createElement('div');
  item.textContent = text;
  item.style.fontSize = fontSize;
  item.style.fontWeight = fontWeight;
  item.style.fontFamily = fontFamily;
  item.style.color = '#fff';
  item.style.padding = '4px 8px';
  item.style.transition = `transform ${3 / style.speed}s ease-out, opacity 0.3s`;
  item.style.opacity = '0';

  panel.appendChild(item);
  requestAnimationFrame(() => {
    item.style.opacity = '1';
  });

  while (panel.children.length > style.maxItems) {
    const first = panel.firstChild;
    if (first) {
      first.style.opacity = '0';
      first.style.transform = 'translateY(-10px)';
      setTimeout(() => first.remove(), 300);
    } else {
      break;
    }
  }
}

function switchPreviewMode() {
  const mode = getRenderMode();
  const scrolling = document.getElementById('danmuPreviewScrolling');
  const floating = document.getElementById('danmuPreviewFloating');
  if (scrolling) scrolling.classList.toggle('hidden', mode !== 'scrolling');
  if (floating) floating.classList.toggle('hidden', mode !== 'floating_panel');
}

function tick() {
  const mode = getRenderMode();
  if (mode === 'scrolling') {
    renderScrollingPreview();
  } else {
    renderFloatingPreview();
  }
}

export function refreshDanmuPreview() {
  switchPreviewMode();
  tick();
}

export function initDanmuPreview() {
  const preview = document.getElementById('danmuStylePreview');
  if (!preview) return;

  switchPreviewMode();

  const fields = [
    'danmu_render_mode',
    'danmu_speed',
    'danmu_font_size',
    'danmu_opacity',
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

  fields.forEach((id) => {
    const el = getField(id);
    if (el) {
      el.addEventListener('input', refreshDanmuPreview);
      el.addEventListener('change', refreshDanmuPreview);
    }
  });

  if (previewTimer) clearInterval(previewTimer);
  previewTimer = setInterval(() => {
    const previewEl = document.getElementById('danmuStylePreview');
    if (!previewEl || previewEl.closest('[hidden]')) return;
    tick();
  }, 2500);
}
