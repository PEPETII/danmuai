import { apiFetch } from "./transport.js";
import { getLanguage, t } from "./i18n.js";
import { isMaskedApiKey, configDefaultValue, getConfigDefaultsCache } from "./settings-defaults.js";
import {
  findProvider,
  getProviderWebsite,
  isCustomProvider,
  getDefaultEndpoint,
  MODAL_PROVIDER_REGION_CHINA,
  MODAL_PROVIDER_REGION_INTERNATIONAL,
  inferModalProviderRegion,
  fillModelProviderSelect,
} from "./settings-providers.js";
import {
  getModelCatalogModels,
  getModelNameFromCatalog,
  pickDefaultCatalogModelId,
} from "./settings-model-catalog.js";
import {
  bindModelDefaultSelect,
  initModelApiKeyVisibility,
  resetModelApiKeyVisibility,
  syncModelDefaultSelect,
  syncModelModalUIState,
  setModelModalBusy,
  expandModelModalAdvanced,
} from "./settings-model-modal-state.js";
import {
  clearModelValidationErrors,
  validateModelForm,
} from "./settings-model-modal-validation.js";
import {
  abortModelProbe,
  initModelModalProbe,
  probeModelConnection,
} from "./settings-model-modal-probe.js";

let customModelDeps = {
  showToast: () => {},
  reloadConfigFromServer: async () => ({}),
  syncVisionModelPickerFromForm: () => {},
  updateModelActiveSourceBanner: () => {},
};

let cachedCustomModels = [];
let modelModalBindingsWired = false;

const MODEL_TEMPERATURE_MIN = 0;
const MODEL_TEMPERATURE_MAX = 2;
const MODEL_TEMPERATURE_DEFAULT = 0.8;

function coerceModelTemperature(value) {
  if (value === undefined || value === null || value === "") return null;
  const parsed = typeof value === "number" ? value : parseFloat(String(value));
  if (Number.isNaN(parsed)) return null;
  if (parsed < MODEL_TEMPERATURE_MIN) return MODEL_TEMPERATURE_MIN;
  if (parsed > MODEL_TEMPERATURE_MAX) return MODEL_TEMPERATURE_MAX;
  return parsed;
}

function resolveModelTemperatureFallback(existingValue) {
  const existing = coerceModelTemperature(existingValue);
  if (existing !== null) return existing;
  const cached = getConfigDefaultsCache()?.temperature;
  const fromCache = coerceModelTemperature(cached);
  if (fromCache !== null) return fromCache;
  const fallback = configDefaultValue("temperature");
  const fromDefault = coerceModelTemperature(fallback);
  if (fromDefault !== null) return fromDefault;
  return MODEL_TEMPERATURE_DEFAULT;
}

function parseModelTemperatureInput() {
  const raw = document.getElementById("modelTemperature")?.value;
  if (raw === undefined || raw === null || raw === "") {
    return MODEL_TEMPERATURE_DEFAULT;
  }
  const parsed = parseFloat(String(raw));
  if (Number.isNaN(parsed)) return MODEL_TEMPERATURE_DEFAULT;
  if (parsed < MODEL_TEMPERATURE_MIN) return MODEL_TEMPERATURE_MIN;
  if (parsed > MODEL_TEMPERATURE_MAX) return MODEL_TEMPERATURE_MAX;
  return parsed;
}

export function getCachedCustomModels() {
  return cachedCustomModels;
}

export function customModelSupportsMic(modelId) {
  const id = (modelId || "").trim();
  if (!id) return false;
  const hit = cachedCustomModels.find((model) => {
    const ids = Array.isArray(model.model_ids)
      ? model.model_ids.map((x) => String(x || "").trim())
      : [];
    const def = (model.default_model_id || "").trim();
    return ids.includes(id) || def === id;
  });
  return Boolean(hit?.supportsMic);
}

export function configureSettingsCustomModels(deps) {
  customModelDeps = { ...customModelDeps, ...deps };
}

/** 激活人格实际会用到的 model_id 集合（显式绑定 + 未绑定则用全局默认）。 */
function collectActivePersonaModelIds(personaeItems, globalDefaultModelId) {
  const used = new Set();
  const globalId = (globalDefaultModelId || "").trim();
  const items = Array.isArray(personaeItems) ? personaeItems : [];
  for (const item of items) {
    if (!item?.active) continue;
    const bound = (item.model_id || "").trim();
    if (bound) used.add(bound);
    else if (globalId) used.add(globalId);
  }
  return used;
}

function profileUsesAnyModelId(model, usedModelIds) {
  if (!usedModelIds || usedModelIds.size === 0) return false;
  const def = (model.default_model_id || "").trim();
  if (def && usedModelIds.has(def)) return true;
  const ids = Array.isArray(model.model_ids) ? model.model_ids : [];
  return ids.some((id) => {
    const mid = String(id || "").trim();
    return mid && usedModelIds.has(mid);
  });
}

