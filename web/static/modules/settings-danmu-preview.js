/**
 * 弹幕样式预览 (W-PR-INTAKE-022 / W-FP-STYLEGEN-WEB-001)
 *
 * 纯前端预览：横向 scrolling 在样式生成器「横向模式」实时渲染。
 * 从下到上浮动面板的堆积预览见 app-style-generator-page.js。
 */

import { t } from './i18n.js';

const PREVIEW_TEXTS = [
  t('dynamic.settingsDanmuPreview.这波操作666'),
  t('dynamic.settingsDanmuPreview.哈哈哈哈哈太搞了'),
  t('dynamic.settingsDanmuPreview.主播好强'),
  t('dynamic.settingsDanmuPreview.前方高能预警'),
  'awsl',
];

const PREVIEW_ROOT = {
  rootId: 'horizontalDanmuStylePreview',
  trackId: 'horizontalDanmuPreviewTrack',
  bandsId: 'horizontalDanmuTrackBands',
  scrollingId: 'horizontalDanmuPreviewScrolling',
};

let previewTimer = null;
const previewIndices = new Map();
let configSnapshot = {};

export function updateDanmuPreviewSnapshot(cfg = {}) {
  if (!cfg || typeof cfg !== 'object') return;
  configSnapshot = { ...configSnapshot, ...cfg };
}

function getField(id) {
  return document.getElementById(id);
}

function getNumber(id, fallback) {
  const el = getField(id);
  if (el && el.value !== '') {
    const num = Number(el.value);
    if (!Number.isNaN(num)) return num;
  }
  const snap = configSnapshot[id];
  if (snap !== undefined && snap !== '') {
    const num = Number(snap);
    if (!Number.isNaN(num)) return num;
  }
  return fallback;
}

function getSelect(id, fallback) {
  const el = getField(id);
  if (el && el.value) return el.value;
  const snap = configSnapshot[id];
  if (snap !== undefined && snap !== null && String(snap) !== '') return String(snap);
  return fallback;
}

function getChecked(id) {
  const el = getField(id);
  if (el) return el.checked;
  const snap = configSnapshot[id];
  if (snap === '1' || snap === 'true' || snap === true) return true;
  if (snap === '0' || snap === 'false' || snap === false) return false;
  return false;
}

function getRenderMode() {
  return getSelect('danmu_render_mode', 'scrolling');
}

function buildScrollingStyle() {
  const speed = getNumber('danmu_speed', 3);
  const fontSize = getNumber('font_size', 24);
  const opacity = Math.max(0, Math.min(1, getNumber('opacity', 100) / 100));
  const fontFamily = getSelect('danmu_font_family', '');
  const bold = getChecked('danmu_font_bold');
  const color = resolvePreviewColor();

  return { speed, fontSize, opacity, fontFamily, bold, color };
}

function resolvePreviewColor() {
  const rawSelected = getField('danmu_font_color_selected')?.value
    ?? configSnapshot.danmu_font_color_selected
    ?? '["#FFFFFF"]';
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

  const mode = getField('danmu_font_color_mode')?.value
    ?? configSnapshot.danmu_font_color_mode
    ?? 'equal';
  if (mode === 'weighted') {
    const rawWeights = getField('danmu_font_color_weights')?.value
      ?? configSnapshot.danmu_font_color_weights
      ?? '{}';
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

function renderScrollingPreviewForRoot(root) {
  const track = document.getElementById(root.trackId);
  if (!track) return;

  const style = buildScrollingStyle();
  track.innerHTML = '';

  const idx = previewIndices.get(root.rootId) ?? 0;
  const text = PREVIEW_TEXTS[idx % PREVIEW_TEXTS.length];
  previewIndices.set(root.rootId, idx + 1);

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

const TRACK_TOP_MARGIN = 50;
const TRACK_BOTTOM_MARGIN = 80;
const TRACK_LINE_HEIGHT = 40;
const LAYOUT_MODE_RATIOS = {
  fullscreen: 1.0,
  '3/4': 0.75,
  '1/2': 0.5,
  '1/4': 0.25,
};

function renderTrackBandsForRoot(root) {
  const bandsEl = document.getElementById(root.bandsId);
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
  const previewH = 120;
  const refScreenH = 1080;
  const drawableH = refScreenH * ratio;
  const scale = previewH / refScreenH;

  const topBand = document.createElement('div');
  topBand.className = 'danmu-track-band danmu-track-band-top';
  topBand.style.top = '0px';
  topBand.style.height = `${Math.max(1, TRACK_TOP_MARGIN * scale)}px`;
  topBand.title = t('dynamic.settingsDanmuPreview.顶部安全边距_TRACK_TOP_MARGI', { margin: TRACK_TOP_MARGIN });
  bandsEl.appendChild(topBand);

  const bottomBandTop = drawableH - TRACK_BOTTOM_MARGIN;
  if (bottomBandTop > TRACK_TOP_MARGIN) {
    const bottomBand = document.createElement('div');
    bottomBand.className = 'danmu-track-band danmu-track-band-bottom';
    bottomBand.style.top = `${bottomBandTop * scale}px`;
    bottomBand.style.height = `${Math.max(1, TRACK_BOTTOM_MARGIN * scale)}px`;
    bottomBand.title = t('dynamic.settingsDanmuPreview.底部安全边距_TRACK_BOTTOM_MA', { margin: TRACK_BOTTOM_MARGIN });
    bandsEl.appendChild(bottomBand);
  }

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

  const drawableMarker = document.createElement('div');
  drawableMarker.className = 'danmu-track-drawable-marker';
  drawableMarker.style.top = `${drawableH * scale}px`;
  drawableMarker.title = t('dynamic.settingsDanmuPreview.可绘制区底部_drawableH_px_l', { drawableH, layoutMode });
  bandsEl.appendChild(drawableMarker);
}

function tickRoot(root) {
  const previewEl = document.getElementById(root.rootId);
  if (!previewEl || previewEl.closest('[hidden]')) return;
  if (getRenderMode() !== 'scrolling') return;
  renderTrackBandsForRoot(root);
  renderScrollingPreviewForRoot(root);
}

function tick() {
  tickRoot(PREVIEW_ROOT);
}

export function refreshDanmuPreview() {
  tick();
}

function bindPreviewFieldListeners() {
  const fields = [
    'danmu_render_mode',
    'danmu_speed',
    'font_size',
    'opacity',
    'danmu_font_family',
    'danmu_font_bold',
    'danmu_font_color_selected',
    'danmu_font_color_weights',
    'danmu_font_color_mode',
    'danmu_lines',
    'layout_mode',
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
}

export function initDanmuPreview() {
  if (!document.getElementById(PREVIEW_ROOT.rootId)) return;

  bindPreviewFieldListeners();

  if (previewTimer) clearInterval(previewTimer);
  previewTimer = setInterval(tick, 2500);
}
