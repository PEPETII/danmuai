/**
 * 模块：settings — 助手设置页（7 个 tab）+ 视觉模型选择 + 识图框选 + 压缩预览。
 *
 * 关键数据：
 *   - CONFIG_FIELDS：白名单字段表，决定 GET /api/config 与 PUT /api/config
 *     序列化时哪些 key 会被读写；新增字段必须先在此登记。
 *   - SETTINGS_RESTORE_GROUPS / SETTINGS_RESTORE_CHECKBOXES：助手设置
 *     「恢复默认」按 tab 分组；默认值唯一来源是 GET /api/config/defaults，
 *     勿在此硬编码。api_key 不参与恢复；识图区域走独立 API 不在此恢复。
 *
 * 数据流：
 *   collectFormData() 读 DOM → patch 对象 → 调 PUT /api/config（主线程回执）
 *   fillForm(config)   写 DOM ← GET /api/config 响应
 *   applyDefaultToField(field, value)  「恢复默认」逐字段归位
 *
 * 子模块挂载点（由 app.js init 顺序调用）：
 *   - initSettingsTabs / initSettingsUiMode：tab 切换 + 简化/全面模式
 *   - initSettingsFieldHints：每个字段的悬浮提示
 *   - initCaptureRegionControls：鼠标框选子区域（POST /api/capture-region）
 *   - initNormalBatchControls / initRestoreDefaultsControls：「正常批」与「恢复默认」
 *   - bindSettingsControls：保存按钮 + onConfigSaved 回调（让 app.js 在保存后
 *     拉取当前人格最新提示词）
 *
 * 兼容锚点：
 *   - “选「自定义」则需自己逐项设置” 文案已迁到 settings-hints.js，但保留此注释供静态回归断言定位。
 *
 * 线程模型：所有函数都在浏览器主线程运行；写操作 PUT /api/config 由
 * app/web_console.py 的 WebConsoleBridge 经主线程落库（详见 W-016）。
 */

import { API, apiFetch } from './transport.js';
import {
  applyCaptureRegionFromPayload,
  configureSettingsCaptureRegion,
  initCaptureRegionControls,
} from './settings-capture-region.js';
import {
  CONFIG_FIELDS,
  initNormalBatchControls,
  MASKED_API_KEY,
} from './settings-defaults.js';
import {
  collectFormData,
  configureSettingsCore,
  fillForm,
  initFloatingPanelV2Controls,
  initNumberFieldValidation,
  initOpacityWarning,
  initRestoreDefaultsControls,
  loadConfigDefaults,
  reloadConfigFromServer,
} from './settings-core.js';
import {
  closeModelModal,
  collectModelForm,
  configureSettingsCustomModels,
  customModelSupportsMic,
  loadCustomModels,
  openModelModal,
} from './settings-custom-models.js';
import {
  bindCompressPreviewControls,
  configureSettingsCompressPreview,
} from './settings-compress-preview.js';
import {
  bindFontControls,
  configureSettingsFonts,
} from './settings-fonts.js';
import {
  initContentPageFieldHints,
  initSettingsFieldHints,
  initSidebarNavFloatingHints,
} from './settings-hints.js';
import {
  catalogModelSupportsMic,
  configureSettingsModelCatalog,
  evaluateMicAudioSupported,
  loadModelCatalog,
  pickDefaultCatalogModelId as pickDefaultCatalogModelIdImpl,
  pickDefaultMicCatalogModelId as pickDefaultMicCatalogModelIdImpl,
  renderMicModelPicker as renderMicModelPickerImpl,
  renderVisionModelPicker as renderVisionModelPickerImpl,
  syncMicModelPickerFromForm as syncMicModelPickerFromFormImpl,
  syncMicModelToHidden as syncMicModelToHiddenImpl,
  syncVisionModelPickerFromForm as syncVisionModelPickerFromFormImpl,
  syncVisionModelToHidden as syncVisionModelToHiddenImpl,
} from './settings-model-catalog.js';
import {
  applyApiModeValue as applyApiModeValueImpl,
  applyMicProviderPreset as applyMicProviderPresetImpl,
  applyProviderPreset as applyProviderPresetImpl,
  configureSettingsProviders,
  guessProviderIdFromEndpoint,
  loadProviders,
  resolveProviderIdForPicker as resolveProviderIdForPickerImpl,
  syncApiModeLockState as syncApiModeLockStateImpl,
  syncMicProviderPresetFromEndpoint as syncMicProviderPresetFromEndpointImpl,
  syncProviderPresetFromEndpoint as syncProviderPresetFromEndpointImpl,
} from './settings-providers.js';
import {
  bindMicTestControls,
  configureSettingsMicTools,
} from './settings-mic-tools.js';
import {
  configureSettingsTabs,
  initSettingsTabs,
  initSettingsUiMode,
  switchSettingsTab,
} from './settings-tabs.js';
import { markProbeSuccess } from './app-setup-guide.js';
import { initDanmuPreview, refreshDanmuPreview } from './settings-danmu-preview.js';