export async function loadCustomModels() {
  if (!modelModalBindingsWired) {
    modelModalBindingsWired = true;
    try {
      initModelModalBindings();
    } catch (_e) {
      /* DOM not ready yet */
    }
  }
  const [data, personaeData] = await Promise.all([
    apiFetch("/api/custom-models"),
    apiFetch("/api/personae").catch(() => ({ items: [] })),
  ]);
  cachedCustomModels = data.items || [];
  const list = document.getElementById("customModelsList");
  if (!list) return;
  list.innerHTML = "";
  if (!data.items.length) {
    list.innerHTML = t("dynamic.settingsCustomModels.p_class_text_sm_text_g");
    return;
  }
  const usedByActivePersonae = collectActivePersonaModelIds(
    personaeData?.items,
    data.default_model_id,
  );
  data.items.forEach((model, index) => {
    const row = document.createElement("div");
    row.className =
      "custom-model-row flex flex-wrap items-center gap-3 p-3 bg-cream rounded-xl text-sm";
    const inUseByPersona = profileUsesAnyModelId(model, usedByActivePersonae);
    const isDefault = model.default_model_id === data.default_model_id;

    // 列 1：模型名 + provider chip
    const colName = document.createElement("div");
    colName.className = "flex items-center gap-2 min-w-0 flex-1";
    const nameSpan = document.createElement("span");
    nameSpan.className = "font-semibold text-warmText truncate";
    nameSpan.textContent = model.name || t("common.unnamed");
    colName.appendChild(nameSpan);
    const providerId = model.provider || "";
    const provider = providerId ? findProvider(providerId) : null;
    if (provider && provider.label) {
      const chip = document.createElement("span");
      chip.className =
        "custom-model-provider-chip px-2 py-0.5 rounded-full bg-softPeach text-warmText text-xs font-semibold";
      chip.textContent = provider.label;
      colName.appendChild(chip);
    }
    if (model.supportsMic) {
      const mic = document.createElement("span");
      mic.className = "text-sky-600 text-xs font-bold";
      mic.textContent = t("dynamic.settingsCustomModels.支持麦克风");
      colName.appendChild(mic);
    }
    if (model.complete === false) {
      const warn = document.createElement("span");
      warn.className = "text-amber-600 text-xs font-bold";
      warn.textContent = t("dynamic.settingsCustomModels.配置不完整");
      colName.appendChild(warn);
    }

    // 列 2：默认 modelId + 数组长度（+N 表示多 N 项）
    const colModelId = document.createElement("div");
    colModelId.className =
      "custom-model-id-col text-gray-500 text-xs whitespace-nowrap";
    const modelIds = Array.isArray(model.model_ids) ? model.model_ids : [];
    const defaultId = model.default_model_id || "";
    const extra = Math.max(0, modelIds.length - 1);
    const idSpan = document.createElement("span");
    idSpan.className = "font-mono";
    idSpan.textContent = defaultId;
    colModelId.appendChild(idSpan);
    if (extra > 0) {
      const extraSpan = document.createElement("span");
      extraSpan.className = "text-gray-400";
      extraSpan.textContent = ` (+${extra})`;
      colModelId.appendChild(extraSpan);
    }

    // 列 3：全局默认档案或有激活人格正在使用时显示非交互「使用中」徽章
    const colStatus = document.createElement("div");
    colStatus.className = "custom-model-status-col";
    if (isDefault || inUseByPersona) {
      const badge = document.createElement("span");
      badge.className =
        "custom-model-in-use-badge px-2 py-0.5 rounded-full bg-softPeach text-warmText text-xs font-bold";
      badge.textContent = t("dynamic.settingsCustomModels.使用_2");
      colStatus.appendChild(badge);
    }

    // 列 4：操作按钮组（编辑 / 删除）
    const colActions = document.createElement("div");
    colActions.className = "custom-model-actions flex items-center gap-2";
    const editBtn = document.createElement("button");
    editBtn.type = "button";
    editBtn.className = "px-3 py-1 border border-gray-200 rounded-lg text-xs";
    editBtn.textContent = t("common.edit");
    editBtn.onclick = () => openModelModal(index, model);
    const delBtn = document.createElement("button");
    delBtn.type = "button";
    delBtn.className =
      "px-3 py-1 border border-red-200 rounded-lg text-xs text-red-600";
    delBtn.textContent = t("common.delete");
    delBtn.onclick = () => openDeleteModelConfirm(model, index);
    colActions.appendChild(editBtn);
    colActions.appendChild(delBtn);

    row.appendChild(colName);
    row.appendChild(colModelId);
    row.appendChild(colStatus);
    row.appendChild(colActions);
    list.appendChild(row);
  });
}

