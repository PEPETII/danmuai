const NORMAL_REPLY_COUNT_MIN = 1;
const NORMAL_REPLY_COUNT_MAX = 50;
const DEFAULT_NORMAL_REPLY_COUNT = 5;
const FLOATING_PANEL_NORMAL_REPLY_COUNT = 10;
const NORMAL_RECOGNITION_INTERVAL_SEC = 5;
const DEFAULT_FLOATING_PANEL_SPEED = '1';

/** 按 danmu_render_mode 回落的节奏/速度默认值（与 app/config_defaults.py 对齐） */
export const RENDER_MODE_DEFAULT_OVERRIDES = {
  scrolling: {
    normal_recognition_interval_sec: String(NORMAL_RECOGNITION_INTERVAL_SEC),
    normal_reply_count: String(DEFAULT_NORMAL_REPLY_COUNT),
    floating_panel_speed: DEFAULT_FLOATING_PANEL_SPEED,
  },
  floating_panel: {
    normal_recognition_interval_sec: String(NORMAL_RECOGNITION_INTERVAL_SEC),
    normal_reply_count: String(FLOATING_PANEL_NORMAL_REPLY_COUNT),
    floating_panel_speed: DEFAULT_FLOATING_PANEL_SPEED,
  },
};

const REPLY_COUNT_MIN = 2;
const REPLY_COUNT_MAX = 7;
const DANMU_MAX_CHARS_MIN = 5;
const DANMU_MAX_CHARS_MAX = 80;
const DEFAULT_DANMU_MAX_CHARS_ZH = 15;
const DEFAULT_DANMU_MAX_CHARS_EN = 40;

export const MASKED_API_KEY = '********';

/** 判断表单/API 中的掩码占位符（未修改的已保存 Key）。 */
export function isMaskedApiKey(value) {
  return value === MASKED_API_KEY;
}

export const CONFIG_FIELDS = [
  'api_endpoint', 'api_mode', 'model', 'temperature', 'max_tokens',
  'danmu_speed', 'danmu_lines', 'danmu_max_chars', 'dedup_threshold',
  'screen_index', 'layout_mode', 'opacity', 'font_size', 'hotkey',
  'eviction_mode', 'danmu_pending_entry_cap', 'danmu_track_retention_cap', 'reply_queue_max_items',
  'image_max_width', 'image_quality',
  'mic_window_sec', 'mic_input_device_id', 'mic_api_endpoint', 'mic_api_mode', 'mic_model',
  'normal_recognition_interval_sec', 'normal_reply_count',
  'danmu_render_mode',
  'bililive_dm_mode_enabled',
  'floating_panel_width',
  'floating_panel_max_items',
  'floating_panel_speed',
  'floating_panel_x_offset',
  'floating_panel_y_offset',
  'floating_panel_opacity',
  'floating_panel_font_size',
  'danmu_font_family',
  'floating_panel_font_family',
];

export const SETTINGS_RESTORE_GROUPS = {
  api: [
    'api_endpoint', 'api_mode', 'screen_index', 'model', 'temperature', 'max_tokens',
  ],
  mic: [
    'mic_window_sec', 'mic_input_device_id', 'mic_api_endpoint', 'mic_api_mode', 'mic_model',
  ],
  capture: [],
  danmu: [
    'normal_recognition_interval_sec', 'normal_reply_count', 'danmu_speed', 'danmu_lines',
    'danmu_max_chars', 'opacity', 'dedup_threshold', 'layout_mode', 'hotkey',
    'eviction_mode', 'danmu_pending_entry_cap', 'danmu_track_retention_cap', 'reply_queue_max_items',
    'danmu_render_mode', 'floating_panel_width', 'floating_panel_max_items',
    'floating_panel_speed', 'floating_panel_x_offset', 'floating_panel_y_offset',
    'floating_panel_opacity', 'floating_panel_font_size',
  ],
  'bililive-dm': ['bililive_dm_mode_enabled'],
  font: [
    'danmu_font_family', 'floating_panel_font_family',
    'font_size', 'floating_panel_font_size',
  ],
  rhythm: ['image_max_width', 'image_quality'],
  'danmu-read': [],
};

export const SETTINGS_RESTORE_CHECKBOXES = {
  api: [],
  mic: ['mic_mode_enabled', 'mic_use_visual_model'],
  capture: [],
  danmu: ['empty_accel'],
  'bililive-dm': ['bililive_dm_mode_enabled'],
  font: ['danmu_font_bold', 'floating_panel_font_bold'],
  rhythm: [],
};

let configDefaultsCache = null;

function clampNormalReplyCount(value, fallback = DEFAULT_NORMAL_REPLY_COUNT) {
  const n = parseInt(value, 10);
  if (Number.isNaN(n)) return fallback;
  return Math.max(NORMAL_REPLY_COUNT_MIN, Math.min(NORMAL_REPLY_COUNT_MAX, n));
}