export { MASKED_API_KEY } from './settings-defaults.js';
export { initNormalBatchControls } from './settings-defaults.js';
export {
  applyCaptureRegionFromPayload,
  initCaptureRegionControls,
} from './settings-capture-region.js';
export {
  collectFormData,
  fillForm,
  initFloatingPanelV2Controls,
  initOpacityWarning,
  initRestoreDefaultsControls,
  initNumberFieldValidation,
  loadConfigDefaults,
  reloadConfigFromServer,
} from './settings-core.js';
export { loadCustomModels } from './settings-custom-models.js';
export { loadFontFamilies, uploadFontFile } from './settings-fonts.js';
export {
  initContentPageFieldHints,
  initSettingsFieldHints,
  initSidebarNavFloatingHints,
} from './settings-hints.js';
export { loadModelCatalog } from './settings-model-catalog.js';
export { loadProviders } from './settings-providers.js';
export {
  getActiveSettingsTabId,
  initSettingsTabs,
  initSettingsUiMode,
  switchSettingsTab,
} from './settings-tabs.js';
let bindDeps = {
  showToast: () => {},
  navigate: () => {},
  onConfigSaved: null,
  onSettingsTabSwitch: null,
};

export function configureSettingsBindings(deps) {
  bindDeps = { ...bindDeps, ...deps };
  configureSettingsTabs({
    onSettingsTabSwitch: bindDeps.onSettingsTabSwitch,
  });
  configureSettingsCaptureRegion({
    showToast,
  });
  configureSettingsCompressPreview({
    showToast,
  });
  configureSettingsModelCatalog({
    updateMicModeHint,
    onCatalogLoadFailed: () => {
      showToast('模型目录加载失败，视觉模型列表可能为空，请刷新页面重试', true);
    },
  });
  configureSettingsMicTools({
    showToast,
  });
  configureSettingsProviders({
    showToast,
    pickDefaultCatalogModelId,
    renderVisionModelPicker,
    pickDefaultMicCatalogModelId,
    renderMicModelPicker,
    updateMicModeHint,
  });
  configureSettingsFonts({
    showToast,
  });
  configureSettingsCustomModels({
    showToast,
    reloadConfigFromServer,
    syncVisionModelPickerFromForm,
    updateModelActiveSourceBanner,
  });
  configureSettingsCore({
    showToast,
    loadCustomModels,
    applyCaptureRegionFromPayload,
    syncVisionModelToHidden,
    syncMicModelToHidden,
    syncProviderPresetFromEndpoint,
    applyApiModeValue,
    syncApiModeLockState,
    syncVisionModelPickerFromForm,
    syncMicProviderPresetFromEndpoint,
    syncMicModelPickerFromForm,
    populateMicInputDevices,
    applyMicIndependentVisibility,
    updateMicModeHint,
    updateModelActiveSourceBanner,
    updateMicActiveSourceBanner,
    setMicAudioLikelySupported: (value) => {
      micAudioLikelySupported = value;
    },
    refreshDanmuPreview,
  });
}

function showToast(msg, isError = false) {
  bindDeps.showToast(msg, isError);
}

function navigate(page) {
  bindDeps.navigate(page);
}

function pickDefaultCatalogModelId(providerId) {
  // platform.default_model_id 优先级逻辑已下沉到 settings-model-catalog.js。
  return pickDefaultCatalogModelIdImpl(providerId);
}

function pickDefaultMicCatalogModelId(providerId) {
  return pickDefaultMicCatalogModelIdImpl(providerId);
}

function renderVisionModelPicker(providerId, selectedModelId, options = {}) {
  return renderVisionModelPickerImpl(providerId, selectedModelId, options);
}