import { activateFocusTrap, deactivateFocusTrap } from "./modal-focus-trap.js";

const TAG_MAX_LEN = 200;

function getTagInputState() {
  const container = document.getElementById("modelIdsTags");
  const input = document.getElementById("modelIdsInput");
  return { container, input };
}

function readTagChips() {
  const { container } = getTagInputState();
  if (!container) return [];
  return Array.from(container.querySelectorAll(".tag-chip[data-value]")).map(
    (chip) => ({
      value: chip.getAttribute("data-value") || "",
      isDefault: chip.hasAttribute("data-default"),
      el: chip,
    }),
  );
}

function getModelIdsFromChips() {
  return readTagChips()
    .map((c) => c.value)
    .filter(Boolean);
}

function getDefaultModelIdFromChips() {
  const chips = readTagChips();
  const def = chips.find((c) => c.isDefault);
  return def?.value || chips[0]?.value || "";
}

function markFirstChipDefault() {
  const chips = readTagChips();
  if (!chips.length) return;
  const hasDefault = chips.some((c) => c.isDefault);
  if (hasDefault) return;
  applyChipDefault(chips[0].el, true);
}

function applyChipDefault(chipEl, isDefault) {
  if (!chipEl) return;
  if (isDefault) {
    chipEl.setAttribute("data-default", "1");
  } else {
    chipEl.removeAttribute("data-default");
  }
  let mark = chipEl.querySelector(".tag-default-mark");
  if (isDefault && !mark) {
    mark = document.createElement("span");
    mark.className = "tag-default-mark";
    mark.textContent = t("common.defaultLabel");
    chipEl.insertBefore(mark, chipEl.querySelector(".tag-remove"));
  } else if (!isDefault && mark) {
    mark.remove();
  }
}

function renderTagChip(value, isDefault) {
  const chip = document.createElement("span");
  chip.className = "tag-chip";
  chip.setAttribute("data-value", value);
  if (isDefault) chip.setAttribute("data-default", "1");
  const label = document.createElement("span");
  label.textContent = value;
  chip.appendChild(label);
  if (isDefault) {
    const mark = document.createElement("span");
    mark.className = "tag-default-mark";
    mark.textContent = t("common.defaultLabel");
    chip.appendChild(mark);
  }
  const removeBtn = document.createElement("button");
  removeBtn.type = "button";
  removeBtn.className = "tag-remove";
  removeBtn.textContent = "×";
  removeBtn.setAttribute("aria-label", t("common.delete"));
  removeBtn.addEventListener("click", (e) => {
    e.stopPropagation();
    const wasDefault = chip.hasAttribute("data-default");
    chip.remove();
    if (wasDefault) markFirstChipDefault();
  });
  chip.addEventListener("click", () => {
    const chips = readTagChips();
    chips.forEach((c) => applyChipDefault(c.el, c.el === chip));
  });
  return chip;
}

function addTagChip(value) {
  const { container, input } = getTagInputState();
  if (!container || !input) return false;
  const trimmed = String(value || "").trim();
  if (!trimmed) return false;
  if (trimmed.length > TAG_MAX_LEN) {
    customModelDeps.showToast(
      t("dynamic.settingsCustomModels.模型_ID_长度超过_TAG_MAX_LEN", {
        maxLen: TAG_MAX_LEN,
      }),
      true,
    );
    return false;
  }
  const existing = getModelIdsFromChips();
  if (existing.some((id) => id === trimmed)) {
    const dup = container.querySelector(
      `.tag-chip[data-value="${CSS.escape(trimmed)}"]`,
    );
    if (dup) {
      dup.classList.add("error");
      setTimeout(() => dup.classList.remove("error"), 320);
    }
    return false;
  }
  const isFirst = existing.length === 0;
  const chip = renderTagChip(trimmed, isFirst);
  container.insertBefore(chip, input);
  input.value = "";
  syncModelDefaultSelect();
  return true;
}

function clearTagChips() {
  const { container } = getTagInputState();
  if (!container) return;
  container.querySelectorAll(".tag-chip").forEach((chip) => chip.remove());
}

function fillTagChips(modelIds, defaultModelId) {
  clearTagChips();
  const ids = Array.isArray(modelIds) ? modelIds : [];
  const defId = (defaultModelId || "").trim();
  ids.forEach((id) => {
    const value = String(id || "").trim();
    if (!value) return;
    const isDefault = defId ? value === defId : false;
    const chip = renderTagChip(value, isDefault);
    const { container, input } = getTagInputState();
    if (container && input) container.insertBefore(chip, input);
  });
  markFirstChipDefault();
}

