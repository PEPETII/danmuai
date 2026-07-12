import { API } from './transport.js';
import { getLanguage, t } from './i18n.js';
import {
  guessProviderIdFromEndpoint,
  resolveMicProviderIdForPicker,
  resolveProviderIdForPicker,
} from './settings-providers.js';

const VISION_MODEL_CUSTOM_VALUE = '__custom__';
const MIC_MODEL_CUSTOM_VALUE = '__mic_custom__';

let catalogDeps = {
  updateMicModeHint: () => {},
  onCatalogLoadFailed: () => {},
  onVisionModelChanged: () => {},
};

let catalogCache = { platforms: [] };
let catalogLoadFailureLogged = false;
let floatingTooltipEl = null;
let floatingTooltipDismissBound = false;

export function configureSettingsModelCatalog(deps) {
  catalogDeps = { ...catalogDeps, ...deps };
}

export async function loadModelCatalog() {
  try {
    const res = await fetch(`${API.base}/api/model-catalog`);
    if (!res.ok) {
      throw new Error(`HTTP ${res.status}`);
    }
    catalogCache = await res.json();
  } catch (error) {
    catalogCache = { platforms: [] };
    if (!catalogLoadFailureLogged) {
      catalogLoadFailureLogged = true;
      console.warn('loadModelCatalog failed; using empty catalog fallback', error);
      catalogDeps.onCatalogLoadFailed(error);
    }
  }
  if (!catalogCache.platforms) catalogCache.platforms = [];
}

function getVisibleCatalogPlatforms() {
  const platforms = catalogCache.platforms || [];
  const lang = getLanguage();
  if (lang === 'en') {
    return platforms.filter((platform) => platform.region === 'international' || platform.region === 'global');
  }
  if (lang === 'zh') {
    return platforms.filter((platform) => platform.region === 'china' || platform.region === 'global');
  }
  return platforms;
}

function resolveCatalogPlatform(providerId) {
  if (!providerId) return null;
  return getVisibleCatalogPlatforms().find((platform) => platform.provider_id === providerId) || null;
}

function resolveFullCatalogPlatform(providerId) {
  if (!providerId) return null;
  return catalogCache.platforms.find((platform) => platform.provider_id === providerId) || null;
}

export function catalogModelSupportsMic(modelId) {
  const id = (modelId || '').trim();
  if (!id) return false;
  for (const platform of catalogCache.platforms || []) {
    const hit = (platform.models || []).find((model) => model.id === id);
    if (hit) return Boolean(hit.supports_mic);
  }
  return false;
}

export function catalogModelSupportsThinkingToggle(modelId) {
  const id = (modelId || '').trim();
  if (!id) return false;
  for (const platform of catalogCache.platforms || []) {
    const hit = (platform.models || []).find((model) => model.id === id);
    if (hit) return Boolean(hit.supports_thinking_toggle);
  }
  return false;
}

export function pickDefaultCatalogModelId(providerId) {
  const platform = resolveCatalogPlatform(providerId);
  if (!platform?.models?.length) return '';
  const preferred = platform.default_model_id;
  if (preferred && platform.models.some((model) => model.id === preferred)) {
    return preferred;
  }
  const cheapest = platform.models.find((model) => model.cheapest);
  return (cheapest || platform.models[0]).id;
}

function formatTokenPrice(value, currency = 'CNY') {
  if (value === null || value === undefined) return '-';
  const num = Number(value);
  if (Number.isNaN(num)) return '-';
  const isUsd = String(currency || 'CNY').toUpperCase() === 'USD';
  const unit = isUsd ? 'USD' : t('settings.text.modelCatalogCurrencyUnit');
  return `${Number.isInteger(num) ? String(num) : String(num)} ${unit} / M tokens`;
}

