export const SG_SINGLE_COLOR_FIELDS = [
  'floating_panel_outline_color',
  'floating_panel_shadow_color',
  'floating_panel_border_color',
  'floating_panel_username_color',
];

export function normalizeHex(raw) {
  if (typeof raw !== 'string') return null;
  const s = raw.trim().toUpperCase();
  if (/^#[0-9A-F]{6}$/.test(s) || /^#[0-9A-F]{8}$/.test(s)) return s;
  return null;
}

/** native <input type="color"> only accepts #RRGGBB */
export function hexToColorInputValue(raw, fallback = '#FFFFFF') {
  const h = normalizeHex(raw);
  if (!h) {
    const fb = normalizeHex(fallback) || '#FFFFFF';
    return fb.slice(0, 7);
  }
  return h.slice(0, 7);
}

export function mergePickerRgbPreserveAlpha(pickerRgb, previousHex) {
  const rgb = hexToColorInputValue(pickerRgb, '#FFFFFF');
  const prev = normalizeHex(previousHex);
  if (prev && prev.length === 9) return `${rgb}${prev.slice(7, 9)}`;
  return rgb;
}

export function parsePalette(raw) {
  try {
    const arr = typeof raw === 'string' ? JSON.parse(raw || '[]') : raw;
    if (!Array.isArray(arr)) return [];
    return arr.map(normalizeHex).filter(Boolean);
  } catch {
    return [];
  }
}

export function parseWeights(raw) {
  try {
    const obj = typeof raw === 'string' ? JSON.parse(raw || '{}') : raw;
    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return {};
    const out = {};
    Object.entries(obj).forEach(([k, v]) => {
      const color = normalizeHex(k);
      const n = Number(v);
      if (color && Number.isFinite(n) && n >= 0) out[color] = n;
    });
    return out;
  } catch {
    return {};
  }
}

/** equal: colors[i % n]；weighted: 与 Qt overlay 相同 32-bit 哈希位 */
export function pickStyleColor(colors, mode, weights, styleIndex) {
  const list = Array.isArray(colors) ? colors.filter(Boolean) : [];
  if (!list.length) return '#FFFFFF';
  if (mode === 'weighted') {
    const wmap = weights || {};
    const pairs = list.map((c) => [c, Number(wmap[c]) > 0 ? Number(wmap[c]) : 0]);
    const total = pairs.reduce((s, [, w]) => s + w, 0);
    if (total > 0) {
      // Match floating_panel_overlay._pick_palette_color: (style_index * 2654435761) & 0xFFFFFFFF / 2^32
      let h = ((Number(styleIndex) || 0) * 2654435761) >>> 0;
      let r = (h / 4294967296) * total;
      for (const [c, w] of pairs) {
        r -= w;
        if (r <= 0) return c;
      }
      return pairs[pairs.length - 1][0];
    }
  }
  const idx = Math.abs(Number(styleIndex) || 0) % list.length;
  return list[idx];
}

export function hexToRgba(hex, alphaOverride) {
  const h = normalizeHex(hex) || '#FFFFFF';
  const r = parseInt(h.slice(1, 3), 16);
  const g = parseInt(h.slice(3, 5), 16);
  const b = parseInt(h.slice(5, 7), 16);
  let a = alphaOverride;
  if (a === undefined) {
    a = h.length === 9 ? parseInt(h.slice(7, 9), 16) / 255 : 1;
  }
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}