function updateProviderWebsiteDisplay(providerId) {
  const nameEl = document.getElementById("modelProviderName");
  const webRow = document.getElementById("modelProviderWebsite");
  const webLink = document.getElementById("modelProviderWebsiteLink");
  const openBtn = document.getElementById("modelOpenWebsite");
  const migrationEl = document.getElementById("modelProviderMigrationWarning");
  const provider = findProvider(providerId);
  if (nameEl) {
    if (provider && provider.id) {
      nameEl.textContent = t(
        "dynamic.settingsCustomModels.当前预设_provider_label",
        {
          providerLabel: provider.label,
        },
      );
      nameEl.classList.remove("hidden");
    } else {
      nameEl.textContent = "";
      nameEl.classList.add("hidden");
    }
  }
  const website = getProviderWebsite(providerId);
  if (webRow && webLink && openBtn) {
    if (website) {
      webLink.textContent = website;
      webLink.href = website;
      openBtn.dataset.website = website;
      webRow.classList.remove("hidden");
    } else {
      webLink.textContent = "";
      webLink.href = "";
      delete openBtn.dataset.website;
      webRow.classList.add("hidden");
    }
  }
  if (migrationEl) {
    const status = String(provider?.lifecycle_status || "")
      .trim()
      .toLowerCase();
    const notice = String(provider?.notice || "").trim();
    const migrationUrl = String(provider?.migration_url || "").trim();
    const sunsetDate = String(provider?.sunset_date || "").trim();
    if (status === "migrating" || status === "legacy") {
      const parts = [];
      if (notice) {
        parts.push(notice);
      } else if (sunsetDate) {
        parts.push(
          getLanguage() === "en"
            ? `This provider is scheduled for shutdown on ${sunsetDate}.`
            : `该服务商计划于 ${sunsetDate} 停服。`,
        );
      }
      if (migrationUrl) {
        const linkLabel =
          getLanguage() === "en" ? "View migration notice" : "查看迁移公告";
        parts.push(
          `<a class="underline text-amber-900" href="${migrationUrl}" target="_blank" rel="noopener noreferrer">${linkLabel}</a>`,
        );
      }
      migrationEl.innerHTML = parts.join(" ");
      migrationEl.classList.remove("hidden");
    } else {
      migrationEl.textContent = "";
      migrationEl.classList.add("hidden");
    }
  }
}

const MODEL_ID_CUSTOM_VALUE = "__custom__";

/** 根据 provider 构建 #modelIdPreset 下拉选项 */
function buildModelIdPresetOptions(providerId) {
  const select = document.getElementById("modelIdPreset");
  if (!select) return;
  select.innerHTML = "";
  const models = getModelCatalogModels(providerId);
  models.forEach((m) => {
    const opt = document.createElement("option");
    opt.value = m.id;
    opt.textContent = `${m.name || m.id}`;
    select.appendChild(opt);
  });
  const customOpt = document.createElement("option");
  customOpt.value = MODEL_ID_CUSTOM_VALUE;
  customOpt.textContent = t("dynamic.settingsCustomModels.自定义配置");
  select.appendChild(customOpt);
  return models;
}

/** 编辑模式下按已有模型回填下拉选中状态 */
function syncModelIdPresetFromForm(modelIds, defaultModelId, providerId) {
  const select = document.getElementById("modelIdPreset");
  if (!select) return;
  const primaryId =
    (defaultModelId || "").trim() || (modelIds && modelIds[0]) || "";
  const models = getModelCatalogModels(providerId);
  const knownIds = new Set(models.map((m) => m.id));
  if (primaryId && knownIds.has(primaryId)) {
    select.value = primaryId;
  } else {
    select.value = MODEL_ID_CUSTOM_VALUE;
  }
}

/** 设置 chip 输入区的可见性和可用性 */
function setChipInputState(visible, disabled) {
  const wrap = document.getElementById("modelIdsTagsWrap");
  const input = document.getElementById("modelIdsInput");
  if (wrap) {
    if (visible) {
      wrap.classList.remove("hidden");
    } else {
      wrap.classList.add("hidden");
    }
  }
  if (input) {
    input.disabled = disabled;
    if (disabled) {
      input.placeholder = "";
    } else {
      input.placeholder = t(
        "dynamic.settingsCustomModels.例如_doubao_1_5_pro_32k_25",
      );
    }
  }
}

/** 设置 API 地址字段只读/可编辑状态 */
function setEndpointReadonly(readonly) {
  const el = document.getElementById("modelEndpoint");
  if (!el) return;
  if (readonly) {
    el.setAttribute("readonly", "");
    el.classList.add("bg-gray-100", "cursor-not-allowed");
  } else {
    el.removeAttribute("readonly");
    el.classList.remove("bg-gray-100", "cursor-not-allowed");
  }
}