function renderMicModelPicker(providerId, selectedModelId, options = {}) {
  return renderMicModelPickerImpl(providerId, selectedModelId, options);
}

function syncVisionModelToHidden() {
  return syncVisionModelToHiddenImpl();
}

function syncVisionModelPickerFromForm(selectedModelId) {
  return syncVisionModelPickerFromFormImpl(selectedModelId);
}

function syncMicModelToHidden() {
  return syncMicModelToHiddenImpl();
}

function syncMicModelPickerFromForm(selectedModelId) {
  return syncMicModelPickerFromFormImpl(selectedModelId);
}

function syncProviderPresetFromEndpoint() {
  return syncProviderPresetFromEndpointImpl();
}

function applyApiModeValue(mode) {
  return applyApiModeValueImpl(mode);
}

function syncApiModeLockState() {
  return syncApiModeLockStateImpl();
}

function resolveProviderIdForPicker() {
  return resolveProviderIdForPickerImpl();
}

export function syncProviderPresetAfterEndpointEdit() {
  syncProviderPresetFromEndpoint();
  renderVisionModelPicker(resolveProviderIdForPicker(), document.getElementById('model')?.value || '');
}

function syncMicProviderPresetFromEndpoint() {
  return syncMicProviderPresetFromEndpointImpl();
}

export function applyProviderPreset(providerId) {
  // 兼容锚点：旧文件曾在此清空 api_key，并调用 renderVisionModelPicker(providerId, defaultModelId, { providerSwitch: true })。
  // apiKeyEl.value = '';
  return applyProviderPresetImpl(providerId);
}

function applyMicProviderPreset(providerId) {
  return applyMicProviderPresetImpl(providerId);
}

let micAudioLikelySupported = true;
let micDevicesCache = null;

function micInputDeviceSelectValue() {
  return document.getElementById('mic_input_device_id')?.value || '';
}

function currentMicDeviceContext() {
  const selectedValue = micInputDeviceSelectValue();
  const selectedId = selectedValue === '' ? null : Number.parseInt(selectedValue, 10);
  const devices = micDevicesCache?.devices || [];
  const selected = Number.isInteger(selectedId)
    ? devices.find((item) => item.id === selectedId)
    : null;
  return {
    selectedId: Number.isInteger(selectedId) ? selectedId : null,
    selectedLabel: selected?.name || '',
    defaultLabel: micDevicesCache?.default_input_device_label || '',
  };
}

function refreshMicInputDeviceHint() {
  const hint = document.getElementById('micInputDeviceHint');
  if (!hint) return;
  const { selectedId, selectedLabel, defaultLabel } = currentMicDeviceContext();
  if (selectedId === null) {
    hint.textContent = defaultLabel
      ? `当前将跟随 Windows 默认录音设备：${defaultLabel}`
      : '默认跟随 Windows 当前默认录音设备；也可以手动固定到某一只麦克风。';
    return;
  }
  hint.textContent = selectedLabel
    ? `当前固定使用：${selectedLabel}`
    : '当前已手动固定设备；如设备拔出，将在运行时回退到系统默认输入。';
}

export async function populateMicInputDevices(selectedValue = '', options = {}) {
  const { useConfigCurrentLabel = false } = options;
  const select = document.getElementById('mic_input_device_id');
  if (!select) return;
  try {
    micDevicesCache = await apiFetch('/api/mic/devices');
  } catch (_error) {
    micDevicesCache = { available: false, default_input_device_label: '', devices: [] };
  }
  const currentFallbackLabel = useConfigCurrentLabel
    ? document.getElementById('micActiveSourceBanner')?.dataset.defaultInputLabel || ''
    : '';
  const defaultLabel = micDevicesCache?.default_input_device_label || currentFallbackLabel || '未检测到默认输入';
  select.innerHTML = '';
  const follow = document.createElement('option');
  follow.value = '';
  follow.textContent = `跟随系统默认（当前：${defaultLabel}）`;
  select.appendChild(follow);
  (micDevicesCache?.devices || []).forEach((device) => {
    const opt = document.createElement('option');
    opt.value = String(device.id);
    opt.textContent = device.is_default ? `${device.name}（默认）` : device.name;
    select.appendChild(opt);
  });
  if ([...select.options].some((opt) => opt.value === String(selectedValue || ''))) {
    select.value = String(selectedValue || '');
  } else {
    select.value = '';
  }
  select.disabled = micDevicesCache?.available === false;
  refreshMicInputDeviceHint();
}