function buildModelRowBadges(model) {
  const wrap = document.createElement('span');
  wrap.className = 'vision-model-badges shrink-0';
  const add = (text) => {
    const badge = document.createElement('span');
    badge.className = 'vision-model-badge';
    badge.textContent = text;
    wrap.appendChild(badge);
  };
  if (model.cheapest && model.supports_mic) {
    add(t('dynamic.settingsModelCatalog.最便宜_麦克风'));
    return wrap;
  }
  if (model.cheapest) add(t('dynamic.settingsModelCatalog.本平台最便宜'));
  if (model.supports_mic) add(t('dynamic.settingsCustomModels.支持麦克风'));
  return wrap.childElementCount ? wrap : null;
}

function buildModelTooltipHtml(model) {
  const price = model.price || {};
  return (
    t('dynamic.settingsModelCatalog.span_class_model_toolt')
    + t('dynamic.settingsModelCatalog.span_class_model_toolt_2')
    + t('dynamic.settingsModelCatalog.span_class_model_toolt_3')
    + t('dynamic.settingsModelCatalog.span_class_model_toolt_4')
    + t('dynamic.settingsModelCatalog.span_class_model_toolt_5')
  );
}

function ensureFloatingTooltip() {
  if (!floatingTooltipEl) {
    floatingTooltipEl = document.createElement('div');
    floatingTooltipEl.id = 'uiTooltipFloat';
    floatingTooltipEl.className = 'ui-tooltip-float';
    floatingTooltipEl.setAttribute('role', 'tooltip');
    document.body.appendChild(floatingTooltipEl);
  }
  return floatingTooltipEl;
}

export function hideFloatingTooltip() {
  if (!floatingTooltipEl) return;
  floatingTooltipEl.style.display = 'none';
  floatingTooltipEl.style.visibility = '';
  floatingTooltipEl.classList.remove('ui-tooltip-float--wide');
}

function bindFloatingTooltipDismiss() {
  if (floatingTooltipDismissBound) return;
  floatingTooltipDismissBound = true;
  const hide = () => hideFloatingTooltip();
  window.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
  document.getElementById('settingsForm')?.addEventListener('scroll', hide, true);
}

function positionFloatingTooltip(anchor) {
  const tip = ensureFloatingTooltip();
  tip.style.visibility = 'hidden';
  tip.style.display = 'block';
  const anchorRect = anchor.getBoundingClientRect();
  const tipRect = tip.getBoundingClientRect();
  const margin = 10;
  let top = anchorRect.bottom + margin;
  let left = anchorRect.left + anchorRect.width / 2 - tipRect.width / 2;
  if (top + tipRect.height > window.innerHeight - margin) {
    top = anchorRect.top - tipRect.height - margin;
  }
  left = Math.max(margin, Math.min(left, window.innerWidth - tipRect.width - margin));
  top = Math.max(margin, Math.min(top, window.innerHeight - tipRect.height - margin));
  tip.style.top = `${Math.round(top)}px`;
  tip.style.left = `${Math.round(left)}px`;
  tip.style.visibility = 'visible';
}

export function showFloatingTooltip(anchor, content, options = {}) {
  bindFloatingTooltipDismiss();
  const { html = false, wide = false, tipId = '' } = options;
  const tip = ensureFloatingTooltip();
  tip.classList.toggle('ui-tooltip-float--wide', Boolean(wide));
  if (tipId) tip.id = tipId;
  else tip.removeAttribute('id');
  if (html) tip.innerHTML = content;
  else tip.textContent = content;
  positionFloatingTooltip(anchor);
}

export function wireFloatingTooltipButton(btn, onShow) {
  btn.addEventListener('click', (e) => e.preventDefault());
  btn.addEventListener('mouseenter', onShow);
  btn.addEventListener('mouseleave', hideFloatingTooltip);
  btn.addEventListener('focus', onShow);
  btn.addEventListener('blur', hideFloatingTooltip);
}