/** 处理模型 ID 下拉变化 */
function onModelIdPresetChange() {
  const select = document.getElementById("modelIdPreset");
  if (!select) return;
  const value = select.value;
  const providerId = document.getElementById("modelProvider")?.value || "";

  if (value === MODEL_ID_CUSTOM_VALUE) {
    // 自定义配置：启用 chip 输入
    setChipInputState(true, false);
  } else {
    // 预设模型：保留选中 ID 供保存，但隐藏不可编辑的 chip 输入区
    clearTagChips();
    addTagChip(value);
    setChipInputState(false, true);

    // 新增模式下同步显示名称
    const editIndex = parseInt(
      document.getElementById("modelEditIndex")?.value || "-1",
      10,
    );
    if (editIndex < 0) {
      const modelName = getModelNameFromCatalog(providerId, value);
      const nameEl = document.getElementById("modelName");
      if (nameEl && modelName) {
        nameEl.value = modelName;
      }
    }
  }
}

/** 将存储的 mode（如 openai-compatible）映射为 #modelMode 下拉值 */
function modeToSelectValue(mode, providerId = "") {
  const raw = String(mode ?? "")
    .trim()
    .toLowerCase();
  if (raw === "doubao") return "doubao";
  if (
    raw === "openai" ||
    raw === "openai-compatible" ||
    raw === "openai_compatible"
  ) {
    return "openai";
  }
  if (providerId) {
    const provider = findProvider(providerId);
    if (provider?.mode) {
      return provider.mode === "openai-compatible" ? "openai" : provider.mode;
    }
  }
  return "openai";
}

/** 初始化模型弹窗「平台区域」下拉（文案随界面语言） */
function initModelProviderRegionSelect(preferredValue = MODAL_PROVIDER_REGION_CHINA) {
  const el = document.getElementById("modelProviderRegion");
  if (!el) return;
  const value = preferredValue || el.value || MODAL_PROVIDER_REGION_CHINA;
  el.innerHTML = "";
  [
    { value: MODAL_PROVIDER_REGION_CHINA, label: t("dynamic.settingsCustomModels.国内") },
    { value: MODAL_PROVIDER_REGION_INTERNATIONAL, label: t("dynamic.settingsCustomModels.国外") },
  ].forEach(({ value: optionValue, label }) => {
    const opt = document.createElement("option");
    opt.value = optionValue;
    opt.textContent = label;
    el.appendChild(opt);
  });
  el.value = value;
}

/** 切换平台区域：重建模型平台列表并联动刷新下游字段 */
function onModalProviderRegionChange() {
  const regionEl = document.getElementById("modelProviderRegion");
  const modalRegion = regionEl?.value || MODAL_PROVIDER_REGION_CHINA;
  const prevProviderId = document.getElementById("modelProvider")?.value || "";
  fillModelProviderSelect(modalRegion, prevProviderId);
  const providerId = document.getElementById("modelProvider")?.value || "";
  onProviderChangeInModal(providerId, { isEdit: false });
  syncModelModalUIState({
    providerId,
    isEdit: false,
    catalogModels: getModelCatalogModels(providerId),
    customProvider: isCustomProvider(providerId),
  });
}

/** 处理服务商切换联动 */
function onProviderChangeInModal(providerId, options = {}) {
  const { isEdit = false } = options;
  updateProviderWebsiteDisplay(providerId);

  // 联动 API 地址
  const endpointEl = document.getElementById("modelEndpoint");
  if (isCustomProvider(providerId)) {
    // 自定义服务商：API 地址可编辑
    if (!isEdit) {
      if (endpointEl) endpointEl.value = "";
    }
    setEndpointReadonly(false);
  } else {
    // 非自定义服务商：API 地址自动填入 + 只读
    const defaultEp = getDefaultEndpoint(providerId);
    if (endpointEl) endpointEl.value = defaultEp;
    setEndpointReadonly(true);
  }

  // 联动模型 ID 下拉
  buildModelIdPresetOptions(providerId);
  const models = getModelCatalogModels(providerId);

  if (isCustomProvider(providerId)) {
    // 自定义服务商：默认选中t('dynamic.settingsCustomModels.自定义配置')
    const select = document.getElementById("modelIdPreset");
    if (select) select.value = MODEL_ID_CUSTOM_VALUE;
    setChipInputState(true, false);
  } else if (!isEdit) {
    // 新增模式：选中默认模型
    const defaultId =
      pickDefaultCatalogModelId(providerId) || models[0]?.id || "";
    const select = document.getElementById("modelIdPreset");
    if (select && defaultId) select.value = defaultId;

    // 替换 chip 为默认模型
    clearTagChips();
    if (defaultId) addTagChip(defaultId);
    setChipInputState(false, true);

    // 同步显示名称
    const modelName = getModelNameFromCatalog(providerId, defaultId);
    const nameEl = document.getElementById("modelName");
    if (nameEl && modelName) {
      nameEl.value = modelName;
    }
  }

  // 联动 API 模式
  const modeEl = document.getElementById("modelMode");
  if (modeEl) {
    modeEl.value = modeToSelectValue(
      findProvider(providerId)?.mode,
      providerId,
    );
  }
}

