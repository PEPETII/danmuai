export const STYLE_PRESET_CAPABILITIES = {
  classic: {
    bubble: false,
    tail: false,
    radius: false,
    padding: false,
    shadow: false,
    border: false,
    shape: false,
    layout: false,
  },
  blivechat_line: {
    bubble: true,
    tail: true,
    radius: true,
    padding: true,
    shadow: true,
    border: true,
    shape: true,
    layout: true,
  },
};

const DEFAULT_STYLE_CAPABILITIES = STYLE_PRESET_CAPABILITIES.blivechat_line;

export function isStyleWeightBold(weight) {
  const n = Number(weight);
  return Number.isFinite(n) && n >= 600;
}

/** 保存时从权威字段派生遗留配置键，保持 API/预览兼容。 */
export function applyDerivedLegacyStyleFields(data) {
  if (!data || typeof data !== 'object') return data;
  const contentSize = parseInt(String(data.floating_panel_content_size ?? ''), 10);
  const size = Number.isFinite(contentSize) ? contentSize : 16;
  data.floating_panel_font_size = String(Math.max(12, Math.min(48, size)));

  const bold = isStyleWeightBold(data.floating_panel_content_weight)
    || isStyleWeightBold(data.floating_panel_username_weight);
  data.floating_panel_font_bold = bold ? '1' : '0';

  const tailW = parseInt(String(data.floating_panel_tail_width ?? ''), 10);
  const tailH = parseInt(String(data.floating_panel_tail_height ?? ''), 10);
  const tw = Number.isFinite(tailW) ? tailW : 0;
  const th = Number.isFinite(tailH) ? tailH : 0;
  data.floating_panel_tail_size = String(Math.max(0, Math.min(32, Math.max(tw, th))));
  return data;
}

export function resolveBasePresetId(configuredPreset, presets) {
  if (configuredPreset === 'classic') return 'classic';
  if (configuredPreset === 'blivechat_line') return 'blivechat_line';
  return presets?.presets?.blivechat_line ? 'blivechat_line' : 'classic';
}

/** 将 preset 解析为当前基础样式的能力表；只控制 UI 可见性。 */
export function resolvePresetCapabilities(preset, activePresetId = 'blivechat_line') {
  if (preset === 'custom_css') {
    return { customCssMode: true };
  }
  const baseId = preset === 'classic' || preset === 'blivechat_line'
    ? preset
    : activePresetId;
  return STYLE_PRESET_CAPABILITIES[baseId] || DEFAULT_STYLE_CAPABILITIES;
}