function createModelPriceHint(model) {
  const wrap = document.createElement('span');
  wrap.className = 'field-hint-wrap relative shrink-0';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'field-hint-btn';
  btn.setAttribute('aria-label', t('dynamic.settingsModelCatalog.查看_model_id_的价格说明'));
  btn.innerHTML = '<svg class="ui-icon" aria-hidden="true"><use href="#i-info"></use></svg>';
  wireFloatingTooltipButton(btn, () => {
    showFloatingTooltip(btn, buildModelTooltipHtml(model), { html: true, wide: true });
  });
  wrap.append(btn);
  return wrap;
}

function appendVisionModelRowMeta(row, model) {
  const badges = buildModelRowBadges(model);
  if (badges) row.appendChild(badges);
  row.appendChild(createModelPriceHint(model));
}

function setVisionModelValue(modelId) {
  const hidden = document.getElementById('model');
  if (hidden) hidden.value = modelId || '';
  catalogDeps.updateMicModeHint();
  catalogDeps.onVisionModelChanged();
}

export function syncVisionModelToHidden() {
  const customWrap = document.getElementById('visionModelCustom');
  const customInput = document.getElementById('modelCustom');
  const checked = document.querySelector('input[name="vision_model_choice"]:checked');
  if (checked?.value === VISION_MODEL_CUSTOM_VALUE) {
    setVisionModelValue(customInput?.value?.trim() || '');
    return;
  }
  if (checked) {
    setVisionModelValue(checked.value);
    return;
  }
  if (customWrap && !customWrap.classList.contains('hidden') && customInput) {
    setVisionModelValue(customInput.value.trim());
  }
}

function showVisionModelCustom(show, initialValue = '') {
  const wrap = document.getElementById('visionModelCustom');
  const input = document.getElementById('modelCustom');
  if (!wrap || !input) return;
  if (show) {
    wrap.classList.remove('hidden');
    if (initialValue !== undefined && initialValue !== null) input.value = initialValue;
    input.oninput = () => setVisionModelValue(input.value.trim());
  } else {
    wrap.classList.add('hidden');
    input.oninput = null;
  }
}

function setVisionModelPickerVisible(visible) {
  const picker = document.getElementById('visionModelPicker');
  if (!picker) return;
  picker.classList.toggle('hidden', !visible);
}

export function renderVisionModelPicker(providerId, selectedModelId, options = {}) {
  const picker = document.getElementById('visionModelPicker');
  if (!picker) return;

  const { providerSwitch = false } = options;
  const platform = resolveCatalogPlatform(providerId);
  if (!platform || !platform.models?.length) {
    picker.innerHTML = '';
    setVisionModelPickerVisible(false);
    const customInitial = providerSwitch ? '' : (selectedModelId || '');
    showVisionModelCustom(true, customInitial);
    setVisionModelValue(customInitial);
    return;
  }

  setVisionModelPickerVisible(true);
  picker.innerHTML = '';
  const knownIds = new Set(platform.models.map((model) => model.id));
  const defaultId = pickDefaultCatalogModelId(providerId);
  let selected;
  let useCustom;
  if (providerSwitch) {
    selected = defaultId || platform.models[0].id;
    useCustom = false;
  } else {
    selected = selectedModelId && knownIds.has(selectedModelId)
      ? selectedModelId
      : (defaultId || platform.models[0].id);
    useCustom = Boolean(selectedModelId && !knownIds.has(selectedModelId));
  }

  platform.models.forEach((model) => {
    const row = document.createElement('label');
    row.className = 'vision-model-row';
    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = 'vision_model_choice';
    radio.value = model.id;
    radio.checked = !useCustom && model.id === selected;
    radio.addEventListener('change', () => {
      if (radio.checked) {
        showVisionModelCustom(false);
        setVisionModelValue(model.id);
      }
    });

    const textWrap = document.createElement('span');
    textWrap.className = 'vision-model-id flex flex-col min-w-0';
    const nameSpan = document.createElement('span');
    nameSpan.className = 'font-semibold text-warmText truncate';
    nameSpan.textContent = model.name || model.id;
    const idSpan = document.createElement('span');
    idSpan.className = 'text-xs text-gray-400 truncate';
    idSpan.textContent = model.id;
    textWrap.append(nameSpan, idSpan);

    row.append(radio, textWrap);
    appendVisionModelRowMeta(row, model);
    picker.appendChild(row);
  });

  const otherRow = document.createElement('label');
  otherRow.className = 'vision-model-row';
  const otherRadio = document.createElement('input');
  otherRadio.type = 'radio';
  otherRadio.name = 'vision_model_choice';
  otherRadio.value = VISION_MODEL_CUSTOM_VALUE;
  otherRadio.checked = useCustom;
  otherRadio.addEventListener('change', () => {
    const current = document.getElementById('model')?.value || '';
    showVisionModelCustom(true, useCustom ? (selectedModelId || current) : '');
    syncVisionModelToHidden();
  });
  const otherLabel = document.createElement('span');
  otherLabel.className = 'vision-model-id';
  otherLabel.textContent = t('dynamic.settingsModelCatalog.手动输入模型_ID');
  otherRow.append(otherRadio, otherLabel);
  picker.appendChild(otherRow);

  if (useCustom) {
    showVisionModelCustom(true, selectedModelId);
  } else {
    setVisionModelValue(selected);
  }
}