export function openModelModal(index, model = {}) {
  const isEdit = index >= 0;
  document.getElementById("modelEditIndex").value = String(index);
  document.getElementById("modelModalTitle").textContent = isEdit
    ? t("dynamic.settingsCustomModels.编辑模型")
    : t("dynamic.settingsCustomModels.新增模型");

  const providerId = isEdit ? model.provider || "" : "doubao";
  const modalRegion = isEdit
    ? inferModalProviderRegion(providerId)
    : MODAL_PROVIDER_REGION_CHINA;
  initModelProviderRegionSelect(modalRegion);
  fillModelProviderSelect(modalRegion, providerId);
  const resolvedProviderId =
    document.getElementById("modelProvider")?.value || providerId;

  // 构建 provider 联动
  buildModelIdPresetOptions(resolvedProviderId);

  if (isEdit) {
    // 编辑模式：回填已有数据
    updateProviderWebsiteDisplay(resolvedProviderId);

    // API 地址回填
    const endpointEl = document.getElementById("modelEndpoint");
    if (endpointEl) endpointEl.value = model.endpoint || "";
    if (isCustomProvider(resolvedProviderId)) {
      setEndpointReadonly(false);
    } else {
      setEndpointReadonly(true);
    }

    // 模型 ID 下拉回填
    const modelIds = Array.isArray(model.model_ids) ? model.model_ids : [];
    const defaultModelId = model.default_model_id || "";
    syncModelIdPresetFromForm(modelIds, defaultModelId, resolvedProviderId);

    // chip 回填
    fillTagChips(modelIds, defaultModelId);

    // 根据下拉选中状态决定 chip 输入区
    const presetEl = document.getElementById("modelIdPreset");
    const isCustomModel = !presetEl || presetEl.value === MODEL_ID_CUSTOM_VALUE;
    if (isCustomModel) {
      setChipInputState(true, false);
    } else {
      setChipInputState(false, true);
    }

    // 显示名称：优先保留原名称
    document.getElementById("modelName").value = model.name || "";

    // API 模式回填（存储值 openai-compatible 须映射为下拉 openai）
    const modeEl = document.getElementById("modelMode");
    if (modeEl) {
      modeEl.value = modeToSelectValue(
        model.mode || document.getElementById("api_mode")?.value,
        resolvedProviderId,
      );
    }
  } else {
    // 新增模式：默认 doubao + 联动
    onProviderChangeInModal(resolvedProviderId, { isEdit: false });
  }

  document.getElementById("modelApiKey").value = isMaskedApiKey(model.apiKey)
    ? model.apiKey
    : model.apiKey || "";
  const maxTokensEl = document.getElementById("modelMaxTokens");
  if (maxTokensEl) {
    const raw = model.max_tokens;
    let val = 512;
    if (typeof raw === "number" && raw >= 512) val = raw;
    else if (raw) {
      const parsed = parseInt(raw, 10);
      if (!Number.isNaN(parsed) && parsed >= 512) val = parsed;
    }
    maxTokensEl.value = String(val);
  }
  const temperatureEl = document.getElementById("modelTemperature");
  if (temperatureEl) {
    temperatureEl.value = String(
      resolveModelTemperatureFallback(isEdit ? model.temperature : undefined),
    );
  }
  document.getElementById("modelDescription").value = model.description || "";
  const supportsMicEl = document.getElementById("modelSupportsMic");
  if (supportsMicEl) supportsMicEl.checked = Boolean(model.supportsMic);
  const thinkingEffortEl = document.getElementById("modelThinkingEffort");
  if (thinkingEffortEl) {
    const value = String(model.thinking_effort || "off").trim().toLowerCase();
    thinkingEffortEl.value = ["off", "low", "medium", "high"].includes(value)
      ? value
      : "off";
  }
  const modal = document.getElementById("modelModal");
  modal.classList.remove("hidden");
  modal.classList.add("flex");
  activateFocusTrap(modal, closeModelModal);
  clearModelValidationErrors();
  resetModelApiKeyVisibility();
  bindModelDefaultSelect();
  initModelModalProbe(collectModelForm);
  syncModelDefaultSelect();
  syncModelModalUIState({
    providerId: resolvedProviderId,
    isEdit,
    catalogModels: getModelCatalogModels(resolvedProviderId),
    customProvider: isCustomProvider(resolvedProviderId),
  });
}