function isMicUseVisualModel() {
  return document.getElementById('mic_use_visual_model')?.checked !== false;
}

function applyMicIndependentVisibility() {
  const section = document.getElementById('micIndependentSection');
  if (!section) return;
  section.classList.toggle('hidden', isMicUseVisualModel());
}

function getMicConfigContext() {
  if (isMicUseVisualModel()) {
    return {
      apiMode: document.getElementById('api_mode')?.value || 'doubao',
      modelId: (document.getElementById('model')?.value || '').trim(),
      endpoint: document.getElementById('api_endpoint')?.value || '',
    };
  }
  return {
    apiMode: document.getElementById('mic_api_mode')?.value || 'doubao',
    modelId: (document.getElementById('mic_model')?.value || '').trim(),
    endpoint: document.getElementById('mic_api_endpoint')?.value || '',
  };
}

function micModeConfigSupported() {
  const { apiMode, modelId, endpoint } = getMicConfigContext();
  const supportsMicDeclared = isMicUseVisualModel()
    ? customModelSupportsMic(modelId)
    : false;
  return evaluateMicAudioSupported({
    apiMode,
    modelId,
    endpoint,
    supportsMicDeclared,
    serverLikelySupported: micAudioLikelySupported,
  });
}

export function updateMicActiveSourceBanner(cfg) {
  const banner = document.getElementById('micActiveSourceBanner');
  if (!banner) return;
  const micOn = document.getElementById('mic_mode_enabled')?.checked
    || cfg?.mic_mode_enabled === '1';
  if (!micOn) {
    banner.classList.add('hidden');
    banner.textContent = '';
    delete banner.dataset.defaultInputLabel;
    return;
  }
  const activeInputLabel = cfg?.active_input_device_label || '';
  const defaultInputLabel = cfg?.default_input || micDevicesCache?.default_input_device_label || '';
  if (defaultInputLabel) {
    banner.dataset.defaultInputLabel = defaultInputLabel;
  }
  const useVisual = document.getElementById('mic_use_visual_model')?.checked !== false
    && cfg?.mic_use_visual_model !== '0';
  const inputSuffix = activeInputLabel
    ? ` · 输入：${activeInputLabel}`
    : (defaultInputLabel ? ` · 默认输入：${defaultInputLabel}` : '');
  if (useVisual) {
    const usesCustom = cfg?.uses_custom_credentials === true;
    const modelId = (cfg?.active_model_id || cfg?.model || document.getElementById('model')?.value || '').trim();
    const endpoint = usesCustom
      ? (cfg?.custom_models || []).find((m) => m.modelId === modelId)?.endpoint
        || document.getElementById('api_endpoint')?.value
        || ''
      : (document.getElementById('api_endpoint')?.value || cfg?.api_endpoint || '');
    banner.textContent = `开麦使用识图模型：${modelId || '未选'} @ ${endpoint || '未配置'}${inputSuffix}`;
  } else {
    const modelId = (document.getElementById('mic_model')?.value || cfg?.mic_model || '').trim();
    const endpoint = document.getElementById('mic_api_endpoint')?.value || cfg?.mic_api_endpoint || '';
    banner.textContent = `开麦使用独立麦克风模型：${modelId || '未选'} @ ${endpoint || '未配置'}${inputSuffix}`;
  }
  if (cfg?.fallback_to_default) {
    banner.textContent += ` · 所选设备不可用，已回退到系统默认`;
  }
  banner.classList.remove('hidden');
  refreshMicInputDeviceHint();
}