export function syncVisionModelPickerFromForm(selectedModelId) {
  renderVisionModelPicker(resolveProviderIdForPicker(), selectedModelId || '');
}

export function pickDefaultMicCatalogModelId(providerId) {
  const platform = resolveCatalogPlatform(providerId);
  if (!platform?.models?.length) return '';
  const micModel = platform.models.find((model) => model.supports_mic);
  return micModel ? micModel.id : '';
}

function setMicModelValue(modelId) {
  const hidden = document.getElementById('mic_model');
  if (hidden) hidden.value = modelId || '';
  catalogDeps.updateMicModeHint();
}

export function syncMicModelToHidden() {
  const customWrap = document.getElementById('micModelCustom');
  const customInput = document.getElementById('micModelCustomInput');
  const checked = document.querySelector('input[name="mic_model_choice"]:checked');
  if (checked?.value === MIC_MODEL_CUSTOM_VALUE) {
    setMicModelValue(customInput?.value?.trim() || '');
    return;
  }
  if (checked) {
    setMicModelValue(checked.value);
    return;
  }
  if (customWrap && !customWrap.classList.contains('hidden') && customInput) {
    setMicModelValue(customInput.value.trim());
  }
}

function showMicModelCustom(show, initialValue = '') {
  const wrap = document.getElementById('micModelCustom');
  const input = document.getElementById('micModelCustomInput');
  if (!wrap || !input) return;
  if (show) {
    wrap.classList.remove('hidden');
    if (initialValue !== undefined && initialValue !== null) input.value = initialValue;
    input.oninput = () => setMicModelValue(input.value.trim());
  } else {
    wrap.classList.add('hidden');
    input.oninput = null;
  }
}

function setMicModelPickerVisible(visible) {
  const picker = document.getElementById('micModelPicker');
  if (!picker) return;
  picker.classList.toggle('hidden', !visible);
}