function resolveDanmuMaxCharsPreview(lang = 'zh') {
  const el = document.getElementById('danmu_max_chars');
  const raw = parseInt(el?.value ?? '', 10);
  const fallback = lang === 'en' ? DEFAULT_DANMU_MAX_CHARS_EN : DEFAULT_DANMU_MAX_CHARS_ZH;
  const value = Number.isNaN(raw) || raw <= 0 ? fallback : raw;
  return Math.max(DANMU_MAX_CHARS_MIN, Math.min(value, DANMU_MAX_CHARS_MAX));
}

function buildNormalReplyContractPreviewZh(count, maxChars) {
  const total = clampNormalReplyCount(count, DEFAULT_NORMAL_REPLY_COUNT);
  const limit = maxChars ?? resolveDanmuMaxCharsPreview('zh');
  const examples = Array.from({ length: total }, (_, i) => `弹幕${i + 1}`);
  return (
    '直播弹幕评论员。只输出 JSON 字符串数组，无解释、无 Markdown。'
    + `固定 ${total} 条，每条≤${limit}字。`
    + `格式：["${examples.join('", "')}"]。`
  );
}

export function updateNormalBatchPreview() {
  const countEl = document.getElementById('normal_reply_count');
  if (!countEl) return;
  const barrageEnabled = document.getElementById('petBarrageModeEnabled')?.checked === true;
  const count = barrageEnabled ? 5 : clampNormalReplyCount(countEl.value, DEFAULT_NORMAL_REPLY_COUNT);
  countEl.value = String(count);
  const hint = document.getElementById('normalBatchTotalHint');
  if (hint) {
    hint.textContent = `每次固定 ${count} 条 · 保存后会同步到人格工坊的「输出契约」`;
  }
  const maxChars = resolveDanmuMaxCharsPreview('zh');
  const preview = buildNormalReplyContractPreviewZh(count, maxChars);
  const previewEl = document.getElementById('normalBatchContractPreview');
  if (previewEl) previewEl.textContent = preview;
  const contractEl = document.getElementById('personaContract');
  if (contractEl) contractEl.value = preview;
}

export function initNormalBatchControls() {
  ['normal_reply_count', 'normal_recognition_interval_sec', 'danmu_max_chars'].forEach((id) => {
    document.getElementById(id)?.addEventListener('input', updateNormalBatchPreview);
    document.getElementById(id)?.addEventListener('change', updateNormalBatchPreview);
  });
  updateNormalBatchPreview();
}

export function resolveRenderModeDefault(mode, key) {
  const normalized = mode === 'floating_panel' ? 'floating_panel' : 'scrolling';
  const overrides = RENDER_MODE_DEFAULT_OVERRIDES[normalized] || RENDER_MODE_DEFAULT_OVERRIDES.scrolling;
  if (overrides[key] !== undefined) return overrides[key];
  return undefined;
}

export function configDefaultValue(key, mode) {
  const resolvedMode = mode
    ?? document.getElementById('danmu_render_mode')?.value
    ?? 'scrolling';
  const modeDefault = resolveRenderModeDefault(resolvedMode, key);
  if (modeDefault !== undefined) return modeDefault;
  if (configDefaultsCache && configDefaultsCache[key] !== undefined && configDefaultsCache[key] !== '') {
    return String(configDefaultsCache[key]);
  }
  return '';
}

export function setConfigDefaultsCache(value) {
  configDefaultsCache = value;
}

export function getConfigDefaultsCache() {
  return configDefaultsCache;
}

export function allRestorableSettingKeys() {
  const keys = new Set();
  Object.values(SETTINGS_RESTORE_GROUPS).forEach((group) => {
    group.forEach((key) => keys.add(key));
  });
  Object.values(SETTINGS_RESTORE_CHECKBOXES).forEach((group) => {
    group.forEach((key) => keys.add(key));
  });
  return [...keys];
}

export function restorableKeysForScope(scope, activeSettingsTabId) {
  if (scope === 'all') return allRestorableSettingKeys();
  const fields = SETTINGS_RESTORE_GROUPS[activeSettingsTabId] || [];
  const checkboxes = SETTINGS_RESTORE_CHECKBOXES[activeSettingsTabId] || [];
  return [...fields, ...checkboxes];
}

export function clampReplyCount(value, fallback = 2) {
  const n = parseInt(value, 10);
  if (Number.isNaN(n)) return fallback;
  return Math.max(REPLY_COUNT_MIN, Math.min(REPLY_COUNT_MAX, n));
}

export function clampNormalIntervalSec(value, fallback = 5) {
  const n = parseInt(value, 10);
  if (Number.isNaN(n)) return fallback;
  return Math.max(1, Math.min(60, n));
}