export function updateMicModeHint() {
  const hint = document.getElementById('micModeHint');
  const micOn = document.getElementById('mic_mode_enabled')?.checked;
  if (!hint) return;
  if (!micOn) {
    hint.classList.add('hidden');
    hint.textContent = '';
    return;
  }
  const { apiMode, modelId, endpoint } = getMicConfigContext();
  const providerId = guessProviderIdFromEndpoint(endpoint, apiMode);
  const { selectedId, selectedLabel, defaultLabel } = currentMicDeviceContext();
  if (selectedId !== null && micDevicesCache?.available && !selectedLabel) {
    hint.classList.remove('hidden');
    hint.textContent = `麦克风输入设备不可用：已选择的设备当前不存在，运行时将回退到系统默认（${defaultLabel || '未检测到默认输入'}）。`;
    return;
  }
  if (micModeConfigSupported()) {
    hint.classList.add('hidden');
    hint.textContent = '';
    return;
  }
  hint.classList.remove('hidden');
  const prefix = '麦克风可能无法识别你的声音：';
  if (providerId === 'mimo') {
    hint.textContent = `${prefix}需使用 MiMo-V2.5（mimo-v2.5）。当前模型「${modelId || '未选'}」不支持开麦；请在麦克风标签改选 mimo-v2.5 或开启「与识图模型相同」，保存后再开始弹幕。`;
    return;
  }
  if (apiMode !== 'doubao' && providerId !== 'doubao') {
    hint.textContent = `${prefix}当前模型「${modelId || '未选'}」未声明 mic_audio 支持。请在模型配置档案中勾选「支持麦克风」，或改用豆包/MiMo，或在麦克风标签单独配置。`;
    return;
  }
  hint.textContent = `${prefix}当前模型「${modelId || '未选'}」可能听不懂麦克风。请改选带「支持麦克风」的模型（例如 doubao-seed-2-0-mini），保存后再开始弹幕。`;
}

function updateModelActiveSourceBanner(cfg) {
  const banner = document.getElementById('modelActiveSourceBanner');
  if (!banner) return;
  const usesCustom = cfg?.uses_custom_credentials === true;
  if (!usesCustom) {
    banner.classList.add('hidden');
    banner.textContent = '';
    return;
  }
  const name = cfg.model_display_name || cfg.active_model_id || '';
  const id = cfg.active_model_id || '';
  banner.textContent =
    `当前默认模型来自模型配置档案「${name}」（${id}）。助手设置中的 API 地址与密钥不用于生成弹幕，请在模型配置档案列表中维护。`;
  banner.classList.remove('hidden');
  if (cfg.provider_model_mismatch) {
    banner.textContent +=
      ' 另外：当前 API 地址与已选模型目录不一致，保存配置时可能被拒绝，请重新选择视觉模型。';
  }
}

export async function loadScreens() {
  const screens = await fetch(`${API.base}/api/screens`).then((r) => r.json());
  const sel = document.getElementById('screen_index');
  if (!sel) return;
  const current = sel.value;
  sel.innerHTML = '';
  screens.forEach((s) => {
    const opt = document.createElement('option');
    opt.value = String(s.index);
    opt.textContent = s.label;
    sel.appendChild(opt);
  });
  if (current !== '') sel.value = current;
  sel.disabled = screens.length <= 1;
}