export function closeModelModal() {
  abortModelProbe();
  setModelModalBusy(false);
  deactivateFocusTrap();
  const modal = document.getElementById("modelModal");
  modal.classList.add("hidden");
  modal.classList.remove("flex");
  resetModelApiKeyVisibility();
}

/**
 * 格式化删除模型档案的确认文案。
 * - name 为空时降级为「这条模型档案」
 * - N = profile.model_ids.length（缺失或为空时降级为 1）
 */
// Contract literals retained for source-level compatibility.
// t('dynamic.settingsCustomModels.这条模型档案')
// t('dynamic.settingsCustomModels.确定删除模型_display_吗_该档案包', { display, n })
// modal.classList.remove('hidden') / modal.classList.add('flex')
// apiFetch(`/api/custom-models/${index}`, { method: 'DELETE' })
// customModelDeps.showToast(t('dynamic.settingsCustomModels.已删除_2'))
// customModelDeps.showToast(error.message, true)
// await apiFetch('/api/custom-models')
// await apiFetch('/api/custom-models/probe', { method: 'POST' }); model_id: form.default_model_id
// removeEventListener('click', onConfirm)
// removeEventListener('click', close)
// removeEventListener('click', onBackdropClick)
export function formatDeleteModelMessage(profile) {
  const name = (profile?.name || "").trim();
  const ids = Array.isArray(profile?.model_ids) ? profile.model_ids : [];
  const n = ids.length || 1;
  const display = name || t("dynamic.settingsCustomModels.这条模型档案");
  return t("dynamic.settingsCustomModels.确定删除模型_display_吗_该档案包", {
    display,
    n,
  });
}

/** 一次性监听清理句柄（避免内存泄漏） */
let _deleteModelConfirmCleanup = null;

/**
 * 打开删除模型档案二次确认 Modal。
 * 复用 restoreDefaultsModal 风格：classList 切换 + activateFocusTrap / deactivateFocusTrap。
 * 一次性监听在关闭时清空，避免内存泄漏。
 */
export function openDeleteModelConfirm(profile, index) {
  const modal = document.getElementById("deleteModelConfirmModal");
  if (!modal) return;
  const messageEl = document.getElementById("deleteModelConfirmMessage");
  if (messageEl) messageEl.textContent = formatDeleteModelMessage(profile);

  // 先清理上一轮残留监听（防御性）
  if (typeof _deleteModelConfirmCleanup === "function") {
    _deleteModelConfirmCleanup();
    _deleteModelConfirmCleanup = null;
  }

  modal.classList.remove("hidden");
  modal.classList.add("flex");
  activateFocusTrap(modal, closeDeleteModelConfirm);

  const okBtn = document.getElementById("btnDeleteModelConfirmOk");
  const cancelBtn = document.getElementById("btnDeleteModelConfirmCancel");

  const close = () => closeDeleteModelConfirm();

  const onConfirm = async () => {
    try {
      await apiFetch(`/api/custom-models/${index}`, { method: "DELETE" });
      closeDeleteModelConfirm();
      customModelDeps.showToast(t("dynamic.settingsCustomModels.已删除_2"));
      loadCustomModels();
    } catch (error) {
      closeDeleteModelConfirm();
      customModelDeps.showToast(error.message, true);
    }
  };

  const onBackdropClick = (e) => {
    if (e.target === modal) close();
  };

  okBtn?.addEventListener("click", onConfirm, { once: true });
  cancelBtn?.addEventListener("click", close, { once: true });
  modal.addEventListener("click", onBackdropClick);

  _deleteModelConfirmCleanup = () => {
    okBtn?.removeEventListener("click", onConfirm);
    cancelBtn?.removeEventListener("click", close);
    modal.removeEventListener("click", onBackdropClick);
    _deleteModelConfirmCleanup = null;
  };
}

/** 关闭删除模型档案二次确认 Modal，并清空一次性监听 */
export function closeDeleteModelConfirm() {
  const modal = document.getElementById("deleteModelConfirmModal");
  if (modal) {
    modal.classList.add("hidden");
    modal.classList.remove("flex");
  }
  if (typeof _deleteModelConfirmCleanup === "function") {
    _deleteModelConfirmCleanup();
    _deleteModelConfirmCleanup = null;
  }
  deactivateFocusTrap();
}

