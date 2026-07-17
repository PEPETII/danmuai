/**
 * 弹幕样式预览 (W-PR-INTAKE-022)
 *
 * 纯前端预览：读取 settingsTab-danmu 表单值，实时渲染弹幕效果。
 * 不调用后端、不写入持久化、不接入真实 overlay。
 */

import { t } from './i18n.js';

const PREVIEW_TEXTS = [
  t('dynamic.settingsDanmuPreview.这波操作666'),
  t('dynamic.settingsDanmuPreview.哈哈哈哈哈太搞了'),
  t('dynamic.settingsDanmuPreview.主播好强'),
  t('dynamic.settingsDanmuPreview.前方高能预警'),
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
  const fontFamily = getSelect('danmu_font_family', '');
  const bold = getChecked('danmu_font_bold');
  const color = resolvePreviewColor();

  return {
    speed,
    fontSize,
    opacity,
    fontFamily,
    bold,
    color,
  };
}

function resolvePreviewColor() {
  const rawSelected = getField('danmu_font_color_selected')?.value ?? '["#FFFFFF"]';
  let selected = [];
  try {
    selected = JSON.parse(rawSelected);
  } catch {
    selected = [];
  }
  if (!Array.isArray(selected) || selected.length === 0) {
    return '#FFFFFF';
  }
  selected = selected.filter((c) => typeof c === 'string' && c.trim());
  if (selected.length === 0) return '#FFFFFF';
  if (selected.length === 1) return selected[0];

  const mode = getField('danmu_font_color_mode')?.value ?? 'equal';
  if (mode === 'weighted') {
    const rawWeights = getField('danmu_font_color_weights')?.value ?? '{}';
    let weightsMap = {};
    try {
      weightsMap = JSON.parse(rawWeights);
    } catch {
      weightsMap = {};
    }
    const weights = selected.map((color) => {
      const w = weightsMap[color];
      const v = parseFloat(w);
      return Number.isNaN(v) ? 0 : v;
    });
    const total = weights.reduce((a, b) => a + b, 0);
    if (total > 0) {
      const r = Math.random() * total;
      let acc = 0;
      for (let i = 0; i < selected.length; i++) {
        acc += weights[i];
        if (r <= acc) return selected[i];
      }
      return selected[selected.length - 1];
    }
  }
  return selected[Math.floor(Math.random() * selected.length)];
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

function renderScrollingPreview() {
  const track = document.getElementById('danmuPreviewTrack');
  if (!track) return;

  const style = buildScrollingStyle();
  track.innerHTML = '';

  const text = PREVIEW_TEXTS[previewIndex % PREVIEW_TEXTS.length];
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
  item.style.color = style.color;
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

  const text = PREVIEW_TEXTS[previewIndex % PREVIEW_TEXTS.length];
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

// W-TRACK-VIS-002: 轨道几何可视化。基于表单值与 engine 常量(top_margin=50,
// bottom_margin=80, line_height=40)在预览容器内按比例绘制轨道分隔线与
// 顶/底安全边距带。预览容器高度固定(CSS 7.5rem),按屏幕高度比例缩放。
const TRACK_TOP_MARGIN = 50;
const TRACK_BOTTOM_MARGIN = 80;
const TRACK_LINE_HEIGHT = 40;
const LAYOUT_MODE_RATIOS = {
  fullscreen: 1.0,
  '3/4': 0.75,
  '1/2': 0.5,
  '1/4': 0.25,
};

function renderTrackBands() {
  const bandsEl = document.getElementById('danmuTrackBands');
  if (!bandsEl) return;
  const mode = getRenderMode();
  if (mode !== 'scrolling') {
    bandsEl.classList.add('hidden');
    bandsEl.innerHTML = '';
    return;
  }
  bandsEl.classList.remove('hidden');
  bandsEl.innerHTML = '';

  const layoutMode = getSelect('layout_mode', 'fullscreen');
  const ratio = LAYOUT_MODE_RATIOS[layoutMode] ?? 1.0;
  // 预览容器高度(与 CSS .danmu-preview-scrolling height: 7.5rem 对齐)
  const previewH = 120;
  // 用一个虚拟屏幕高度作为比例参考(与 engine 默认 1080 一致)
  const refScreenH = 1080;
  const drawableH = refScreenH * ratio;
  const scale = previewH / refScreenH;

  // 顶部安全边距带
  const topBand = document.createElement('div');
  topBand.className = 'danmu-track-band danmu-track-band-top';
  topBand.style.top = '0px';
  topBand.style.height = `${Math.max(1, TRACK_TOP_MARGIN * scale)}px`;
  topBand.title = t('dynamic.settingsDanmuPreview.顶部安全边距_TRACK_TOP_MARGI', { margin: TRACK_TOP_MARGIN });
  bandsEl.appendChild(topBand);

  // 底部安全边距带(在 drawable 底部)
  const bottomBandTop = drawableH - TRACK_BOTTOM_MARGIN;
  if (bottomBandTop > TRACK_TOP_MARGIN) {
    const bottomBand = document.createElement('div');
    bottomBand.className = 'danmu-track-band danmu-track-band-bottom';
    bottomBand.style.top = `${bottomBandTop * scale}px`;
    bottomBand.style.height = `${Math.max(1, TRACK_BOTTOM_MARGIN * scale)}px`;
    bottomBand.title = t('dynamic.settingsDanmuPreview.底部安全边距_TRACK_BOTTOM_MA', { margin: TRACK_BOTTOM_MARGIN });
    bandsEl.appendChild(bottomBand);
  }

  // 轨道分隔线
  const linesRequested = getNumber('danmu_lines', 20);
  let y = TRACK_TOP_MARGIN;
  let drawn = 0;
  const maxY = drawableH - TRACK_BOTTOM_MARGIN - TRACK_LINE_HEIGHT;
  while (y <= maxY && drawn < linesRequested) {
    const line = document.createElement('div');
    line.className = 'danmu-track-line';
    line.style.top = `${y * scale}px`;
    line.title = t('dynamic.settingsDanmuPreview.轨道_drawn_1_y_y', { trackNum: drawn + 1, y });
    bandsEl.appendChild(line);
    y += TRACK_LINE_HEIGHT;
    drawn += 1;
  }

  // 可绘制区边界标记
  const drawableMarker = document.createElement('div');
  drawableMarker.className = 'danmu-track-drawable-marker';
  drawableMarker.style.top = `${drawableH * scale}px`;
  drawableMarker.title = t('dynamic.settingsDanmuPreview.可绘制区底部_drawableH_px_l', { drawableH, layoutMode });
  bandsEl.appendChild(drawableMarker);
}

function tick() {
  const mode = getRenderMode();
  if (mode === 'scrolling') {
    renderTrackBands();
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
    'danmu_font_family',
    'danmu_font_bold',
    'danmu_font_color_selected',
    'danmu_font_color_weights',
    'danmu_font_color_mode',
    'danmu_lines',
    'layout_mode',
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

  const swatchContainer = document.getElementById('danmuFontColorSwatches');
  if (swatchContainer) {
    swatchContainer.addEventListener('click', refreshDanmuPreview);
  }
  document.querySelectorAll('input[name="danmu_font_color_mode_radio"]').forEach((r) => {
    r.addEventListener('change', refreshDanmuPreview);
  });
  const weightContainer = document.getElementById('danmuFontColorWeights');
  if (weightContainer) {
    weightContainer.addEventListener('input', refreshDanmuPreview);
  }

  if (previewTimer) clearInterval(previewTimer);
  previewTimer = setInterval(() => {
    const previewEl = document.getElementById('danmuStylePreview');
    if (!previewEl || previewEl.closest('[hidden]')) return;
    tick();
  }, 2500);
}