export function bindSettingsControls(deps = {}) {
  configureSettingsBindings(deps);
  const { onConfigSaved } = bindDeps;

  document.getElementById('mic_mode_enabled')?.addEventListener('change', () => {
    updateMicModeHint();
    updateMicActiveSourceBanner({});
  });
  document.getElementById('mic_input_device_id')?.addEventListener('change', () => {
    refreshMicInputDeviceHint();
    updateMicModeHint();
    updateMicActiveSourceBanner({});
  });
  document.getElementById('mic_use_visual_model')?.addEventListener('change', () => {
    applyMicIndependentVisibility();
    updateMicModeHint();
    updateMicActiveSourceBanner({});
  });
  document.getElementById('micProviderPreset')?.addEventListener('change', (e) => {
    const id = e.target.value;
    if (id) applyMicProviderPreset(id);
    else syncMicProviderPresetFromEndpoint();
  });
  ['mic_api_endpoint', 'mic_api_mode'].forEach((id) => {
    document.getElementById(id)?.addEventListener('change', () => {
      syncMicProviderPresetFromEndpoint();
      syncMicModelPickerFromForm(document.getElementById('mic_model')?.value || '');
      updateMicModeHint();
      updateMicActiveSourceBanner({});
    });
    document.getElementById(id)?.addEventListener('input', () => {
      syncMicProviderPresetFromEndpoint();
      updateMicModeHint();
      updateMicActiveSourceBanner({});
    });
  });

  document.getElementById('settingsForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.submitter || document.activeElement;
    await window.withLoadingState(btn, btn?.textContent, async () => {
      try {
        await apiFetch('/api/config', { method: 'POST', body: JSON.stringify({ data: collectFormData() }) });
        const cfg = await reloadConfigFromServer();
        refreshDanmuPreview();
        // 同时保存 danmu-read 专用配置
        if (window.saveDanmuReadSettings) {
          await window.saveDanmuReadSettings();
        }
        const active = cfg.active_model_id || cfg.model || '';
        const label = cfg.model_display_name && cfg.model_display_name !== active
          ? `${cfg.model_display_name}（${active}）`
          : active;
        showToast(label ? `配置已保存，当前生效模型：${label}` : '配置已保存~');
        if (onConfigSaved) onConfigSaved();
        const keyInput = document.getElementById('api_key');
        if (keyInput?.value && keyInput.value !== MASKED_API_KEY) {
          keyInput.value = MASKED_API_KEY;
        }
        const micKeyInput = document.getElementById('mic_api_key');
        if (micKeyInput?.value && micKeyInput.value !== MASKED_API_KEY) {
          micKeyInput.value = MASKED_API_KEY;
        }
        const danmuReadKeyInput = document.getElementById('danmuReadApiKey');
        if (danmuReadKeyInput?.value && danmuReadKeyInput.value !== MASKED_API_KEY) {
          danmuReadKeyInput.value = MASKED_API_KEY;
        }
      } catch (err) {
        showToast(err.message || '保存时出了点小状况', true);
      }
    });
  });


  document.getElementById('btnProbe')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    await window.withLoadingState(btn, btn.textContent, async () => {
      const data = collectFormData();
      const keyField = (document.getElementById('api_key')?.value || '').trim();
      try {
        const res = await apiFetch('/api/probe', {
          method: 'POST',
          body: JSON.stringify({
            api_endpoint: data.api_endpoint,
            api_key: keyField === MASKED_API_KEY ? MASKED_API_KEY : (data.api_key || ''),
            model: data.model,
            api_mode: data.api_mode,
          }),
        });
        showToast(res.message || (res.ok ? '连接成功' : '连接失败'), !res.ok);
        if (res.ok) markProbeSuccess();
      } catch (err) {
        showToast(err.message || '网络连接似乎睡着了', true);
      }
    });
  });

  bindMicTestControls();

  document.getElementById('toggleKey')?.addEventListener('click', () => {
    const inp = document.getElementById('api_key');
    inp.type = inp.type === 'password' ? 'text' : 'password';
  });

  document.getElementById('toggleMicKey')?.addEventListener('click', () => {
    const inp = document.getElementById('mic_api_key');
    if (inp) inp.type = inp.type === 'password' ? 'text' : 'password';
  });

  bindCompressPreviewControls();

  document.getElementById('btnModelCancel')?.addEventListener('click', closeModelModal);

  document.getElementById('providerPreset')?.addEventListener('change', (e) => {
    if (e.target.value) applyProviderPreset(e.target.value);
    else syncProviderPresetAfterEndpointEdit();
  });

  document.getElementById('api_endpoint')?.addEventListener('change', () => {
    syncProviderPresetAfterEndpointEdit();
  });
  document.getElementById('api_mode')?.addEventListener('change', () => {
    syncProviderPresetAfterEndpointEdit();
    updateMicModeHint();
  });

  document.getElementById('modelModalForm')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = e.submitter || document.activeElement;
    await window.withLoadingState(btn, btn?.textContent, async () => {
      const index = parseInt(document.getElementById('modelEditIndex').value, 10);
      const body = collectModelForm();
      try {
        if (index >= 0) {
          await apiFetch(`/api/custom-models/${index}`, { method: 'PUT', body: JSON.stringify(body) });
        } else {
          await apiFetch('/api/custom-models', { method: 'POST', body: JSON.stringify(body) });
        }
        closeModelModal();
        showToast('模型已保存~');
        loadCustomModels();
      } catch (err) {
        showToast(err.message, true);
      }
    });
  });
  document.getElementById('btnModelProbe')?.addEventListener('click', async (e) => {
    const btn = e.currentTarget;
    await window.withLoadingState(btn, btn.textContent, async () => {
      try {
        const index = parseInt(document.getElementById('modelEditIndex')?.value || '-1', 10);
        const res = await apiFetch('/api/custom-models/probe', {
          method: 'POST',
          body: JSON.stringify({ ...collectModelForm(), index }),
        });
        showToast(res.message, !res.ok);
      } catch (err) {
        showToast(err.message, true);
      }
    });
  });

  bindFontControls();
  initDanmuPreview();
  initNumberFieldValidation();
}