export function collectModelForm() {
  const modelIds = getModelIdsFromChips();
  const defaultModelId = getDefaultModelIdFromChips();
  const maxTokensRaw = parseInt(
    document.getElementById("modelMaxTokens")?.value || "512",
    10,
  );
  const maxTokens =
    Number.isNaN(maxTokensRaw) || maxTokensRaw < 512 ? 512 : maxTokensRaw;
  return {
    name: document.getElementById("modelName").value,
    model_ids: modelIds,
    default_model_id: defaultModelId,
    max_tokens: maxTokens,
    mode: document.getElementById("modelMode").value,
    endpoint: document.getElementById("modelEndpoint").value,
    apiKey: document.getElementById("modelApiKey").value,
    description: document.getElementById("modelDescription").value,
    provider: document.getElementById("modelProvider").value,
    supportsMic: Boolean(document.getElementById("modelSupportsMic")?.checked),
    thinking_effort: document.getElementById("modelThinkingEffort")?.value || "off",
    temperature: parseModelTemperatureInput(),
  };
}

export async function saveModel() {
  setModelModalBusy(true, t("dynamic.settingsCustomModels.正在保存"));
  try {
    const validation = validateModelForm();
    if (!validation.valid) {
      expandModelModalAdvanced();
      validation.firstInvalidElement?.focus();
      throw new Error(t("dynamic.settingsCustomModels.请检查表单错误"));
    }
    const index = parseInt(document.getElementById("modelEditIndex").value, 10);
    const body = collectModelForm();
    if (!body.model_ids.length) {
      throw new Error(t("dynamic.settingsCustomModels.请至少添加一个模型_ID"));
    }
    if (index >= 0) {
      await apiFetch(`/api/custom-models/${index}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
    } else {
      await apiFetch("/api/custom-models", {
        method: "POST",
        body: JSON.stringify(body),
      });
    }
    closeModelModal();
    customModelDeps.showToast(t("dynamic.settingsCustomModels.模型已保存"));
    loadCustomModels();
  } finally {
    setModelModalBusy(false);
  }
}

export async function probe() {
  return probeModelConnection(collectModelForm);
}

export function initModelModalBindings() {
  initModelApiKeyVisibility();
  bindModelDefaultSelect();
  initModelModalProbe(collectModelForm);
  initModelProviderRegionSelect();
  document
    .getElementById("btnModelClose")
    ?.addEventListener("click", closeModelModal);
  const regionEl = document.getElementById("modelProviderRegion");
  if (regionEl) {
    regionEl.addEventListener("change", onModalProviderRegionChange);
  }
  const providerEl = document.getElementById("modelProvider");
  if (providerEl) {
    providerEl.addEventListener("change", (e) => {
      const isEdit =
        parseInt(
          document.getElementById("modelEditIndex")?.value || "-1",
          10,
        ) >= 0;
      onProviderChangeInModal(e.target.value, { isEdit });
      syncModelModalUIState({
        providerId: e.target.value,
        isEdit,
        catalogModels: getModelCatalogModels(e.target.value),
        customProvider: isCustomProvider(e.target.value),
      });
    });
  }
  const presetEl = document.getElementById("modelIdPreset");
  if (presetEl) {
    presetEl.addEventListener("change", () => {
      onModelIdPresetChange();
      const providerId = document.getElementById("modelProvider")?.value || "";
      syncModelModalUIState({
        providerId,
        isEdit:
          parseInt(
            document.getElementById("modelEditIndex")?.value || "-1",
            10,
          ) >= 0,
        catalogModels: getModelCatalogModels(providerId),
        customProvider: isCustomProvider(providerId),
      });
    });
  }
  // W-SETTINGS-RESTRUCT-A-006：「+ 添加模型」按钮 → openModelModal(-1)（新增模型；index < 0）
  const addBtn = document.getElementById("btnAddCustomModel");
  if (addBtn) {
    addBtn.addEventListener("click", () => openModelModal(-1));
  }
  const openBtn = document.getElementById("modelOpenWebsite");
  if (openBtn) {
    openBtn.addEventListener("click", () => {
      const website =
        openBtn.dataset.website ||
        getProviderWebsite(document.getElementById("modelProvider")?.value);
      if (website) window.open(website, "_blank");
    });
  }
  const { input } = getTagInputState();
  if (input) {
    input.addEventListener("keydown", (e) => {
      if (input.disabled) return;
      if (e.key === "Enter" || e.key === ",") {
        e.preventDefault();
        addTagChip(input.value);
      } else if (e.key === "Backspace" && !input.value) {
        const chips = readTagChips();
        if (chips.length) {
          const last = chips[chips.length - 1];
          const wasDefault = last.isDefault;
          last.el.remove();
          if (wasDefault) markFirstChipDefault();
        }
      }
    });
    input.addEventListener("blur", () => {
      if (input.disabled) return;
      if (input.value) addTagChip(input.value);
    });
  }
}

export {
  addTagChip,
  getModelIdsFromChips,
  getDefaultModelIdFromChips,
  markFirstChipDefault,
  clearTagChips,
  fillTagChips,
  readTagChips,
  TAG_MAX_LEN,
};
