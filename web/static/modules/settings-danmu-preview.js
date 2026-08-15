/**
 * 弹幕样式预览 (W-PR-INTAKE-022 / W-FP-STYLEGEN-WEB-001)
 *
 * 纯前端预览：横向模式样式生成器内居中静态展示一条示例弹幕。
 * 从下到上浮动面板的堆积预览见 app-style-generator-page.js。
 */

const STATIC_PREVIEW_TEXT = '我喜欢你';

const PREVIEW_ROOT = {
  rootId: 'horizontalDanmuStylePreview',
  sampleId: 'horizontalDanmuPreviewSample',
};

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

function buildPreviewStyle() {
  const fontSize = getNumber('font_size', 24);
  const opacity = Math.max(0, Math.min(1, getNumber('opacity', 100) / 100));
  const fontFamily = getSelect('danmu_font_family', '');
  const bold = getChecked('danmu_font_bold');
  const color = resolvePreviewColor();

  return { fontSize, opacity, fontFamily, bold, color };
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
      let bestColor = selected[0];
      let bestWeight = -1;
      for (let i = 0; i < selected.length; i++) {
        if (weights[i] > bestWeight) {
          bestWeight = weights[i];
          bestColor = selected[i];
        }
      }
      return bestColor;
    }
  }
  return selected[0];
}

function renderStaticPreviewForRoot(root) {
  const sampleEl = document.getElementById(root.sampleId);
  if (!sampleEl) return;

  const style = buildPreviewStyle();
  sampleEl.textContent = STATIC_PREVIEW_TEXT;
  sampleEl.style.fontSize = `${style.fontSize}px`;
  sampleEl.style.opacity = String(style.opacity);
  sampleEl.style.fontWeight = style.bold ? 'bold' : 'normal';
  sampleEl.style.fontFamily = style.fontFamily || '';
  sampleEl.style.color = style.color;
  sampleEl.style.textShadow = '0 0 4px rgba(0,0,0,0.8)';
}

export function refreshDanmuPreview() {
  const previewEl = document.getElementById(PREVIEW_ROOT.rootId);
  if (!previewEl || previewEl.closest('[hidden]')) return;
  renderStaticPreviewForRoot(PREVIEW_ROOT);
}

function bindPreviewFieldListeners() {
  const fields = [
    'font_size',
    'opacity',
    'danmu_font_family',
    'danmu_font_bold',
    'danmu_font_color_selected',
    'danmu_font_color_weights',
    'danmu_font_color_mode',
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
  refreshDanmuPreview();
}
