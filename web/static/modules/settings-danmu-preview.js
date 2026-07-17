/**
 * 弹幕样式预览 (W-PR-INTAKE-022 / W-FP-STYLEGEN-WEB-001)
 *
 * 纯前端预览：横向 scrolling 仍在本模块实时渲染。
 * 从下到上浮动面板的堆积预览已迁到 #style-generator（app-style-generator-page.js），
 * 本模块在 floating_panel 模式下仅切换入口提示，不再维护第二份简化堆积 DOM。
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
  }
  // floating_panel：仅展示入口（HTML 静态），不跑第二套堆积预览
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
    // 基础字体镜像字段仍监听（影响设置页展示；浮动堆积预览不在此实现）
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
    if (getRenderMode() !== 'scrolling') return;
    tick();
  }, 2500);
}