export function renderMicModelPicker(providerId, selectedModelId, options = {}) {
  const picker = document.getElementById('micModelPicker');
  if (!picker) return;

  const { providerSwitch = false } = options;
  const platform = resolveCatalogPlatform(providerId);
  const micModels = (platform?.models || []).filter((model) => model.supports_mic);
  if (!micModels.length) {
    picker.innerHTML = '';
    setMicModelPickerVisible(false);
    const customInitial = providerSwitch ? '' : (selectedModelId || '');
    showMicModelCustom(true, customInitial);
    setMicModelValue(customInitial);
    return;
  }

  setMicModelPickerVisible(true);
  picker.innerHTML = '';
  const knownIds = new Set(micModels.map((model) => model.id));
  const defaultId = pickDefaultMicCatalogModelId(providerId);
  let selected;
  let useCustom;
  if (providerSwitch) {
    selected = defaultId || micModels[0].id;
    useCustom = false;
  } else {
    selected = selectedModelId && knownIds.has(selectedModelId)
      ? selectedModelId
      : (defaultId || micModels[0].id);
    useCustom = Boolean(selectedModelId && !knownIds.has(selectedModelId));
  }

  micModels.forEach((model) => {
    const row = document.createElement('label');
    row.className = 'vision-model-row';
    const radio = document.createElement('input');
    radio.type = 'radio';
    radio.name = 'mic_model_choice';
    radio.value = model.id;
    radio.checked = !useCustom && model.id === selected;
    radio.addEventListener('change', () => {
      if (radio.checked) {
        showMicModelCustom(false);
        setMicModelValue(model.id);
      }
    });

    const textWrap = document.createElement('span');
    textWrap.className = 'vision-model-id flex flex-col min-w-0';
    const nameSpan = document.createElement('span');
    nameSpan.className = 'font-semibold text-warmText truncate';
    nameSpan.textContent = model.name || model.id;
    const idSpan = document.createElement('span');
    idSpan.className = 'text-xs text-gray-400 truncate';
    idSpan.textContent = model.id;
    textWrap.append(nameSpan, idSpan);

    row.append(radio, textWrap);
    appendVisionModelRowMeta(row, model);
    picker.appendChild(row);
  });

  const otherRow = document.createElement('label');
  otherRow.className = 'vision-model-row';
  const otherRadio = document.createElement('input');
  otherRadio.type = 'radio';
  otherRadio.name = 'mic_model_choice';
  otherRadio.value = MIC_MODEL_CUSTOM_VALUE;
  otherRadio.checked = useCustom;
  otherRadio.addEventListener('change', () => {
    const current = document.getElementById('mic_model')?.value || '';
    showMicModelCustom(true, useCustom ? (selectedModelId || current) : '');
    syncMicModelToHidden();
  });
  const otherLabel = document.createElement('span');
  otherLabel.className = 'vision-model-id';
  otherLabel.textContent = t('dynamic.settingsModelCatalog.手动输入模型_ID');
  otherRow.append(otherRadio, otherLabel);
  picker.appendChild(otherRow);

  if (useCustom) {
    showMicModelCustom(true, selectedModelId);
  } else {
    setMicModelValue(selected);
  }
}

export function syncMicModelPickerFromForm(selectedModelId) {
  renderMicModelPicker(resolveMicProviderIdForPicker(), selectedModelId || '');
}

export function evaluateMicAudioSupported({
  apiMode,
  modelId,
  endpoint,
  supportsMicDeclared = false,
  serverLikelySupported = false,
}) {
  const id = (modelId || '').trim();
  if (serverLikelySupported) return true;
  if (supportsMicDeclared) return true;
  if (catalogModelSupportsMic(id)) return true;
  const providerId = guessProviderIdFromEndpoint(endpoint, apiMode);
  if (apiMode === 'doubao' || providerId === 'doubao') {
    return catalogModelSupportsMic(id);
  }
  if (providerId === 'mimo') {
    return id === 'mimo-v2.5' && catalogModelSupportsMic(id);
  }
  return false;
}

export function getMicConfigProviderId(apiMode, modelId, endpoint, options = {}) {
  const providerId = guessProviderIdFromEndpoint(endpoint, apiMode);
  const micSupported = evaluateMicAudioSupported({
    apiMode,
    modelId,
    endpoint,
    supportsMicDeclared: options.supportsMicDeclared,
    serverLikelySupported: options.serverLikelySupported,
  });
  return { providerId, micSupported };
}

export function getModelCatalogPlatform(providerId) {
  return resolveFullCatalogPlatform(providerId);
}

export function getModelCatalogModels(providerId) {
  const platform = resolveFullCatalogPlatform(providerId);
  return platform?.models || [];
}

export function getModelNameFromCatalog(providerId, modelId) {
  const platform = resolveFullCatalogPlatform(providerId);
  if (!platform?.models) return '';
  const model = platform.models.find((m) => m.id === modelId);
  return model ? model.name : '';
}
